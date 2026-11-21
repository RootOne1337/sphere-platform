"""Start or reuse the local road planner and registered image service on Windows."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


def code_digest():
    folder = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in (
        "live_destination.py",
        "live_destination_atlas.py",
        "destination_tiles.py",
        "destination_detail.py",
        "destination_itinerary.py",
        "world_scene_acquisition.py",
        "world_scene_retrieval.py",
        "render_world_search_views.py",
        "observe_world_journey.mjs",
        "verify_world_scene_candidates.py",
    ):
        digest.update(hashlib.sha256((folder / name).read_bytes()).digest())
    return digest.hexdigest()


def get(url):
    try:
        with urlopen(
            Request(url, headers={"Origin": "http://127.0.0.1:3015"}), timeout=2
        ) as response:
            return json.load(response)
    except (URLError, TimeoutError):
        return None


def start(module, args, url, log):
    existing = get(url)
    if existing is not None:
        return existing
    root = Path(__file__).resolve().parents[3]
    name = module.rsplit(".", 1)[-1]
    log_file = log / (name + "-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".log")
    with log_file.open("xb") as output:
        process = subprocess.Popen(
            [sys.executable, "-u", "-m", module, *map(str, args)],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    end = time.monotonic() + 90
    while time.monotonic() < end:
        if process.poll() is not None:
            raise RuntimeError(f"{name} exited; see {log_file}")
        result = get(url)
        if result is not None:
            return result
        time.sleep(0.4)
    raise TimeoutError(f"{name} did not start; see {log_file}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("map-folder", "atlas", "logs"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument(
        "--search-atlas", action="append", nargs=2, default=[], metavar=("DISTRICT", "NPZ")
    )
    parser.add_argument(
        "--water", type=Path, help="Source data/water.dat for detailed street map tiles"
    )
    parser.add_argument("--world-search-config", type=Path)
    parser.add_argument("--drive-region", action="append", default=[], metavar="DISTRICT")
    parser.add_argument("--search-hfov", action="append", type=float, default=[])
    args = parser.parse_args()
    folder = args.map_folder.resolve(strict=True)
    atlas = args.atlas.resolve(strict=True)
    adapter = (folder / "journey/ariane-nav.dll").resolve(strict=True)
    logs = args.logs.resolve()
    logs.mkdir(parents=True, exist_ok=True)
    road = start(
        "scripts.pilot.world_map_lab.serve_world_navmesh",
        ["--folder", folder, "--adapter", adapter, "--port", "8817"],
        "http://127.0.0.1:8817/api/world",
        logs,
    )
    search_args = []
    for angle in args.search_hfov:
        search_args.extend(["--search-hfov", str(angle)])
    for name in args.drive_region:
        search_args.extend(["--drive-region", name])
    expected_config = None
    if args.world_search_config:
        config = args.world_search_config.resolve(strict=True)
        search_args.extend(["--world-search-config", config])
        expected_config = hashlib.sha256(config.read_bytes()).hexdigest()
    expected = {}
    for label, filename in args.search_atlas:
        path = Path(filename).resolve(strict=True)
        search_args.extend(["--search-atlas", label, path])
        with path.open("rb") as source:
            expected[label] = hashlib.file_digest(source, "sha256").hexdigest()
    if args.water:
        search_args.extend(["--detail-folder", folder, "--water", args.water.resolve(strict=True)])
    visual = start(
        "scripts.pilot.world_map_lab.live_destination",
        ["--atlas", atlas, "--logs", logs, *search_args],
        "http://127.0.0.1:8849/world",
        logs,
    )
    with atlas.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    if (
        visual.get("codeDigest") != code_digest()
        or (visual.get("worldSearch") or {}).get("config") != expected_config
        or visual.get("searchCameraHfovs", []) != args.search_hfov
        or visual.get("searchAtlases", {}) != expected
        or visual.get("driveRegions", []) != args.drive_region
        or (args.water and not visual.get("streetTiles"))
        or visual.get("atlasDigest") != digest
        or visual.get("mapRevision") != road["drive"]["placementRevision"]
    ):
        raise ValueError(
            "The running visual atlas or road revision differs from the selected files"
        )
    print("Ready: http://127.0.0.1:3015")


if __name__ == "__main__":
    main()
