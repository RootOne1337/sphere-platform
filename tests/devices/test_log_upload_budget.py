"""No rejected/unfinished upload may buffer a whole journal or append a prefix."""
from __future__ import annotations

import asyncio
import importlib
import threading
import uuid
from contextvars import ContextVar
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.services import device_log_upload as upload


def make_request(chunks=(), *, length=None, disconnect=False, headers=None):
    chunks = list(chunks) or [b'']
    events = [
        {'type': 'http.request', 'body': chunk, 'more_body': index < len(chunks) - 1 or disconnect}
        for index, chunk in enumerate(chunks)
    ]
    if disconnect:
        events.append({'type': 'http.disconnect'})
    state = SimpleNamespace(calls=0, bytes=0)

    async def receive():
        event = events[state.calls]
        state.calls += 1
        state.bytes += len(event.get('body', b''))
        return event

    headers = headers if headers is not None else ([] if length is None else [(b'content-length', str(length).encode())])
    request = Request({'type': 'http', 'method': 'POST', 'path': '/api/v1/logs/upload', 'headers': headers}, receive)
    return request, state


@pytest.mark.asyncio
async def test_declared_oversize_is_rejected_before_receiving_any_body():
    request, state = make_request([b'never read'], length=8 * 1024 * 1024)
    stored = []
    with pytest.raises(upload.LogUploadTooLarge):
        await upload.receive_and_store_log(request, stored.append)
    assert state.calls == 0 and stored == [] and not hasattr(request, '_body')


@pytest.mark.asyncio
@pytest.mark.parametrize('length', [None, 1])
async def test_overflow_stops_on_first_excess_chunk_without_writer_or_body_cache(length):
    chunk = b'x' * 65536
    request, state = make_request([chunk] * 128, length=length)
    stored = []
    with pytest.raises(upload.LogUploadTooLarge):
        await upload.receive_and_store_log(request, stored.append)
    assert state.calls == 9 and state.bytes == 589824
    assert stored == [] and not hasattr(request, '_body')


