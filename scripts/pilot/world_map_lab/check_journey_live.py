"""Run a short city itinerary through the public browser controls and verify both transfers."""

import argparse
import json
import time
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

from scripts.pilot.world_map_lab.check_journey_rgb import Lane
from scripts.pilot.world_map_lab.prepare_world_journey import pedestrian_near
from scripts.pilot.world_map_lab.world_navmesh import Network
from scripts.pilot.world_map_lab.world_trip import TripPlanner


def check(folder, home, chrome):
    out = folder / "journey"
    config = json.loads((out / "route.json").read_bytes())
    walk, road, _ = [Lane(k) for k in config["legs"]]
    start = walk.at(walk.arc[-1] - 14).tolist()
    vehicle = config["vehicle"]
    with ExitStack() as scope:
        nets = {
            mode: scope.enter_context(Network(folder, mode, adapter=out / "ariane-nav.dll"))
            for mode in ("walk", "drive")
        }
        planner = TripPlanner(nets, folder)
        for end in pedestrian_near(nets["walk"], nets["drive"], road.at(120)):
            choice = planner.route(start, end, vehicle)
            legs = choice["legs"]
            if [k["mode"] for k in legs] == ["walk", "drive", "walk"] and min(
                k["length"] for k in legs
            ) > 6:
                break
        else:
            raise RuntimeError("No complete mixed city itinerary")
    points = dict(start=start, end=end, vehicle=vehicle)
    query = urlencode({"mode": "trip", **{k: ",".join(map(str, p)) for k, p in points.items()}})
    url = home + "/explore?" + query
    (out / "city-trip.json").write_text(
        json.dumps(dict(url=url, lengths=[x["length"] for x in legs], **points)), encoding="utf8"
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=chrome, args=["--enable-gpu", "--use-angle=d3d11"]
        )
        page = browser.new_page(viewport={"width": 1100, "height": 720})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url)
        page.wait_for_function("window.journey", timeout=90000)
        page.locator("#pilot").click()
        link = page.locator("#traceLink")
        link.wait_for(state="visible", timeout=60000)
        ident = link.get_attribute("href").split("id=")[-1]
        print("attempt", ident, flush=True)
        try:
            page.wait_for_function(
                "document.querySelector('#message').textContent.includes('опор')", timeout=90000
            )
            page.reload()
            page.wait_for_function(
                "document.querySelector('#pilot').textContent.includes('Остановить')", timeout=60000
            )
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                status = page.request.get(home + "/api/journey/state?id=" + ident).json()
                if status["state"] not in ("starting", "running"):
                    break
                page.wait_for_timeout(700)
            trace = page.request.get(home + "/api/journey/trace?id=" + ident)
            rows = [json.loads(row) for row in trace.text().splitlines()]
            result = dict(
                id=ident,
                result=status["state"],
                phases=sorted(set(r["phase"] for r in rows)),
                frames=len(rows),
                errors=errors,
                restoredOnReload=True,
            )
            (out / "city-ui-check.json").write_text(json.dumps(result), encoding="utf8")
            print(result, flush=True)
            assert not errors and result["result"] == "arrived" and result["phases"] == [0, 1, 2], (
                result
            )
        finally:
            if page.request.get(home + "/api/journey/state?id=" + ident).json()["state"] in (
                "running",
                "starting",
            ):
                page.request.post(
                    home + "/api/journey/stop", data={"id": ident}, headers={"Origin": home}
                )
            browser.close()


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--folder", required=True, type=Path)
    cli.add_argument("--url", default="http://127.0.0.1:8817")
    cli.add_argument("--chrome", default="C:/Program Files/Google/Chrome/Application/chrome.exe")
    args = cli.parse_args()
    check(args.folder, args.url, args.chrome)
