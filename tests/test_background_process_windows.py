"""Verify console creation flags and the real GUI Python child-process boundary."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import discovery_publisher


def test_publisher_commands_explicitly_disable_windows_console(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    def run(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout=b"ok", stderr=b"")
    monkeypatch.setattr(subprocess, "run", run)
    assert discovery_publisher.run_command(["command"]) == b"ok"
    assert calls[0]["creationflags"] == 0x08000000
    assert calls[0]["capture_output"] and calls[0]["timeout"] == 30


@pytest.mark.skipif(os.name != "nt", reason="Windows GUI subsystem and console handles")
def test_pythonw_runner_and_publisher_child_have_no_console(tmp_path):
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    assert pythonw.exists()
    output = tmp_path / "result.json"
    probe = tmp_path / "probe.py"
    probe.write_text('''import ctypes, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from scripts.discovery_publisher import run_command
parent_console = ctypes.windll.kernel32.GetConsoleWindow()
child_console = int(run_command([sys.argv[3], "-c", "import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())"]))
Path(sys.argv[1]).write_text(json.dumps({"parent_console": parent_console, "child_console": child_console}))
''')
    child = subprocess.Popen([str(pythonw), str(probe), str(output), str(Path(__file__).resolve().parents[1]), sys.executable],
        creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        child.wait(timeout=20)
        deadline = time.monotonic() + 5
        while not output.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert child.returncode == 0 and output.exists()
        assert json.loads(output.read_text()) == {"parent_console": 0, "child_console": 0}
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
