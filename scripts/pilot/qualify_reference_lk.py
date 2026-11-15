"""Measure an exported Reference-LK route and publish its controlled-test receipt."""

import argparse
import hashlib
import json
import tempfile
import time
import uuid
from collections import Counter
from contextlib import closing
from pathlib import Path

from motor_worker.browser_teach import decoded_browser, validate_browser
from motor_worker.policy import PolicyFrame
from motor_worker.route_confirmation import ReferenceLKConfirmationLocalizer
from motor_worker.route_reference_lk import CACHE_FILE, SIZE, ReferenceLKRoute, canonical_hash
from scripts.pilot.atomic_json import write_json
from scripts.pilot.route_preparation_source import attempt_cancelled, attempt_source
from scripts.pilot.route_reference_lk_export import (
    QUALIFICATION_SCHEMA,
    VALIDATION_SCHEMA,
    validate_reference_lk_qualification,
    validate_reference_lk_receipt,
)
from scripts.pilot.route_workspace import ID, resource_checkpoint, route_resource_profile


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _video_digest(capture):
    with (capture.root / "video.h264").open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _replay(route, capture, kind, check, deadline):
    import cv2 as cv

    timed = kind == "same_recording_heldout_transport"
    unrelated = kind == "unrelated_negative"
    taught = set() if unrelated else set(route.source_frame_indices)
    references = set(route.reference_rgb_sha256)
    if capture.geometry[0] * SIZE[1] != capture.geometry[1] * SIZE[0]:
        raise ValueError("reference_lk_replay_geometry")
    rows, seen = [], set()
    now, wall, first_ticks, previous_ticks = 0., None, None, -90000

    def tracker():
        epoch, episode, goal = (str(uuid.uuid4()) for _ in range(3))
        clock = time.perf_counter if timed else lambda: now
        return ReferenceLKConfirmationLocalizer(route, capture_epoch=epoch, episode_id=episode,
                                                goal_revision=goal, clock=clock)

    localizer = tracker()
    try:
        with closing(decoded_browser(capture)) as source:
            for meta, image in source:
                if deadline is not None and time.monotonic() >= deadline:
                    raise RuntimeError("reference_lk_replay_deadline")
                ticks = meta["relative_ticks_90k"]
                if meta["index"] in taught or ticks - previous_ticks < 18000:
                    continue
                rgb = cv.resize(image.to_ndarray(format="rgb24"), SIZE, interpolation=cv.INTER_AREA)
                plain = rgb.tobytes()
                source_sha = _digest(plain)
                if source_sha in references or unrelated and source_sha in seen:
                    continue
                if unrelated and rows and ticks - previous_ticks > 45000:
                    localizer.close()
                    localizer = tracker()
                if len(rows) >= 3000:
                    raise ValueError("reference_lk_replay_quota")
                seen.add(source_sha)
                previous_ticks = ticks
                if len(rows) % 60 == 0:
                    check()
                row = dict(source_index=meta["index"], source_rgb_sha256=source_sha)
                if timed:
                    if wall is None:
                        wall, first_ticks = time.perf_counter(), ticks
                    delay = wall + (ticks - first_ticks) / 90000 - time.perf_counter()
                    if delay > 0:
                        time.sleep(delay)
                    now = time.perf_counter()
                    ok, encoded = cv.imencode(".jpg", cv.cvtColor(rgb, cv.COLOR_RGB2BGR),
                                               [cv.IMWRITE_JPEG_QUALITY, 86])
                    if not ok or encoded.nbytes > 384 * 1024:
                        raise ValueError("reference_lk_replay_jpeg")
                    row["jpeg_sha256"] = _digest(encoded.tobytes())
                    plain = cv.cvtColor(cv.imdecode(encoded, cv.IMREAD_COLOR), cv.COLOR_BGR2RGB).tobytes()
                else:
                    now = ticks / 90000
                start = time.perf_counter()
                frame = PolicyFrame(localizer.epoch, meta["index"] + 1, now, *SIZE, plain)
                pose = localizer.observe(frame, episode_id=localizer.episode,
                                         goal_revision=localizer.goal, scene="active")
                row.update(actualdecoded_rgb_sha256=pose.source_rgb_sha256, state=pose.state,
                           compute_ms=(time.perf_counter() - start) * 1000,
                           diagnostic={"method": localizer.last_diagnostic.get("method")})
                rows.append(row)
    finally:
        localizer.close()
    counts = Counter(row["state"] for row in rows)
    late = [row for row in rows if row["compute_ms"] > 250]
    result = dict(schema=VALIDATION_SCHEMA, kind=kind, execution_qualified=False,
                  source_capture_sha256=_digest(capture.originals["manifest.json"]),
                  sample_count=len(rows), sample_rows=rows, counts=dict(counts), offline_media_clock=not timed,
                  untaught_source_indices=not unrelated, raw_rgb_source_bound=True,
                  freshness_lower_bound=dict(receiver_age_budget_ms=250, samples_exceeding_budget=len(late),
                      localized_samples_exceeding_budget=sum(row["state"] == "localized" for row in late)))
    if timed:
        result["transport"] = dict(codec="jpeg", quality=86, width=SIZE[0], height=SIZE[1])
    if unrelated:
        result.update(unrelated_sources=True, false_pose_count=counts["confirming"] + counts["localized"])
    return result


