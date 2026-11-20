"""Index places where a pedestrian can board a vehicle on the same physical surface."""

import argparse
import tempfile
from contextlib import ExitStack
from pathlib import Path

import numpy as np

from scripts.pilot.world_map_lab.world_navmesh import Network, checksum


def build(folder, adapter):
    with ExitStack() as scope:
        walk, drive = (
            scope.enter_context(Network(folder, name, adapter=adapter))
            for name in ("walk", "drive")
        )
        if any(
            walk.meta[key] != drive.meta[key]
            for key in ("placementRevision", "geometrySha256", "bounds")
        ):
            raise ValueError("walking and driving surfaces must describe the same world")
        mesh = checksum(folder / "drive.nav.zip")
        faces = drive.faces()
        if not np.array_equal(faces["group"], drive.labels):
            raise ValueError("drive components differ from polygon labels")
        rows = []
        centers = faces["xyz"].sum(axis=1) / faces["vertices"][:, None]

        def transfer(x, y, z, group):
            levels = drive.levels(x, y)
            if not levels:
                return False
            height = min(levels, key=lambda h: abs(h - z))
            if abs(height - z) > 2 or drive.component([x, y, height]) != group:
                return False
            foot = [w for w in walk.levels(x, y) if abs(w - height) <= 0.375]
            if not foot:
                return False
            wz = min(foot, key=lambda h: abs(h - height))
            wc = walk.component([x, y, wz])
            if wc is None:
                return False
            rows.append((x, y, height, wz, group, wc))
            return True

        for i, ((x, y, z), face) in enumerate(zip(centers, faces, strict=True)):
            group = int(face["group"])
            if not transfer(x, y, z, group):
                for vertex in face["xyz"][: face["vertices"]]:
                    candidate = (centers[i] + vertex * 3) / 4
                    if transfer(*candidate, group):
                        break
        points = np.array(
            rows,
            dtype=[(k, "<f4") for k in ("x", "y", "dz", "wz")]
            + [(k, "<u4") for k in ("drive", "walk")],
        )
        with tempfile.NamedTemporaryFile(dir=folder, suffix=".npz", delete=False) as stream:
            tmp = Path(stream.name)
        try:
            np.savez_compressed(
                tmp,
                points=points,
                walkMesh=checksum(folder / "walk.nav.zip"),
                driveMesh=mesh,
                version=1,
            )
            tmp.replace(folder / "taxi-transfers.npz")
        finally:
            tmp.unlink(missing_ok=True)
        print(f"{len(points)} shared surfaces from {len(faces)} road polygons", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", required=True, type=Path)
    parser.add_argument("--adapter", type=Path)
    args = parser.parse_args()
    build(args.folder, args.adapter)
