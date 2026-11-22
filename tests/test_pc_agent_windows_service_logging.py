from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from agent.windows_service import MAX_RECORD_BYTES, ServiceLogHandler


def test_service_log_rotation_bounds_utf8_and_keeps_latest_record(tmp_path):
    path = tmp_path / "agent-service.log"
    max_bytes = 20 * 1024
    handler = ServiceLogHandler(path, maxBytes=max_bytes, backupCount=4, encoding="utf-8")
    logger = logging.Logger("fixture")
    logger.addHandler(handler)
    try:
        for index in range(10):
            logger.info("record=%d %s\nsecond line", index, "тест" * MAX_RECORD_BYTES)
    finally:
        handler.close()

    files = sorted(tmp_path.glob("agent-service.log*"))
    assert len(files) == 5
    for file in files:
        data = file.read_bytes()
        assert len(data) <= max_bytes
        lines = data.splitlines()
        assert len(lines) == 1
        assert len(lines[0]) <= MAX_RECORD_BYTES
        assert lines[0].decode("utf-8").endswith(" [truncated]")
    assert "record=9" in path.read_text(encoding="utf-8")


def test_service_records_startup_configuration_error_without_input(tmp_path, monkeypatch):
    monkeypatch.setenv("SPHERE_TELEMETRY_INTERVAL", "invalid-fixture-value")
    agent_dir = Path(__file__).resolve().parents[1] / "pc-agent"
    startup = (
        "from pathlib import Path; import sys; "
        "from agent.windows_service import run_service; run_service(Path(sys.argv[1]))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", startup, str(tmp_path)],
        cwd=agent_dir,
        capture_output=True,
        check=False,
        timeout=20,
    )

    log = (tmp_path / "agent-service.log").read_text(encoding="utf-8")
    assert proc.returncode == 1
    assert proc.stderr == b""
    assert "PC Agent service bootstrap started" in log
    assert "PC Agent service failed (ValidationError)" in log
    assert "invalid-fixture-value" not in log
