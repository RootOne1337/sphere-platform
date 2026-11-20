"""Held-out camera offsets on the map. The lookup receives only its prior and the new image."""

import argparse
import json
import math
from contextlib import ExitStack
from pathlib import Path

import numpy as np
from playwright.sync_api import sync_playwright

from scripts.pilot.world_map_lab.check_journey_rgb import (
    H,
    Lane,
    W,
    confirm_recovery,
    correct,
    rgb_pair,
    wide_pose,
)
from scripts.pilot.world_map_lab.world_navmesh import Network


def check(folder, url, chrome):
    out = folder / "journey"
    lane = Lane(json.loads((out / "route.json").read_bytes())["legs"][1])
    bike = json.loads((out / "vehicles.json").read_bytes())["faggio"]
    eye = bike["lift"] + bike["seat"][2] + 0.61
    results = []
    with ExitStack() as scope:
        nets = [
            scope.enter_context(Network(folder, k, adapter=out / "ariane-nav.dll"))
            for k in ("drive", "walk")
        ]
        pw = scope.enter_context(sync_playwright())
        browser = pw.chromium.launch(
            executable_path=chrome, args=["--enable-gpu", "--use-angle=d3d11"]
        )
        page = browser.new_page()
        page.route(
            "**/rgb-lab",
            lambda r: r.fulfill(
                content_type="text/html",
                body='<canvas id="eye"></canvas><script type="importmap">{"imports":{"three":"/detail/js/three.module.js"}}</script>',
            ),
        )
        page.goto(url + "/rgb-lab")
        focal = page.evaluate(
            Path(__file__).with_name("observe_world_journey.mjs").read_text(encoding="utf8"),
            dict(width=W, height=H, model="faggio"),
        )
        for station, offset in ((30, 8.7), (240, -9.1), (1100, 7.6), (6505, -8.5), (40, 35)):
            p = lane.at(station)
            forward = lane.at(station + 1) - p
            yaw = math.atan2(forward[1], forward[0])
            prior = [*p[:2], p[2] + eye, yaw, -0.045]
            normal = np.array([-math.sin(yaw), math.cos(yaw)])
            xy = p[:2] + offset * normal
            levels = [z for net in nets for z in net.levels(*xy) if abs(z - p[2]) < 3]
            if not levels:
                results.append(dict(station=station, offset=offset, ground=False))
                continue
            live = [*xy, min(levels, key=lambda z: abs(z - p[2])) + eye, yaw + 0.19, -0.045]
            vehicle = dict(mounted=True, pan=0)
            rgb_pair(page, prior, live, vehicle)
            first = wide_pose(page, prior, nets, focal, eye)
            # Only the evaluator knows the injected displacement. Its upper bound
            # distinguishes a poor search prior from an unobservable reference image.
            optimum = correct(live, page.evaluate("p=>mapPairWithLastImage(p)", live), focal)
            optimum_cost = page.evaluate("p=>rankRenderedPoses(p)", [live])[0]
            first_error = float(np.linalg.norm(first[0] - live[:3])) if first else None
            accepted = False
            error = None
            second_cost = None
            if first:
                # A second frame with a deliberate pan supplies independent image evidence.
                pan = 0.18
                rgb_pair(
                    page,
                    [*prior[:3], yaw + pan, prior[4]],
                    [*live[:3], live[3] + pan, live[4] + 0.003],
                    dict(mounted=True, pan=pan),
                )
                candidate = [*first[0], first[1] + pan, prior[4]]
                second_cost = page.evaluate("p=>rankRenderedPoses(p)", [candidate])[0]
                fit = confirm_recovery(page, candidate, focal)
                if fit:
                    accepted = True
                    error = float(np.linalg.norm(fit[0] - live[:3]))
            results.append(
                dict(
                    station=station,
                    offset=offset,
                    ground=True,
                    accepted=bool(accepted),
                    positionError=error,
                    firstPoseError=first_error,
                    secondViewCost=second_cost,
                    oracleInliers=optimum[2] if optimum else 0,
                    oracleCost=optimum_cost,
                )
            )
        browser.close()
    (out / "displacement-probes.json").write_text(json.dumps(results, indent=2), encoding="utf8")
    print(results)
    if any(
        r.get("accepted") and (r["positionError"] > 1 or abs(r["offset"]) > 20) for r in results
    ):
        raise RuntimeError("false displacement recovery")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--folder", type=Path, required=True)
    cli.add_argument("--url", default="http://127.0.0.1:8817")
    cli.add_argument("--chrome", default="C:/Program Files/Google/Chrome/Application/chrome.exe")
    args = cli.parse_args()
    check(args.folder, args.url, args.chrome)
