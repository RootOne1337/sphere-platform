"""Drive a simulated body using image-to-map pose corrections, with independent surface checks."""

import argparse
import base64
import json
import math
import os
import time
from contextlib import ExitStack
from pathlib import Path

import cv2
import numpy as np
from playwright.sync_api import sync_playwright

from scripts.pilot.world_map_lab.serve_world_navmesh import movement_step
from scripts.pilot.world_map_lab.world_navmesh import Network

W, H = 320, 180
DT = 0.2


def angle(x):
    return math.atan2(math.sin(x), math.cos(x))


class Lane:
    def __init__(self, leg):
        path = np.asarray(leg["path"])
        self.path = path[np.r_[True, np.linalg.norm(np.diff(path, axis=0), axis=1) > 0.0001]]
        self.ds = np.linalg.norm(np.diff(self.path, axis=0), axis=1)
        self.arc = np.r_[0, np.cumsum(self.ds)]
        self.vectors = np.diff(self.path, axis=0)
        self.mode = leg["mode"]

    def curve_limits(self):
        stations = np.linspace(0, self.arc[-1], max(2, math.ceil(self.arc[-1] / 1.25)) + 1)
        xyz = np.asarray([self.at(x) for x in stations])
        angles = np.unwrap(np.arctan2(np.diff(xyz[:, 1]), np.diff(xyz[:, 0])))
        bends = np.abs(np.gradient(angles, stations[:-1]))
        caps = np.minimum(24.0, np.sqrt(3.5 / np.maximum(0.0001, bends)))
        caps = np.r_[caps, 0.0]
        for i in range(len(caps) - 2, -1, -1):
            caps[i] = min(
                caps[i], math.sqrt(caps[i + 1] ** 2 + 2 * 5.5 * (stations[i + 1] - stations[i]))
            )
        return stations, caps

    def at(self, s):
        s = np.clip(s, 0, self.arc[-1])
        i = min(len(self.ds) - 1, self.arc.searchsorted(s, side="right") - 1)
        return self.path[i] + self.vectors[i] * ((s - self.arc[i]) / self.ds[i])

    def progress(self, p, prior):
        start = max(0, self.arc.searchsorted(prior - 12) - 1)
        stop = max(start + 1, min(len(self.ds), self.arc.searchsorted(prior + 30)))
        v = self.vectors[start:stop, :2]
        a = self.path[start:stop, :2]
        f = np.clip(np.sum((p[:2] - a) * v, axis=1) / np.maximum(1e-8, np.sum(v * v, axis=1)), 0, 1)
        errors = np.linalg.norm(a + f[:, None] * v - p[:2], axis=1)
        i = errors.argmin()
        return self.arc[start + i] + f[i] * self.ds[start + i], errors[i]


def correct(pose, images, focal, descriptors=False, *, sparse_scene=False):
    ref, dep, live = [
        np.frombuffer(base64.b64decode(x), dtype="<u2" if i == 1 else "u1").reshape(H, W)
        for i, x in enumerate(images)
    ]
    dep = dep.astype(np.float32) / 128.0
    # Far surfaces on an incline can vary by several map units across three
    # pixels. Keep close depth boundaries masked in both tracking passes.
    depth_limit = np.maximum(1.4, dep * 0.065) if sparse_scene else 1.4
    mask = (
        np.uint8(
            (dep > 1.3) & (dep < 130) & (cv2.dilate(dep, None) - cv2.erode(dep, None) < depth_limit)
        )
        * 255
    )
    mask[int(H * 0.78) :] = 0
    if descriptors:
        detector = cv2.SIFT_create(nfeatures=600, contrastThreshold=0.018)
        k1, d1 = detector.detectAndCompute(ref, mask)
        k2, d2 = detector.detectAndCompute(live, None)
        if d1 is None or d2 is None or min(len(d1), len(d2)) < 18:
            return None
        matcher = cv2.BFMatcher(cv2.NORM_L2)

        def unique(left, right):
            return {
                a.queryIdx: a.trainIdx
                for a, b in matcher.knnMatch(left, right, k=2)
                if a.distance < 0.8 * b.distance
            }

        matches = unique(d1, d2)
        reverse = unique(d2, d1)
        pairs = [(k1[i].pt, k2[j].pt) for i, j in matches.items() if reverse.get(j) == i]
        if len(pairs) < 18:
            return None
        xy, uv = np.float32(pairs).transpose(1, 0, 2)
    else:
        corners, quality, separation = (400, 0.002, 3) if sparse_scene else (220, 0.006, 5)
        pts = cv2.goodFeaturesToTrack(ref, corners, quality, separation, mask=mask)
        if pts is None or len(pts) < 10:
            return None
        q, hit, _ = cv2.calcOpticalFlowPyrLK(ref, live, pts, None, winSize=(21, 21), maxLevel=3)
        back, ret, _ = cv2.calcOpticalFlowPyrLK(live, ref, q, None, winSize=(21, 21), maxLevel=3)
        ok = (
            (hit.ravel() > 0)
            & (ret.ravel() > 0)
            & (np.linalg.norm(back - pts, axis=2).ravel() < 0.8)
        )
        xy, uv = pts[:, 0][ok], q[:, 0][ok]
    if len(xy) < 10:
        return None
    y, x = np.rint(xy).astype(int).T[::-1]
    z = dep[y, x]
    cx, cy = (W - 1) / 2, (H - 1) / 2
    xyz = np.column_stack([(xy[:, 0] - cx) * z / focal, (xy[:, 1] - cy) * z / focal, z])
    k = np.array([[focal, 0, cx], [0, focal, cy], [0, 0, 1]], np.float64)
    valid, r, t, ids = cv2.solvePnPRansac(
        xyz,
        uv,
        k,
        None,
        iterationsCount=80,
        reprojectionError=1.4,
        confidence=0.997,
        flags=cv2.SOLVEPNP_EPNP,
    )
    if not valid or ids is None or len(ids) < 10:
        return None
    ids = ids.ravel()
    if np.ptp(uv[ids, 0]) < 0.14 * W or np.ptp(uv[ids, 1]) < 0.09 * H:
        return None
    r, t = cv2.solvePnPRefineLM(xyz[ids], uv[ids], k, None, r, t)
    rot = cv2.Rodrigues(r)[0]
    a, p = pose[3:5]
    c, s = math.cos(a), math.sin(a)
    cp, sp = math.cos(p), math.sin(p)
    axes = np.array([[s, -c, 0], [sp * c, sp * s, -cp], [cp * c, cp * s, sp]])
    d = -(rot.T @ t).ravel() @ axes
    heading = rot[2] @ axes
    yaw = math.atan2(heading[1], heading[0])
    if np.linalg.norm(d) > (7 if descriptors else 2.6) or abs(angle(yaw - a)) > (
        0.42 if descriptors else 0.27
    ):
        return None
    return np.array(pose[:3]) + d, yaw, len(ids)


