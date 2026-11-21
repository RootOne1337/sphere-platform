"""Fit text IPL placements and their scene-local LOD links in the browser game's tables."""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.pilot.world_map_lab.export_full_game_world import digest, source_file

MAX_INSTANCES = 4096
MAX_SCENES = 40


def requires_packing(scenes):
    return sum(scene["instances"] > 0 for scene in scenes) > MAX_SCENES or any(
        scene["instances"] > MAX_INSTANCES for scene in scenes
    )


def placements(path):
    rows = []
    inside = False
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.partition("#")[0].strip()
        if not line:
            continue
        if not inside and line.lower() == "inst":
            inside = True
        elif inside and line.lower() == "end":
            inside = False
        elif inside and line.count(",") == 10:
            payload, lod = line.rsplit(",", 1)
            rows.append((payload, int(lod)))
        else:
            raise ValueError(f"unsupported IPL section or row in {path.name}")
    if inside:
        raise ValueError(f"unterminated inst section in {path.name}")
    return rows


def lod_groups(targets):
    """Keep each LOD parent, all its children and all further descendants together."""
    roots = {}
    groups = defaultdict(list)
    for start in range(len(targets)):
        current = start
        chain = set()
        while current not in roots and targets[current] != -1:
            if current in chain:
                raise ValueError("cyclic scene-local LOD")
            chain.add(current)
            current = targets[current]
            if not 0 <= current < len(targets):
                raise ValueError("scene-local LOD outside scene")
        root = roots.get(current, current)
        roots[current] = root
        for child in chain:
            roots[child] = root
        groups[root].append(start)
    return groups.values()


def pack_scenes(folder, scenes, output):
    rows = []
    targets = []
    bins = []
    for scene in scenes:
        local = placements(source_file(folder, scene["packaged"]))
        if len(local) != scene["instances"] or sum(t >= 0 for _, t in local) != scene["lodLinks"]:
            raise ValueError(f"wrong placement counts in {scene['packaged']}")
        offset = len(rows)
        for group in lod_groups([t for _, t in local]):
            if len(group) > MAX_INSTANCES:
                raise ValueError("one LOD group exceeds the engine's scene capacity")
            for bucket in bins:
                if len(bucket) + len(group) <= MAX_INSTANCES:
                    break
            else:
                bucket = []
                bins.append(bucket)
            bucket.extend(offset + i for i in group)
        rows.extend(payload for payload, _ in local)
        targets.extend(offset + t if t >= 0 else -1 for _, t in local)
    if len(bins) > MAX_SCENES:
        raise ValueError(f"packing needs {len(bins)} scene tables, engine has {MAX_SCENES}")
    if sum(map(len, bins)) != len(rows):
        raise ValueError("incomplete placement packing")
    result = {}
    for number, bucket in enumerate(bins):
        bucket.sort()
        indices = {original: local for local, original in enumerate(bucket)}
        name = f"brp{number:03}.ipl"
        path = output / name
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write("inst\n")
            for original in bucket:
                target = targets[original]
                index = -1 if target < 0 else indices[target]
                stream.write(f"{rows[original]},{index}\n")
            stream.write("end\n")
        # Read the file as shipped. Recover every original target using the reverse
        # mapping, including identical model placements and shared LOD parents.
        for original, (payload, index) in zip(bucket, placements(path), strict=True):
            if index < -1 or index >= len(bucket):
                raise ValueError(f"invalid packed LOD index in {name}")
            if rows[original] != payload or targets[original] != (
                -1 if index == -1 else bucket[index]
            ):
                raise ValueError(f"placement or LOD target changed in {name}")
        result[name] = {"instances": len(bucket), "sha256": digest(path)}
    return result


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--world", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    folder = (args.world / "data/maps/brworld").resolve(strict=True)
    manifest = json.loads((args.world / "world-manifest.json").read_bytes())
    for scene in manifest["scenes"]:
        if digest(source_file(folder, scene["packaged"])) != scene["sha256"]:
            raise ValueError("source scene checksum mismatch")
    if args.output.exists():
        raise ValueError("choose a new output folder")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.output.parent) as temp:
        stage = Path(temp) / "scenes"
        stage.mkdir()
        result = pack_scenes(folder, manifest["scenes"], stage)
        proof = dict(
            sourceScenes=len(manifest["scenes"]),
            instances=manifest["instances"],
            lodLinks=manifest["lodLinks"],
            sourceWorld=digest(args.world / "world-manifest.json"),
            scenes=result,
            gameplayVerified=False,
        )
        (stage / "scene-check.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
        stage.rename(args.output)
    print(f"{len(result)} scenes, {sum(s['instances'] for s in result.values())} placements")
