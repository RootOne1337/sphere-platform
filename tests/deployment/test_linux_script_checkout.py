"""Windows Git checkout must preserve executable Linux entrypoint bytes."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("relative", [
    "infrastructure/nginx/docker-entrypoint.sh",
    "infrastructure/tunnel/entrypoint.sh",
    "android/gradlew",
])
def test_autocrlf_checkout_preserves_linux_script_line_endings(tmp_path, relative):
    git = shutil.which("git")
    assert git, "Git is required to verify Windows checkout behavior"
    source = REPOSITORY / relative
    script = tmp_path / relative
    script.parent.mkdir(parents=True, exist_ok=True)
    # Git stores LF blobs; reproduce an actual Windows checkout from that index.
    script.write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))
    shutil.copyfile(REPOSITORY / ".gitattributes", tmp_path / ".gitattributes")

    def run(*arguments):
        result = subprocess.run([git, "-c", "core.autocrlf=true", *arguments],
            cwd=tmp_path, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr

    run("init", "--quiet")
    run("add", ".gitattributes", relative)
    script.unlink()
    run("checkout-index", "--force", relative)
    assert b"\r" not in script.read_bytes(), f"CRLF breaks Linux execution: {relative}"
