"""Recheck the cross-world itinerary against source collision and the published problem locations."""

import argparse
import json
import math
from contextlib import ExitStack
from pathlib import Path

import numpy as np

from scripts.pilot.world_map_lab.check_route_support import support
from scripts.pilot.world_map_lab.world_navmesh import Network, checksum


def run(folder):
    journey = folder / "journey"
    route = json.loads((journey / "route.json").read_bytes())
    review = json.loads((folder / "review.json").read_bytes())
    previous = json.loads((folder / "fixed-pair-recheck.json").read_bytes())
    result = {"routeSha256": checksum(journey / "route.json"), "legs": [], "sites": [], "pairs": {}}
    with ExitStack() as stack:
        nets = {mode: stack.enter_context(Network(folder, mode)) for mode in ("walk", "drive")}
        if any(n.meta["placementRevision"] != route["revision"] for n in nets.values()):
            raise ValueError("scene revision mismatch")
        for mode, net in nets.items():
            if net.meta != review["summary"][mode]["manifest"]:
                raise ValueError("review revision mismatch")
            result["pairs"][mode] = [
                {
                    "index": i,
                    "status": net.route(row["start"], row["end"])["status"],
                    "previous": row["after"],
                }
                for i, row in enumerate(previous[mode]["pairs"], 1)
            ]
        for site in review["sites"]:
            result["sites"].append(
                {
                    "id": site["id"],
                    "status": nets[site["mode"]].route(*site["anchors"])["status"],
                    "previous": site["after"]["status"],
                    "category": site["category"],
                }
            )
        samples = []
        cuts = []
        for leg in route["legs"]:
            path = np.asarray(leg["path"])
            arc = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))]
            positions = np.linspace(0.0, arc[-1], math.ceil(arc[-1] / 8) + 1)
            xyz = np.stack([np.interp(positions, arc, axis) for axis in path.T], axis=1)
            cuts.append((len(samples), len(samples) + len(xyz)))
            samples.extend(xyz)
        heights = support(samples, folder, nets["walk"].meta["bounds"])
        for (lo, hi), leg in zip(cuts, route["legs"], strict=True):
            errors = heights[lo:hi]
            valid = [e for e in errors if e is not None]
            result["legs"].append(
                dict(
                    mode=leg["mode"],
                    samples=len(errors),
                    withinHalf=sum(e <= 0.5 for e in valid),
                    p95=float(np.percentile(valid, 95)) if valid else None,
                    exceptions=[
                        {"position": samples[lo + i].tolist(), "error": e}
                        for i, e in enumerate(errors)
                        if e is None or e > 0.5
                    ],
                )
            )
    (journey / "surface-audit.json").write_text(json.dumps(result, indent=2), encoding="utf8")
    print(
        [(leg["samples"], leg["withinHalf"]) for leg in result["legs"]],
        sum(r["previous"] != r["status"] for r in result["sites"]),
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--folder", required=True, type=Path)
    run(p.parse_args().folder)
