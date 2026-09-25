"""Verify that private local-pilot artifacts are excluded from Docker contexts."""
from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    token = uuid.uuid4().hex
    pilot_root = ROOT / ".local-pilot"
    pilot_root_existed = pilot_root.exists()
    probe_dir = pilot_root / f"docker-context-probe-{token}"
    sentinel = probe_dir / "private-sentinel.txt"
    dockerfile = ROOT / f".dockerignore-probe-{token}.Dockerfile"
    relative_sentinel = sentinel.relative_to(ROOT).as_posix()

    try:
        probe_dir.mkdir(parents=True, exist_ok=False)
        sentinel.write_text("synthetic private context probe\n", encoding="utf-8")
        dockerfile.write_text(
            f"FROM scratch\nCOPY {relative_sentinel} /private-sentinel.txt\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            ["docker", "build", "--no-cache", "--file", dockerfile.name, "."],
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        try:
            sentinel.unlink(missing_ok=True)
        finally:
            try:
                probe_dir.rmdir()
            finally:
                try:
                    dockerfile.unlink(missing_ok=True)
                finally:
                    if not pilot_root_existed:
                        try:
                            pilot_root.rmdir()
                        except OSError:
                            # Do not remove a directory another process populated.
                            pass

    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode == 0:
        raise SystemExit("Docker unexpectedly copied a .local-pilot sentinel into the build context")
    if "not found" not in output.lower() or sentinel.name not in output:
        raise SystemExit(f"Docker exclusion probe failed for an unrelated reason:\n{output[-4000:]}")

    print("Docker context exclusion passed: synthetic .local-pilot sentinel was unavailable to COPY.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