def image_standstill(previous, current_image, prior, focal):
    """Check commanded translation against live inter-frame tracks after camera rotation."""
    if previous is None:
        return False
    old, depth, camera = previous
    translation = np.asarray(prior[:3]) - camera[:3]
    if np.linalg.norm(translation) < 0.24 or abs(angle(prior[3] - camera[3])) > 0.18:
        return False

    def axes(pose):
        a, pitch = pose[3:]
        c, s = math.cos(a), math.sin(a)
        cp, sp = math.cos(pitch), math.sin(pitch)
        return np.array([[s, -c, 0], [sp * c, sp * s, -cp], [cp * c, cp * s, sp]])

    near = (
        np.frombuffer(base64.b64decode(depth), dtype="<u2").reshape(H, W).astype(np.float32) / 128
    )
    mask = np.uint8((near > 2.5) & (near < 70)) * 255
    mask[int(0.78 * H) :] = 0

    def gray(data):
        return np.frombuffer(base64.b64decode(data), dtype="u1").reshape(H, W)

    ref, live = gray(old), gray(current_image)
    pts = cv2.goodFeaturesToTrack(ref, 120, 0.004, 6, mask=mask)
    if pts is None or len(pts) < 12:
        return False
    nxt, hit, _ = cv2.calcOpticalFlowPyrLK(ref, live, pts, None, winSize=(17, 17), maxLevel=2)
    good = hit.ravel() > 0
    if good.sum() < 12:
        return False
    xy, nxt = pts[:, 0][good], nxt[:, 0][good]
    center = np.array([(W - 1) / 2, (H - 1) / 2])
    ij = np.rint(xy).astype(int)
    points = (
        np.column_stack([(xy - center) / focal, np.ones(len(xy))]) * near[ij[:, 1], ij[:, 0], None]
    )
    current_axes = axes(prior)
    rotated = points @ axes(camera) @ current_axes.T
    moved = rotated - translation @ current_axes.T

    def project(points):
        return center + focal * points[:, :2] / np.maximum(0.1, points[:, 2:])

    rot, motion = project(rotated), project(moved)
    useful = np.linalg.norm(motion - rot, axis=1) > 1.2
    if useful.sum() < 12 or np.ptp(xy[useful, 0]) < W * 0.15 or np.ptp(xy[useful, 1]) < H * 0.08:
        return False
    stationary_error = np.median(np.linalg.norm(nxt[useful] - rot[useful], axis=1))
    moving_error = np.median(np.linalg.norm(nxt[useful] - motion[useful], axis=1))
    return stationary_error < 0.6 and moving_error > stationary_error + 0.9


def sparse_correction(page, prior, images, focal):
    """Accept a small update on weakly textured surfaces only after rendering it back."""
    fit = correct(prior, images, focal, sparse_scene=True)
    if (
        not fit
        or fit[2] < 18
        or np.linalg.norm(fit[0] - prior[:3]) > 0.75
        or abs(angle(fit[1] - prior[3])) > 0.065
    ):
        return None
    corrected = [*fit[0], fit[1], prior[4]]
    after, before = page.evaluate("q=>rankRenderedPoses(q)", [corrected, prior])
    return fit if after <= 9 and after <= before + 0.5 else None


def rgb_pair(page, prior, live, phase):
    return page.evaluate("q=>observePair(q)", [prior, live, phase])


