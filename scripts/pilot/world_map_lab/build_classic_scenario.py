"""Compile an original offline main.scm for the classic PC game and its normal controls."""

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.pilot.world_map_lab.native_route import native_route


def spawn(path):
    x, y, z = path[0]
    p = next((p for p in path[1:] if math.hypot(p[0] - x, p[1] - y) > 0.01), None)
    if p is None:
        raise ValueError("no initial heading")
    return {
        "position": f"{x:.5f} {y:.5f} {z + 0.6:.5f}",
        "xy": f"{x:.5f} {y:.5f}",
        "heading": f"{math.degrees(math.atan2(x - p[0], p[1] - y)):.5f}",
    }


def build(route, compiler, destination):
    paths, _, digest = native_route(route)
    person, bike = spawn(paths[0]), spawn(paths[1])
    text = f"""VAR_INT player scplayer reserved0[7] player_group reserved1[255] reserved2[142] flag_player_on_mission
{{
LVAR_INT scooter
LVAR_FLOAT eyeX eyeY eyeZ aimX aimY aimZ
SCRIPT_NAME BRTEST
DO_FADE 0 0
SET_AREA_VISIBLE 0
SET_TIME_OF_DAY 12 0
FORCE_WEATHER_NOW 1
REQUEST_COLLISION {person["xy"]}
REQUEST_COLLISION {bike["xy"]}
LOAD_SCENE {person["position"]}
REQUEST_MODEL 462
LOAD_ALL_MODELS_NOW
CREATE_PLAYER 0 {person["position"]} player
GET_PLAYER_CHAR player scplayer
GET_PLAYER_GROUP player player_group
GIVE_PLAYER_CLOTHES_OUTSIDE_SHOP player VEST VEST 0
GIVE_PLAYER_CLOTHES_OUTSIDE_SHOP player JEANSDENIM JEANS 2
GIVE_PLAYER_CLOTHES_OUTSIDE_SHOP player SNEAKERBINCBLK SNEAKER 3
BUILD_PLAYER_MODEL player
SET_CHAR_HEADING scplayer {person["heading"]}
CREATE_CAR 462 {bike["position"]} scooter
SET_CAR_HEADING scooter {bike["heading"]}
MARK_MODEL_AS_NO_LONGER_NEEDED 462
SET_PLAYER_CONTROL player 1
DO_FADE 500 1
camera_loop:
    WAIT 0
    SET_CAR_DENSITY_MULTIPLIER 0.0
    SET_PED_DENSITY_MULTIPLIER 0.0
    GET_OFFSET_FROM_CHAR_IN_WORLD_COORDS scplayer 0.0 0.20 0.66 eyeX eyeY eyeZ
    GET_OFFSET_FROM_CHAR_IN_WORLD_COORDS scplayer 0.0 7.0 0.58 aimX aimY aimZ
    SET_FIXED_CAMERA_POSITION eyeX eyeY eyeZ 0.0 0.0 0.0
    POINT_CAMERA_AT_POINT aimX aimY aimZ 2
GOTO camera_loop
}}
"""
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as tmp:
        out = Path(tmp) / "scenario"
        out.mkdir()
        (out / "main.sc").write_text(text, encoding="ascii")
        for mode, src, dst in (
            ("compile", "main.sc", "main.scm"),
            ("decompile", "main.scm", "main.ir2"),
        ):
            subprocess.run(
                [
                    str(compiler.resolve(strict=True)),
                    mode,
                    "--config=gtasa",
                    "--guesser",
                    *(["-emit-ir2"] if mode == "decompile" else []),
                    src,
                    "-o",
                    dst,
                ],
                cwd=out,
                check=True,
            )
        ir = (out / "main.ir2").read_text(encoding="utf8")
        if not all(
            op in ir
            for op in (
                "CREATE_PLAYER",
                "CREATE_CAR",
                "SET_PLAYER_CONTROL",
                "SET_FIXED_CAMERA_POSITION",
            )
        ):
            raise ValueError("compiled scenario failed instruction readback")
        (out / "classic-scenario.json").write_text(
            json.dumps(
                {
                    "routeSha256": digest,
                    "files": {
                        name: hashlib.sha256((out / name).read_bytes()).hexdigest()
                        for name in ("main.scm", "script.img")
                    },
                    "compilerSha256": hashlib.sha256(compiler.read_bytes()).hexdigest(),
                    "vehicleModel": 462,
                    "gameDriveVerified": False,
                },
                indent=2,
            ),
            encoding="utf8",
        )
        out.rename(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("route", "compiler", "output"):
        parser.add_argument("--" + key, required=True, type=Path)
    args = parser.parse_args()
    build(args.route, args.compiler, args.output)
