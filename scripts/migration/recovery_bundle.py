"""Copy a private migration staging directory to another SSD and verify its bytes.

The destination is new and must be outside the source tree. This never deletes
source data, overwrites a package, encrypts data, or changes an application.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

try:
    from .backup_data import protect_directory
except ImportError:  # Direct invocation: python scripts/migration/recovery_bundle.py
    from backup_data import protect_directory

MANIFEST = "RECOVERY-BUNDLE.json"
RECEIPT = "RECOVERY-VERIFICATION.json"
RESERVE = 1024**3


def safe_child(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or ".." in path.parts or "\\" in relative or ":" in relative:
        raise ValueError("Invalid package-relative path")
    child = root.joinpath(*path.parts)
    if not child.resolve().is_relative_to(root.resolve()):
        raise ValueError("Package path escapes its root")
    if child.is_symlink() or any(p.is_symlink() for p in child.parents if p != root.parent):
        raise ValueError("Symbolic links are not accepted in recovery packages")
    return child


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(root: Path) -> dict:
    document = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    if document.get("schemaVersion") != 1 or not document.get("complete"):
        raise ValueError("Incomplete or unsupported recovery package")
    expected = set()
    total = 0
    for row in document["files"]:
        if row["path"] in expected:
            raise ValueError("Duplicate package entry")
        expected.add(row["path"])
        path = safe_child(root, row["path"])
        if path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
            raise ValueError(f"Integrity failure: {row['path']}")
        total += row["bytes"]
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual - {MANIFEST, RECEIPT} != expected:
        raise ValueError("Package contains unlisted or missing files")
    result = {"verifiedAtUtc": datetime.now(timezone.utc).isoformat(), "verified": True,
              "files": len(expected), "bytes": total,
              "differentLogicalVolume": document["differentLogicalVolume"],
              "limits": "Integrity only; not proof of application restore, physical disk independence, or encryption."}
    (root / RECEIPT).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def copy_bundle(source: Path, destination: Path, allow_same_volume: bool = False) -> dict:
    source, destination = source.resolve(), destination.resolve()
    if not source.is_dir() or not destination.parent.is_dir():
        raise ValueError("Source and destination parent must already exist")
    if destination.exists():
        raise ValueError("Destination must not exist")
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("Source and destination must not overlap")
    different_volume = os.stat(source).st_dev != os.stat(destination.parent).st_dev
    if not different_volume and not allow_same_volume:
        raise ValueError("Destination is on the same logical volume; use another SSD or explicitly --allow-same-volume")
    files = []
    for file in source.rglob("*"):
        if file.is_symlink():
            raise ValueError("Refusing symbolic link in source")
        if file.is_file():
            rel = file.relative_to(source).as_posix()
            if file.name.endswith(".partial"):
                raise ValueError("Incomplete .partial artifact found; finish capture before copying")
            if rel not in {MANIFEST, RECEIPT}:
                files.append((file, rel, file.stat().st_size))
    if not files:
        raise ValueError("Empty source")
    total = sum(row[2] for row in files)
    if shutil.disk_usage(destination.parent).free < total + RESERVE:
        raise ValueError("Destination lacks room for package and 1 GiB reserve")
    destination.mkdir(mode=0o700)
    protect_directory(destination)
    rows = []
    for file, rel, size in files:
        target = safe_child(destination, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        before = file.stat()
        hasher = hashlib.sha256()
        with file.open("rb") as src, target.open("xb") as dst:
            while block := src.read(8 * 1024**2):
                if shutil.disk_usage(destination).free < len(block) + RESERVE:
                    raise ValueError("Destination reserve reached; incomplete package retained")
                dst.write(block)
                hasher.update(block)
        after = file.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("Source changed while copying; incomplete package retained")
        if target.stat().st_size != size:
            raise ValueError("Copy size mismatch")
        rows.append({"path": rel, "bytes": size, "sha256": hasher.hexdigest()})
    document = {"schemaVersion": 1, "createdAtUtc": datetime.now(timezone.utc).isoformat(),
                "complete": True, "private": True, "differentLogicalVolume": different_volume,
                "files": rows}
    (destination / MANIFEST).write_text(json.dumps(document, indent=2), encoding="utf-8")
    return verify(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("copy")
    create.add_argument("source", type=Path)
    create.add_argument("destination", type=Path)
    create.add_argument("--allow-same-volume", action="store_true")
    check = sub.add_parser("verify")
    check.add_argument("package", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    result = (copy_bundle(args.source, args.destination, args.allow_same_volume)
              if args.command == "copy" else verify(args.package.resolve()))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
