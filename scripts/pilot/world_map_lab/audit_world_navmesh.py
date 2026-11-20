"""Measure reachability, source-surface coverage and known gaps across the two world meshes."""

import argparse
import json
from collections import Counter
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np

from scripts.pilot.world_map_lab.collect_ariane_nav_geometry import DRIVE, FOOT, HEADER
from scripts.pilot.world_map_lab.world_navmesh import Network

# Fixed independent observations from the earlier source inspection, before this bake.
PROBES = {
    "Батырево": [
        (2041.2, 2853),
        (1997, 2785.8),
        (1941.4, 2711),
        (1901, 2659.1),
        (1845.4, 2605.4),
        (1956.7, 1626.2),
        (1954.8, 1754.8),
        (1563.1, 1718.3),
        (2598, 1895),
        (2087.3, 1900.7),
    ],
    "Южный": [
        (2111.2, -1737),
        (2111.2, -1863.8),
        (2193.8, -2007.8),
        (2285.9, -2157.5),
        (2065.1, -2253.5),
        (2099.7, -2315),
        (2067, -2411),
        (2065.1, -2468.6),
        (2224.5, -2568.4),
        (2687.2, -2579.9),
    ],
}


def projected_area(xyz):
    u = xyz[:, 1, :2] - xyz[:, 0, :2]
    v = xyz[:, 2, :2] - xyz[:, 0, :2]
    return np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]) * 0.5


def source_samples(folder, rng):
    data = np.memmap(folder / "world-geometry.bin", mode="r", dtype="u1")
    rows = {DRIVE: [], FOOT: []}
    cursor = 8
    while cursor < len(data):
        kind, n, *_ = HEADER.unpack_from(data, cursor)
        cursor += HEADER.size
        if kind in rows:
            rows[kind].append(np.ndarray((n, 3, 3), "<f4", data, cursor))
        cursor += 36 * n
    result = {}
    for kind, parts in rows.items():
        tri = np.concatenate(parts)
        areas = projected_area(tri).astype("f8")
        chosen = tri[rng.choice(len(tri), 1000, p=areas / areas.sum())]
        t = rng.random((len(chosen), 2))
        t[t.sum(axis=1) > 1] = 1 - t[t.sum(axis=1) > 1]
        result[kind] = (
            chosen[:, 0]
            + (chosen[:, 1] - chosen[:, 0]) * t[:, :1]
            + (chosen[:, 2] - chosen[:, 0]) * t[:, 1:]
        )
    return result


def inspect(folder, mode, samples):
    rng = np.random.default_rng(68129)
    with Network(folder, mode) as nav:
        with np.load(folder / f"{mode}-faces.npz", allow_pickle=False) as cache:
            if str(cache["geometry"]) != nav.meta["geometrySha256"]:
                raise ValueError("mesh and face cache have different source geometry")
            faces = cache["faces"]
        xyz = faces["xyz"]
        areas = np.zeros(len(faces))
        for j in range(1, 5):
            areas += projected_area(xyz[:, [0, j, j + 1]]) * (faces["vertices"] > j + 1)
        groups = np.bincount(faces["group"], weights=areas)
        main = groups.argmax()
        centers = xyz.sum(axis=1) / faces["vertices"][:, None]

        def surface(i):
            x, y, z = centers[i]
            heights = nav.levels(x, y)
            return [
                float(x),
                float(y),
                float(min(heights, key=lambda h: abs(h - z))) if heights else float(z),
            ]

        # Uniform by projected polygon area, includes disconnected components.
        choices = rng.choice(len(faces), size=(32, 2), p=areas / areas.sum())
        tests = []
        for a, b in choices:
            start, goal = surface(a), surface(b)
            tic = perf_counter()
            path = nav.route(start, goal)
            tests.append(
                {
                    "start": start,
                    "end": goal,
                    "status": path["status"],
                    "length": path["length"],
                    "ms": round((perf_counter() - tic) * 1000, 1),
                    "sameGroup": bool(faces["group"][a] == faces["group"][b]),
                }
            )
        # Test both extreme axes of the largest component, independently of path success.
        route_examples = []
        selected = np.flatnonzero((faces["group"] == main) & (areas > 1))
        for axis in (0, 1):
            xy = centers[selected, axis]
            a, b = surface(selected[xy.argmin()]), surface(selected[xy.argmax()])
            answer = nav.route(a, b)
            route_examples.append({"start": a, "end": b, **answer})
        missing = []
        for point in samples:
            heights = nav.levels(*point[:2])
            if not any(abs(h - point[2]) <= 0.65 for h in heights):
                missing.append(point.tolist())
        probes = {
            district: [{"xy": p, "heights": nav.levels(*p)} for p in points]
            for district, points in PROBES.items()
        }
        # A separate map layer shows exactly the polygons on which this planner can search.
        west, east, south, north = nav.meta["bounds"]
        width = 3200
        height = int(np.ceil((north - south) * width / (east - west)))
        mask = np.zeros((height, width), np.uint8)
        xx = xyz[:, :, :2].copy()
        xx[:, :, 0] = (xx[:, :, 0] - west) * width / (east - west)
        xx[:, :, 1] = (north - xx[:, :, 1]) * height / (north - south)
        pixels = np.rint(xx * 16).astype(np.int32)
        for i, vertices in enumerate(faces["vertices"]):
            cv2.fillConvexPoly(mask, pixels[i, :vertices], 255, shift=4)
        overlay = np.zeros((height, width, 4), np.uint8)
        overlay[mask > 0] = (219, 190, 48, 168) if mode == "drive" else (120, 204, 94, 138)
        if not cv2.imwrite(str(folder / f"{mode}-overlay.png"), overlay):
            raise OSError("failed to export navigation mask")
        return {
            "manifest": nav.meta,
            "components": int(np.sum(groups > 0)),
            "totalArea": float(areas.sum()),
            "largestComponentFraction": float(groups.max() / areas.sum()),
            "topComponentAreas": np.sort(groups)[-8:][::-1].tolist(),
            "pairs": tests,
            "outcomes": dict(Counter(row["status"] for row in tests)),
            "routeExamples": route_examples,
            "probes": probes,
            "sourceSamples": len(samples),
            "coveredSamples": len(samples) - len(missing),
            "rejectedSourceSamples": missing,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True)
    args = parser.parse_args()
    samples = source_samples(args.folder, np.random.default_rng(88211))
    result = {}
    for mode, source in (("drive", DRIVE), ("walk", FOOT)):
        result[mode] = inspect(args.folder, mode, samples[source])
        r = result[mode]
        print(mode, r["outcomes"], r["largestComponentFraction"], r["coveredSamples"], flush=True)
    (args.folder / "world-navigation-audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
