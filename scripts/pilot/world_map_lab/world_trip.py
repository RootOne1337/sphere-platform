"""Static drive-to-walk itineraries on independently connected navigation surfaces."""

import math

import numpy as np
from scipy.spatial import cKDTree


class TripPlanner:
    def __init__(self, networks, folder):
        self.drive, self.walk = networks["drive"], networks["walk"]
        with np.load(folder / "drive-faces.npz", allow_pickle=False) as cache:
            if str(cache["geometry"]) != self.drive.meta["geometrySha256"]:
                raise ValueError("drive index does not match loaded mesh")
            if "mesh" in cache:
                from scripts.pilot.world_map_lab.world_navmesh import checksum

                if str(cache["mesh"]) != checksum(folder / "drive.nav.zip"):
                    raise ValueError("stale road index")
            faces = cache["faces"]
            if len(faces) != self.drive.meta["polygons"] or (
                self.drive.labels is not None
                and not np.array_equal(faces["group"], self.drive.labels)
            ):
                raise ValueError("stale component assignments")
        # Polygon centres propose transfers. Both legs still need full Detour paths.
        self.centers = faces["xyz"].sum(axis=1) / faces["vertices"][:, None]
        self.groups = faces["group"]
        self.tree = cKDTree(self.centers)
        self.indexes = {}
        ordered = np.argsort(self.groups, kind="stable")
        for rows in np.split(ordered, 1 + np.flatnonzero(np.diff(self.groups[ordered]))):
            group = self.groups[rows[0]]
            if len(rows) >= 4:
                self.indexes[int(group)] = (rows, cKDTree(self.centers[rows]))

    @staticmethod
    def leg(mode, route):
        return {"mode": mode, "length": route["length"], "path": route["path"]}

    def route(self, start, end, vehicle=None):
        if vehicle is None:
            return self.from_vehicle(start, end, allow_walk=True)
        if np.shape(vehicle) != (3,) or not np.isfinite(vehicle).all():
            raise ValueError("expected finite vehicle XYZ")
        unavailable = {"status": "no_itinerary", "legs": [], "length": 0.0, "path": []}
        ds = [z for z in self.drive.levels(*vehicle[:2]) if abs(z - vehicle[2]) <= 0.375]
        if not ds:
            return unavailable
        dz = min(ds, key=lambda z: abs(z - vehicle[2]))
        ws = [h for h in self.walk.levels(*vehicle[:2]) if abs(h - dz) <= 0.375]
        if not ws:
            return unavailable
        first = self.walk.route(start, [*vehicle[:2], min(ws, key=lambda h: abs(h - dz))])
        if first["status"] != "complete":
            return unavailable
        onward = self.from_vehicle([*vehicle[:2], dz], end, allow_walk=False)
        if onward["status"] != "complete":
            return unavailable
        if first["length"] > 0.01:
            onward["legs"].insert(0, self.leg("walk", first))
            onward["length"] += first["length"]
        return onward

    def from_vehicle(self, start, end, allow_walk):
        if len(start) != 3 or len(end) != 3 or not np.isfinite([start, end]).all():
            raise ValueError("finite XYZ needed for both endpoints")
        walk = self.walk.route(start, end) if allow_walk else {"status": "unavailable"}
        best = [self.leg("walk", walk)] if walk["status"] == "complete" else []
        score = walk["length"] if best else math.inf
        # Select only surfaces actually underneath the starting point.
        start_heights = [z for z in self.drive.levels(*start[:2]) if abs(z - start[2]) <= 0.5]
        if start_heights:
            start_drive = [*start[:2], min(start_heights, key=lambda h: abs(h - start[2]))]
            direct = self.drive.route(start_drive, end)
            if (
                direct["status"] == "complete"
                and direct["length"] / 3 < score
                and any(abs(z - end[2]) <= 0.5 for z in self.drive.levels(*end[:2]))
            ):
                best = [self.leg("drive", direct)]
                score = direct["length"] / 3
            _, nearest = self.tree.query(start_drive, k=min(12, len(self.centers)))
            candidates = []
            for group in dict.fromkeys(int(self.groups[i]) for i in np.atleast_1d(nearest)):
                if group not in self.indexes:
                    continue
                rows, tree = self.indexes[group]
                _, near = tree.query(end, k=min(48, len(rows)))
                points = []
                for i in np.atleast_1d(near):
                    center = self.centers[rows[i]]
                    if any(np.linalg.norm(center - p) < 12 for p in points):
                        continue
                    points.append(center)
                    if len(points) >= 4:
                        break
                candidates.extend(points)
            for point in candidates:
                x, y, z = map(float, point)
                ds = self.drive.levels(x, y)
                if not ds:
                    continue
                dz = min(ds, key=lambda level: abs(level - z))
                ws = [h for h in self.walk.levels(x, y) if abs(h - dz) <= 0.375]
                if not ws:
                    continue
                wz = min(ws, key=lambda level: abs(level - dz))
                drive_stop = [x, y, dz]
                walk_start = [x, y, wz]
                if (
                    np.linalg.norm(np.subtract(start_drive, drive_stop)) / 3
                    + np.linalg.norm(np.subtract(walk_start, end))
                    >= score
                ):
                    continue
                onward = self.walk.route(walk_start, end)
                if onward["status"] != "complete" or onward["length"] >= score:
                    continue
                first = self.drive.route(start_drive, drive_stop)
                if first["status"] != "complete":
                    continue
                cost = first["length"] / 3 + onward["length"]
                if cost < score:
                    best = [self.leg("drive", first), self.leg("walk", onward)]
                    score = cost
        return {
            "status": "complete" if best else "no_itinerary",
            "legs": best,
            "length": sum(leg["length"] for leg in best),
            "path": [],
        }
