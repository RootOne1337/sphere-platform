"""Feed relit recorded frames to the route observer at their source cadence."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from contextlib import closing, nullcontext
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from scripts.pilot.route_replay_lighting import LIGHTING_POLICY, LIGHTING_PROFILES, apply_lighting
from scripts.pilot.route_resource_monitor import TaskResourceMonitor
from scripts.pilot.route_workspace import (
    ID,
    ROOT,
    checked_json,
    digest_file,
    resource_checkpoint,
    route_resource_profile,
)

POLICIES = ("lk", "recovery", "recovery-prewarm", "recovery720", "recovery640")
SIZE = (960, 540)


def sample_windows(frames, end, excluded, windows, samples, *, allow_short=False):
    """Choose future frames at >=200 ms spacing. Never replay map keyframes."""
    import cv2 as cv

    span = (samples + 1) * 18000
    if end < span * windows:
        if not allow_short:
            raise ValueError("route_lighting_replay_insufficient_video")
        windows = max(1, end // span)
    starts = [round((end - span) * at / (windows - 1)) for at in range(windows)] if windows > 1 else [0]
    batches = [[] for _ in starts]
    at, target = 0, starts[0]
    with closing(frames):
        for row, frame in frames:
            ticks = row["relative_ticks_90k"]
            if ticks < target or row["index"] in excluded:
                continue
            if ticks > starts[at] + span:
                if not allow_short:
                    raise ValueError("route_lighting_replay_sampling_gap")
                while at < windows and ticks > starts[at] + span:
                    at += 1
                if at == windows:
                    break
                if ticks < starts[at]:
                    target = starts[at]
                    continue
            rgb = cv.resize(frame.to_ndarray(format="rgb24"), SIZE, interpolation=cv.INTER_AREA)
            batches[at].append((row["index"], ticks / 90000, rgb))
            target = ticks + 18000
            if len(batches[at]) == samples:
                at += 1
                if at == windows:
                    return [batch for batch in batches if batch]
                target = starts[at]
    if allow_short and any(batches):
        return [batch for batch in batches if batch]
    raise ValueError("route_lighting_replay_sampling_incomplete")


def archived_frames(path, geometry_sha):
    """A small held-out real run. Keep its own recorded gaps."""
    import cv2 as cv
    import numpy as np

    if path.stat().st_size > 32 * 1024**2:
        raise ValueError("route_lighting_archive_quota")
    with ZipFile(path) as archive:
        info = archive.getinfo("metadata.json")
        if info.file_size > 256 * 1024:
            raise ValueError("route_lighting_archive_quota")
        document = json.loads(archive.read(info))
        binding = document["binding"]
        if binding["geometrySha256"] != geometry_sha or binding["querySize"] != list(SIZE):
            raise ValueError("route_lighting_archive_binding")
        frames = document["frames"]
        if not 1 <= len(frames) <= 60:
            raise ValueError("route_lighting_archive_quota")
        batch = []
        for row in frames:
            info = archive.getinfo(f"frame-{row['sequence']:06d}.jpg")
            if info.file_size > 384 * 1024:
                raise ValueError("route_lighting_jpeg_quota")
            raw = archive.read(info)
            if hashlib.sha256(raw).hexdigest() != row["jpegSha256"]:
                raise ValueError("route_lighting_archive_frame_binding")
            bgr = cv.imdecode(np.frombuffer(raw, np.uint8), cv.IMREAD_COLOR)
            if bgr is None or bgr.shape != (SIZE[1], SIZE[0], 3):
                raise ValueError("route_lighting_archive_geometry")
            batch.append((row["sequence"], row["elapsedMs"] / 1000, cv.cvtColor(bgr, cv.COLOR_BGR2RGB)))
        if any(right[1] <= left[1] for left, right in zip(batch, batch[1:])):
            raise ValueError("route_lighting_archive_frame_order")
        return batch


def reduced_features(width):
    """Experimental extraction scale. Return to the calibrated 960px grid."""
    import cv2 as cv
    import numpy as np

    from motor_worker.route_localization import extract_gray_features

    size = (width, SIZE[1] * width // SIZE[0])

    def extract(gray, mask):
        small = cv.resize(gray, size, interpolation=cv.INTER_AREA)
        support = cv.resize(mask, size, interpolation=cv.INTER_AREA) == 255
        pixels, desc = extract_gray_features(small, support.astype(np.uint8) * 255)
        pixels = (pixels + .5) * (SIZE[0] / width) - .5
        x, y = np.rint(pixels).astype(int).T
        allowed = mask[y, x] != 0
        return pixels[allowed], desc[allowed]

    return extract


def replay(batch, policy, profile, route, sidecar, seed, *, recorded_jpeg=False, compare_trace=True):
    import cv2 as cv
    import numpy as np

    from motor_worker import route_descriptor_recovery as recovery
    from motor_worker.policy import PolicyFrame
    from motor_worker.route_confirmation import ReferenceLKConfirmationLocalizer

    prepared = []
    for index, media, rgb in batch:
        if not recorded_jpeg:
            relit = apply_lighting(rgb, profile, seed=seed)
            ok, jpeg = cv.imencode(".jpg", cv.cvtColor(relit, cv.COLOR_RGB2BGR), [cv.IMWRITE_JPEG_QUALITY, 86])
            if not ok or len(jpeg) > 384 * 1024:
                raise ValueError("route_lighting_jpeg_quota")
            rgb = cv.cvtColor(cv.imdecode(jpeg, cv.IMREAD_COLOR), cv.COLOR_BGR2RGB)
        prepared.append((index, media, rgb.tobytes()))
    kwargs = dict(capture_epoch=str(uuid4()), episode_id=str(uuid4()), goal_revision=str(uuid4()), clock=time.perf_counter)
    tracker = (ReferenceLKConfirmationLocalizer(route, **kwargs) if policy == "lk"
               else recovery.ReferenceLKRecoveryLocalizer(route, sidecar=sidecar, **kwargs))
    variant = (patch.object(recovery, "extract_gray_features", reduced_features(int(policy[-3:])))
               if policy[-3:].isdigit() else nullcontext())
    trace = np.asarray(route.camera_trace)
    rows, cursor = [], 0
    with closing(tracker), variant:
        prewarm_ms = None
        if policy == "recovery-prewarm":
            began = time.perf_counter()
            tracker._coarse_matches(tracker.descriptors[:1])
            prewarm_ms = (time.perf_counter() - began) * 1000
        start = time.perf_counter() + .025
        while cursor < len(prepared):
            # Drop superseded images on overload, as the browser does.
            captured = start + prepared[cursor][1] - prepared[0][1]
            remaining = captured - time.perf_counter()
            if remaining > 0:
                time.sleep(remaining)
            if cursor + 1 < len(prepared) and start + prepared[cursor + 1][1] - prepared[0][1] <= time.perf_counter():
                cursor += 1
                continue
            index, media, rgb = prepared[cursor]
            cv.setRNGSeed(17)
            began = time.perf_counter()
            frame = PolicyFrame(tracker.epoch, cursor + 1, captured, *SIZE, rgb)
            pose = tracker.observe(frame, episode_id=tracker.episode, goal_revision=tracker.goal, scene="active")
            done = time.perf_counter()
            age = (done - captured) * 1000
            diagnostic = tracker.last_diagnostic
            error = None
            if compare_trace and pose.center is not None:
                expected = [np.interp(media, route.source_seconds, axis) for axis in trace.T]
                error = float(np.linalg.norm(np.asarray(pose.center) - expected))
            rows.append(dict(index=index, mediaSeconds=media, state=pose.state, reason=pose.reason, inliers=pose.inliers,
                             method=diagnostic.get("method"), verified=diagnostic.get("verifiedCandidateCount"),
                             centerErrorUnits=error, ageMs=age, computeMs=(done-began)*1000,
                             localizedOnTime=pose.state == "localized" and age <= 250))
            cursor += 1
    return dict(rows=rows, dropped=len(prepared)-len(rows), prewarmMs=prewarm_ms)


def summary(runs):
    import numpy as np

    rows = [row for run in runs for row in run["rows"]]
    total = len(rows) + sum(run["dropped"] for run in runs)
    localized = [row for row in rows if row["localizedOnTime"]]
    errors = [row["centerErrorUnits"] for row in localized if row["centerErrorUnits"] is not None]
    warm = [run["prewarmMs"] for run in runs if run["prewarmMs"] is not None]
    return dict(total=total, dropped=total-len(rows), localizedOnTime=len(localized),
                states=dict(Counter(row["state"] for row in rows)),
                methods=dict(Counter(row["method"] for row in rows)),
                reasons=dict(Counter(row["reason"] for row in rows)),
                ageP95Ms=float(np.percentile([row["ageMs"] for row in rows], 95)),
                prewarmP95Ms=float(np.percentile(warm, 95)) if warm else None,
                centerErrorP95Units=float(np.percentile(errors, 95)) if errors else None)


def run(args):
    import cv2 as cv

    from motor_worker.browser_teach import decoded_browser, validate_browser
    from motor_worker.route_reference_lk import ReferenceLKRoute
    from scripts.pilot.route_descriptor_attachment import load_descriptor_recovery
    from scripts.pilot.route_workspace import RouteWorkspaces

    job, output = args.job.resolve(strict=True), args.output.absolute()
    pilot = (ROOT / ".local-pilot").resolve(strict=True)
    if (output.exists() or not output.parent.resolve(strict=True).is_relative_to(pilot)
            or output.resolve().is_relative_to(job)):
        raise ValueError("route_lighting_report_scope")
    identity = checked_json(job / "navigation/active.json").get("id")
    if not isinstance(identity, str) or not ID.fullmatch(identity):
        raise ValueError("route_lighting_replay_attempt")
    nav = job / "navigation" / identity
    if checked_json(nav / "state.json")["phase"] != "ready":
        raise ValueError("route_lighting_replay_requires_ready_map")
    receipt = checked_json(nav / "receipt.json")
    capture_folder = job / "input"
    source_files = [job / "navigation/active.json", nav / "receipt.json", nav / "route.json",
                    nav / "reference-lk.npz", *(capture_folder / name for name in
                    ("manifest.json", "COMPLETE", "video.h264", "frames.jsonl", "inputs.jsonl"))]
    if args.archive:
        source_files.append(args.archive.resolve(strict=True))
    if args.diagnostic:
        source_files.extend(path.resolve(strict=True) for path in args.diagnostic)
    cv.setNumThreads(2)
    with TaskResourceMonitor(ROOT) as monitor:
        budget = route_resource_profile(job)
        resource_checkpoint(output.parent, profile=budget, snapshot=monitor.sample())
        attachment, attachment_paths, _ = load_descriptor_recovery(
            nav, receipt, stamp=RouteWorkspaces._runtime_source_stamp)
        if attachment is None and set(args.policies) != {"lk"}:
            raise ValueError("route_lighting_replay_requires_descriptor_attachment")
        source_files.extend(attachment_paths)
        before = {str(path): digest_file(path) for path in source_files}
        if before[str(capture_folder / "manifest.json")] != receipt["source_capture_sha256"]:
            raise ValueError("route_lighting_capture_binding")
        capture = validate_browser(capture_folder)
        with closing(ReferenceLKRoute.load(nav / "route.json", sha256=receipt["sha256"])) as route:
            windows = sample_windows(decoded_browser(capture), capture.frames[-1]["relative_ticks_90k"],
                                     set(route.source_frame_indices), args.windows, args.samples)
            real = archived_frames(args.archive, receipt["geometry_sha256"]) if args.archive else None
            diagnostic_windows = []
            if args.diagnostic:
                from scripts.pilot.route_diagnostic_video import (
                    decoded_diagnostic_video,
                    validate_diagnostic_video,
                )

                diagnostic = validate_diagnostic_video(*args.diagnostic)
                if (diagnostic.metadata["job"] != job.name
                        or diagnostic.metadata.get("geometrySha256") not in {None, receipt["geometry_sha256"]}
                        or diagnostic.geometry[0] * SIZE[1] != diagnostic.geometry[1] * SIZE[0]):
                    raise ValueError("route_lighting_diagnostic_source")
                end = min(60 * 90000, diagnostic.frames[-1]["relative_ticks_90k"])
                diagnostic_windows = sample_windows(decoded_diagnostic_video(diagnostic), end, set(),
                                                    args.windows, args.samples, allow_short=True)
            groups = {}
            for profile in args.profiles:
                for policy in args.policies:
                    resource_checkpoint(output.parent, profile=budget, snapshot=monitor.sample())
                    groups[f"{profile}/{policy}"] = [replay(batch, policy, profile, route, attachment, args.seed) for batch in windows]
            if real:
                compressed = [(index, at * .2, rgb) for at, (index, _, rgb) in enumerate(real)]
                for policy in args.policies:
                    resource_checkpoint(output.parent, profile=budget, snapshot=monitor.sample())
                    groups[f"archive_original_cadence/{policy}"] = [
                        replay(real, policy, "original", route, attachment, args.seed,
                               recorded_jpeg=True, compare_trace=False)]
                    groups[f"archive_artificial_5hz/{policy}"] = [
                        replay(compressed, policy, "original", route, attachment, args.seed,
                               recorded_jpeg=True, compare_trace=False)]
            for policy in args.policies if diagnostic_windows else ():
                resource_checkpoint(output.parent, profile=budget, snapshot=monitor.sample())
                groups[f"vehicle_diagnostic_video/{policy}"] = [
                    replay(batch, policy, "original", route, attachment, args.seed, compare_trace=False)
                    for batch in diagnostic_windows]
        if any(digest_file(Path(path)) != value for path, value in before.items()):
            raise RuntimeError("route_lighting_replay_source_changed")
    report = dict(scope="OFFLINE_RECORDED_OBSERVER_ONLY", physicalActions=0, sourceFilesUnchanged=True,
                  centerErrorReference="interpolated reconstruction trace, not independent ground truth",
                  seed=args.seed, lightingPolicy=LIGHTING_POLICY, sourceFiles=before,
                  summary={key: summary(value) for key, value in groups.items()},
                  groups=groups)
    with output.open("x", encoding="utf-8") as file:
        json.dump(report, file, indent=2, allow_nan=False)
    print(json.dumps(report["summary"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--diagnostic", type=Path, nargs=3, metavar=("VIDEO", "INDEX", "METADATA"))
    parser.add_argument("--profiles", nargs="+", choices=LIGHTING_PROFILES, default=LIGHTING_PROFILES)
    parser.add_argument("--policies", nargs="+", choices=POLICIES, default=("lk", "recovery"))
    parser.add_argument("--windows", type=int, choices=range(2, 7), default=4)
    parser.add_argument("--samples", type=int, choices=range(4, 17), default=6)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    if len(set(args.profiles)) != len(args.profiles) or len(set(args.policies)) != len(args.policies):
        parser.error("profiles and policies must be unique")
    run(args)


if __name__ == "__main__":
    main()
