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
    before, after = (course_gates(paths[i], spacing=3.0) for i in (0, 2))
    foot = "LOCATE_CHAR_ON_FOOT_3D scplayer"
    points = [(foot, before[0], (0.9, 0.9, 1.7))]
    points.extend((foot, p, (1.7, 1.7, 1.7)) for p in before[1:])
    first_road = len(points)
    points.extend(("LOCATE_CAR_3D scooter", p, (2.1, 2.1, 1.8)) for p in gates)
    last_road = len(points) - 1
    points.append((foot, after[0], (2.5, 2.5, 1.8)))
    points.extend((foot, p, (1.7, 1.7, 1.7)) for p in after[1:-1])
    points.append((foot, after[-1], (1.0, 1.0, 1.8)))
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
    code.extend(
        [
            f"IF stage > {first_road}",
            f"    IF stage <= {last_road}",
            "        IF NOT IS_CHAR_IN_CAR scplayer scooter",
            "            stage = -1",
            "        ENDIF",
            "    ENDIF",
            "ENDIF",
        ]
    )

    # At a point near the far end of a long trip, scan only the matching page.
    # Branches jump directly to that page, so the observer runs in logarithmic time.
    def emit(lo, hi):
        if hi - lo > 8:
            mid = (lo + hi) // 2
            code.extend([f"IF stage >= {mid}", f"    GOTO checkpoint_{mid}", "ENDIF"])
            emit(lo, mid)
            code.append(f"checkpoint_{mid}:")
            emit(mid, hi)
            return
        for n in range(lo, hi):
            op, point, bounds = points[n]
            coords = " ".join(f"{v:.5f}" for v in (*point, *bounds))
            code.extend([f"IF stage = {n}", f"    IF {op} {coords} 0"])
            if op.startswith("LOCATE_CAR"):
                code.append("        GOTO " + ("last_road_gate" if n == last_road else "road_gate"))
            else:
                code.append("        stage += 1")
                if n == len(points) - 1:
                    code.extend(["        PRINT_BIG M_PASS 5000 1", "        stage = -1"])
            code.append("    ENDIF")
            if op == foot:
                # A foot gate increments the stage here. Never consume a second gate this tick.
                code.append("    RETURN")
            code.append("ENDIF")
        code.append("RETURN")

    emit(0, len(points))
    code.extend(
        [
            "last_road_gate:",
            "IF NOT IS_CAR_STOPPED scooter",
            "    RETURN",
            "ENDIF",
            "road_gate:",
            "IF IS_CHAR_IN_CAR scplayer scooter",
            "    stage += 1",
            "ENDIF",
            "RETURN",
        ]
    )
    return "\n".join(code), len(gates)