def reacquire(page, prior, lane, station, eye):
    """Compare independently rendered map hypotheses with the last observed intensity frame."""
    heading = prior[3]
    basis = np.array(
        [[math.cos(heading), math.sin(heading)], [-math.sin(heading), math.cos(heading)]]
    )
    offsets = [(a, b) for a in (-6, -3, 0, 3, 6) for b in (-3, 0, 3)]
    poses = [[*(np.asarray(prior[:2]) + np.array([a, b]) @ basis), *prior[2:]] for a, b in offsets]
    for ds in (-15, -9, 0, 9, 15):
        p = lane.at(station + ds)
        poses.append([*p[:2], p[2] + eye, *prior[3:]])

    def rank(choices):
        return np.asarray(page.evaluate("q=>rankRenderedPoses(q)", choices))

    scores = rank(poses)
    i = int(scores.argmin())
    best = poses[i]
    loss = scores[i]
    if loss > 24:
        return None
    for step, turn in ((1.5, 0.055), (0.65, 0.025), (0.25, 0.009), (0.11, 0.004)):
        options = [best]
        for along, side, dyaw in (
            (step, 0, 0),
            (-step, 0, 0),
            (0, step, 0),
            (0, -step, 0),
            (0, 0, turn),
            (0, 0, -turn),
            (step, step, 0),
            (-step, -step, 0),
            (step, -step, 0),
            (-step, step, 0),
        ):
            pos = np.asarray(best[:2]) + np.array([along, side]) @ basis
            options.append([*pos, best[2], best[3] + dyaw, best[4]])
        scores = rank(options)
        j = int(scores.argmin())
        best = options[j]
        loss = scores[j]
    alternatives = [
        [*(np.asarray(best[:2]) + shift), *best[2:]]
        for shift in (basis[0] * 2, -basis[0] * 2, basis[1] * 1.5, -basis[1] * 1.5)
    ]
    if loss > 7.5 or loss + 0.75 > float(min(rank(alternatives))) * 0.88:
        return None
    return np.array(best[:3]), best[3], 0


# When stopped, use contrasting views to expose vertical structure hidden in
# the direction of travel. Each candidate needs a second independent image.
RECOVERY_PANS = (0, 55, -55, 105, -105, 160)
RECOVERY_START = 12


