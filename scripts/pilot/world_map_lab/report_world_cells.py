"""Build a local, clickable map of real browser render samples and original missing placements."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import numpy as np
from PIL import Image

from scripts.pilot.world_map_lab.inspect_world_cells import exterior_ocean_floor


def report(folder, surfaces):
    plan = json.loads((folder / "plan.json").read_bytes())
    audit = json.loads((folder / "fidelity.json").read_bytes())
    samples = json.loads((folder / "samples.json").read_bytes())
    summary = json.loads((folder / "result.json").read_bytes())
    comparison = folder / "source-vs-render.json"
    probes = {}
    if comparison.exists():
        for row in json.loads(comparison.read_bytes()):
            index = row["sample"]
            if row["cell"] != plan["sites"][index]["cell"] or index in probes:
                raise ValueError("source rays belong to another camera plan")
            hits = [q for q in row["probes"] if q["source"]]
            holes = [q["source"] for q in hits if q["suspect"]]
            probes[index] = {"tested": len(row["probes"]), "expected": len(hits), "holes": holes}
    findings = {}
    findings_file = folder / "findings.json"
    if findings_file.is_file():
        valid_cells = {tuple(s["cell"]) for s in plan["sites"]}
        for item in json.loads(findings_file.read_bytes()):
            cell = tuple(item["cell"])
            if cell not in valid_cells or cell in findings or not isinstance(item["text"], str):
                raise ValueError("invalid field finding for this camera plan")
            findings[cell] = item["text"]
    sites = [
        {
            **s,
            "oceanFloor": bool(exterior_ocean_floor(s["ground"])),
            "sample": samples.get(str(i)),
            "coverage": probes.get(i),
            "finding": findings.get(tuple(s["cell"])),
        }
        for i, s in enumerate(plan["sites"])
    ]
    keys = np.array([s["cell"] for s in sites] + plan["cellsWithoutSample"])
    lo = keys.min(axis=0) * 512
    hi = (keys.max(axis=0) + 1) * 512
    side = 1200
    dims = np.maximum(1, np.rint((hi - lo) * side / (hi - lo).max()).astype(int))
    pic = np.zeros((dims[1], dims[0], 3), np.uint8)
    pic[:] = [17, 29, 32]
    for file, color in zip(reversed(surfaces), [(45, 71, 72), (105, 150, 143)], strict=True):
        with np.load(file, allow_pickle=False) as f:
            if str(f["geometry"]) != plan["geometry"]:
                raise ValueError("wrong surface geometry")
            faces = f["faces"]
        # Polygon centroids give a stable light footprint for the underlying road/walk network.
        n = faces["vertices"]
        valid = np.arange(faces["xyz"].shape[1])[None, :] < n[:, None]
        xyz = (faces["xyz"][:, :, :2] * valid[:, :, None]).sum(axis=1) / n[:, None]
        xy = (xyz - lo) / (hi - lo)
        u = np.clip((xy[:, 0] * dims[0]).astype(int), 0, dims[0] - 1)
        v = np.clip(((1 - xy[:, 1]) * dims[1]).astype(int), 0, dims[1] - 1)
        layer = np.zeros(tuple(reversed(dims)), np.uint8)
        layer[v, u] = 255
        pic[cv2.dilate(layer, np.ones((2, 2), np.uint8)) > 0] = color
    Image.fromarray(pic).save(folder / "surfaces.png")
    outside = [g for g in audit["unavailableSourceRows"] if g["area"] == 0]
    data = json.dumps(
        dict(
            lo=lo.tolist(),
            hi=hi.tolist(),
            sites=sites,
            empty=plan["cellsWithoutSample"],
            gaps=outside,
            summary=summary,
            comparison=(folder / "streaming-comparison.jpg").is_file(),
            horizonComparison=(folder / "horizon-comparison.jpg").is_file(),
            placements=audit["runtimePlacements"],
            materialModels=audit["materials"]["counts"].get("modelsWithUnresolvedDraws", 0),
        ),
        ensure_ascii=False,
    ).replace("<", "\\u003c")
    template = Path(__file__).with_name("world_cell_report.html").read_text(encoding="utf8")
    (folder / "index.html").write_text(template.replace("WORLD_REPORT_DATA", data), encoding="utf8")


def publish(folder, destination):
    """Publish immutable gallery files first. Switch the index after every frame is in place."""
    source = folder.resolve(strict=True)
    html = (source / "index.html").read_bytes()
    samples = json.loads((source / "samples.json").read_bytes())
    files = {
        "index.html",
        "surfaces.png",
        "result.json",
        "fidelity.json",
        "samples.json",
        "plan.json",
    }
    files.update(
        name
        for name in (
            "source-vs-render.json",
            "streaming-comparison.jpg",
            "horizon-comparison.jpg",
            "findings.json",
        )
        if (source / name).is_file()
    )
    for row in samples.values():
        rel = Path(row["file"])
        resolved = (source / rel).resolve(strict=True)
        if (
            rel.is_absolute()
            or not resolved.is_relative_to(source)
            or resolved.suffix.lower() != ".jpg"
        ):
            raise ValueError("frame outside checked gallery")
        files.add(rel.as_posix())
    destination.mkdir(parents=True, exist_ok=True)
    fingerprint = hashlib.sha256()
    with TemporaryDirectory(dir=destination) as temp:
        staged = Path(temp) / "gallery"
        staged.mkdir()
        for name in sorted(files):
            content = (source / name).read_bytes()
            fingerprint.update(name.encode() + b"\0" + hashlib.sha256(content).digest())
            target = staged / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        release = "render-" + fingerprint.hexdigest()[:16]
        if not (destination / release).exists():
            os.replace(staged, destination / release)
        index = Path(temp) / "index.html"
        index.write_bytes(html.replace(b"<head>", f'<head><base href="{release}/">'.encode(), 1))
        os.replace(index, destination / "index.html")
    return release


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", type=Path)
    parser.add_argument("surfaces", type=Path, nargs=2)
    parser.add_argument("--publish-to", type=Path)
    args = parser.parse_args()
    report(args.suite, args.surfaces)
    if args.publish_to:
        print("published", publish(args.suite, args.publish_to))
