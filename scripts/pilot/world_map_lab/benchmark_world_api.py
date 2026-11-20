"""Measure end-to-end loopback planning latency with independent simultaneous requests."""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np

from scripts.pilot.world_map_lab.world_navmesh import checksum


def run(folder, port):
    origin = f"http://127.0.0.1:{port}"
    controls = json.loads((folder / "fixed-pair-recheck.json").read_bytes())
    published = json.loads((folder / "review.json").read_bytes())
    with urlopen(origin + "/api/world", timeout=30) as answer:
        manifests = json.load(answer)
    jobs = []
    for mode in ("drive", "walk"):
        if published["summary"][mode]["manifest"] != manifests[mode]:
            raise ValueError("server and benchmark folder differ")
        for pair in controls[mode]["pairs"]:
            if pair["after"] == "complete":
                coords = {k: ",".join(map(str, pair[k])) for k in ("start", "end")}
                jobs.append(origin + "/api/path?" + urlencode(dict(mode=mode, **coords)))

    def request(url):
        start = time.perf_counter()
        with urlopen(url, timeout=45) as response:
            record = json.load(response)
        if record["status"] != "complete" or not record["path"]:
            raise ValueError("lost route under simultaneous load")
        return 1000 * (time.perf_counter() - start)

    request(jobs[0])
    request(jobs[-1])
    report = {}
    for workers in (1, 10, 20):
        measurements = []
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for _ in range(2):
                measurements.extend(pool.map(request, jobs))
        report[str(workers)] = {
            "requests": len(measurements),
            "p50": round(float(np.median(measurements)), 2),
            "p95": round(float(np.percentile(measurements, 95)), 2),
            "requestsPerSecond": round(len(measurements) / (time.perf_counter() - started), 1),
        }
    output = {
        "meshes": {m: checksum(folder / f"{m}.nav.zip") for m in ("drive", "walk")},
        "workers": report,
    }
    (folder / "api-benchmark.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8817)
    args = parser.parse_args()
    run(args.folder, args.port)
