"""Call the real delete handler against one temporary log and an injected I/O failure."""

import asyncio
import importlib
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


async def main() -> None:
    router = importlib.import_module("backend.api.v1.logs.router")
    with TemporaryDirectory(prefix="sphere-log-audit-") as temp:
        archive = Path(temp) / "fixture-archive"
        archive.mkdir()
        log = archive / "fixture.log"
        log.write_text("Synthetic log", encoding="utf-8")
        unlink = os.unlink
        attempted = []

        def deny_fixture_unlink(filename, *args, **kwargs):
            if Path(os.fsdecode(filename)).name == log.name:
                attempted.append(log.name)
                raise PermissionError("Injected failure removing the fixture log")
            return unlink(filename, *args, **kwargs)

        with (
            patch.object(router, "_owned_device", new_callable=AsyncMock),
            patch.object(router, "_device_log_path", return_value=archive),
            patch("os.unlink", side_effect=deny_fixture_unlink),
        ):
            response = await router.delete_device_logs("fixture-device", _user=object(), db=object())

        assert attempted == [log.name]
        assert response.status_code == 204
        assert log.is_file()
        print(json.dumps({"http_status": response.status_code, "unlink_permission_error_injected": True,
                          "archive_still_contains_fixture_log": log.is_file()}))


if __name__ == "__main__":
    asyncio.run(main())
