"""Render every frame of the local mixed trip and publish a seekable H.264 movie."""

import argparse
import base64
import hashlib
import json
import math
import os
import shutil
import subprocess
import time
from fractions import Fraction
from pathlib import Path

import av
from playwright.sync_api import sync_playwright


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def render(args):
    base = Path(__file__).parent
    folder = args.folder
    dest = args.attempt or folder
    route_hash = digest(folder / "route.json")
    payload = None
    model = "faggio"
    focal_at_640 = args.focal_at_640
    if args.attempt:
        stats = json.loads((dest / "rgb-drive.json").read_bytes())
        if focal_at_640 is None:
            focal_at_640 = stats.get("camera", {}).get("focalAt640")
        if focal_at_640 is not None and not 80 <= focal_at_640 <= 1200:
            raise ValueError("invalid focal length in trace")
        rows = [json.loads(line) for line in (dest / "telemetry.jsonl").read_bytes().splitlines()]
        if (
            not rows
            or rows != stats["rows"]
            or any(
                row["frame"] != i + 1 or abs(row["simTime"] - (i + 1) * 0.2) > 0.001
                for i, row in enumerate(rows)
            )
        ):
            raise ValueError("trace is incomplete or not bound to the result")
        model = (
            json.loads((dest / "settings.json").read_bytes())["model"]
            if (dest / "settings.json").is_file()
            else args.model
        )
        payload = dict(
            route=json.loads((dest / "route.json").read_bytes()),
            rows=rows,
            dt=0.2,
            result=stats["result"],
            title=args.title,
            eyeHeight=args.eye_height,
            verticalFov=(
                math.degrees(2 * math.atan(180 / focal_at_640))
                if focal_at_640 is not None
                else None
            ),
        )

    hashes = {
        p.name: digest(p)
        for p in (
            *(
                base / n
                for n in (
                    "journey_record.mjs",
                    "journey_dashboard.mjs",
                    "journey_scene.mjs",
                    "ariane_terrain_materials.mjs",
                    "journey_vehicle.mjs",
                    "journey_path.mjs",
                    "journey_app.mjs",
                )
            ),
            *(folder / n for n in ("horizon.bin", "terrain.jpg", model + ".glb", "vehicles.json")),
        )
    }
    if payload:
        hashes["telemetry.jsonl"] = digest(dest / "telemetry.jsonl")
        hashes["attemptRoute"] = digest(dest / "route.json")
    key = hashlib.sha256(
        json.dumps(
            [
                hashes,
                route_hash,
                args.width,
                args.height,
                args.bitrate,
                args.title,
                args.detail_radius,
                args.eye_height,
                focal_at_640,
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()[:16]
    chunks = dest / ("frames-" + key)
    chunks.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=args.chrome,
            args=[
                "--enable-gpu",
                "--use-angle=d3d11",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
            ],
        )
        page = browser.new_page(viewport={"width": args.width, "height": args.height})
        if payload:
            page.add_init_script(
                script="window.captureAttempt=" + json.dumps(payload, separators=(",", ":"))
            )
        page.goto(
            args.url.rstrip("/") + f"/explore?capture=1&model={model}&detail={args.detail_radius}",
            timeout=120000,
        )
        page.wait_for_function("window.journey || window.journeyError", timeout=180000)
        if message := page.evaluate("window.journeyError || null"):
            raise RuntimeError(message)
        served = page.evaluate(
            """async()=>Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",await(await fetch("/journey/route.json")).arrayBuffer())),b=>b.toString(16).padStart(2,"0")).join("")"""
        )
        if served != route_hash:
            raise ValueError("capture server is serving another route")
        if payload:
            page.evaluate((base / "journey_dashboard.mjs").read_text(encoding="utf8"))
        record = page.evaluate(
            (base / "journey_record.mjs").read_text(encoding="utf-8"),
            dict(width=args.width, height=args.height, fps=30, bitrate=args.bitrate),
        )
        if payload:
            phases = []
            for index, leg in enumerate(payload["route"]["legs"]):
                section = [r for r in payload["rows"] if r["phase"] == index]
                if section:
                    phases.append(
                        dict(
                            start=round(section[0]["simTime"] - payload["dt"], 4),
                            end=section[-1]["simTime"],
                            mode=leg["mode"],
                            length=leg.get("length"),
                        )
                    )
            record["legs"] = phases
        count = math.ceil(record["duration"] * 30) + 1
        print(json.dumps(record, ensure_ascii=False), "frames", count, flush=True)
        rows = []
        report_at = time.monotonic()
        for i in range(0, count, 120):
            path = chunks / f"{i:06}.h264"
            rows.append(path)
            if path.exists():
                continue
            data = page.evaluate("([i,n])=>recordFrames(i,n)", [i, min(120, count - i)])
            tmp = path.with_suffix(".partial")
            tmp.write_bytes(base64.b64decode(data, validate=True))
            tmp.replace(path)
            if time.monotonic() - report_at >= 10 or i == 0:
                print(min(i + 120, count), "/", count, flush=True)
                report_at = time.monotonic()
        browser.close()
    ff = shutil.which("ffmpeg")
    if ff is None:
        import imageio_ffmpeg

        ff = imageio_ffmpeg.get_ffmpeg_exe()
    temp = dest / "film.rendering.mp4"
    proc = subprocess.Popen(
        [
            ff,
            "-loglevel",
            "error",
            "-y",
            "-r",
            "30",
            "-f",
            "h264",
            "-i",
            "pipe:0",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-threads",
            "6",
            "-preset",
            "veryfast",
            "-crf",
            "21",
            "-bf",
            "0",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-t",
            str(count / 30),
            "-movflags",
            "+faststart",
            str(temp),
        ],
        stdin=subprocess.PIPE,
    )
    with proc.stdin:
        for path in rows:
            with path.open("rb") as part:
                shutil.copyfileobj(part, proc.stdin)
    if proc.wait():
        raise RuntimeError("mux failed")
    with av.open(str(temp)) as container:
        video = container.streams.video[0]
        if (
            video.frames != count
            or video.average_rate != 30
            or (video.width, video.height) != (args.width, args.height)
            or not container.streams.audio
        ):
            raise RuntimeError("movie verification failed")
        first = None
        for i, packet in enumerate(p for p in container.demux(video) if p.size):
            if first is None:
                first = packet.pts
            if (packet.pts - first) * video.time_base != Fraction(i, 30):
                raise RuntimeError("nonuniform frame clock")
        if i + 1 != count:
            raise RuntimeError("truncated video")
    record.update(
        routeSha256=hashes["attemptRoute"] if payload else route_hash,
        sceneRouteSha256=route_hash,
        sourceHashes=hashes,
        frames=count,
        fps=30,
        width=args.width,
        height=args.height,
        movieSha256=digest(temp),
        mode="recorded_rgb_control" if payload else "planned_motion_in_offline_scene",
        result=payload["result"] if payload else None,
        vehicle=model,
        detailRadius=args.detail_radius,
        eyeHeight=args.eye_height,
        focalAt640=focal_at_640,
    )
    temp.replace(dest / "film.mp4")
    receipt = dest / "film.partial.json"
    receipt.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    receipt.replace(dest / "film.json")
    for part in rows:
        part.unlink(missing_ok=True)
    if not any(chunks.iterdir()):
        chunks.rmdir()
    print(json.dumps(record, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--url", default="http://127.0.0.1:8817")
    cli.add_argument("--folder", required=True, type=Path)
    cli.add_argument("--attempt", type=Path)
    cli.add_argument("--title", default="Проезд по изображению")
    cli.add_argument("--model", choices=("faggio", "premier"), default="faggio")
    cli.add_argument("--width", default=1920, type=int)
    cli.add_argument("--height", default=1080, type=int)
    cli.add_argument("--bitrate", default=9000000, type=int)
    cli.add_argument("--detail-radius", default=320, type=int, choices=(320, 640, 960))
    cli.add_argument("--eye-height", default=1.68, type=float)
    cli.add_argument("--focal-at-640", type=float)
    cli.add_argument(
        "--chrome",
        default=str(
            Path(os.environ.get("ProgramFiles", "C:/Program Files"))
            / "Google/Chrome/Application/chrome.exe"
        ),
    )
    args = cli.parse_args()
    if not 0.8 <= args.eye_height <= 2.4 or (
        args.focal_at_640 is not None and not 80 <= args.focal_at_640 <= 1200
    ):
        cli.error("invalid recording camera calibration")
    render(args)
