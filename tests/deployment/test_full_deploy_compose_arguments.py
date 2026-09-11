"""Preserve shipped Bash initialization before exercising Compose command paths."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("production", [False, True])
@pytest.mark.parametrize("operation", ["build_images", "seed_data"])
def test_initialized_bash_passes_compose_files_as_distinct_arguments(tmp_path, production, operation):
    executable = shutil.which("bash")
    if os.name == "nt":
        candidate = Path("C:/Program Files/Git/bin/bash.exe")
        executable = str(candidate) if candidate.exists() else None
    if not executable:
        if os.environ.get("CI"):
            pytest.fail("Bash is required to verify the shipped launcher")
        pytest.skip("Bash unavailable")

    # Keep the complete initialization: set/IFS, defaults and option parsing.
    # Only the automatic main call is omitted; Docker is a subprocess double.
    source = (REPOSITORY / "scripts/full-deploy.sh").read_text(encoding="utf-8")
    prefix, entrypoint = source.rsplit('\nmain "$@"', 1)
    assert not entrypoint.strip()
    library = tmp_path / "full-deploy-library.sh"
    library.write_text(prefix + "\n", encoding="utf-8")
    calls = tmp_path / "calls.jsonl"
    boundary = tmp_path / "docker_boundary.py"
    boundary.write_text('''import json, os, sys
args = sys.argv[1:]
with open(os.environ['LAUNCHER_CALLS'], 'a', encoding='utf-8') as f:
    f.write(json.dumps(args) + '\\n')
overlay = 'docker-compose.production.yml' if os.environ['LAUNCHER_PRODUCTION'] == '1' else 'docker-compose.full.yml'
if args[:5] != ['compose', '-f', 'docker-compose.yml', '-f', overlay]:
    print('Compose file options were not passed as distinct arguments', file=sys.stderr)
    sys.exit(64)
''', encoding="utf-8")
    script = tmp_path / "run.sh"
    script.write_text('''source "$LAUNCHER_LIBRARY" "$@"
PROJECT_DIR="$LAUNCHER_ROOT"
LOG_FILE="$LAUNCHER_ROOT/deploy.log"
docker() { "$LAUNCHER_PYTHON" "$LAUNCHER_BOUNDARY" "$@"; }
"$LAUNCHER_OPERATION"
''', encoding="utf-8")
    env = os.environ.copy()
    env.update(LAUNCHER_LIBRARY=library.as_posix(), LAUNCHER_ROOT=tmp_path.as_posix(),
        LAUNCHER_CALLS=calls.as_posix(), LAUNCHER_BOUNDARY=boundary.as_posix(),
        LAUNCHER_PYTHON=Path(sys.executable).as_posix(), LAUNCHER_OPERATION=operation,
        LAUNCHER_PRODUCTION="1" if production else "0",
        SPHERE_ADMIN_EMAIL="pilot@example.org", SPHERE_ADMIN_PASSWORD="synthetic-launcher-password")
    result = subprocess.run([executable, script.as_posix(), "--headless", *(["--production"] if production else [])],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=20)
    recorded = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()]
    assert result.returncode == 0, result.stdout + result.stderr + "\nargv: " + repr(recorded)
    assert len(recorded) == (1 if operation == "build_images" else 2)
    assert recorded[0][5] == ("build" if operation == "build_images" else "run")
