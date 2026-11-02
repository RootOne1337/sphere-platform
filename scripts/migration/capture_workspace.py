"""Preserve Git history and the source working tree in a PRIVATE recovery directory.

This does not include ignored runtime data; use backup_data.py and capture-host.ps1 too.
Never upload the output to a public repository. Requires only Python 3.12+ and Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import zipfile

try:
    from .backup_data import protect_directory
except ImportError:
    from backup_data import protect_directory
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GENERATED = ("frontend/.next-audit/", "output/", "frontend/.next/")


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.PIPE)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def paths(*args: str) -> list[str]:
    return [p for p in git("ls-files", "-z", *args).decode("utf-8").split("\0") if p]


def verify(destination: Path) -> dict:
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["artifacts"]:
        file = destination / item["file"]
        if file.stat().st_size != item["bytes"] or sha256(file) != item["sha256"]:
            raise ValueError(f"Artifact integrity failure: {item['file']}")
    with zipfile.ZipFile(destination / "working-tree.zip") as archive:
        if archive.testzip() is not None:
            raise ValueError("Working tree ZIP CRC failure")
        for item in manifest["files"]:
            with archive.open(item["path"]) as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                    raise ValueError(f"Source integrity failure: {item['path']}")
    subprocess.run(["git", "bundle", "verify", str(destination / "repository.bundle")],
                   cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return {"verified": True, "sourceFiles": len(manifest["files"]),
            "artifacts": len(manifest["artifacts"]), "independentBackup": False}


def capture(destination: Path) -> dict:
    if destination.exists():
        raise ValueError("Destination must be a new directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    reserve = (12 if os.stat(destination.parent).st_dev == os.stat(ROOT).st_dev else 1) * 1024**3
    if shutil.disk_usage(destination.parent).free < reserve + 2 * 1024**3:
        raise ValueError("Need space for capture plus reserve (12 GiB on source volume, 1 GiB on another SSD)")
    destination.mkdir(mode=0o700)
    protect_directory(destination)
    tracked = set(paths("--cached"))
    untracked = set(paths("--others", "--exclude-standard"))
    selected = sorted(tracked | {p for p in untracked if not p.startswith(GENERATED)})
    excluded = sorted(untracked - set(selected))
    before_head = git("rev-parse", "HEAD").decode().strip()
    status = git("status", "--porcelain=v1", "-uall")
    (destination / "git-status.txt").write_bytes(status)
    subprocess.run(["git", "bundle", "create", str(destination / "repository.bundle"), "--all"],
                   cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    entries = []
    missing = []
    with zipfile.ZipFile(destination / "working-tree.zip", "w", zipfile.ZIP_DEFLATED,
                         compresslevel=3) as archive:
        for rel in selected:
            if shutil.disk_usage(destination).free < reserve:
                raise ValueError("Destination reserve reached; incomplete capture retained")
            file = ROOT / rel
            if not file.is_file():
                missing.append(rel)
                continue
            before = file.stat()
            archive.write(file, rel)
            # Verify the archive bytes against a stable source read, never claim an atomic snapshot.
            digest = sha256(file)
            after = file.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError(f"Source changed during capture: {rel}; retry when edits finish")
            entries.append({"path": rel, "bytes": after.st_size, "sha256": digest,
                            "tracked": rel in tracked})
    if before_head != git("rev-parse", "HEAD").decode().strip():
        raise ValueError("Git HEAD changed during capture; retry")
    artifacts = []
    for name in ("repository.bundle", "working-tree.zip", "git-status.txt"):
        file = destination / name
        artifacts.append({"file": name, "bytes": file.stat().st_size, "sha256": sha256(file)})
    manifest = {"schemaVersion": 1, "createdAtUtc": datetime.now(timezone.utc).isoformat(),
                "gitHead": before_head, "private": True, "independentBackup": False,
                "consistency": "Per-file stable reads; source files are verified inside ZIP. Not a host snapshot.",
                "files": entries, "missingTrackedPaths": missing,
                "excludedGeneratedPaths": excluded, "artifacts": artifacts}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    result = verify(destination)
    (destination / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    result = verify(args.destination.resolve()) if args.verify else capture(args.destination.resolve())
    print(json.dumps(result))


if __name__ == "__main__":
    main()
