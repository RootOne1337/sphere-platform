"""Re-estimate SfM reference camera pose from its own recorded 2D/3D tracks.

An internal numerical consistency check, not an independent pose or road test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from pathlib import Path

from motor_worker.route_localization import SIZE, RouteLocalizer, SparseRoute
from scripts.pilot.atomic_json import write_json
from scripts.pilot.reconstruct_route import checkpoint


def run(model, route_file, route_sha, output):
    import cv2
    import numpy as np
    import pycolmap

    cv2.setNumThreads(4)
    cv2.setRNGSeed(17)
    model, output = Path(model), Path(output)
    checkpoint(output.parent)
    if output.exists():
        raise FileExistsError(output)
    route = SparseRoute.load(route_file, sha256=route_sha)
    files = sorted(model.glob("*.bin"))

    def hashes():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}

    before = hashes()
    rec = pycolmap.Reconstruction(model)
    localizer = RouteLocalizer(
        route,
        capture_epoch=str(uuid.uuid4()),
        episode_id=str(uuid.uuid4()),
        goal_revision=str(uuid.uuid4()),
        diagnostic_partial_map=True,
        candidate_limit=5,
    )
    output.mkdir()
    write_json(
        output / "intent.json", {"scope": "offline_model_self_consistency", "physical_actions": 0}
    )
    results = []
    for n, image in enumerate(sorted(rec.images.values(), key=lambda im: im.name)):
        if n % 8 == 0:
            checkpoint(output)
        camera = rec.cameras[image.camera_id]
        observations = [
            p
            for p in image.points2D
            if p.has_point3D() and len(rec.points3D[p.point3D_id].track.elements) >= 3
        ]
        xyz = np.asarray(
            [rec.points3D[p.point3D_id].xyz for p in observations], np.float64
        ).reshape(-1, 3)
        xy = np.asarray([p.xy for p in observations], np.float64).reshape(-1, 2)
        xy *= np.asarray([SIZE[0] / camera.width, SIZE[1] / camera.height])
        result = localizer._verify_correspondences(xyz, xy) if len(xyz) >= 24 else None
        original = image.cam_from_world().inverse().translation
        difference = None if result is None else float(np.linalg.norm(result[0] - original))
        results.append(
            {
                "image": image.name,
                "observations": len(observations),
                "pnp_passed": result is not None,
                "inliers": None if result is None else result[2],
                "center_difference_units": difference,
            }
        )
    if before != hashes():
        raise ValueError("self_pnp_model_changed")
    write_json(
        output / "report.json",
        {
            "schema": "sphere-sfm-self-pnp-v1",
            "samples": results,
            "source_model_sha256": before,
            "same_model": True,
            "ground_truth": False,
            "physical_actions": 0,
            "execution_qualified": False,
        },
    )
    return results


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("model", "route", "sha", "output"):
        p.add_argument("--" + name, required=True)
    a = p.parse_args()
    r = run(a.model, a.route, a.sha, a.output)
    print(json.dumps({"images": len(r), "pnp_passed": sum(s["pnp_passed"] for s in r)}))


if __name__ == "__main__":
    main()
