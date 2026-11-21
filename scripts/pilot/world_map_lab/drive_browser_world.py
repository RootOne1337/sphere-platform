"""Drive a local browser game from captured RGB with the existing cross-world policy."""

import argparse
import asyncio
import base64
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

import cv2
import numpy as np
from playwright.async_api import async_playwright

from scripts.pilot.world_map_lab.browser_test_input import NO_POINTER_LOCK
from scripts.pilot.world_map_lab.classic_window import KeyLease
from scripts.pilot.world_map_lab.classic_world_pilot import WorldCoursePilot
from scripts.pilot.world_map_lab.record_native_journey import CAPTURE, READY, encode

# A read-only capture track also supplies an independent frame clock.
TRACK = """async () => {
    const stream = document.querySelector('#screen').captureStream(30);
    const v = document.createElement('video');
    v.muted = true;
    v.srcObject = stream;
    await v.play();
    const copy = document.createElement('canvas');
    copy.width = 448;
    copy.height = 252;
    const ctx = copy.getContext('2d');
    let serial = 0, last = 0;
    function frame(now) {
        const w = v.videoWidth, h = v.videoHeight;
        const cw = Math.min(w, h * copy.width / copy.height);
        const ch = cw * copy.height / copy.width;
        ctx.drawImage(v, (w-cw)/2, (h-ch)/2, cw, ch, 0, 0, copy.width, copy.height);
        serial++;
        last = now;
        v.requestVideoFrameCallback(frame);
    }
    v.requestVideoFrameCallback(frame);
    window.readJourneyFrame = previous => serial === previous ? null : {
        serial, age: performance.now()-last,
        jpeg: copy.toDataURL('image/jpeg', .94).split(',')[1]
    };
}"""


async def run(url, game, bank, output, chrome, seconds):
    if urlsplit(url).hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("local game server required")
    output.mkdir(parents=True, exist_ok=False)
    cv2.setNumThreads(4)
    pilot = WorldCoursePilot(game / "sphere-route.json", bank, 70, cross_renderer=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            executable_path=chrome, args=["--enable-gpu", "--use-angle=d3d11"]
        )
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        await page.add_init_script(NO_POINTER_LOCK)
        with (
            (output / "observer.jsonl").open("x", encoding="utf8") as truth,
            (output / "decisions.jsonl").open("x", encoding="utf8") as decisions,
            (output / "keys.jsonl").open("x", encoding="utf8") as keys,
            (output / "capture.webm").open("xb") as video,
        ):

            def observer(msg):
                if any(
                    k in msg.text
                    for k in (
                        "br_observe",
                        "br_camera",
                        "br_assets",
                        "error",
                        "panic",
                        "unresolved",
                    )
                ):
                    print(json.dumps([time.monotonic(), msg.text]), file=truth, flush=True)

            page.on("console", observer)
            await page.goto(
                url.rstrip("/")
                + "/?autostart=1&pointer=off&full=1&backend=webgpu&cache_mb=64&mods=br-game-profile&strict=1&inworld=0",
                wait_until="commit",
            )
            boot_deadline = time.monotonic() + 240
            while not await page.evaluate(READY):
                state = await page.evaluate("()=>window.saGame?.status || {}")
                if state.get("error") or time.monotonic() > boot_deadline:
                    raise RuntimeError(f"game did not start: {state}")
                if state.get("state") in (2, 4, 7):
                    await page.keyboard.press("Enter", delay=80)
                await asyncio.sleep(2)
            size = await page.evaluate("()=>window.saGame.status.client")
            if size != [1920, 1080]:
                raise RuntimeError(f"unexpected native video mode {size}")
            await page.expose_function(
                "writeJourneyChunk", lambda s: video.write(base64.b64decode(s))
            )
            await page.evaluate(CAPTURE.replace("8000000", "20000000"), "writeJourneyChunk")
            await page.evaluate(TRACK)
            pending = asyncio.Queue()

            def enqueue(k, down):
                pending.put_nowait((k, down))

            lease = KeyLease(lambda: True, enqueue, walk_turn_seconds=0.045)

            async def input_loop():
                while True:
                    lease.tick()
                    while not pending.empty():
                        k, down = pending.get_nowait()
                        op = page.keyboard.down if down else page.keyboard.up
                        await op("Key" + k)
                        print(json.dumps([time.monotonic(), k, down]), file=keys, flush=True)
                    if lease.stopped:
                        break
                    await asyncio.sleep(0.012)

            worker = asyncio.create_task(input_loop())
            origin = time.monotonic()
            serial = 0
            last_match = origin
            reason = "time_limit"
            try:
                while time.monotonic() - origin < seconds:
                    if worker.done():
                        await worker
                        break
                    started = time.monotonic()
                    frame = await page.evaluate("n=>window.readJourneyFrame(n)", serial)
                    if frame:
                        serial = frame["serial"]
                        raw = cv2.imdecode(
                            np.frombuffer(base64.b64decode(frame["jpeg"]), np.uint8),
                            cv2.IMREAD_COLOR,
                        )
                        rgb = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
                        captured = started - max(0, frame["age"]) / 1000
                        row = await asyncio.to_thread(pilot.frame, rgb, captured - origin, captured)
                        row["serial"] = serial
                        row["capture_monotonic_s"] = captured
                        print(json.dumps(row, allow_nan=False), file=decisions, flush=True)
                        lease.refresh(row, captured)
                        if row["vision"] in ("matched", "tracked") and row["latency_ms"] < 250:
                            last_match = time.monotonic()
                        if row.get("goal_seen"):
                            reason = "visual_goal"
                            break
                    if time.monotonic() - last_match > 30:
                        reason = "no_fresh_localization"
                        break
                    await asyncio.sleep(max(0.01, 0.19 - (time.monotonic() - started)))
            finally:
                lease.close()
                await worker
                await page.evaluate("()=>window.sphereStopVideo()")
        await browser.close()
    stats = encode(output / "capture.webm", output / "first-person.mp4")
    result = dict(
        stopReason=reason,
        lastStage=pilot.journey.stage,
        routeSha256=pilot.route_hash,
        startMonotonicS=origin,
        **stats,
    )
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf8")
    print(json.dumps(result))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--url", required=True)
    for name in ("game", "bank", "output"):
        cli.add_argument("--" + name, required=True, type=Path)
    cli.add_argument("--chrome", default="C:/Program Files/Google/Chrome/Application/chrome.exe")
    cli.add_argument("--seconds", type=float, default=2400)
    asyncio.run(run(**vars(cli.parse_args())))
