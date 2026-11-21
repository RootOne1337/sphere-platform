"""Record the short keyboard camera regression on the local Kremlin Faggio fixture."""

import argparse
import base64
import json
import re
import time
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import sync_playwright

from scripts.pilot.world_map_lab.record_native_journey import CAPTURE, encode

# This fixed input sequence isolates camera changes. It does not test navigation.
KEYS = (
    (2.15, "w", True),
    (3.57, "w", False),
    (4.29, "f", True),
    (4.39, "f", False),
    (9.40, "w", True),
    (10.83, "w", False),
    (11.18, "s", True),
    (12.26, "s", False),
    (14.75, "f", True),
    (14.87, "f", False),
    (18.45, "w", True),
    (19.53, "w", False),
)
PLAYER = re.compile(
    r"br_observe t=(\d+) xyz=(\S+) in_world=true hp=(\S+) driver=(true|false) model=(.*)"
)


def record(port, dest, chrome):
    dest.mkdir(parents=True, exist_ok=False)
    url = (
        f"http://127.0.0.1:{port}/?autostart=1&inworld=0&strict=1"
        "&backend=webgpu&mods=br-game-profile&cache_mb=64&pointer=click"
    )
    report = {
        "url": url,
        "purpose": "camera regression",
        "autonomous": False,
        "commands": [],
        "telemetry": [],
        "cameraControlPassed": False,
    }
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=chrome, args=["--enable-gpu", "--use-angle=d3d11"]
        )
        try:
            page = browser.new_page(viewport={"width": 1024, "height": 768})

            def log(message):
                text = message.text
                if any(
                    word in text for word in ("br_camera ", "br_observe ", " trapped:", "panicked")
                ):
                    report["telemetry"].append(text)

            page.on("console", log)
            page.goto(url, wait_until="commit", timeout=60000)
            page.wait_for_function(
                "() => window.saGame?.status?.state===9 && window.saGame.status.presents>=100",
                timeout=160000,
            )
            with (dest / "camera.webm").open("xb") as stream:
                binding = "cameraChunk" + uuid4().hex
                page.expose_function(
                    binding, lambda chunk: stream.write(base64.b64decode(chunk, validate=True))
                )
                page.evaluate(CAPTURE, binding)
                start = time.monotonic()
                for target, key, down in KEYS:
                    page.wait_for_timeout(max(0, (start + target - time.monotonic()) * 1000))
                    (page.keyboard.down if down else page.keyboard.up)(key)
                    report["commands"].append([time.monotonic() - start, key, down])
                page.wait_for_timeout(max(0, (start + 21.3 - time.monotonic()) * 1000))
                page.evaluate("() => window.sphereStopVideo()")
            report["engine"] = page.evaluate("window.saGame.status")
            report["movie"] = encode(dest / "camera.webm", dest / "camera.mp4")
            samples = [m for line in report["telemetry"] if (m := PLAYER.search(line))]
            phases = []
            for sample in samples:
                state = (sample[4], sample[5])
                if not phases or state != phases[-1]:
                    phases.append(state)
            hp = [float(s[3]) for s in samples]
            if (
                phases != [("false", "None"), ("true", "Some(ModelId(462))"), ("false", "None")]
                or max(hp) - min(hp) > 0.2
                or report["engine"].get("error")
                or report["engine"].get("blocked")
                or not any("br_camera " in s for s in report["telemetry"])
            ):
                raise ValueError("camera fixture lost the rider, health, telemetry or engine")
            report["cameraControlPassed"] = True
        finally:
            (dest / "camera.json").write_text(json.dumps(report, indent=2), encoding="utf8")
            browser.close()


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--port", required=True, type=int)
    cli.add_argument("--chrome", default="C:/Program Files/Google/Chrome/Application/chrome.exe")
    cli.add_argument("--output", required=True, type=Path)
    opts = cli.parse_args()
    record(opts.port, opts.output, opts.chrome)
