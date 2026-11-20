"""Compile the offline Faggio acceptance fixture against the selected sa-engine SDK."""

import argparse
import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path


def build(engine, journey, build_dir, cargo):
    sdk = (engine / "crates/sa-mod").resolve(strict=True)
    source = Path(__file__).with_name("native_scenario.rs")
    trip = json.loads((journey / "city-trip.json").read_bytes())
    receipt = json.loads((journey / "city-ui-check.json").read_bytes())
    run = (journey / "runs" / receipt["id"]).resolve(strict=True)
    if run.parent != (journey / "runs").resolve():
        raise ValueError("invalid route directory")
    route = json.loads((run / "route.json").read_bytes())
    drive = next(leg for leg in route["legs"] if leg["mode"] == "drive")["path"]
    delta = [b - a for a, b in zip(drive[0], drive[1])]
    heading = math.degrees(math.atan2(-delta[0], delta[1]))
    walk = route["legs"][0]["path"]
    if route["legs"][0]["mode"] != "walk" or math.dist(walk[0], trip["start"]) > 0.4:
        raise ValueError("unexpected initial pedestrian leg")
    first = next((p for p in walk[1:] if math.dist(walk[0][:2], p[:2]) > 0.01), None)
    if first is None:
        raise ValueError("initial pedestrian direction unavailable")
    start_heading = math.degrees(math.atan2(walk[0][0] - first[0], first[1] - walk[0][1]))
    project = build_dir / "fixture-src"
    (project / "src").mkdir(exist_ok=True, parents=True)
    (project / "Cargo.toml").write_text(
        '[workspace]\n[package]\nname="sphere-journey"\nversion="0.1.0"\nedition="2024"\n[lib]\ncrate-type=["cdylib"]\n[dependencies]\nsa-mod={path='
        + json.dumps(sdk.as_posix())
        + "}\n",
        encoding="utf8",
    )
    shutil.copyfile(source, project / "src/lib.rs")
    if (
        math.dist(drive[0], trip["vehicle"]) > 0.4
        or math.dist(route["legs"][-1]["path"][-1], trip["end"]) > 0.4
    ):
        raise ValueError("mixed route does not match the selected scenario")
    coords = [
        "const ROAD:&[[f32;3]]=&["
        + ",".join("[" + ",".join(f"{v:.8f}" for v in p) + "]" for p in drive)
        + "];"
    ]
    for field, name in (("start", "START"), ("vehicle", "PARK"), ("end", "GOAL")):
        pos = trip[field]
        if len(pos) != 3 or not all(map(math.isfinite, pos)):
            raise ValueError("invalid scenario location")
        coords.append(f"const {name}: [f32;3]=[" + ",".join(f"{p:.8f}" for p in pos) + "];")
    (project / "src/points.rs").write_text(
        "\n".join(coords)
        + f"\nconst PARK_HEADING:f32={heading:.8f};\nconst START_HEADING:f32={start_heading:.8f};\n",
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
                gameDriveVerified=False,
            )
        )
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "journey", "build-dir"):
        cli.add_argument("--" + name, type=Path, required=True)
    cli.add_argument("--cargo", default="cargo")
    args = cli.parse_args()
    build(args.engine, args.journey, args.build_dir, args.cargo)