@pytest.mark.asyncio
@pytest.mark.parametrize('declared', [False, True])
@pytest.mark.parametrize('size', [0, 480 * 1024, 512 * 1024])
async def test_accepted_boundary_preserves_all_original_bytes(size, declared):
    payload = (b'\x00\xff\n\r\xd0\xb0\xd0\xb1' * (size // 8 + 1))[:size]
    chunks = [payload[index:index + 10003] for index in range(0, size, 10003)]
    request, _ = make_request(chunks, length=size if declared else None)
    stored = []
    await upload.receive_and_store_log(request, stored.append)
    assert stored == [payload] and not hasattr(request, '_body')


@pytest.mark.asyncio
@pytest.mark.parametrize('value', [b'-1', b'+1', b'1_0', b' 1', b'', b'nan', b'\xff'])
async def test_invalid_length_fails_before_receive(value):
    request, state = make_request([b'prefix'], headers=[(b'content-length', value)])
    with pytest.raises(upload.LogUploadInvalidBody):
        await upload.receive_and_store_log(request, lambda body: pytest.fail('Writer called'))
    assert state.calls == 0


@pytest.mark.asyncio
async def test_duplicate_length_and_integer_conversion_budget():
    request, state = make_request(headers=[(b'content-length', b'1'), (b'content-length', b'1')])
    with pytest.raises(upload.LogUploadInvalidBody):
        await upload.receive_and_store_log(request, lambda body: pytest.fail('Writer called'))
    assert state.calls == 0
    request, state = make_request(length='9' * 5000)
    with pytest.raises(upload.LogUploadTooLarge):
        await upload.receive_and_store_log(request, lambda body: pytest.fail('Writer called'))
    assert state.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('length', [1, 99])
async def test_completed_body_with_wrong_declared_length_is_not_appended(length):
    request, _ = make_request([b'partial'], length=length)
    with pytest.raises(upload.LogUploadInvalidBody):
        await upload.receive_and_store_log(request, lambda body: pytest.fail('Writer called'))


@pytest.mark.asyncio
async def test_client_disconnect_and_total_receive_deadline_never_append(monkeypatch):
    request, _ = make_request([b'partial'], disconnect=True)
    with pytest.raises(upload.LogUploadInvalidBody):
        await upload.receive_and_store_log(request, lambda body: pytest.fail('Writer called'))
    monkeypatch.setattr(upload, 'RECEIVE_TIMEOUT_SECONDS', 0.03)
    calls = []

    async def receive():
        calls.append(True)
        if len(calls) > 1:
            await asyncio.sleep(0.005)  # Continuous progress still has a total deadline.
        return {'type': 'http.request', 'body': b'x', 'more_body': True}

    request = Request({'type': 'http', 'headers': []}, receive)
    with pytest.raises(upload.LogUploadTimeout):
        await upload.receive_and_store_log(request, lambda body: pytest.fail('Writer called'))
    assert 0 < len(calls) < 20 and not hasattr(request, '_body')


@pytest.mark.asyncio
async def test_saturation_rejects_without_reading_and_body_cancellation_releases_slot(monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(upload, '_slots', slots)
    entered = asyncio.Event()

    async def receive():
        entered.set()
        await asyncio.Future()

    request = Request({'type': 'http', 'headers': []}, receive)
    task = asyncio.create_task(upload.receive_and_store_log(request, lambda body: pytest.fail('Writer called')))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        rejected, state = make_request([b'never read'])
        with pytest.raises(upload.LogUploadBusy):
            await upload.receive_and_store_log(rejected, lambda body: pytest.fail('Writer called'))
        assert state.calls == 0
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert slots.acquire(blocking=False)
    slots.release()


@pytest.mark.asyncio
async def test_loop_remains_responsive_and_cancelled_http_does_not_free_running_writer(monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(upload, '_slots', slots)
    entered, finish = threading.Event(), threading.Event()

    def writer(body):
        entered.set()
        assert finish.wait(3)

    request, _ = make_request([b'complete'])
    task = asyncio.create_task(upload.receive_and_store_log(request, writer))
    try:
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.005)
        assert entered.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        rejected, state = make_request([b'never read'])
        with pytest.raises(upload.LogUploadBusy):
            await upload.receive_and_store_log(rejected, writer)
        assert state.calls == 0
    finally:
        finish.set()
        for _ in range(100):
            if slots.acquire(blocking=False):
                slots.release()
                break
            await asyncio.sleep(0.005)
        else:
            pytest.fail('Writer completion did not release admission')


@pytest.mark.asyncio
async def test_writer_failure_submission_failure_and_request_context(monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(upload, '_slots', slots)
    correlation = ContextVar('upload_test_correlation', default='missing')
    token = correlation.set('request-fixture')

    def failure(body):
        assert correlation.get() == 'request-fixture'
        raise OSError('private path must not become successful upload')

    try:
        request, _ = make_request([b'complete'])
        with pytest.raises(upload.LogUploadUnavailable):
            await upload.receive_and_store_log(request, failure)
    finally:
        correlation.reset(token)
    assert slots.acquire(blocking=False)
    slots.release()
    executor = SimpleNamespace(submit=lambda *args: (_ for _ in ()).throw(RuntimeError('executor unavailable')))
    monkeypatch.setattr(upload, '_executor', executor)
    request, _ = make_request([b'complete'])
    with pytest.raises(RuntimeError, match='executor unavailable'):
        await upload.receive_and_store_log(request, failure)
    assert slots.acquire(blocking=False)
    slots.release()


@pytest.fixture
def route_fixture(monkeypatch, tmp_path):
    router = importlib.import_module('backend.api.v1.logs.router')
    auth = importlib.import_module('backend.api.ws.android.router')
    identity = str(uuid.uuid4())
    owned = AsyncMock(return_value=SimpleNamespace(id=identity))
    monkeypatch.setattr(router, '_LOGS_DIR', tmp_path)
    monkeypatch.setattr(router, '_owned_device', owned)
    authenticate = AsyncMock(return_value=object())
    monkeypatch.setattr(auth, 'authenticate_ws_token', authenticate)
    return SimpleNamespace(router=router, path=tmp_path, device_id=identity, owned=owned, authenticate=authenticate)


async def call_route(fixture, request, **overrides):
    kwargs = dict(device_id=None, x_device_id=fixture.device_id, x_api_key='isolated-fixture-token', db=object())
    kwargs.update(overrides)
    return await fixture.router.upload_logs(request, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize('identity', ['header', 'legacy_query'])
async def test_route_preserves_file_format_and_moves_all_filesystem_operations_off_loop(route_fixture, monkeypatch, identity):
    fixture = route_fixture
    loop_thread = threading.get_ident()
    get_file, cleanup = fixture.router._get_log_file, fixture.router._clean_old_logs
    threads = []

    def observed_get(device_id):
        threads.append(threading.get_ident())
        return get_file(device_id)

    def observed_cleanup(device_id):
        threads.append(threading.get_ident())
        cleanup(device_id)

    monkeypatch.setattr(fixture.router, '_get_log_file', observed_get)
    monkeypatch.setattr(fixture.router, '_clean_old_logs', observed_cleanup)
    payload = b'original\n\x00\xff\r\n'
    request, _ = make_request([payload], length=len(payload))
    kwargs = {'device_id': fixture.device_id, 'x_device_id': None} if identity == 'legacy_query' else {}
    response = await call_route(fixture, request, **kwargs)
    assert response.status_code == 204
    files = list(fixture.path.rglob('*.log'))
    assert len(files) == 1
    content = files[0].read_bytes()
    assert content.startswith(b'\n--- Uploaded at ') and content.endswith(b' ---\n' + payload)
    assert len(threads) == 2 and all(thread != loop_thread for thread in threads)


@pytest.mark.asyncio
@pytest.mark.parametrize('rejection', ['no_key', 'auth', 'foreign', 'conflict'])
async def test_auth_or_identity_rejection_precedes_body_and_creates_no_file(route_fixture, rejection):
    fixture = route_fixture
    kwargs = {}
    expected = {'no_key': 401, 'auth': 401, 'foreign': 404, 'conflict': 400}[rejection]
    if rejection == 'no_key':
        kwargs['x_api_key'] = None
    elif rejection == 'auth':
        fixture.authenticate.side_effect = HTTPException(status_code=401)
    elif rejection == 'foreign':
        fixture.owned.side_effect = HTTPException(status_code=404)
    else:
        kwargs['device_id'] = str(uuid.uuid4())
    request, state = make_request([b'never read'])
    with pytest.raises(HTTPException) as caught:
        await call_route(fixture, request, **kwargs)
    assert caught.value.status_code == expected and state.calls == 0
    assert not list(fixture.path.rglob('*'))


@pytest.mark.asyncio
@pytest.mark.parametrize('problem,status', [('size', 413), ('length', 400), ('busy', 503), ('io', 503), ('timeout', 408)])
async def test_route_errors_never_claim_204_or_leak_private_storage_path(route_fixture, monkeypatch, problem, status):
    fixture = route_fixture
    request, state = make_request([b'complete'], length=upload.MAX_BODY_BYTES + 1 if problem == 'size' else 1 if problem == 'length' else None)
    if problem == 'busy':
        monkeypatch.setattr(upload, '_slots', threading.BoundedSemaphore(0))
    elif problem == 'io':
        monkeypatch.setattr(fixture.router, '_get_log_file', lambda _: (_ for _ in ()).throw(OSError('/private/storage/path')))
    elif problem == 'timeout':
        monkeypatch.setattr(upload, 'RECEIVE_TIMEOUT_SECONDS', 0)
    with pytest.raises(HTTPException) as caught:
        await call_route(fixture, request)
    assert caught.value.status_code == status and '/private' not in caught.value.detail
    if status == 503:
        assert caught.value.headers == {'Retry-After': '1'}
    if problem in {'size', 'busy'}:
        assert state.calls == 0
    assert not list(fixture.path.rglob('*'))
