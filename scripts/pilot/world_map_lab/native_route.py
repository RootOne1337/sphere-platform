"""Read one walk, Faggio and walk itinerary shared by the map exporter and gameplay fixture."""

import hashlib
import json
import math


def native_route(file):
    raw = file.read_bytes()
    legs = json.loads(raw)["legs"]
    if [leg["mode"] for leg in legs] != ["walk", "drive", "walk"]:
        raise ValueError("native Faggio scenario requires walk, drive, walk")
    paths = [leg["path"] for leg in legs]
    for path in paths:
        if len(path) < 2 or any(len(p) != 3 or not all(map(math.isfinite, p)) for p in path):
            raise ValueError("each native leg needs finite 3D positions")
        if sum(math.dist(a, b) for a, b in zip(path, path[1:])) < 1:
            raise ValueError("leg shorter than one unit")
    if any(math.dist(left[-1], right[0]) > 0.4 for left, right in zip(paths, paths[1:])):
        raise ValueError("native route has a gap at a transfer")
    trip = dict(start=paths[0][0], vehicle=paths[1][0], end=paths[2][-1])
    return paths, trip, hashlib.sha256(raw).hexdigest()


def course_gates(road, spacing=6.0):
    gates = [road[0]]
    station = 0.0
    next_gate = spacing
    for a, b in zip(road, road[1:]):
        length = math.dist(a, b)
        while length > 0 and next_gate <= station + length:
            t = (next_gate - station) / length
            gates.append([u + t * (v - u) for u, v in zip(a, b)])
            next_gate += spacing
        station += length
    if math.dist(gates[-1], road[-1]) > 0.01:
        gates.append(road[-1])
    return gates
