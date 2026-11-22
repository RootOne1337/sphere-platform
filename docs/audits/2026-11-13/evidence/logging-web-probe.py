"""Operator evidence from isolated files, in-process HTTP and a synthetic WebSocket."""

import asyncio
import importlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

import httpx
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

os.environ['JWT_SECRET_KEY'] = 'audit-web-evidence-fixture-only-20261113'
os.environ['POSTGRES_URL'] = 'postgresql+asyncpg://127.0.0.1:1/sphere_audit_20261113'
os.environ['REDIS_URL'] = 'redis://127.0.0.1:1/0'

from backend.core.audit_identity import AuditIdentity
from backend.middleware.request_id import RequestIdMiddleware
from backend.services.audit_query import csv_document
from backend.services.device_log_reader import read_log_tail


def log_tail():
    incident = 'isolated_archive_incident'
    with TemporaryDirectory(prefix='sphere-log-web-audit-') as directory:
        path = Path(directory)
        for day in range(10, 14):
            line = incident if day == 10 else 'regular fixture line'
            (path / f'agent_2026-11-{day}.log').write_text(line + '\n', encoding='utf-8')
        recent = read_log_tail(path, lines=1000, date=None, search=incident)
        dated = read_log_tail(path, lines=1000, date='2026-11-10', search=incident)
    assert recent['lines'] == [] and recent['read']['files_available'] == 4
    assert recent['read']['files_scanned'] == 3 and dated['lines'] == [incident]
    return {'default': recent, 'explicit_utc_date': dated}


async def audit_receipt():
    module = importlib.import_module('backend.middleware.audit')
    identity = AuditIdentity(UUID(int=1), UUID(int=2))
    device_id = str(UUID(int=3))
    rows = []
    app = FastAPI()
    app.add_middleware(BaseHTTPMiddleware, dispatch=module.audit_middleware)
    app.add_middleware(RequestIdMiddleware)

    @app.post('/api/v1/devices/{device}/ui-hierarchy')
    @app.post('/api/v1/devices/{device}/screenshot/native')
    async def operation(request: Request):
        request.state.audit_identity = identity
        return Response(status_code=503)

    session = SimpleNamespace(add=rows.append, commit=AsyncMock())
    session_scope = AsyncMock()
    session_scope.__aenter__.return_value = session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://audit.fixture') as client:
        with patch.object(module, 'AsyncSessionLocal', return_value=session_scope), patch.object(
            module, 'bind_tenant_context', AsyncMock()
        ):
            hierarchy = await client.post(f'/api/v1/devices/{device_id}/ui-hierarchy', headers={'X-Request-ID': 'fixture-hierarchy'})
            screenshot = await client.post(f'/api/v1/devices/{device_id}/screenshot/native', headers={'X-Request-ID': 'fixture-screenshot'})

    for index, row in enumerate(rows, 1):
        row.id = UUID(int=index + 10)
        row.created_at = datetime(2026, 11, 13, tzinfo=timezone.utc)
    assert session.commit.await_count == 2
    ids = [response.headers['X-Request-ID'] for response in (hierarchy, screenshot)]
    assert len(set(ids)) == 2
    assert [row.action for row in rows] == ['post.devices', 'post.devices']
    assert [row.resource_id for row in rows] == [device_id, device_id]
    assert all(set(row.meta) == {'status', 'duration_ms', 'http_status'} for row in rows)
    projected = [SimpleNamespace(id=row.id, created_at=row.created_at, user_id=row.user_id, action=row.action,
                                 resource_type=row.resource_type, resource_id=row.resource_id,
                                 ip_address=row.ip_address, status='FAILED') for row in rows]
    csv = csv_document(projected).lstrip('\ufeff')
    assert all(request_id not in csv for request_id in ids)
    return {'response_request_ids': ids, 'recorded_actions': [row.action for row in rows], 'recorded_resource': device_id,
            'recorded_meta_keys': sorted(rows[0].meta), 'csv_header': csv.splitlines()[0]}


async def websocket_auth_timeout():
    module = importlib.import_module('backend.api.ws.stream.router')
    ws = SimpleNamespace(accept=AsyncMock(), receive_json=AsyncMock(side_effect=TimeoutError), close=AsyncMock())
    with patch.object(module, 'StreamSessionHistory') as history:
        await module.stream_viewer_ws(ws, str(UUID(int=3)))
        history.assert_not_called()
    ws.close.assert_awaited_once_with(code=4003, reason='auth_timeout')
    return {**ws.close.await_args.kwargs, 'history_created': False}


async def observe():
    return {'log_tail': log_tail(), 'audit_receipt': await audit_receipt(),
            'websocket_auth_timeout': await websocket_auth_timeout()}


if __name__ == '__main__':
    print(json.dumps(asyncio.run(observe()), ensure_ascii=True, indent=2))
