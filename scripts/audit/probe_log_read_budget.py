"""Measure the device log reader with disposable files, never live device logs."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import subprocess
import tempfile
import tracemalloc
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch


async def probe() -> dict:
    from backend.api.v1.logs import router as log_router

    device_id = "00000000-0000-0000-0000-000000000033"
    prefix = b"2026-10-06T00:00:00Z I/fixture: "
    row = prefix + b"x" * (127 - len(prefix)) + b"\n"
    assert len(row) == 128
    per_file = 8 * 1024 * 1024
    with tempfile.TemporaryDirectory(prefix="sphere-log-budget-") as temporary:
        with patch.object(log_router, "_LOGS_DIR", Path(temporary)), patch.object(
            log_router, "_owned_device", AsyncMock(),
        ):
            directory = log_router._device_log_path(device_id)
            directory.mkdir()
            today = datetime.now(timezone.utc).date()
            for days in range(3):
                path = directory / f"agent_{today - timedelta(days=days)}.log"
                with path.open("wb") as stream:
                    for _ in range(per_file // 65536):
                        stream.write(row * 512)
            whole_file_reads = []
            original = Path.read_text

            def counted_read(path, *args, **kwargs):
                if path.parent == directory:
                    whole_file_reads.append(path.stat().st_size)
                return original(path, *args, **kwargs)

            tracemalloc.start()
            try:
                with patch.object(Path, "read_text", counted_read):
                    response = await log_router.get_device_logs(
                        device_id, lines=1000, date=None, search=None,
                        _principal=object(), db=object(),
                    )
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            payload = json.loads(response.body)
            assert payload['total'] == 1000 and len(payload['lines']) == 1000
            assert all(line == row.decode().rstrip('\n') for line in payload['lines'])
            root = Path(__file__).resolve().parents[2]
            paths = ['backend/api/v1/logs/router.py', 'backend/services/device_log_reader.py']
            hashes = {name: hashlib.sha256((root / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
                      for name in paths if (root / name).exists()}
            return {
                "observedAt": datetime.now(timezone.utc).isoformat(),
                "source": subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                "workingTreeModified": subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', *paths], cwd=root).returncode != 0,
                "workingFileHashes": hashes,
                "fixtureBytes": per_file * 3, "files": 3, "requestedLines": 1000,
                "returnedLines": len(payload['lines']), "pythonTracedPeakBytes": peak,
                "wholeFileReadBytes": sum(whole_file_reads),
                "linesSha256": hashlib.sha256(json.dumps(payload['lines']).encode()).hexdigest(),
                "readMetadata": payload.get('read'), "liveServicesContacted": False,
                "authorizationProven": False, "temporaryFilesRemoved": False,
                "hostDiskWriterIdentified": False,
            }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expect-bounded', action='store_true')
    args = parser.parse_args()
    os.environ.setdefault('JWT_SECRET_KEY', secrets.token_urlsafe(48))
    result = asyncio.run(probe())
    # TemporaryDirectory has exited before the receipt is persisted.
    result['temporaryFilesRemoved'] = True
    if args.expect_bounded:
        assert result['wholeFileReadBytes'] == 0
        assert result['readMetadata']['bytes_scanned'] <= result['readMetadata']['scan_byte_limit']
        assert result['pythonTracedPeakBytes'] < result['fixtureBytes']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
