"""Record the first-person canvas of a local sa-engine scenario, preserving source timestamps."""

import argparse
import base64
import hashlib
import json
import math
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from playwright.sync_api import sync_playwright

READY = "() => {const s=window.saGame?.status;return s?.state===9 && s.presents>0 && !s.error && !s.inMenu}"
PHASES = ("start", "boarded", "parked_and_exited", "goal_on_foot")
SAMPLE = re.compile(
    r"sphere_truth t=(\d+) pos=([\d.+-]+),([\d.+-]+),([\d.+-]+) mounted=(true|false) health=([\d.+-]+) head=(true|false)"
)
CAPTURE = """async binding => {
    const stream = document.querySelector('#screen').captureStream(30);
    const mimeType = ['video/webm;codecs=vp8', 'video/webm;codecs=vp9'].find(t => MediaRecorder.isTypeSupported(t));
    // Chrome can skip about a second on the first offscreen-canvas capture.
    // Exercise the same track before F6; the warm-up never enters the film.
    const options = {mimeType, videoBitsPerSecond: 8000000};
    const warmup = new MediaRecorder(stream, options);
    warmup.start(250);
    await new Promise(done => setTimeout(done, 2100));
    await new Promise(done => { warmup.onstop = done; warmup.stop(); });
    const rec = new MediaRecorder(stream, options);
    let written = Promise.resolve();
    rec.ondataavailable = e => {
        if (!e.data.size) return;
        written = written.then(async () => {
            const buf = new Uint8Array(await e.data.arrayBuffer());
            let s = '';
            for (let i=0;i<buf.length;i+=32768) s += String.fromCharCode(...buf.subarray(i,i+32768));
            await window[binding](btoa(s));
        });
    };
    window.sphereStopVideo = () => new Promise((resolve,reject) => {
        rec.onstop = () => {stream.getTracks().forEach(t=>t.stop()); written.then(resolve,reject)};
        rec.stop();
    });
    rec.start(1000);
}"""


def validate(events):
    phase = -1
    points = [[], [], []]
    previous = None
    goal_sample = False
    rode_course = False
    for event in events:
        line = event["line"]
        found = re.search(r"sphere_scenario event=(\w+)", line)
        if found:
            name = found[1]
            if name in (
                "unplanned_dismount",
                "camera_command_failed",
                "ground_or_vehicle_not_loaded",
            ):
                raise ValueError(name)
            if name == "drive_route_complete":
                if phase != 1 or rode_course:
                    raise ValueError("out-of-order course completion")
                rode_course = True
            if name == "parked_and_exited" and not rode_course:
                raise ValueError("unverified progress along the selected driving route")
            if name in PHASES:
                if phase + 1 >= len(PHASES) or PHASES[phase + 1] != name:
                    raise ValueError("out-of-order native event " + name)
                phase += 1
        if "sphere_truth " in line and phase >= 0:
            sample = SAMPLE.search(line)
            if not sample:
                raise ValueError("invalid observer sample")
            stamp, x, y, z, mounted, health, head = sample.groups()
            stamp = int(stamp)
            if previous is not None and not 0 < stamp - previous <= 1500:
                raise ValueError("discontinuous game samples")
            previous = stamp
            if head != "true" or float(health) <= 0 or (mounted == "true") != (phase == 1):
                raise ValueError("observer lost first person, health or vehicle")
            goal_sample = phase == 3
            points[min(phase, 2)].append(tuple(map(float, (x, y, z))))
    if phase != 3 or not goal_sample:
        raise ValueError("incomplete journey: " + ", ".join(PHASES[: phase + 1]))
    lengths = [sum(math.dist(a, b) for a, b in zip(p, p[1:])) for p in points]
    if min(lengths) < 1:
        raise ValueError("movement missing from a walking or driving leg")
    return lengths


