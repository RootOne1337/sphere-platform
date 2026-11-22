"""Verify the pinned upstream Java subset; optionally restore missing locked files.

No latest-branch resolution, execution or replacement of locally modified source.
To upgrade, review a new official commit and update both SDK/native locks first.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from scripts.build_awg_native import checked_source

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-missing", action="store_true", help="Download missing files at the locked commit only")
    args = parser.parse_args()
    directory = ROOT / "android/awg-sdk"
    lock = json.loads((directory / "upstream.lock.json").read_text(encoding="utf-8"))
    if lock["upstream"] != "amnezia-vpn/amneziawg-android" or not re.fullmatch("[0-9a-f]{40}", lock["commit"]):
        raise ValueError("Invalid pinned upstream identity")
    paths = set()
    for source, expected in lock["sources"].items():
        if source == "COPYING":
            path = directory / source
        elif re.fullmatch(r"tunnel/src/main/java/org/amnezia/awg/(?:GoBackend\.java|(?:config|crypto|util)/[A-Za-z0-9]+\.java)", source):
            path = directory / "src/main/java" / source.removeprefix("tunnel/src/main/java/")
        else:
            raise ValueError("Unexpected vendored source path")
        if not re.fullmatch("[0-9a-f]{64}", expected) or not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Invalid source hash/path")
        paths.add(path.resolve())
        if not path.exists() and args.fetch_missing:
            checked_source(path, expected, f'https://raw.githubusercontent.com/{lock["upstream"]}/{lock["commit"]}/{source}')
        if not path.is_file() or hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() != expected:
            raise ValueError("Missing/changed pinned SDK source: " + source)
    actual = {p.resolve() for p in (directory / "src/main/java").rglob("*.java")} | {(directory / "COPYING").resolve()}
    if actual != paths:
        raise ValueError("Unlisted SDK source")
    print(f"Pinned AWG SDK verified: {len(paths) - 1} Java sources and license")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
