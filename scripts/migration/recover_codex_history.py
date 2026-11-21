"""Build a PRIVATE SQLite salvage candidate from a saved copy; never replace Codex.

The CLI requires a previously trusted sqlite3 executable and its expected SHA256.
Integrity does not prove every original row was recovered. Keep original journals.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess

try:
    from .backup_data import protect_directory
except ImportError:
    from backup_data import protect_directory
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def database_summary(path: Path) -> dict:
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        counts = {}
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            try:
                counts[name] = db.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0]
            except sqlite3.DatabaseError:
                counts[name] = None
        try:
            integrity = [r[0] for r in db.execute("PRAGMA integrity_check")]
        except sqlite3.DatabaseError:
            integrity = ["database disk image is malformed"]
        result = {"counts": counts, "integrityOk": integrity == ["ok"]}
        if "thread_items" in names:
            try:
                result["invalidItemJson"] = db.execute(
                    "SELECT count(*) FROM thread_items WHERE NOT json_valid(item_json)").fetchone()[0]
            except sqlite3.DatabaseError:
                result["invalidItemJson"] = None
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--sqlite-exe", type=Path, required=True)
    parser.add_argument("--sqlite-sha256", required=True)
    args = parser.parse_args()
    source, out = args.snapshot.resolve(), args.destination.resolve()
    if not source.is_file() or out.exists() or not out.parent.is_dir():
        raise ValueError("Need existing saved snapshot and a new destination")
    if source.name == "thread_history_1.sqlite" and ".codex" in source.parts:
        raise ValueError("Use a saved snapshot, never the live Codex database")
    if sha256(args.sqlite_exe) != args.sqlite_sha256:
        raise ValueError("sqlite3 executable hash mismatch")
    if shutil.disk_usage(out.parent).free < 16 * 1024**3:
        raise ValueError("Need 16 GiB free before salvage; at least 12 GiB must remain")
    out.mkdir(mode=0o700)
    protect_directory(out)
    script = out / "recovery.private.sql"
    candidate = out / "candidate.sqlite"
    with script.open("xb") as sql, (out / "recover.private.log").open("xb") as errors:
        subprocess.run([str(args.sqlite_exe), "-readonly", str(source), ".recover --ignore-freelist"],
                       stdout=sql, stderr=errors, timeout=240, check=True)
    if shutil.disk_usage(out).free < source.stat().st_size + 12 * 1024**3:
        raise ValueError("Insufficient reserve for candidate; private recovery SQL retained")
    with script.open("rb") as sql, (out / "import.private.log").open("xb") as errors:
        subprocess.run([str(args.sqlite_exe), "-bail", str(candidate)], stdin=sql,
                       stdout=subprocess.DEVNULL, stderr=errors, timeout=240, check=True)
    before, after = database_summary(source), database_summary(candidate)
    receipt = {"createdAtUtc": datetime.now(timezone.utc).isoformat(), "private": True,
               "sourceSha256": sha256(source), "candidateSha256": sha256(candidate),
               "source": before, "candidate": after, "installed": False,
               "completeRecoveryProven": False,
               "limit": "Structural salvage only. Retain transcripts and source; inspect missing rows and schema before offline installation."}
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps({"candidateIntegrityOk": after["integrityOk"], "installed": False,
                      "completeRecoveryProven": False, "candidateTables": len(after["counts"])}))


if __name__ == "__main__":
    main()