def encode(source, dest):
    import av
    from imageio_ffmpeg import get_ffmpeg_exe

    with av.open(str(source)) as file:
        stamps = [
            None if f.pts is None else float(f.pts * f.time_base) for f in file.decode(video=0)
        ]
    if None in stamps or any(b < a for a, b in zip(stamps, stamps[1:])):
        raise ValueError("missing or decreasing capture timestamps")
    times = list(dict.fromkeys(stamps))
    if len(times) < 2:
        raise ValueError("invalid capture timestamps")
    subprocess.run(
        [
            shutil.which("ffmpeg") or get_ffmpeg_exe(),
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-vf",
            "select='isnan(prev_selected_pts)+gt(pts,prev_selected_pts)',pad=ceil(iw/2)*2:ceil(ih/2)*2",
            "-enc_time_base",
            "1:1000",
            "-fps_mode",
            "vfr",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(dest),
        ],
        check=True,
    )
    with av.open(str(dest)) as file:
        encoded = sum(1 for _ in file.decode(video=0))
    if encoded != len(times):
        raise ValueError("transcode changed the number of captured frames")
    return dict(
        frames=encoded,
        coincidentSourceFrames=len(stamps) - len(times),
        seconds=times[-1] - times[0],
        sourceFps=(len(times) - 1) / (times[-1] - times[0]),
        maxFrameGap=max(b - a for a, b in zip(times, times[1:])),
    )


def capture(page, folder, timeout, start_scene):
    folder.mkdir(parents=True, exist_ok=False)
    events = []
    started = time.monotonic()

    def observe(msg):
        line = msg.text
        if "sphere_scenario " in line or "sphere_truth " in line:
            events.append(dict(elapsed=time.monotonic() - started, line=line))

    page.on("console", observe)
    try:
        page.wait_for_function(READY, timeout=timeout * 1000)
        with (folder / "capture.webm").open("xb") as stream:
            binding = "sphereWriteVideo" + uuid4().hex
            page.expose_function(
                binding, lambda chunk: stream.write(base64.b64decode(chunk, validate=True))
            )
            page.evaluate(CAPTURE, binding)
            try:
                start_scene()
                end = time.monotonic() + timeout
                while time.monotonic() < end:
                    page.wait_for_timeout(100)
                    if any(
                        k in e["line"]
                        for e in events[-12:]
                        for k in (
                            "event=goal_on_foot",
                            "event=ground_or_vehicle_not_loaded",
                            "event=unplanned_dismount",
                            "event=camera_command_failed",
                            "start_failed=",
                        )
                    ):
                        break
            finally:
                page.evaluate("() => window.sphereStopVideo()")
        lengths = validate(events)
        pending = folder / "encoding.mp4"
        movie = encode(folder / "capture.webm", pending)
        # Retain partial recordings for diagnosis. Only publish a completed run.
        duration = events[-1]["elapsed"] - events[0]["elapsed"]
        if movie["seconds"] + 0.3 < duration:
            raise ValueError("video ended before the observed journey")
        pending.rename(folder / "journey.mp4")
        with (folder / "journey.mp4").open("rb") as f:
            movie["sha256"] = hashlib.file_digest(f, "sha256").hexdigest()
        (folder / "recording.json").write_text(
            json.dumps(dict(movie=movie, legDistances=lengths, events=PHASES), indent=2),
            encoding="utf8",
        )
        return movie
    finally:
        page.remove_listener("console", observe)
        (folder / "events.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in events), encoding="utf8"
        )


def local(url):
    parts = urlsplit(url)
    if (
        parts.scheme != "http"
        or parts.hostname not in ("localhost", "127.0.0.1", "::1")
        or parts.username
    ):
        raise ValueError("expected the dedicated loopback test browser")
    return parts


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--cdp-url", required=True)
    cli.add_argument("--game-url", required=True)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--timeout", type=int, default=300)
    args = cli.parse_args()
    local(args.cdp_url)
    target = local(args.game_url)

    def matches(page):
        u = urlsplit(page.url)
        return (u.scheme, u.netloc, u.path.rstrip("/")) == (
            target.scheme,
            target.netloc,
            target.path.rstrip("/"),
        ) and "sphere-journey" in parse_qs(u.query).get("mods", [""])[0].split(",")

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(args.cdp_url)
        pages = [p for ctx in browser.contexts for p in ctx.pages if matches(p)]
        if len(pages) != 1:
            raise ValueError("expected exactly one open local sphere-journey tab")
        page = pages[0]
        print(capture(page, args.output, args.timeout, lambda: page.keyboard.press("F6")))
