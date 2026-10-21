import json
import subprocess
import sys

import pytest

from scripts.pilot import install_vpn_catalog_batch as installer


@pytest.mark.parametrize("failure", [ValueError("private-sentinel"), OSError("private-sentinel"),
                                    subprocess.SubprocessError("private-sentinel")])
def test_installer_cli_does_not_disclose_errors_or_invent_installation(monkeypatch, capsys, failure):
    monkeypatch.setattr(sys, "argv", ["install", "--artifact", ".local-pilot/fixture", "--source", "a" * 40,
                                     "--expected-image-id", "sha256:" + "b" * 64, "--apply"])

    def rejected(*args, **kwargs):
        assert kwargs == {"_vpn_catalog_batch": True}
        raise failure

    monkeypatch.setattr(installer.live, "execute", rejected)
    assert installer.main() == 2
    captured = capsys.readouterr()
    assert captured.err == "" and "private-sentinel" not in captured.out
    assert json.loads(captured.out) == {"runtimeInstalled": None, "state": "not-admitted",
                                       "detail": "Review private plan/CI/host evidence"}