def build(route, compiler, destination, world=None, *, actor_camera=False):
    paths, _, digest = native_route(route)
    world_binding = {}
    if world is not None:
        manifest = (world / "world-manifest.json").read_bytes()
        if json.loads(manifest).get("scope") != "all-active-source-scenes":
            raise ValueError("expected a full source world")
        world_binding["worldManifestSha256"] = hashlib.sha256(manifest).hexdigest()
    person, bike = spawn(paths[0]), spawn(paths[1])
    observer, gate_count = journey_observer(paths)
    if actor_camera:
        # Follow the pedestrian while walking and the chassis while riding.
        # The second vector is a local look-at point in CCam::Process_AttachedCam.
        # Looking at the zero vector from eye level points the lens at the feet.
        # A forward view two degrees below horizontal keeps the street landmarks in view.
        mount_view = "ATTACH_CAMERA_TO_VEHICLE scooter 0.0 0.46 1.22 0.0 8.5 0.94 0.0 1"
        foot_view = "ATTACH_CAMERA_TO_CHAR scplayer 0.0 0.28 0.65 0.0 9.0 0.47 0.0"
        camera_start = f"{foot_view} 2"
        camera_tick = f"""    SET_CHAR_VISIBLE scplayer 0
    seatedView = 0
    IF IS_CHAR_IN_CAR scplayer scooter
        seatedView = 1
    ELSE
        IF IS_CHAR_GETTING_IN_TO_A_CAR scplayer
            IF LOCATE_CHAR_ANY_MEANS_CAR_3D scplayer scooter 1.25 1.25 1.5 0
                seatedView = 1
            ENDIF
        ENDIF
    ENDIF
    IF seatedView = 1
        IF survey = 1
            {mount_view}
            survey = 0
        ENDIF
    ELSE
        IF survey = 0
            {foot_view} 2
            survey = 1
        ENDIF
    ENDIF"""
    else:
        camera_start = ""
        camera_tick = f"""    GET_OFFSET_FROM_CHAR_IN_WORLD_COORDS scplayer 0.0 0.20 0.66 eyeX eyeY eyeZ
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
    POINT_CAMERA_AT_POINT aimX aimY aimZ 2"""
    text = f"""VAR_INT player scplayer reserved0[7] player_group reserved1[255] reserved2[142] flag_player_on_mission
{{
LVAR_INT scooter stage survey seatedView
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
{camera_start}
DO_FADE 500 1
camera_loop:
    WAIT 0
    SET_CAR_DENSITY_MULTIPLIER 0.0
    SET_PED_DENSITY_MULTIPLIER 0.0
{camera_tick}
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
                "ATTACH_CAMERA_TO_CHAR" if actor_camera else "SET_FIXED_CAMERA_POSITION",
            )
        ):
            raise ValueError("compiled scenario failed instruction readback")
        if (
            ir.count("LOCATE_CAR_3D") != gate_count
            or ir.count("IS_CHAR_IN_CAR") != (3 if actor_camera else 2)
            or ir.count("IS_CAR_STOPPED") != 1
        ):
            raise ValueError("compiled native course markers differ from the selected road")
        if actor_camera and (
            ir.count("IS_CHAR_GETTING_IN_TO_A_CAR") != 1
            or ir.count("SET_CHAR_VISIBLE") != 1
            or ir.count("ATTACH_CAMERA_TO_CHAR") != 2
            or ir.count("ATTACH_CAMERA_TO_VEHICLE") != 1
            or any(
                op in ir
                for op in (
                    "SET_FIXED_CAMERA_POSITION",
                    "POINT_CAMERA_AT_POINT",
                    "SET_CHAR_COORDINATES",
                    "SET_CAR_COORDINATES",
                    "WARP_CHAR",
                )
            )
        ):
            raise ValueError("actor camera mission contains a forced motion or camera reset")
        # Confirm every gate position from the compiled game bytecode in driving order.
        stored = [
            line.split()[2:5] for line in ir.splitlines() if line.startswith("LOCATE_CAR_3D ")
        ]
        for actual, point in zip(stored, course_gates(paths[1]), strict=True):
            xyz = [float.fromhex(v.removesuffix("f")) for v in actual]
            if math.dist(xyz, point) > 0.001:
                raise ValueError("compiled driving checkpoint coordinates differ")
        walk_points = [*course_gates(paths[0], 3.0), *course_gates(paths[2], 3.0)]
        walk_rows = [
            line.split()[2:5]
            for line in ir.splitlines()
            if line.startswith("LOCATE_CHAR_ON_FOOT_3D ")
        ]
        for actual, point in zip(walk_rows, walk_points, strict=True):
            xyz = [float.fromhex(v.removesuffix("f")) for v in actual]
            if math.dist(xyz, point) > 0.001:
                raise ValueError("compiled walking checkpoint coordinates differ")
        if world_binding:
            raw = route.read_bytes()
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("route changed during compilation")
            (out / "sphere-route.json").write_bytes(raw)
        (out / "classic-scenario.json").write_text(
            json.dumps(
                {
                    **world_binding,
                    "routeSha256": digest,
                    "files": {
                        name: hashlib.sha256((out / name).read_bytes()).hexdigest()
                        for name in ("main.scm", "script.img")
                    },
                    "compilerSha256": hashlib.sha256(compiler.read_bytes()).hexdigest(),
                    "vehicleModel": 462,
                    "cameraMode": "attached-to-ped-or-vehicle"
                    if actor_camera
                    else "diagnostic-head-survey",
                    "orderedNativeRoadChecks": gate_count,
                    "orderedWalkingChecks": [len(course_gates(paths[i], 3.0)) for i in (0, 2)],
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
    parser.add_argument(
        "--world", type=Path, help="bind the chosen itinerary to an existing full world"
    )
    parser.add_argument(
        "--actor-camera",
        action="store_true",
        help="use forward-facing native pedestrian and vehicle cameras",
    )
    args = parser.parse_args()
    build(args.route, args.compiler, args.output, args.world, actor_camera=args.actor_camera)
