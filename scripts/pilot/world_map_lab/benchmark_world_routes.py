"""Compare cluster-guided and unrestricted routing on identical XYZs and one fixed mesh."""

import argparse
import json
from pathlib import Path
from time import perf_counter_ns

import numpy as np

from scripts.pilot.world_map_lab.world_navmesh import Network, checksum


def benchmark(folder, previous, rounds):
    controls = json.loads((previous / "fixed-pair-recheck.json").read_bytes())
    report = {}
    for mode in ("drive", "walk"):
        samples = {"cluster": [], "unrestricted": [], "previous": []}
        with Network(folder, mode) as nav, Network(previous, mode) as old:
            graph = nav.graph
            if not graph:
                raise ValueError("component index required")
            for iteration in range(rounds):
                for i, pair in enumerate(controls[mode]["pairs"]):
                    for name in (
                        ("previous", "cluster", "unrestricted")
                        if (iteration + i) % 2
                        else ("unrestricted", "cluster", "previous")
                    ):
                        net = old if name == "previous" else nav
                        nav.graph = graph if name == "cluster" else None
                        start = perf_counter_ns()
                        try:
                            r = net.route(pair["start"], pair["end"])
                        finally:
                            nav.graph = graph
                        ms = (perf_counter_ns() - start) / 1e6
                        snap = []
                        if r["path"]:
                            for target, actual in zip(
                                (pair["start"], pair["end"]),
                                (r["path"][0], r["path"][-1]),
                                strict=True,
                            ):
                                vec = np.subtract(target, actual)
                                snap.append([float(np.linalg.norm(vec[:2])), abs(float(vec[2]))])
                        samples[name].append(
                            {
                                "pair": i + 1,
                                "outcome": r["status"],
                                "length": round(r["length"], 2),
                                "ms": round(ms, 3),
                                "endpointError": snap,
                            }
                        )
        summary = {}
        for name, rows in samples.items():
            summary[name] = {}
            for status in ("complete", "disconnected", "endpoint_unavailable"):
                times = [r["ms"] for r in rows if r["outcome"] == status]
                if times:
                    summary[name][status] = dict(
                        n=len(times),
                        p50=round(float(np.median(times)), 2),
                        p95=round(float(np.percentile(times, 95)), 2),
                    )
        ratios = []
        for a, b in zip(samples["cluster"], samples["unrestricted"], strict=True):
            if a["outcome"] != b["outcome"]:
                raise ValueError("optimization changed reachability")
            if b["length"] > 1:
                ratios.append(a["length"] / b["length"])
        report[mode] = {
            "mesh": checksum(folder / f"{mode}.nav.zip"),
            "timing": summary,
            "lengthRatioMax": max(ratios),
            "lengthRatioMedian": float(np.median(ratios)),
            "runs": samples,
        }
        print(mode, summary, "max length ratio", max(ratios), flush=True)
    (folder / "route-benchmark.json").write_text(json.dumps(report), encoding="utf-8")


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--folder", required=True, type=Path)
    a.add_argument("--previous", required=True, type=Path)
    a.add_argument("--rounds", type=int, default=3)
    q = a.parse_args()
    benchmark(q.folder, q.previous, q.rounds)
