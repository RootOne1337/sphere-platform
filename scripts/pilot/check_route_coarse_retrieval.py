"""Offline comparison of thumbnail, orientation and RootSIFT reference retrieval.

This diagnostic tests top-three reference choices with the existing LK and PnP
gates. PnP acceptance alone is not ground truth or permission to navigate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import cv2 as cv
import numpy as np

from motor_worker.browser_teach import decoded_browser, validate_browser
from motor_worker.route_descriptor_recovery import ReferenceLKRecoveryLocalizer
from motor_worker.route_localization import coarse_reference_votes, extract_gray_features
from motor_worker.route_reference_lk import ReferenceLKRoute
from scripts.pilot.check_route_lighting_replay import (
    CAPTURE_FILES, holdout_coverage, holdout_window, sample_holdout_windows, validate_holdout_windows,
)
from scripts.pilot.route_descriptor_attachment import load_descriptor_recovery
from scripts.pilot.route_workspace import RouteWorkspaces, digest_file


def orientation(gray, mask):
    """A small spatial unsigned-gradient histogram, normalized per cell."""
    small = cv.resize(gray, (128, 72), interpolation=cv.INTER_AREA)
    allowed = cv.resize(mask, (128, 72), interpolation=cv.INTER_AREA) > 250
    allowed = cv.erode(allowed.astype(np.uint8), np.ones((3, 3), np.uint8)) != 0
    gx = cv.Sobel(small, cv.CV_32F, 1, 0, ksize=3)
    gy = cv.Sobel(small, cv.CV_32F, 0, 1, ksize=3)
    mag, angle = cv.cartToPolar(gx, gy, angleInDegrees=True)
    bins = np.minimum((np.mod(angle, 180) / 30).astype(np.int32), 5)
    yy, xx = np.indices(small.shape)
    indices = ((yy // 8) * 16 + xx // 8) * 6 + bins
    hist = np.bincount(indices[allowed], weights=mag[allowed], minlength=9 * 16 * 6)
    hist = hist.reshape(-1, 6).astype(np.float32)
    hist /= np.maximum(np.linalg.norm(hist, axis=1, keepdims=True), 1e-6)
    return hist.reshape(-1)


def evaluate_reference(localizer, gray, at):
    arrays, mask = localizer._cache.arrays, localizer.mask
    start, end = map(int, arrays["offsets"][at:at + 2])
    old = arrays["pixels"][start:end].reshape(-1, 1, 2)
    options = dict(winSize=(21, 21), maxLevel=3,
                   criteria=(cv.TERM_CRITERIA_EPS | cv.TERM_CRITERIA_COUNT, 30, .01))
    forward, status, error = cv.calcOpticalFlowPyrLK(arrays["grays"][at], gray, old, None, **options)
    if forward is None or status is None or error is None:
        return 0, None
    backward, back_status, _ = cv.calcOpticalFlowPyrLK(gray, arrays["grays"][at], forward, None, **options)
    if backward is None or back_status is None:
        return 0, None
    pixels = forward.reshape(-1, 2)
    inside = (np.isfinite(pixels).all(axis=1) & (pixels[:, 0] >= 0) & (pixels[:, 0] < 960)
              & (pixels[:, 1] >= 0) & (pixels[:, 1] < 540))
    allowed = np.zeros(len(pixels), bool)
    xy = np.minimum(np.rint(pixels[inside]).astype(int), [959, 539])
    allowed[inside] = mask[xy[:, 1], xy[:, 0]] != 0
    delta = np.linalg.norm(backward.reshape(-1, 2) - old.reshape(-1, 2), axis=1)
    keep = ((status.reshape(-1) == 1) & (back_status.reshape(-1) == 1)
            & np.isfinite(delta) & (delta <= 1) & np.isfinite(error.reshape(-1))
            & (error.reshape(-1) <= 12) & allowed)
    count = int(keep.sum())
    if count < 24:
        return count, None
    verified = localizer._verify_correspondences(arrays["xyz"][start:end][keep],
                                                 pixels[keep].astype(np.float64))
    return count, verified


def vote_candidates(votes):
    remaining = votes.copy()
    candidates = []
    for _ in range(3):
        at = int(np.argmax(remaining))
        if remaining[at] < 12:
            break
        candidates.append(at)
        remaining[max(0, at - 3):at + 4] = 0
    return candidates


def sequence_vote_candidates(votes, previous, neighborhoods):
    """Reserve one of three checks for recent appearance with current support."""
    global_candidates = vote_candidates(votes)
    if not global_candidates or previous is None:
        return global_candidates
    first = global_candidates[0]
    prior = np.max(np.where(neighborhoods, previous, 0), axis=1)
    eligible = (votes >= 12) & (prior > 0)
    eligible[first] = False
    if not eligible.any():
        return global_candidates
    score = votes * (0.65 + 0.35 * prior)
    nearby = int(np.argmax(np.where(eligible, score, -1)))
    return [first, nearby, *[at for at in global_candidates[1:] if at != nearby]][:3]


def replay_policy(route, sidecar, batches, policy, jpeg_quality):
    """Exercise actual confirmation and freshness gates on a fresh observer per window."""
    from motor_worker.policy import PolicyFrame
    from motor_worker.route_confirmation import (
        SOFT_VISUAL_MISSES, ReferenceLKConfirmationLocalizer, _BoundedConfirmationMixin,
    )
    from motor_worker.route_descriptor_recovery import _DescriptorRecoverySolve

    class VoteSolve(_DescriptorRecoverySolve):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.vote_prior = None
            seconds = np.asarray(route.source_seconds)
            self.vote_neighborhoods = np.abs(seconds[:, None] - seconds[None, :]) <= 1.0

        def _solve(self, *_unused):
            began = time.perf_counter()
            if not self._has_receiver_budget(.150):
                self.vote_prior = None
                self.last_diagnostic.update(method="offline_rootsift_vote_lk", skipped="receiver_budget")
                return None
            pixels, descriptors = extract_gray_features(self._gray, self.mask)
            candidates = []
            if len(pixels) >= 24 and self._has_receiver_budget(0):
                votes = coarse_reference_votes(self._coarse_matches(descriptors), self.visibility)
                if policy == "sequence_vote":
                    previous = None
                    if self.vote_prior is not None:
                        then, scores = self.vote_prior
                        if 0 < self.last_received - then <= .5:
                            previous = scores
                    candidates = sequence_vote_candidates(votes, previous, self.vote_neighborhoods)
                    self.vote_prior = ((self.last_received, np.where(votes >= 12, votes / votes.max(), 0))
                                       if candidates else None)
                else:
                    candidates = vote_candidates(votes)
            else:
                self.vote_prior = None
            self.last_diagnostic.update(method="offline_rootsift_vote_lk", candidateReferenceIndices=candidates,
                                        coarseAndFeaturesMs=(time.perf_counter() - began) * 1000)
            proposals, retained = [], []
            for at in candidates:
                if not self._has_receiver_budget(0):
                    self.last_diagnostic["skipped"] = "receiver_budget"
                    break
                count, verified = evaluate_reference(self, self._gray, at)
                retained.append(count)
                if verified is not None:
                    proposals.append(verified[:4])
            self.last_diagnostic.update(flowRetainedByCandidate=retained, verifiedCandidateCount=len(proposals),
                                        testedCandidateCount=len(retained))
            return self._rank_proposals(proposals) if proposals else None

    class VoteObserver(_BoundedConfirmationMixin, VoteSolve):
        def observe(self, *args, **kwargs):
            pose = super().observe(*args, **kwargs)
            if pose.state == "unknown" and pose.reason not in SOFT_VISUAL_MISSES:
                self.vote_prior = None
            return pose

    runs = []
    for batch in batches:
        prepared = []
        for index, seconds, rgb in batch:
            ok, encoded = cv.imencode(".jpg", cv.cvtColor(rgb, cv.COLOR_RGB2BGR),
                                      [cv.IMWRITE_JPEG_QUALITY, jpeg_quality])
            if not ok or len(encoded) > 384 * 1024:
                raise ValueError("replay jpeg quota")
            data = cv.cvtColor(cv.imdecode(encoded, cv.IMREAD_COLOR), cv.COLOR_BGR2RGB)
            prepared.append((index, seconds, data.tobytes(), hashlib.sha256(encoded.tobytes()).hexdigest()))
        opts = dict(capture_epoch=str(uuid4()), episode_id=str(uuid4()), goal_revision=str(uuid4()),
                    clock=time.perf_counter)
        tracker = (ReferenceLKConfirmationLocalizer(route, **opts) if policy == "baseline"
                   else VoteObserver(route, sidecar=sidecar, **opts))
        rows, cursor = [], 0
        with closing(tracker):
            start = time.perf_counter() + .025
            while cursor < len(prepared):
                captured = start + prepared[cursor][1] - prepared[0][1]
                delay = captured - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                if cursor + 1 < len(prepared) and start + prepared[cursor + 1][1] - prepared[0][1] <= time.perf_counter():
                    cursor += 1
                    continue
                index, seconds, rgb, jpeg_sha = prepared[cursor]
                cv.setRNGSeed(17)
                frame = PolicyFrame(tracker.epoch, cursor + 1, captured, 960, 540, rgb)
                pose = tracker.observe(frame, episode_id=tracker.episode, goal_revision=tracker.goal, scene="active")
                age_ms = (time.perf_counter() - captured) * 1000
                rows.append({"frame": index, "seconds": seconds, "state": pose.state, "reason": pose.reason,
                             "jpegSha256": jpeg_sha,
                             "inliers": pose.inliers, "center": pose.center, "progressUnits": pose.progress_units,
                             "ageMs": age_ms,
                             "localizedOnTime": pose.state == "localized" and age_ms <= 250,
                             "diagnostic": dict(tracker.last_diagnostic)})
                cursor += 1
        runs.append({"scheduled": len(prepared), "dropped": len(prepared) - len(rows),
                     "scheduledQueries": [{"frame": index, "seconds": seconds, "jpegSha256": sha}
                                          for index, seconds, _, sha in prepared], "rows": rows})
    return runs


def paced_holdout_coverage(windows, replays):
    """Compare exact encoded inputs, then summarize freshness and outages by window."""
    baseline = replays["baseline"]
    result = {}
    for policy, runs in replays.items():
        for control, run in zip(baseline, runs, strict=True):
            if control["scheduledQueries"] != run["scheduledQueries"]:
                raise ValueError("route_coarse_replay_query_mismatch")
        held_out_runs = runs[:len(windows)]
        coverage = holdout_coverage(windows, held_out_runs, timestamp_key="seconds")
        for item, run in zip(coverage, held_out_runs, strict=True):
            rows = run["rows"]
            item.update(dropped=run["dropped"], repliesOver250Ms=sum(row["ageMs"] > 250 for row in rows),
                        framesWithVerifiedGeometryOnTime=sum(row["ageMs"] <= 250 and
                            row["diagnostic"].get("verifiedCandidateCount", 0) > 0 for row in rows),
                        ageP95Ms=float(np.percentile([row["ageMs"] for row in rows], 95)) if rows else None,
                        reasons=dict(Counter(row["reason"] for row in rows)))
        result[policy] = coverage
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    parser.add_argument("holdout", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--window", type=holdout_window, action="append", required=True)
    parser.add_argument("--negative-plan", type=Path,
                        help="Optional prior private plan with unrelated scene images and hashes")
    parser.add_argument("--replay", action="store_true", help="also run paced observer and freshness gates")
    parser.add_argument("--sequence-vote", action="store_true",
                        help="compare a causal two-frame proposal policy in paced replay")
    parser.add_argument("--jpeg-quality", type=int, choices=(86, 92), default=86,
                        help="OpenCV JPEG quality for paced replay (browser encoder may differ)")
    parser.add_argument("--negative-replay", action="store_true",
                        help="also replay unrelated images at artificial 5 Hz, requires --replay and --negative-plan")
    args = parser.parse_args()
    if args.sequence_vote and not args.replay:
        parser.error("--sequence-vote requires --replay")
    if args.negative_replay and not (args.replay and args.negative_plan):
        parser.error("--negative-replay requires --replay and --negative-plan")
    root = Path(__file__).resolve().parents[2]
    pilot = (root / ".local-pilot").resolve(strict=True)
    job, holdout = args.job.resolve(strict=True), args.holdout.resolve(strict=True)
    output = args.output.absolute()
    if (output.exists() or not output.parent.resolve(strict=True).is_relative_to(pilot)
            or output.resolve().is_relative_to(job) or output.resolve().is_relative_to(holdout)):
        raise ValueError("output must be new, under .local-pilot, and outside inputs")
    active = json.loads((job / "navigation/active.json").read_bytes())["id"]
    if len(active) != 32 or any(c not in "0123456789abcdef" for c in active):
        raise ValueError("invalid navigation id")
    nav = job / "navigation" / active
    receipt = json.loads((nav / "receipt.json").read_bytes())
    sidecar, attachment_paths, _ = load_descriptor_recovery(nav, receipt, stamp=RouteWorkspaces._runtime_source_stamp)
    if sidecar is None:
        raise ValueError("descriptor attachment required for offline vote candidate")
    negatives = []
    if args.negative_plan:
        plan_path = args.negative_plan.resolve(strict=True)
        plan = json.loads(plan_path.read_bytes())
        negatives = [(root / item["path"], item) for item in plan["negatives"][::3]]
        if not 1 <= len(negatives) <= 40:
            raise ValueError("negative frame quota")
    paths = [Path(__file__).resolve(), Path(__file__).with_name("check_route_lighting_replay.py").resolve(),
             root / "motor_worker/route_reference_lk.py", root / "motor_worker/route_localization.py",
             root / "motor_worker/route_confirmation.py", root / "motor_worker/route_descriptor_recovery.py",
             job / "navigation/active.json", nav / "route.json", nav / "reference-lk.npz",
             nav / "receipt.json", *attachment_paths] + [folder / name for folder in (job / "input", holdout) for name in CAPTURE_FILES]
    if negatives:
        paths.extend([plan_path, *(path for path, _ in negatives)])
    before = {str(path): digest_file(path) for path in paths}
    if before[str(job / "input/video.h264")] == before[str(holdout / "video.h264")]:
        raise ValueError("holdout must be a distinct capture")
    if before[str(job / "input/manifest.json")] != receipt["source_capture_sha256"]:
        raise ValueError("source capture binding mismatch")
    cv.setNumThreads(2)
    capture = validate_browser(holdout)
    if capture.geometry[0] * 540 != capture.geometry[1] * 960:
        raise ValueError("capture aspect ratio mismatch")
    windows = validate_holdout_windows(args.window, capture.frames[-1]["relative_ticks_90k"])
    batches = sample_holdout_windows(decoded_browser(capture), windows)
    if negatives:
        negative_batch = []
        for path, item in negatives:
            if before[str(path)] != item["png_sha256"]:
                raise ValueError("negative source hash mismatch")
            image = cv.imread(str(path), cv.IMREAD_COLOR)
            if image is None:
                raise ValueError("negative source image unreadable")
            rgb = cv.cvtColor(cv.resize(image, (960, 540), interpolation=cv.INTER_AREA), cv.COLOR_BGR2RGB)
            if hashlib.sha256(rgb.tobytes()).hexdigest() != item["rgb_sha256"]:
                raise ValueError("negative query hash mismatch")
            negative_batch.append((item["file"], None, rgb))
        batches.append(negative_batch)
    rows = []
    replays = {}
    with closing(ReferenceLKRoute.load(nav / "route.json", sha256=receipt["sha256"])) as route:
        with closing(ReferenceLKRecoveryLocalizer(route, sidecar=sidecar, capture_epoch=str(uuid4()),
                                                 episode_id=str(uuid4()), goal_revision=str(uuid4()))) as localizer:
            t0 = time.perf_counter()
            bank = np.stack([orientation(gray, localizer.mask) for gray in localizer._cache.arrays["grays"]])
            index_ms = (time.perf_counter() - t0) * 1000
            for window_index, batch in enumerate(batches):
                for index, seconds, rgb in batch:
                    gray = cv.cvtColor(rgb, cv.COLOR_RGB2GRAY)
                    t0 = time.perf_counter()
                    score = np.mean((localizer._tiny - localizer._thumbnail(gray)) ** 2, axis=1)
                    baseline = np.argsort(score, kind="stable")[:3]
                    baseline_ms = (time.perf_counter() - t0) * 1000
                    t0 = time.perf_counter()
                    desc = orientation(gray, localizer.mask)
                    score = np.mean((bank - desc) ** 2, axis=1)
                    candidate = np.argsort(score, kind="stable")[:3]
                    candidate_ms = (time.perf_counter() - t0) * 1000
                    t0 = time.perf_counter()
                    pixels, descriptors = extract_gray_features(gray, localizer.mask)
                    vote = []
                    if len(pixels) >= 24:
                        votes = coarse_reference_votes(localizer._coarse_matches(descriptors), localizer.visibility)
                        vote = vote_candidates(votes)
                    vote_ms = (time.perf_counter() - t0) * 1000
                    fusion = list(map(int, baseline[:2]))
                    for at in [*vote, *map(int, baseline)]:
                        if at not in fusion:
                            fusion.append(at)
                        if len(fusion) == 3:
                            break
                    results = {}
                    for at in dict.fromkeys(map(int, np.r_[baseline, candidate, vote])):
                        cv.setRNGSeed(17)
                        retained, verified = evaluate_reference(localizer, gray, at)
                        results[at] = {"retained": retained, "pnpAccepted": verified is not None,
                                       "center": verified[0].tolist() if verified is not None else None,
                                       "inliers": verified[2] if verified is not None else None}
                    rows.append({"window": window_index, "frame": index, "seconds": seconds,
                                 "rgbSha256": hashlib.sha256(rgb.tobytes()).hexdigest(),
                                 "baseline": list(map(int, baseline)), "orientation": list(map(int, candidate)),
                                 "vote": vote, "fusion": fusion,
                                 "baselineMs": baseline_ms, "orientationMs": candidate_ms,
                                 "voteMs": vote_ms, "fusionMs": baseline_ms + vote_ms,
                                 "references": results})
        if args.replay:
            replay_batches = batches[:len(windows)]
            if args.negative_replay:
                replay_batches = [*replay_batches,
                                  [(index, at * .2, rgb) for at, (index, _, rgb) in enumerate(batches[-1])]]
            policies = ("baseline", "vote", "sequence_vote") if args.sequence_vote else ("baseline", "vote")
            for policy in policies:
                replays[policy] = replay_policy(route, sidecar, replay_batches, policy, args.jpeg_quality)
    if any(digest_file(Path(path)) != value for path, value in before.items()):
        raise RuntimeError("source changed during experiment")
    def stats(method, subset):
        return {"frames": len(subset),
                "framesWith24Pairs": sum(any(row["references"][i]["retained"] >= 24 for i in row[method]) for row in subset),
                "framesWithPnP": sum(any(row["references"][i]["pnpAccepted"] for i in row[method]) for row in subset),
                "p95RetrievalMs": float(np.percentile([row[method + "Ms"] for row in subset], 95))}
    report = {"scope": "offline_candidate_diagnostic", "physicalActions": 0,
              "independentPoseGroundTruth": False, "sourceFiles": before,
              "windowsSeconds": [[a / 90000, b / 90000] for a, b in windows],
              "indexBuildMs": index_ms, "frames": len(rows),
              "pnpRng": "reset to seed 17 for each reference; independent PnP only, no route or temporal admission",
              "summary": {name: stats(name, rows) for name in ("baseline", "orientation", "vote", "fusion")},
              "byWindow": [{name: stats(name, [row for row in rows if row["window"] == at])
                            for name in ("baseline", "orientation", "vote", "fusion")} for at in range(len(batches))],
              "groupLabels": [*["holdout_window"] * len(windows), *(["unrelated_scene"] if negatives else [])],
              "replayGroupLabels": [*["holdout_original_rtp"] * len(windows),
                                    *(["unrelated_scene_artificial_5hz"] if args.negative_replay else [])],
              "pacedJpegQuality": args.jpeg_quality if replays else None,
              "pacedObserverReplay": replays,
              "pacedHoldoutCoverage": paced_holdout_coverage(windows, replays) if replays else {},
              "rows": rows}
    with output.open("x", encoding="utf-8") as target:
        json.dump(report, target, indent=2, allow_nan=False)
    print(json.dumps({key: report[key] for key in ("frames", "indexBuildMs", "summary")}))


if __name__ == "__main__":
    main()
