"""Measure retained-log upload intake with generated ASGI chunks, never a live APK."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import os
import secrets
import subprocess
import tempfile
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_BYTES = 8 * 1024 * 1024
CHUNK_BYTES = 64 * 1024


async def measure(declared_length: bool) -> dict:
    router = importlib.import_module('backend.api.v1.logs.router')
    auth = importlib.import_module('backend.api.ws.android.router')
    consumed = 0
    receives = 0
    chunk = b'x' * CHUNK_BYTES

    async def receive():
        nonlocal consumed, receives
        receives += 1
        consumed += len(chunk)
        return {'type': 'http.request', 'body': chunk, 'more_body': consumed < FIXTURE_BYTES}

    headers = [(b'content-length', str(FIXTURE_BYTES).encode())] if declared_length else []
    request = Request({'type': 'http', 'method': 'POST', 'path': '/api/v1/logs/upload',
                       'headers': headers}, receive=receive)
    with tempfile.TemporaryDirectory(prefix='sphere-log-upload-budget-') as temporary:
        path = Path(temporary)
        with patch.object(router, '_LOGS_DIR', path), patch.object(router, '_owned_device', AsyncMock(
            return_value=SimpleNamespace(id='00000000-0000-0000-0000-000000000033'),
        )), patch.object(auth, 'authenticate_ws_token', AsyncMock(return_value=object())):
            tracemalloc.start()
            try:
                try:
                    response = await router.upload_logs(request, device_id=None,
                        x_device_id='00000000-0000-0000-0000-000000000033',
                        x_api_key='isolated-probe-token', db=object())
                    status = response.status_code
                except HTTPException as exc:
                    status = exc.status_code
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            assert status == 413
            assert not list(path.rglob('*'))
            result = {'contentLengthDeclared': declared_length, 'generatedBodyBytes': FIXTURE_BYTES,
                      'chunkBytes': CHUNK_BYTES, 'receiveCalls': receives, 'asgiBodyBytesConsumed': consumed,
                      'requestBodyCached': hasattr(request, '_body'), 'pythonTracedPeakBytes': peak,
                      'status': status, 'storedFiles': 0}
    result['temporaryFilesRemoved'] = True
    return result


async def probe() -> dict:
    paths = ['backend/api/v1/logs/router.py', 'backend/services/device_log_upload.py']
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
              for name in paths if (ROOT / name).is_file()}
    return {'observedAt': datetime.now(timezone.utc).isoformat(),
            'source': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'workingTreeModified': bool(subprocess.check_output(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT).strip()),
            'workingFileHashes': hashes,
            'cases': [await measure(True), await measure(False)],
            'liveServicesContacted': False, 'authorizationProven': False,
            'hostDiskWriterIdentified': False, 'aggregateProcessRssBoundProven': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--expect-bounded', action='store_true')
    args = parser.parse_args()
    os.environ.setdefault('JWT_SECRET_KEY', secrets.token_urlsafe(48))
    result = asyncio.run(probe())
    if args.expect_bounded:
        declared, chunked = result['cases']
        assert declared['receiveCalls'] == 0
        assert chunked['asgiBodyBytesConsumed'] <= 512 * 1024 + CHUNK_BYTES
        assert all(not row['requestBodyCached'] for row in result['cases'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
