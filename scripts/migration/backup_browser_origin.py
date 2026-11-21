"""Capture a private, best-effort LIVE Chromium File System origin archive.

The browser is not stopped. Stable file metadata and ZIP/hash checks cannot prove
an application-consistent LevelDB snapshot. Repeat offline after closing browser.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ORIGIN = b"ORIGIN:http_127.0.0.1_3015"


def varint(data, pos):
    result = shift = 0
    while pos < len(data) and shift < 35:
        byte = data[pos]
        pos += 1
        result |= (byte & 127) << shift
        if byte < 128:
            return result, pos
        shift += 7
    raise ValueError("Malformed LevelDB integer")


def origin_mapping(origins: Path) -> str:
    # This is intentionally limited to a log-only database. Never guess if the
    # index has SSTables requiring a full LevelDB reader or the record is split.
    if list(origins.glob("*.ldb")) or list(origins.glob("*.sst")):
        raise ValueError("Origin mapping requires an offline LevelDB reader")
    logs = sorted(origins.glob("*.log"))
    if not logs:
        raise ValueError("Origin mapping log not found")
    batches = []
    for path in logs:
        data = path.read_bytes()
        pending = b""
        for off in range(0, len(data), 32768):
            block = data[off : off + 32768]
            i = 0
            while i + 7 <= len(block):
                length = struct.unpack_from("<H", block, i + 4)[0]
                kind = block[i + 6]
                i += 7
                if not length and not kind:
                    break
                if length > len(block) - i:
                    raise ValueError("Truncated LevelDB record")
                fragment = block[i : i + length]
                i += length
                if kind == 1:
                    batches.append(fragment)
                elif kind == 2:
                    pending = fragment
                elif kind == 3 and pending:
                    pending += fragment
                elif kind == 4 and pending:
                    batches.append(pending + fragment)
                    pending = b""
                else:
                    raise ValueError("Unsupported LevelDB record")
        if pending:
            raise ValueError("Incomplete LevelDB record")
    state = {}
    for batch in sorted(batches, key=lambda x: struct.unpack_from("<Q", x)[0]):
        if len(batch) < 12:
            raise ValueError("Malformed LevelDB write batch")
        count = struct.unpack_from("<I", batch, 8)[0]
        pos = 12
        for _ in range(count):
            tag = batch[pos]
            pos += 1
            length, pos = varint(batch, pos)
            key = batch[pos : pos + length]
            pos += length
            if tag == 1:
                length, pos = varint(batch, pos)
                value = batch[pos : pos + length]
                pos += length
                state[key] = value
            elif tag == 0:
                state.pop(key, None)
            else:
                raise ValueError("Unknown LevelDB operation")
            if pos > len(batch):
                raise ValueError("Malformed LevelDB write batch")
    value = state.get(ORIGIN)
    if not value or not value.isdigit():
        raise ValueError("No verified numeric mapping for requested localhost origin")
    return value.decode("ascii")


def enumerate_files(root: Path):
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs:
            if (Path(directory) / name).is_symlink():
                raise ValueError("Source contains a symlinked directory")
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError("Source contains a symlinked file")
            if name == "LOCK":
                continue
            stat = path.stat()
            result[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return result


def secure_directory(path: Path):
    if os.name == "nt":
        user = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True
        )
        sid = next(csv.reader(io.StringIO(user.stdout)))[1]
        subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"*{sid}:(OI)(CI)F",
                "*S-1-5-18:(OI)(CI)F",
            ],
            capture_output=True,
            check=True,
        )
    else:
        path.chmod(0o700)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", type=Path, required=True, help="Yandex User Data/Default profile"
    )
    parser.add_argument(
        "--bucket", required=True, help="origin directory id, checked against localhost:3015"
    )
    parser.add_argument("destination", type=Path, help="new private destination directory")
    args = parser.parse_args()
    profile = args.profile.resolve(strict=True)
    fs = profile / "File System"
    origins = fs / "Origins"
    if not args.bucket.isascii() or not args.bucket.isdigit():
        parser.error("bucket must be a numeric directory name")
    bucket = fs / args.bucket
    dest = args.destination.resolve()
    if not origins.is_dir() or not bucket.is_dir() or dest.exists() or not dest.parent.is_dir():
        raise ValueError(
            "Need existing origin/bucket and a new destination under an existing directory"
        )
    if dest.is_relative_to(profile) or profile.is_relative_to(dest):
        raise ValueError("Destination must be outside the source profile")
    if origin_mapping(origins) != args.bucket:
        raise ValueError("Requested bucket does not match localhost:3015 mapping")
    roots = {"Origins": origins, args.bucket: bucket}
    before = {name: enumerate_files(path) for name, path in roots.items()}
    source_size = sum(meta[0] for files in before.values() for meta in files.values())
    reserve = (12 if os.stat(dest.parent).st_dev == os.stat(profile).st_dev else 1) * 1024**3
    if shutil.disk_usage(dest.parent).free < reserve + source_size:
        raise ValueError("Insufficient space for capture and destination reserve")
    dest.mkdir(mode=0o700)
    secure_directory(dest)
    archive = dest / "browser-origin.private.zip"
    written = []
    try:
        with zipfile.ZipFile(
            archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True
        ) as z:
            for name, root in roots.items():
                for rel, (expected_size, expected_mtime) in sorted(before[name].items()):
                    path = root / Path(rel)
                    stat = path.stat()
                    if (stat.st_size, stat.st_mtime_ns) != (expected_size, expected_mtime):
                        raise ValueError("Source changed before reading")
                    arcname = f"File System/{name}/{rel}"
                    digest = hashlib.sha256()
                    total = 0
                    with path.open("rb") as src, z.open(arcname, "w", force_zip64=True) as out:
                        for block in iter(lambda: src.read(4 * 1024 * 1024), b""):
                            out.write(block)
                            digest.update(block)
                            total += len(block)
                    stat = path.stat()
                    if total != expected_size or (stat.st_size, stat.st_mtime_ns) != (
                        expected_size,
                        expected_mtime,
                    ):
                        raise ValueError("Source changed during reading")
                    written.append(
                        {
                            "path": arcname,
                            "bytes": total,
                            "mtimeNs": expected_mtime,
                            "sha256": digest.hexdigest(),
                        }
                    )
        if any(enumerate_files(path) != before[name] for name, path in roots.items()):
            raise ValueError("Source file list or metadata changed during capture")
        if origin_mapping(origins) != args.bucket:
            raise ValueError("Origin mapping changed during capture")
        with zipfile.ZipFile(archive) as z:
            for item in written:
                h = hashlib.sha256()
                with z.open(item["path"]) as src:
                    for block in iter(lambda: src.read(4 * 1024 * 1024), b""):
                        h.update(block)
                if h.hexdigest() != item["sha256"]:
                    raise ValueError("ZIP content verification failed")
        archive_hash = hashlib.sha256()
        with archive.open("rb") as stream:
            for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                archive_hash.update(block)
        manifest = {
            "createdAtUtc": datetime.now(timezone.utc).isoformat(),
            "private": True,
            "origin": "http://127.0.0.1:3015",
            "bucket": args.bucket,
            "files": written,
            "sourceBytes": source_size,
            "archiveBytes": archive.stat().st_size,
            "archiveSha256": archive_hash.hexdigest(),
            "sourceWasLive": True,
            "applicationConsistent": False,
            "excluded": ["LevelDB LOCK files"],
            "limitations": "Live metadata/hash checks do not prove LevelDB consistency, recording completeness, browser import, or route recovery. Repeat an offline profile backup after browser exit.",
        }
        with (dest / "manifest.private.json").open("x", encoding="utf8") as f:
            json.dump(manifest, f, indent=2)
            f.write("\n")
        manifest_hash = hashlib.sha256((dest / "manifest.private.json").read_bytes()).hexdigest()
        (dest / "manifest.sha256").write_text(manifest_hash + "\n", encoding="ascii")
        print(
            json.dumps(
                {
                    "verifiedFiles": len(written),
                    "sourceBytes": source_size,
                    "archiveBytes": archive.stat().st_size,
                    "sourceWasLive": True,
                    "applicationConsistent": False,
                }
            )
        )
    except Exception:
        (dest / "INCOMPLETE.txt").write_text(
            "Capture was incomplete or source changed. Do not treat this archive as a verified backup.\n",
            encoding="utf8",
        )
        raise


if __name__ == "__main__":
    main()
