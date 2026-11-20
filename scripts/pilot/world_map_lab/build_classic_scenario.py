"""Compile an original offline main.scm for the classic PC game and its normal controls."""

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.pilot.world_map_lab.native_route import course_gates, native_route


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


def journey_observer(paths):
    """Observe native ped/vehicle state after each engine tick without supplying inputs."""
    gates = course_gates(paths[1])
    # Only the active gate can advance. Returning to the start cannot finish a loop.
    points = [
        ("LOCATE_CHAR_ON_FOOT_3D scplayer", paths[0][0], (0.9, 0.9, 1.7)),
        ("LOCATE_CHAR_ON_FOOT_3D scplayer", paths[1][0], (1.7, 1.7, 1.7)),
    ]
    points.extend(("LOCATE_CAR_3D scooter", p, (2.1, 2.1, 1.8)) for p in gates)
    points.append(("LOCATE_CHAR_ON_FOOT_3D scplayer", paths[1][-1], (2.5, 2.5, 1.8)))
    points.append(("LOCATE_CHAR_ON_FOOT_3D scplayer", paths[2][-1], (1.0, 1.0, 1.8)))
    code = [
        "observe_course:",
        "IF stage < 0",
        "    RETURN",
        "ENDIF",
        "IF IS_CHAR_DEAD scplayer",
        "    stage = -1",
        "    RETURN",
        "ENDIF",
        "IF IS_CAR_DEAD scooter",
        "    stage = -1",
        "    RETURN",
        "ENDIF",
    ]
    last_road = len(points) - 3
    code.extend(
        [
            "IF stage > 2",
            f"    IF stage <= {last_road}",
            "        IF NOT IS_CHAR_IN_CAR scplayer scooter",
            "            stage = -1",
            "        ENDIF",
            "    ENDIF",
            "ENDIF",
        ]
    )
    for n, (op, p, bounds) in enumerate(points):
        coords = " ".join(f"{v:.5f}" for v in (*p, *bounds))
        code.extend([f"IF stage = {n}", f"    IF {op} {coords} 0"])
        if op.startswith("LOCATE_CAR"):
            code.append("        IF IS_CHAR_IN_CAR scplayer scooter")
            if n == last_road:
                code.extend(
                    [
                        "            IF IS_CAR_STOPPED scooter",
                        "                stage += 1",
                        "            ENDIF",
                    ]
                )
            else:
                code.append("            stage += 1")
            code.append("        ENDIF")
        else:
            code.append("        stage += 1")
            if n == len(points) - 1:
                code.extend(["        PRINT_BIG M_PASS 5000 1", "        stage = -1"])
        code.extend(["    ENDIF", "    RETURN", "ENDIF"])
    code.append("RETURN")
    return "\n".join(code), len(gates)


def build(route, compiler, destination):
    paths, _, digest = native_route(route)
    person, bike = spawn(paths[0]), spawn(paths[1])
    observer, gate_count = journey_observer(paths)
    text = f"""VAR_INT player scplayer reserved0[7] player_group reserved1[255] reserved2[142] flag_player_on_mission
{{
LVAR_INT scooter stage survey
LVAR_FLOAT eyeX eyeY eyeZ aimX aimY aimZ scanAngle lookSide
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
stage = 0
survey = 1
TIMERA = 0
DO_FADE 500 1
camera_loop:
    WAIT 0
    SET_CAR_DENSITY_MULTIPLIER 0.0
    SET_PED_DENSITY_MULTIPLIER 0.0
    GET_OFFSET_FROM_CHAR_IN_WORLD_COORDS scplayer 0.0 0.20 0.66 eyeX eyeY eyeZ
    lookSide = 0.0
    IF survey = 1
        IF LOCATE_CHAR_ON_FOOT_3D scplayer {person["position"]} 0.6 0.6 1.7 0
            IF TIMERA > 4800
                TIMERA = 0
            ENDIF
            CSET_LVAR_FLOAT_TO_LVAR_INT scanAngle TIMERA
            scanAngle *= 0.075
            SIN scanAngle lookSide
            lookSide *= 1.7
        ELSE
            survey = 0
        ENDIF
    ENDIF
    GET_OFFSET_FROM_CHAR_IN_WORLD_COORDS scplayer lookSide 7.0 0.58 aimX aimY aimZ
    SET_FIXED_CAMERA_POSITION eyeX eyeY eyeZ 0.0 0.0 0.0
    POINT_CAMERA_AT_POINT aimX aimY aimZ 2
GOSUB observe_course
GOTO camera_loop
{observer}
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
        if (
            ir.count("LOCATE_CAR_3D") != gate_count
            or ir.count("IS_CHAR_IN_CAR") != gate_count + 1
            or ir.count("IS_CAR_STOPPED") != 1
        ):
            raise ValueError("compiled native course markers differ from the selected road")
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
                    "orderedNativeRoadChecks": gate_count,
                    "arrivalVerified": False,
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
