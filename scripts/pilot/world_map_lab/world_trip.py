"""Static drive-to-walk itineraries on independently connected navigation surfaces."""

import math
from copy import deepcopy
from functools import lru_cache

import numpy as np
from scipy.spatial import cKDTree

from scripts.pilot.world_map_lab.world_navmesh import checksum


class TripPlanner:
    def __init__(self, networks, folder, *, walk_folder=None):
        self.drive, self.walk = networks["drive"], networks["walk"]
        with np.load(folder / "drive-faces.npz", allow_pickle=False) as cache:
            if str(cache["geometry"]) != self.drive.meta["geometrySha256"]:
                raise ValueError("drive index does not match loaded mesh")
            if "mesh" in cache:
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

        self._cached_taxi = lru_cache(maxsize=24)(self._plan_taxi)
        self.transfers = {}
        walk_folder = folder if walk_folder is None else walk_folder
        file = walk_folder / "taxi-transfers.npz"
        if walk_folder != folder and not file.is_file():
            raise ValueError("pedestrian release lacks its transfer index")
        if file.is_file():
            with np.load(file, allow_pickle=False) as cache:
                if int(cache["version"]) != 1 or any(
                    str(cache[key]) != checksum(mesh_file)
                    for key, mesh_file in (
                        ("walkMesh", walk_folder / "walk.nav.zip"),
                        ("driveMesh", folder / "drive.nav.zip"),
                    )
                ):
                    raise ValueError("taxi transfers belong to another world")
                portals = cache["points"]
            portals.sort(order=("walk", "drive"))
            cuts = (
                np.flatnonzero((np.diff(portals["walk"]) != 0) | (np.diff(portals["drive"]) != 0))
                + 1
            )
            for part in np.split(portals, cuts) if len(portals) else ():
                group = int(part["walk"][0])
                gid = int(part["drive"][0])
                positions = np.column_stack([part[k] for k in ("x", "y", "wz")])
                self.transfers.setdefault(group, {})[gid] = (
                    positions,
                    part["dz"],
                    cKDTree(positions) if len(part) > 24 else None,
                    positions.min(axis=0),
                    positions.max(axis=0),
                )

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

    def taxi(self, start, end):
        """Plan with a scooter that the offline scene can park at a reachable pickup."""
        if np.shape([start, end]) != (2, 3) or not np.isfinite([start, end]).all():
            raise ValueError("finite XYZ needed for both endpoints")
        return deepcopy(self._cached_taxi(tuple(start), tuple(end)))

    def _plan_taxi(self, start, end):
        for point in (start, end):
            if not any(abs(z - point[2]) <= 0.5 for z in self.walk.levels(*point[:2])):
                return {"status": "endpoint_unavailable", "legs": [], "length": 0.0, "path": []}
        if math.dist(start, end) < 0.01:
            return {"status": "already_there", "legs": [], "length": 0.0, "path": []}
        best = self.from_vehicle(start, end, allow_walk=True)

        def cost(plan):
            return (
                sum(leg["length"] / (3 if leg["mode"] == "drive" else 1) for leg in plan["legs"])
                if plan["legs"]
                else math.inf
            )

        score = cost(best)
        start_stands = self.transfers.get(self.walk.component(start), {})
        end_stands = self.transfers.get(self.walk.component(end), {})
        straight = math.dist(start, end)

        def lower_bound(point, stands):
            low, high = stands[3:]
            return math.dist(point, np.clip(point, low, high))

        # A connected ride must use one drive component, with each foot leg
        # on the component of its own endpoint. Reject unrelated levels first.
        groups = []
        for group in start_stands.keys() & end_stands.keys():
            foot = lower_bound(start, start_stands[group]) + lower_bound(end, end_stands[group])
            bound = max(foot, (straight + 2 * foot) / 3)
            if bound < score + 0.75:
                groups.append((bound, group))

        def nearest(stands, point):
            positions, heights, tree, *_ = stands
            near = (
                np.atleast_1d(tree.query(point, k=min(12, len(heights)))[1])
                if tree
                else np.argsort(np.linalg.norm(positions - point, axis=1))[:12]
            )
            choices = []
            for i in near:
                foot = positions[i].tolist()
                if any(math.dist(foot, p) < 4 for p, _ in choices):
                    continue
                choices.append((foot, [*foot[:2], float(heights[i])]))
                if len(choices) == 3:
                    break
            return choices

        walks = {}

        def walk_leg(a, b):
            key = (tuple(a), tuple(b))
            if key not in walks:
                walks[key] = self.walk.route(a, b)
            return walks[key]

        for bound, group in sorted(groups):
            if bound >= score + 0.75:
                break
            pickups = nearest(start_stands[group], start)
            drops = nearest(end_stands[group], end)
            options = sorted(
                (
                    math.dist(start, pickup_foot)
                    + math.dist(pickup_road, dropoff_road) / 3
                    + math.dist(dropoff_foot, end),
                    pickup_index,
                    dropoff_index,
                )
                for pickup_index, (pickup_foot, pickup_road) in enumerate(pickups)
                for dropoff_index, (dropoff_foot, dropoff_road) in enumerate(drops)
            )
            for optimistic, pickup_index, dropoff_index in options:
                if optimistic >= score + 0.75:
                    break
                pickup_foot, pickup_road = pickups[pickup_index]
                dropoff_foot, dropoff_road = drops[dropoff_index]
                if math.dist(pickup_road, dropoff_road) < 0.5:
                    continue
                first = walk_leg(start, pickup_foot)
                if first["status"] != "complete":
                    continue
                # Once the first real path is known, straight-line distances
                # for the remaining legs can rule the alternative out cheaply.
                drive_lower = math.dist(pickup_road, dropoff_road) / 3
                if first["length"] + drive_lower + math.dist(dropoff_foot, end) >= score + 0.75:
                    continue
                last = walk_leg(dropoff_foot, end)
                if (
                    last["status"] != "complete"
                    or first["length"] + last["length"] + drive_lower >= score + 0.75
                ):
                    continue
                middle = self.drive.route(pickup_road, dropoff_road)
                if middle["status"] != "complete" or middle["length"] < 0.5:
                    continue
                legs = [
                    self.leg(mode, r)
                    for mode, r in (("walk", first), ("drive", middle), ("walk", last))
                    if r["length"] > 0.01
                ]
                value = first["length"] + middle["length"] / 3 + last["length"]
                if value < score:
                    score = value
                    best = {
                        "status": "complete",
                        "legs": legs,
                        "length": sum(leg["length"] for leg in legs),
                        "path": [],
                    }
        if not best["legs"] and self.transfers:
            best["reason"] = (
                "no_walk_to_road"
                if not start_stands
                else "no_road_to_goal"
                if not end_stands
                else "no_common_road"
                if not start_stands.keys() & end_stands.keys()
                else "transfer_path_unavailable"
            )
        road = next((leg for leg in best["legs"] if leg["mode"] == "drive"), None)
        if road:
            best["pickup"] = road["path"][0]
            best["dropoff"] = road["path"][-1]
        return best

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
