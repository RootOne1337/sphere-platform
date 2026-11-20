import argparse
import json
import math
import os
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

cli = argparse.ArgumentParser(
    description="Exercise manual walking, driving, boarding, exit, and free spawn in the local world viewer."
)
cli.add_argument("--folder", type=Path, required=True)
cli.add_argument("--url", default="http://127.0.0.1:8817")
cli.add_argument(
    "--chrome",
    default=str(
        Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        / "Google/Chrome/Application/chrome.exe"
    ),
)
args = cli.parse_args()
out = args.folder / "journey"
home = args.url.rstrip("/")
a = json.loads((out / "route.json").read_bytes())
with sync_playwright() as pw:
    b = pw.chromium.launch(executable_path=args.chrome, args=["--enable-gpu", "--use-angle=d3d11"])
    p = b.new_page(viewport={"width": 1400, "height": 840})
    errors = []
    p.on("pageerror", lambda e: errors.append(str(e)))

    def ready():
        p.wait_for_function("window.journey||window.journeyError", timeout=180000)
        assert not p.evaluate("window.journeyError||null")
        p.wait_for_timeout(250)

    def state():
        return p.evaluate("journey.state()")

    p.goto(home)
    p.locator("#exploreLink").wait_for(state="visible")
    p.locator("#exploreLink").click()
    ready()
    first = state()
    p.screenshot(path=str(out / "manual-start.png"))
    p.keyboard.down("w")
    p.wait_for_timeout(1200)
    p.keyboard.up("w")
    after = state()
    assert math.dist(first["p"], after["p"]) > 1, (first, after)
    p.keyboard.down("a")
    p.wait_for_timeout(300)
    p.keyboard.up("a")
    assert abs(state()["yaw"] - after["yaw"]) > 0.12
    p.locator("#reset").click()
    p.locator("#follow").click()
    p.wait_for_timeout(1100)
    assert state()["following"] and state()["t"] > 0.3
    p.keyboard.press("Escape")
    assert not state()["following"]
    assert p.evaluate("document.pointerLockElement===null")
    route = a["legs"][0]["path"]
    v = a["vehicle"]
    near = [
        route[-1][i] + (route[-2][i] - route[-1][i]) * 1.8 / math.dist(route[-2], route[-1])
        for i in range(3)
    ]

    def joined(x):
        return ",".join(map(str, x))

    p.goto(
        home
        + "/explore?"
        + urlencode(dict(start=joined(near), vehicle=joined(v), end=joined(a["end"]), mode="trip"))
    )
    ready()
    assert not state()["mounted"]
    p.locator("#board").click(timeout=9000)
    assert state()["mounted"]
    pre = state()
    p.keyboard.down("w")
    p.wait_for_timeout(1450)
    p.keyboard.up("w")
    post = state()
    assert math.dist(pre["p"], post["p"]) > 1, (pre, post)
    p.keyboard.press("Escape")
    p.locator("#board").click(timeout=9000)
    p.wait_for_function("!journey.state().mounted", timeout=4000)
    p.goto(home + "/explore?" + urlencode(dict(start=joined(a["end"]), mode="walk")))
    ready()
    assert math.dist(state()["p"], a["end"]) < 0.4
    assert not p.locator("#follow").is_visible()
    p.goto(home)
    p.locator("#example").wait_for(state="visible")
    p.locator("#example").click()
    p.wait_for_function(
        "document.querySelector('#exploreLink').href.includes('end=')", timeout=10000
    )
    p.locator("#exploreLink").click()
    ready()
    assert not errors, errors
    result = dict(
        manualWalk=math.dist(first["p"], after["p"]),
        manualDrive=math.dist(pre["p"], post["p"]),
        board=True,
        exit=True,
        freeSpawn=True,
        plannerLink=p.url,
        pageErrors=errors,
    )
    (out / "manual-check.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf8")
    print(result)
    b.close()