def qualify(job, attempt, unrelated, *, deadline=None):
    """Publish only after the production validator accepts the staged evidence."""
    import shutil
    import cv2 as cv

    if not ID.fullmatch(attempt):
        raise ValueError("route_intent_missing")
    folder = job / "navigation" / attempt
    before = attempt_source(job, folder)
    binding = before["binding"]
    if binding is None:
        raise ValueError("route_reference_lk_requires_source")
    receipt = json.loads((folder / "receipt.json").read_bytes())
    validate_reference_lk_receipt(receipt, folder, source_capture_sha256=binding["source_manifest_sha256"],
        source_index_sha256=binding["reconstruction_input_sha256"], geometry_sha256=binding["geometry_sha256"],
        model_sha256=binding["model_sha256"])
    report_path = folder / "controlled-test-qualification.json"
    if report_path.exists():
        return validate_reference_lk_qualification(receipt, folder, source_binding=binding)
    positive, negative = validate_browser(job / "input"), validate_browser(unrelated)
    sha = lambda capture: _digest(capture.originals["manifest.json"])
    if (sha(positive) != receipt["source_capture_sha256"] or sha(positive) == sha(negative)
            or _video_digest(positive) == _video_digest(negative)):
        raise ValueError("reference_lk_replay_source_binding")

    profile = route_resource_profile(job, "live")

    def check():
        if attempt_cancelled(job, folder):
            raise RuntimeError("cancelled")
        # Decode and pose checking use the same measured cache and receiver
        # ceiling as live mode. Retain a single fresh volume proof for the task.
        resource_checkpoint(folder, profile=profile, snapshot=monitor.sample())

    cv.setNumThreads(2)
    from scripts.pilot.route_resource_monitor import TaskResourceMonitor
    with TaskResourceMonitor(folder) as monitor, tempfile.TemporaryDirectory(prefix="route-qualification-", dir=folder) as tmp:
        staged = Path(tmp).resolve(strict=True)
        if staged.parent != folder.resolve(strict=True):
            raise ValueError("reference_lk_qualification_path")
        for name in ("route.json", CACHE_FILE):
            shutil.copyfile(folder / name, staged / name)
        q = dict(schema=QUALIFICATION_SCHEMA, scope="controlled_experimental_test_only", reviewed=True,
                 execution_qualified=False, route_sha256=receipt["sha256"], cache_sha256=receipt["cache_sha256"],
                 pipeline_sha256=receipt["pipeline_sha256"], source_binding_sha256=canonical_hash(binding))
        with closing(ReferenceLKRoute.load(staged / "route.json", sha256=receipt["sha256"])) as route:
            for name, source, kind in (
                ("positive", positive, "same_recording_heldout"),
                ("transport", positive, "same_recording_heldout_transport"),
                ("negative", negative, "unrelated_negative"),
            ):
                result = _replay(route, source, kind, check, deadline)
                result.update(route_sha256=receipt["sha256"], cache_sha256=receipt["cache_sha256"],
                              pipeline_sha256=receipt["pipeline_sha256"])
                filename = f"reference-lk-{name}.json"
                write_json(staged / filename, result)
                q[name + "_report"] = dict(file=filename, sha256=_digest((staged / filename).read_bytes()))
        write_json(staged / report_path.name, q)
        validate_reference_lk_qualification(receipt, staged, source_binding=binding)
        check()
        if attempt_source(job, folder) != before:
            raise ValueError("route_preparation_source_changed")
        for name in ("positive", "transport", "negative"):
            filename = q[name + "_report"]["file"]
            write_json(folder / filename, json.loads((staged / filename).read_bytes()))
            if _digest((folder / filename).read_bytes()) != q[name + "_report"]["sha256"]:
                raise ValueError("reference_lk_qualification_report_changed")
        write_json(report_path, q)
    return validate_reference_lk_qualification(receipt, folder, source_binding=binding)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--unrelated-capture", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.job.resolve(strict=True), args.attempt, args.unrelated_capture.resolve(strict=True))))


if __name__ == "__main__":
    main()
