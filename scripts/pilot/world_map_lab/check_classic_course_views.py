"""Test offset map views, wrong-place images and the cold walking start, without game input."""

import argparse
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np
from playwright.sync_api import sync_playwright

from scripts.pilot.world_map_lab.bake_world_course import SIZE, arrays, pose_for, renderer
from scripts.pilot.world_map_lab.classic_window import desired_keys
from scripts.pilot.world_map_lab.classic_world_pilot import WorldCoursePilot
from scripts.pilot.world_map_lab.export_full_game_world import digest


def check(route, bank, output, url, chrome):
    if output.exists():
        raise FileExistsError(output)
    cv2.setNumThreads(3)
    results, negatives, startup = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=chrome, headless=True, args=["--enable-gpu", "--use-angle=d3d11"]
        )
        page, f = renderer(browser, url, route)
        pilot = WorldCoursePilot(route, bank, math.degrees(2 * math.atan(SIZE[0] / (2 * f))))

        def image(pose):
            gray, _ = arrays(page.evaluate("p=>mapReference(p)", pose))
            return cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)

        for phase, lane in enumerate(pilot.lanes):
            previous = None
            for station in np.linspace(0.75, lane.arc[-1] - 0.8, 31 if phase == 1 else 7):
                view = pose_for(lane, station, 0.27, 0.035, -0.031)
                rgb = image(view)
                # Local tracking case with a small known prior error (no oracle in native runtime).
                pilot.confirmed = (1, (np.array(view[:3]) + [0.35, -0.35, 0], None, station - 0.5))
                pilot.misses = 0
                start = time.monotonic()
                fit = pilot.locate(rgb, 1.2, phase)
                results.append(
                    dict(
                        phase=phase,
                        s=round(station, 2),
                        found=fit is not None,
                        error=None if fit is None else float(np.linalg.norm(fit[0] - view[:3])),
                        method=pilot.method if fit is not None else None,
                        ms=round((time.monotonic() - start) * 1000, 2),
                    )
                )
                if previous is not None:
                    pilot.confirmed = (1, (np.array(view[:3]), None, station))
                    wrong = pilot.locate(previous, 1.2, phase)
                    negatives.append(dict(phase=phase, station=station, accepted=wrong is not None))
                previous = rgb
        cold = WorldCoursePilot(route, bank)
        for i in range(8):
            pose = pose_for(cold.lanes[0], min(0.6, i * 0.08), 0.05, math.radians(i % 3 - 1), -0.03)
            rgb = image(pose)
            row = cold.frame(rgb, i * 0.2, time.monotonic())
            startup.append([row["vision"], row["supports"], sorted(desired_keys(row)), row["hfov"]])
        blank = cold.frame(np.full((SIZE[1], SIZE[0], 3), 100, np.uint8), 1.7, time.monotonic())
        browser.close()
    summary = dict(
        routeSha256=digest(route),
        indexSha256=digest(bank / "index.json"),
        policySha256=digest(Path(__file__).with_name("classic_world_pilot.py")),
        rows=results,
        negatives=negatives,
        startup=startup,
        blank=sorted(desired_keys(blank)),
        test="offset map renders and known local prior; no native game input",
    )
    output.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf8")
    for phase in range(3):
        rows = [r for r in results if r["phase"] == phase]
        print(f"Leg {phase + 1}: {sum(r['found'] for r in rows)} / {len(rows)} located")
    print(f"Wrong-place accepts: {sum(r['accepted'] for r in negatives)} / {len(negatives)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("route", "bank", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8817")
    parser.add_argument("--chrome")
    check(**vars(parser.parse_args()))
