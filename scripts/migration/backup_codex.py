"""Capture PRIVATE Codex transcripts/settings and consistent SQLite backups.

No login tokens, browser profiles, downloaded runtimes, plugins cache, or app
binaries are copied. Live transcripts are captured at their initial byte length;
run a final capture with the apps closed before erasing Windows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import time
import zipfile

try:
    from .backup_data import protect_directory
except ImportError:
    from backup_data import protect_directory
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

FOLDERS = ("sessions", "archived_sessions", "attachments", "automations", "skills",
           "rules", "memories", "memories_v2", "visualizations", "pets")
ROOT_FILES = ("config.toml", "AGENTS.md", "keybindings.json", "session_index.jsonl",
              "history.jsonl", ".codex-global-state.json", "version.json")


def snapshot_sqlite(source: Path, destination: Path, deadline_seconds: int = 180,
                    preserve_damaged: bool = False) -> dict:
    """Use SQLite's online backup API: include committed WAL transactions."""
    if destination.exists():
        raise ValueError("SQLite snapshot destination already exists")
    deadline = time.monotonic() + deadline_seconds

    def progress(_status: int, _remaining: int, _total: int) -> None:
        if time.monotonic() > deadline:
            raise TimeoutError("SQLite backup deadline reached")

    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst, pages=2048, progress=progress, sleep=0.05)
            dst.commit()
            try:
                integrity = [r[0] for r in dst.execute("PRAGMA integrity_check")]
                tables = [r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            except sqlite3.DatabaseError:
                if not preserve_damaged:
                    raise
                return {"integrityCheck": "FAILED: database disk image is malformed", "tables": None,
                        "recoveryRequired": True}
    if integrity != ["ok"]:
        if preserve_damaged:
            return {"integrityCheck": "FAILED", "tables": len(tables), "recoveryRequired": True}
        raise ValueError("SQLite integrity_check failed in snapshot")
    return {"integrityCheck": "ok", "tables": len(tables)}


def write_file(archive: zipfile.ZipFile, source: Path, name: str) -> dict:
    size = source.stat().st_size
    remaining = size
    hasher = hashlib.sha256()
    with source.open("rb") as src, archive.open(name, "w", force_zip64=True) as dst:
        while remaining:
            block = src.read(min(8 * 1024**2, remaining))
            if not block:
                raise ValueError("Source shrank during snapshot")
            dst.write(block)
            hasher.update(block)
            remaining -= len(block)
    return {"path": name, "bytes": size, "sha256": hasher.hexdigest()}


def verify(destination: Path) -> dict:
    document = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(destination / "codex-private.zip") as archive:
        names = [row["path"] for row in document["files"]]
        if sorted(names) != sorted(archive.namelist()) or len(names) != len(set(names)):
            raise ValueError("Unexpected or missing ZIP entry")
        for row in document["files"]:
            if archive.getinfo(row["path"]).file_size != row["bytes"]:
                raise ValueError("ZIP entry size mismatch")
            with archive.open(row["path"]) as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != row["sha256"]:
                    raise ValueError("ZIP entry hash mismatch")
    return {"verified": True, "files": len(document["files"]),
            "sqliteSnapshots": len(document["sqlite"]),
            "allSqliteHealthy": all(row["integrityCheck"] == "ok" for row in document["sqlite"]),
            "archiveBytes": (destination / "codex-private.zip").stat().st_size,
            "fullOfflineAppRestoreTested": False}


def capture(home: Path, destination: Path) -> dict:
    if not home.is_dir() or destination.exists() or not destination.parent.is_dir():
        raise ValueError("Need existing Codex home, existing destination parent, and new destination")
    if destination.resolve().is_relative_to(home.resolve()):
        raise ValueError("Destination must be outside Codex home")
    reserve = (12 if os.stat(destination.parent).st_dev == os.stat(home).st_dev else 1) * 1024**3
    if shutil.disk_usage(destination.parent).free < reserve + 3 * 1024**3:
        raise ValueError("Need working space above reserve (12 GiB on source volume, 1 GiB on another SSD)")
    destination.mkdir(mode=0o700)
    protect_directory(destination)
    files = []
    databases = []
    partial = destination / "codex-private.zip.partial"
    with zipfile.ZipFile(partial, "x", zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
        for source in sorted(home.glob("*.sqlite")):
            temporary = destination / (source.name + ".snapshot.tmp")
            result = snapshot_sqlite(source, temporary, preserve_damaged=True)
            files.append(write_file(archive, temporary, "codex-home/" + source.name))
            databases.append({"file": source.name, **result})
            temporary.unlink()
            if result["integrityCheck"] != "ok":
                # These are physical live file copies, explicitly separate from
                # the committed SQLite snapshot. They may aid later salvage.
                for raw in (source, Path(str(source) + "-wal"), Path(str(source) + "-shm")):
                    if raw.is_file():
                        files.append(write_file(archive, raw, "codex-raw-live/" + raw.name))
        for name in ROOT_FILES:
            source = home / name
            if source.is_file():
                files.append(write_file(archive, source, "codex-home/" + name))
        for folder in FOLDERS:
            base = home / folder
            if not base.is_dir():
                continue
            for source in sorted(base.rglob("*")):
                if source.is_symlink():
                    raise ValueError("Unexpected symbolic link in Codex home")
                if not source.is_file() or source.suffix in {".pyc", ".lock"}:
                    continue
                if shutil.disk_usage(destination).free < reserve:
                    raise ValueError("Free-space reserve reached")
                files.append(write_file(archive, source, "codex-home/" + source.relative_to(home).as_posix()))
    partial.rename(destination / "codex-private.zip")
    document = {"schemaVersion": 1, "createdAtUtc": datetime.now(timezone.utc).isoformat(),
                "private": True, "files": files, "sqlite": databases,
                "consistency": "SQLite online backup per database; other files at initial byte length. codex-raw-live holds uncoordinated raw+sidecar copies for damaged sources. Live app still changes.",
                "excluded": ["auth.json and OS keychain", "browser/cookies", "plugins/cache and runtimes",
                             "Electron profile (copy separately with app closed)", "ongoing events after capture"],
                "restoreLimits": "Local preservation, not a supported chat import promise. Restore offline to a compatible app version; paths/credentials may need repair."}
    (destination / "manifest.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
    result = verify(destination)
    (destination / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    print(json.dumps(verify(args.destination) if args.verify else capture(args.codex_home, args.destination)))


if __name__ == "__main__":
    main()