def recovery_camera(misses):
    scan = misses - RECOVERY_START
    if 0 <= scan < 2 * len(RECOVERY_PANS):
        return math.radians(RECOVERY_PANS[scan // 2]) + (0.18 if scan % 2 else 0)
    sweep = (0, 0, 12, -18, 28, -36, 52, -56, 78, -82, 110, -115, 155, -155)
    return math.radians(sweep[misses % len(sweep)])


def scan_due(misses):
    return (
        0 <= misses - RECOVERY_START < 2 * len(RECOVERY_PANS) and (misses - RECOVERY_START) % 2 == 0
    )


def wide_pose(page, prior, surfaces, focal, eye, pan=0, *, sparse=False):
    """Rank nearby map views, then require a well-conditioned depth-backed fit."""
    yaw = prior[3]
    forward = np.array([math.cos(yaw - pan), math.sin(yaw - pan)])
    right = np.array([-forward[1], forward[0]])
    candidates = []
    for along in range(-12, 13, 4):
        for across in range(-12, 13, 4):
            x, y = np.asarray(prior[:2]) + along * forward + across * right
            levels = {
                round(z, 2)
                for net in surfaces
                for z in net.levels(x, y)
                if abs(z + eye - prior[2]) < 3
            }
            for z in sorted(levels)[:3]:
                for da in (-0.5, -0.25, 0, 0.25, 0.5):
                    candidates.append([x, y, z + eye, yaw + da, prior[4]])
    if not candidates:
        return None

    def rank(poses):
        return np.asarray(page.evaluate("p=>rankRenderedPoses(p)", poses))

    scores = np.asarray(page.evaluate("p=>rankRenderedPoses(p,true)", candidates))
    fits = []
    for idx in np.argsort(scores)[:10]:
        cand = candidates[idx]
        pair = page.evaluate("p=>mapPairWithLastImage(p)", cand)
        fit = correct(cand, pair, focal)
        if not fit or fit[2] < 18:
            fit = correct(cand, pair, focal, descriptors=True)
        if not fit or fit[2] < 18:
            continue
        pose = [*fit[0], fit[1], prior[4]]
        loss = float(rank([pose])[0])
        if loss < 9:
            fits.append((loss, fit))
    if not fits:
        # Coordinate descent brings the depth image within the LK capture range.
        # Keep distinct seeds so repeating facades can still reject an ambiguous result.
        seeds = []
        for idx in np.argsort(scores):
            seed = candidates[idx]
            if all(
                np.linalg.norm(np.subtract(seed[:2], q[:2])) > 3
                or abs(angle(seed[3] - q[3])) > 0.22
                for q in seeds
            ):
                seeds.append(seed)
            if len(seeds) == 4:
                break
        for seed in seeds:
            for step, turn in ((2, 0.12), (1, 0.065), (0.5, 0.03)):
                choices = [seed]
                for ax, bx, da in (
                    (-1, 0, 0),
                    (1, 0, 0),
                    (0, -1, 0),
                    (0, 1, 0),
                    (-1, -1, 0),
                    (1, 1, 0),
                    (-1, 1, 0),
                    (1, -1, 0),
                    (0, 0, -1),
                    (0, 0, 1),
                ):
                    xy = seed[:2] + step * (ax * forward + bx * right)
                    choices.append([*xy, seed[2], seed[3] + da * turn, seed[4]])
                seed = choices[int(rank(choices).argmin())]
            pair = page.evaluate("p=>mapPairWithLastImage(p)", seed)
            fit = correct(seed, pair, focal)
            if sparse and (not fit or fit[2] < 18):
                fit = sparse_correction(page, seed, pair, focal)
            if fit and fit[2] >= 18:
                loss = float(rank([[*fit[0], fit[1], seed[4]]])[0])
                if loss < 9:
                    fits.append((loss, fit))
    if not fits:
        return None
    fits.sort(key=lambda r: r[0])
    loss, best = fits[0]
    if any(
        value < loss * 1.3 + 1
        and (np.linalg.norm(other[0] - best[0]) > 1.5 or abs(angle(other[1] - best[1])) > 0.08)
        for value, other in fits[1:]
    ):
        return None
    return best


def confirm_recovery(page, candidate, focal, *, sparse=False):
    pair = page.evaluate("p=>mapPairWithLastImage(p)", candidate)
    fit = correct(candidate, pair, focal)
    if sparse and (not fit or fit[2] < 18):
        fit = sparse_correction(page, candidate, pair, focal)
    if (
        not fit
        or fit[2] < 18
        or np.linalg.norm(fit[0] - candidate[:3]) >= 0.65
        or abs(angle(fit[1] - candidate[3])) >= 0.065
    ):
        return None
    pose = [*fit[0], fit[1], candidate[4]]
    # PnP helps confirm the prior even when its tiny correction increases the
    # photometric residual at a sharp edge. Retain the better supported pose.
    after, before = page.evaluate("p=>rankRenderedPoses(p)", [pose, candidate])
    if min(before, after) >= 9:
        return None
    return fit if after <= before else (np.array(candidate[:3]), candidate[3], fit[2])


def corridor_target(network, lane, station, position, target, side, offset, look):
    """Check the next section longitudinally before committing to a lateral clearance offset."""
    end = lane.arc[-1]
    forward = lane.at(min(end, station + look + 5)) - lane.at(min(end, station + look))
    if np.linalg.norm(forward[:2]) < 1 or abs(np.dot(forward[:2], side)) > 1:
        return target, False
    preview = [lane.at(min(end, station + look + d)) for d in (0, 2.5, 5)]

    def open_strip(shift):
        current = position
        for center in preview:
            candidate = center[:2] + side * shift
            distance = np.linalg.norm(candidate - current[:2])
            if distance > 5.99:
                return False
            if distance < 0.025:
                continue
            result = movement_step(network, current.tolist(), candidate.tolist(), "drive")
            current = np.asarray(result["position"])
            if np.linalg.norm(current[:2] - candidate) > 0.075:
                return False
        return True

    if open_strip(offset):
        return target, False
    for shift in sorted(np.arange(-1.5, 1.51, 0.15), key=lambda x: abs(x - offset)):
        if open_strip(shift):
            aligned = target.copy()
            aligned[:2] += side * (shift - offset)
            return aligned, True
    return target, True


def reachable_heading(network, position, target, heading):
    """Find a visible local waypoint from the predicted body centre at a road boundary."""
    delta = target[:2] - position[:2]
    distance = np.linalg.norm(delta)
    if distance < 0.05:
        return heading, False
    direction = math.atan2(delta[1], delta[0])

    def visible(xy):
        dest = position[:2] + (xy - position[:2]) * min(
            1, 5.5 / max(0.001, np.linalg.norm(xy - position[:2]))
        )
        step = movement_step(network, position.tolist(), dest.tolist(), "drive")
        return step["moved"] and np.linalg.norm(np.asarray(step["position"])[:2] - dest) < 0.09

    forward = np.array([math.cos(heading), math.sin(heading)])
    if visible(target[:2]) and visible(position[:2] + forward * min(2.0, distance)):
        return direction, False
    local = network.route(position.tolist(), target.tolist())
    if local["status"] == "complete":
        for q in reversed(local["path"][1:]):
            v = np.asarray(q[:2]) - position[:2]
            if np.linalg.norm(v) > 0.12 and visible(np.asarray(q[:2])):
                return math.atan2(v[1], v[0]), True
    return direction, True


def maneuver(network, position, heading, waypoint, wheelbase):
    """Evaluate short forward and reverse steering arcs against the same local road mesh."""
    goal = waypoint[:2]
    best = None
    for direction in (1, -1):
        for wheel in (0, -0.26, 0.26, -0.55, 0.55):
            p = position.copy()
            yaw = heading
            minimum_clearance = 0.5
            covered = 0.0
            ds = direction * 0.42
            dyaw = ds * math.tan(wheel) / wheelbase
            for _ in range(8):
                mid = yaw + 0.5 * dyaw
                dest = p[:2] + ds * np.array([math.cos(mid), math.sin(mid)])
                change = movement_step(network, p.tolist(), dest.tolist(), "drive")
                next_p = np.asarray(change["position"])
                if not change["moved"] or np.linalg.norm(next_p[:2] - dest) > 0.10:
                    break
                p = next_p
                yaw = angle(yaw + dyaw)
                covered += abs(ds)
                normal = np.array([-math.sin(yaw), math.cos(yaw)])
                for side in (-1, 1):
                    probe = movement_step(
                        network, p.tolist(), (p[:2] + side * 0.5 * normal).tolist(), "drive"
                    )
                    minimum_clearance = min(
                        minimum_clearance, np.linalg.norm(np.asarray(probe["position"])[:2] - p[:2])
                    )
            if covered < 0.8:
                continue
            desired = math.atan2(goal[1] - p[1], goal[0] - p[0])
            cost = (
                np.linalg.norm(goal - p[:2])
                + 0.9 * abs(angle(desired - yaw))
                - 0.9 * covered
                - 1.1 * minimum_clearance
                + (0.65 if direction < 0 else 0)
            )
            if best is None or cost < best[0]:
                best = (cost, direction * 1.8, direction * 1.8 * math.tan(wheel) / wheelbase)
    return None if best is None else best[1:]


def publish_status(folder, state, last):
    tmp = folder / "state.partial"
    tmp.write_text(
        json.dumps({"state": state, "row": last}, separators=(",", ":")), encoding="utf8"
    )
    # Windows readers and antivirus can temporarily hold the previous snapshot.
    # Telemetry is append-only and must keep flowing when the UI snapshot is busy.
    for attempt in range(6):
        try:
            tmp.replace(folder / "state.json")
            return
        except PermissionError:
            if attempt < 5:
                time.sleep(0.005 * (attempt + 1))
    if state != "running":
        (folder / "terminal.json").write_text(tmp.read_text(encoding="utf8"), encoding="utf8")


def run(args):
    sparse = getattr(args, "experimental_tracking", False)
    output_dir = args.run_dir or args.folder / "journey"
    config = json.loads((output_dir / "route.json").read_bytes())
    profiles = json.loads((args.folder / "journey/vehicles.json").read_bytes())
    profile = profiles[args.model]
    mounted_eye = profile["lift"] + profile["seat"][2] + 0.61 if args.model == "faggio" else 1.23
    lanes = [Lane(leg) for leg in config["legs"]]
    drive = next((lane for lane in lanes if lane.mode == "drive"), None)

    def vehicle_info(phase, pan=0):
        if drive is None:
            return {"mounted": False, "park": None, "yaw": 0}
        after = phase > lanes.index(drive)
        p = drive.path[-1] if after else drive.path[0]
        d = p - drive.at(drive.arc[-1] - 2) if after else drive.at(2) - p
        return {
            "mounted": lanes[phase].mode == "drive",
            "park": p.tolist(),
            "yaw": math.atan2(d[1], d[0]),
            "pan": pan,
        }

    rows = []
    result = "time_limit"
    references = []
    with ExitStack() as stack:
        nets = {
            m: stack.enter_context(Network(args.folder, m, adapter=args.adapter))
            for m in ("walk", "drive")
        }
        pw = stack.enter_context(sync_playwright())
        browser = pw.chromium.launch(
            executable_path=args.chrome, args=["--enable-gpu", "--use-angle=d3d11"]
        )
        page = browser.new_page()
        page.route(
            "**/rgb-lab",
            lambda r: r.fulfill(
                content_type="text/html",
                body='<canvas id="eye"></canvas><script type="importmap">{"imports":{"three":"/detail/js/three.module.js"}}</script>',
            ),
        )
        page.goto(args.url.rstrip("/") + "/rgb-lab")
        focal = page.evaluate(
            Path(__file__).with_name("observe_world_journey.mjs").read_text(encoding="utf-8"),
            dict(width=W, height=H, model=args.model),
        )
        if args.probes:
            for phase, lane in enumerate(lanes):
                previous = None
                for j, s in enumerate(np.linspace(1, lane.arc[-1] - 1, 4 if phase != 1 else 48)):
                    p = lane.at(s)
                    v = lane.at(s + 1) - lane.at(s - 1)
                    a = math.atan2(v[1], v[0])
                    eye = mounted_eye if lane.mode == "drive" else 1.68
                    prior = [*p[:2], p[2] + eye, a, -0.045]
                    live = [
                        p[0] + 0.38 * math.sin(a),
                        p[1] - 0.38 * math.cos(a),
                        p[2] + eye + 0.08,
                        a + 0.03,
                        -0.039,
                    ]
                    imgs = rgb_pair(page, prior, live, vehicle_info(phase))
                    t0 = time.perf_counter()
                    fit = correct(prior, imgs, focal)
                    ms = (time.perf_counter() - t0) * 1000
                    blank = [*imgs[:2], base64.b64encode(bytes(W * H)).decode()]
                    wrong = (
                        None if previous is None else correct(prior, [*imgs[:2], previous], focal)
                    )
                    previous = imgs[2]
                    references.append(
                        dict(
                            phase=phase,
                            station=s,
                            accepted=fit is not None,
                            error=None if fit is None else np.linalg.norm(fit[0] - live[:3]),
                            yawError=None
                            if fit is None
                            else math.degrees(abs(angle(fit[1] - live[3]))),
                            blankAccepted=correct(prior, blank, focal) is not None,
                            otherViewAccepted=None if j == 0 else wrong is not None,
                            ms=ms,
                        )
                    )
            (args.folder / "journey" / "rgb-probes.json").write_text(
                json.dumps(references, indent=2), encoding="utf8"
            )
            print(
                "probes",
                len(references),
                "accepted",
                sum(r["accepted"] for r in references),
                "other",
                sum(r["otherViewAccepted"] is True for r in references),
                flush=True,
            )
            return
        if args.run_dir:
            trace = stack.enter_context((output_dir / "telemetry.jsonl").open("w", encoding="utf8"))
        first = lanes[0]
        actual = first.path[0].copy()
        v = first.at(1) - actual
        yaw = math.atan2(v[1], v[0])
        estimated = actual.copy()
        angle_est = yaw + 0.022
        velocity = estimated_speed = 0.0
        unseen = 0
        since_fix = 0.0
        frame = 0
        disturbance = None
        for phase, lane in enumerate(lanes):
            s = 0
            stalled = 0
            pending_wide = None
            maneuver_left = 0
            maneuver_cmd = None
            confirmed_at = None
            still_ticks = 0
            previous_view = None
            clearance_ticks = 0
            moving = lane.mode == "drive"
            eye = mounted_eye if moving else 1.68
            stations, caps = lane.curve_limits()
            for _ in range(9000):
                tick_started = time.perf_counter()
                if args.run_dir and (args.run_dir / "stop").is_file():
                    result = "stopped"
                    break
                if args.displace and disturbance is None and moving and s >= args.displace[0]:
                    # Test plant only. Neither the shift nor the target is supplied to localization.
                    side = np.array([-math.sin(yaw), math.cos(yaw)])
                    xy = actual[:2] + side * args.displace[1]
                    surfaces = [z for z in nets["drive"].levels(*xy) if abs(z - actual[2]) < 1.5]
                    if not surfaces:
                        result = "displacement_without_drivable_surface"
                        break
                    actual = np.array([*xy, min(surfaces, key=lambda z: abs(z - actual[2]))])
                    disturbance = dict(frame=frame + 1, station=float(s), offset=args.displace[1])
                prior = [*estimated[:2], estimated[2] + eye, angle_est, -0.045]
                live = [*actual[:2], actual[2] + eye, yaw, -0.045 + 0.004 * math.sin(frame * 0.13)]
                pan = recovery_camera(unseen)
                prior[3] += pan
                live[3] += pan
                begin = time.perf_counter()
                imgs = rgb_pair(page, prior, live, vehicle_info(phase, pan))
                t0 = time.perf_counter()
                stopped_in_image = (
                    sparse and moving and image_standstill(previous_view, imgs[2], prior, focal)
                )
                if stopped_in_image:
                    prior[:3] = previous_view[2][:3]
                    estimated = np.asarray(prior[:3]) - [0, 0, eye]
                    estimated_speed = 0.0
                    reference = page.evaluate("p=>mapPairWithLastImage(p)", prior)
                    imgs = reference
                    clearance_ticks = 35
                verifying = pending_wide is not None or (
                    unseen >= RECOVERY_START and abs(estimated_speed) < 0.3
                )
                fit = None if verifying else correct(prior, imgs, focal)
                source = "wide_search" if verifying else "pnp"
                if sparse and not verifying and fit is None:
                    fit = sparse_correction(page, prior, imgs, focal)
                    if fit:
                        source = "sparse_pnp"
                if (
                    fit
                    and source == "pnp"
                    and (
                        np.linalg.norm(fit[0] - prior[:3]) > 0.6
                        or abs(angle(fit[1] - prior[3])) > 0.045
                        or fit[2] < 20
                    )
                ):
                    candidate = [*fit[0], fit[1], prior[4]]
                    scores = page.evaluate("q=>rankRenderedPoses(q)", [candidate, prior])
                    if scores[0] > 9 or scores[0] > scores[1] + 0.5:
                        fit = None
                if not verifying and fit is None and unseen in (2, 6, 10, 16, 22, 27):
                    fit = reacquire(page, prior, lane, s, eye)
                    if fit:
                        source = "render_search"
                if fit is None and pending_wide is not None:
                    candidate = [*pending_wide[0], pending_wide[1] + pan, prior[4]]
                    second = confirm_recovery(page, candidate, focal, sparse=sparse)
                    if second:
                        fit = second
                        source = "two_frame_recovery"
                    pending_wide = None
                if fit is None and scan_due(unseen) and abs(estimated_speed) < 0.3:
                    found = wide_pose(page, prior, nets.values(), focal, eye, pan, sparse=sparse)
                    if found:
                        pending_wide = (found[0], angle(found[1] - pan))
                match_ms = (time.perf_counter() - t0) * 1000
                if fit:
                    pending_wide = None
                    estimated = fit[0] - [0, 0, eye]
                    angle_est = angle(fit[1] - pan)
                    unseen = 0
                    since_fix = 0.0
                else:
                    unseen += 1
                s, cross = lane.progress(estimated, s)
                gap = lane.arc[-1] - s
                if (
                    fit is not None
                    and gap < 0.60
                    and np.linalg.norm(estimated[:2] - lane.path[-1, :2]) < 0.6
                    and estimated_speed < 1.4
                ):
                    result = "arrived" if phase == len(lanes) - 1 else "transfer"
                    break
                look = min(4.0, max(0.48, 0.36 * estimated_speed)) if moving else 0.42
                target = lane.at(min(s + look, lane.arc[-1]))
                narrow_ahead = False
                if moving:
                    lo = lane.at(max(0, s + look - 1))
                    hi = lane.at(s + look + 1)
                    dx, dy = hi[:2] - lo[:2]
                    side = np.array([-dy, dx]) / max(0.001, math.hypot(dx, dy))
                    clearance = []
                    for sign in (-1, 1):
                        txy = target[:2] + side * sign * 2.0
                        probe = movement_step(nets["drive"], target.tolist(), txy.tolist(), "drive")
                        clearance.append(
                            np.clip(
                                (np.asarray(probe["position"])[:2] - target[:2]) @ side * sign,
                                0,
                                2.0,
                            )
                        )
                    target = target.copy()
                    offset = (clearance[1] - clearance[0]) * 0.48 * min(1.0, gap / 4.0)
                    target[:2] += side * offset
                    if sparse and clearance_ticks:
                        target, narrow_ahead = corridor_target(
                            nets["drive"], lane, s, estimated, target, side, offset, look
                        )
                        clearance_ticks -= 1
                delta = target - estimated
                cmd_yaw = angle(math.atan2(delta[1], delta[0]) - angle_est)
                constrained = False
                if moving:
                    direction, constrained = reachable_heading(
                        nets["drive"], estimated, target, angle_est
                    )
                    cmd_yaw = angle(direction - angle_est)
                    if fit:
                        displacement = (
                            math.inf
                            if confirmed_at is None
                            else np.linalg.norm(estimated[:2] - confirmed_at)
                        )
                        still_ticks = (
                            still_ticks + 1
                            if displacement < 0.14 and abs(estimated_speed) > 0.7
                            else 0
                        )
                        confirmed_at = estimated[:2].copy()
                    if constrained or still_ticks >= 3:
                        clearance_ticks = 35
                    if not maneuver_left and (constrained or still_ticks >= 3 or stopped_in_image):
                        maneuver_cmd = maneuver(
                            nets["drive"],
                            estimated,
                            angle_est,
                            lane.at(s + 5.0),
                            profile["wheelbase"],
                        )
                        if maneuver_cmd:
                            maneuver_left = 4
                near = lane.at(s + 2) - lane.at(s)
                farther = lane.at(s + 8) - lane.at(s + 2)
                bend = abs(angle(math.atan2(near[1], near[0]) - math.atan2(farther[1], farther[0])))
                target_speed = (
                    min(23.0, math.sqrt(3.0 / max(0.006, bend / 4)), 3.0 / max(0.08, abs(cmd_yaw)))
                    if moving
                    else 2.7
                )
                if moving:
                    target_speed = min(
                        target_speed, float(np.interp(s + min(0.5, gap * 0.2), stations, caps))
                    )
                target_speed = min(
                    target_speed, math.sqrt(2 * (4 if moving else 2) * max(0, gap - 0.18))
                )
                if not moving and abs(cmd_yaw) > 0.55:
                    target_speed *= 0.15
                if narrow_ahead:
                    target_speed = min(target_speed, 3.0)
                if constrained:
                    target_speed = min(target_speed, 1.5)
                if maneuver_left:
                    target_speed = maneuver_cmd[0]
                if unseen:
                    since_fix += abs(estimated_speed) * DT
                    remaining = max(0.0, (18.0 if moving else 2.0) - since_fix)
                    target_speed = min(
                        target_speed, 7.0 if moving else 1.0, math.sqrt(8 * remaining)
                    )
                    if unseen >= 6 or cross > (1.3 if moving else 0.7) or gap < 1.0:
                        target_speed = 0.0
                if unseen >= 6:
                    maneuver_left = 0
                if unseen >= 30:
                    result = "localization_lost"
                    break
                accel = 3.3 if moving else 3.0
                brake = 8 if moving else 5.0
                speed_change = target_speed - estimated_speed
                throttle = float(np.clip(speed_change / (accel * DT), 0, 1))
                braking = float(np.clip(-speed_change / (brake * DT), 0, 1))
                velocity += np.clip(target_speed - velocity, -brake * DT, accel * DT)
                estimated_speed += np.clip(target_speed - estimated_speed, -brake * DT, accel * DT)
                limit = (
                    min(
                        1.65,
                        abs(estimated_speed) * math.tan(0.56) / profile["wheelbase"],
                        7.0 / max(1.0, estimated_speed),
                    )
                    if moving
                    else 2.5
                )
                turn = np.clip(cmd_yaw, -limit * DT, limit * DT)
                if maneuver_left:
                    turn = np.clip(maneuver_cmd[1] * DT, -limit * DT, limit * DT)
                    maneuver_left -= 1
                command_ms = (time.perf_counter() - begin) * 1000
                observed_speed = velocity * 0.987
                theta = yaw + turn * 0.5 * 0.99
                dest = actual[:2] + observed_speed * DT * np.array(
                    [math.cos(theta), math.sin(theta)]
                )
                step = movement_step(nets[lane.mode], actual.tolist(), dest.tolist(), lane.mode)
                yaw = angle(yaw + turn * 0.99)
                body_speed = math.dist(actual[:2], step["position"][:2]) / DT
                if step["moved"]:
                    actual = np.asarray(step["position"])
                    stalled = 0
                elif observed_speed > 0.2 and unseen == 0:
                    stalled += 1
                previous_view = (
                    imgs[2],
                    imgs[1],
                    [*estimated[:2], estimated[2] + eye, angle_est + pan, prior[4]],
                )
                predicted = estimated[:2] + estimated_speed * DT * np.array(
                    [math.cos(angle_est + turn * 0.5), math.sin(angle_est + turn * 0.5)]
                )
                estimate_step = movement_step(
                    nets[lane.mode], estimated.tolist(), predicted.tolist(), lane.mode
                )
                if estimate_step["moved"]:
                    estimated = np.asarray(estimate_step["position"])
                elif any(
                    abs(h - estimated[2]) < 0.42 for h in nets[lane.mode].levels(*estimated[:2])
                ):
                    # The predicted body is already supported. A wall clips its velocity.
                    estimated_speed = 0.0
                else:
                    # A map projection can reject an uncertain prior at a boundary.
                    # Integrate the issued command; the next RGB view corrects the prediction.
                    estimated[:2] = predicted
                    estimated[2] = lane.at(s + estimated_speed * DT)[2]
                angle_est = angle(angle_est + turn)
                frame += 1
                rows.append(
                    dict(
                        frame=frame,
                        mode=lane.mode,
                        simTime=round(frame * DT, 2),
                        requestedSpeed=float(target_speed),
                        steering=float(turn / DT),
                        pan=pan,
                        clearanceLimited=constrained,
                        narrowAhead=narrow_ahead,
                        imageStationary=bool(stopped_in_image),
                        estimatedYaw=angle_est,
                        distance=float(sum(x.arc[-1] for x in lanes[:phase]) + s),
                        phase=phase,
                        s=round(float(s), 3),
                        actual=actual.tolist(),
                        yaw=yaw,
                        estimated=estimated.tolist(),
                        inliers=0 if fit is None else fit[2],
                        cross=float(cross),
                        moved=step["moved"],
                        speed=float(observed_speed),
                        groundSpeed=body_speed,
                        source=source if fit else "prediction",
                        visualConfirmed=bool(fit),
                        disturbance=disturbance
                        if disturbance and disturbance["frame"] == frame
                        else None,
                        lostTicks=unseen,
                        distanceSinceFix=since_fix,
                        commandMs=command_ms,
                        throttle=throttle,
                        brake=braking,
                        matchMs=match_ms,
                        totalMs=(time.perf_counter() - begin) * 1000,
                    )
                )
                if args.run_dir:
                    trace.write(json.dumps(rows[-1], separators=(",", ":")) + "\n")
                    trace.flush()
                    publish_status(output_dir, "running", rows[-1])
                    if (unseen in (3, 12) or stalled == 3) and not (
                        output_dir / f"loss-{frame // 25:06}.jpg"
                    ).exists():
                        ref = np.frombuffer(base64.b64decode(imgs[0]), np.uint8).reshape(H, W)
                        live_image = np.frombuffer(base64.b64decode(imgs[2]), np.uint8).reshape(
                            H, W
                        )
                        cv2.imwrite(
                            str(output_dir / f"loss-{frame // 25:06}.jpg"),
                            np.hstack([ref, live_image]),
                        )
                    if args.realtime:
                        time.sleep(max(0, DT - (time.perf_counter() - tick_started)))
                if not frame % 200:
                    print("step", frame, phase, round(s), round(cross, 2), flush=True)
                if stalled >= 40:
                    result = "surface_blocked"
                    break
            if result != "transfer":
                break
            if np.linalg.norm(actual - lane.path[-1]) > 1.0:
                result = "transfer_out_of_reach"
                break
            if lanes[phase + 1].mode == "drive":
                # Board the parked body at its door. The vehicle has its own heading.
                vehicle = lanes[phase + 1]
                actual = vehicle.path[0].copy()
                estimated = actual.copy()
                tangent = vehicle.at(1) - actual
                yaw = math.atan2(tangent[1], tangent[0])
                angle_est = yaw
            velocity = estimated_speed = 0.0
            result = "time_limit"
        browser.close()
    if result == "arrived" and np.linalg.norm(actual - lanes[-1].path[-1]) > 1.0:
        result = "finish_mismatch"
    if args.run_dir:
        publish_status(output_dir, result, rows[-1] if rows else None)
    out = output_dir / "rgb-drive.json"
    out.write_text(
        json.dumps(dict(result=result, rows=rows, disturbance=disturbance), separators=(",", ":")),
        encoding="utf8",
    )
    print(result, len(rows), rows[-1] if rows else "", flush=True)


if __name__ == "__main__":
    c = argparse.ArgumentParser(description=__doc__)
    c.add_argument("--folder", type=Path, required=True)
    c.add_argument("--url", default="http://127.0.0.1:8817")
    c.add_argument("--probes", action="store_true")
    c.add_argument(
        "--chrome",
        default=str(
            Path(os.environ.get("ProgramFiles", "C:/Program Files"))
            / "Google/Chrome/Application/chrome.exe"
        ),
    )
    c.add_argument("--adapter", type=Path)
    c.add_argument("--run-dir", type=Path)
    c.add_argument(
        "--displace",
        type=float,
        nargs=2,
        metavar=("DRIVE_STATION", "SIDE_OFFSET"),
        help="inject one lateral offset into the test body",
    )
    c.add_argument(
        "--experimental-tracking",
        action="store_true",
        help="test sparse and temporal recovery on the geometric stand",
    )
    c.add_argument("--realtime", action="store_true")
    c.add_argument("--model", choices=["faggio", "premier"], default="faggio")
    run(c.parse_args())
