"""Compile the offline Faggio acceptance fixture against the selected sa-engine SDK."""

import argparse
import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path

from scripts.pilot.world_map_lab.native_route import course_gates, native_route


def build(engine, journey, build_dir, cargo, route_file=None):
    sdk = (engine / "crates/sa-mod").resolve(strict=True)
    source = Path(__file__).with_name("native_scenario.rs")
    if route_file is None:
        trip = json.loads((journey / "city-trip.json").read_bytes())
        receipt = json.loads((journey / "city-ui-check.json").read_bytes())
        run = (journey / "runs" / receipt["id"]).resolve(strict=True)
        if run.parent != (journey / "runs").resolve():
            raise ValueError("invalid route directory")
        route_file = run / "route.json"
    else:
        trip = None
    (walk, drive, _), observed, route_hash = native_route(route_file)
    if trip is None:
        trip = observed
    elif any(math.dist(observed[k], trip[k]) > 0.4 for k in observed):
        raise ValueError("mixed route does not match the selected scenario")

    def heading(path):
        p = next((p for p in path[1:] if math.dist(path[0][:2], p[:2]) > 0.01), None)
        if p is None:
            raise ValueError("leg has no initial heading")
        return math.degrees(math.atan2(path[0][0] - p[0], p[1] - path[0][1]))

    park_heading, start_heading = heading(drive), heading(walk)
    project = build_dir / "fixture-src"
    (project / "src").mkdir(exist_ok=True, parents=True)
    (project / "Cargo.toml").write_text(
        '[workspace]\n[package]\nname="sphere-journey"\nversion="0.1.0"\nedition="2024"\n[lib]\ncrate-type=["cdylib"]\n[dependencies]\nsa-mod={path='
        + json.dumps(sdk.as_posix())
        + "}\n",
        encoding="utf8",
    )
    shutil.copyfile(source, project / "src/lib.rs")
    shutil.copyfile(source.with_name("native_progress.rs"), project / "src/native_progress.rs")
    coords = [
        f"const {name}:&[[f32;3]]=&["
        + ",".join("[" + ",".join(f"{v:.8f}" for v in p) + "]" for p in points)
        + "];"
        for name, points in (("ROAD", drive), ("GATES", course_gates(drive)))
    ]
    coords.append(f'const ROUTE_SHA256:&str="{route_hash}";')
    for field, name in (("start", "START"), ("vehicle", "PARK"), ("end", "GOAL")):
        pos = trip[field]
        if len(pos) != 3 or not all(map(math.isfinite, pos)):
            raise ValueError("invalid scenario location")
        coords.append(f"const {name}: [f32;3]=[" + ",".join(f"{p:.8f}" for p in pos) + "];")
    (project / "src/points.rs").write_text(
        "\n".join(coords)
        + f"\nconst PARK_HEADING:f32={park_heading:.8f};\nconst START_HEADING:f32={start_heading:.8f};\n",
        encoding="ascii",
    )
    target = build_dir / "fixture-target"
    subprocess.run(
        [
            str(cargo),
            "build",
            "--release",
            "--target",
            "wasm32-unknown-unknown",
            "--target-dir",
            str(target),
        ],
        cwd=project,
        check=True,
    )
    out = build_dir / "mods/sphere-journey"
    out.mkdir(exist_ok=True, parents=True)
    mod_file = out / "sphere_journey.wasm"
    shutil.copyfile(target / "wasm32-unknown-unknown/release/sphere_journey.wasm", mod_file)
    (out / "mod.toml").write_text(
        '[mod]\nid="sphere-journey"\nname="Local Faggio test"\nversion="0.1.0"\napi_version="1.16"\nentry="sphere_journey.wasm"\n[permissions]\nstate="write"\nentities=true\nscripts=true\ninput="read"\n',
        encoding="utf8",
    )
    print(
        json.dumps(
            dict(
                file=str(mod_file),
                sha256=hashlib.sha256(mod_file.read_bytes()).hexdigest(),
                routeSha256=route_hash,
                gameDriveVerified=False,
            )
        )
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "build-dir"):
        cli.add_argument("--" + name, type=Path, required=True)
    inputs = cli.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--journey", type=Path)
    inputs.add_argument("--route", type=Path)
    cli.add_argument("--cargo", default="cargo")
    args = cli.parse_args()
    build(args.engine, args.journey, args.build_dir, args.cargo, args.route)
