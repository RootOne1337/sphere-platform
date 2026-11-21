"""Replay already computed candidates to inspect repeated reference hypotheses."""

import hashlib
import json
from pathlib import Path

from motor_worker.visual_global_recovery import GlobalRecovery
from motor_worker.visual_place import PlaceResult
from scripts.pilot.atomic_json import write_json


def run(source, prior, output):
    if output.exists():
        raise ValueError("output_exists")
    raw = source.read_bytes()
    data = json.loads(raw)
    reference = json.loads(prior.read_text("utf-8"))
    if (
        data.get("distinct_recordings") is not True
        or data.get("physical_actions") != 0
        or data["source_sha256"]["reference"] != reference["source_sha256"]
    ):
        raise ValueError("scope_mismatch")
    times = tuple(reference["reference_times"])
    result = {}
    for strategy, series in data["results"].items():
        tracker = GlobalRecovery(times, epoch="saved-replay")
        rows = []
        for item in series["samples"]:
            # This report stores candidate indices but not scores: the prior
            # retrieval already verified each and the tracker uses only the
            # admission floor. This cannot reproduce/assess visual matching.
            candidates = tuple(
                PlaceResult("matched", i, 15, "previously_verified") for i in item["candidates"]
            )
            pose = tracker.observe(
                candidates, item["seconds"], frame_id=item["frame"], epoch="saved-replay"
            )
            if pose.state != item["state"] or pose.reference != item["reference"]:
                raise ValueError("replay_diverged_from_saved_decisions")
            rows.append(
                dict(
                    frame=item["frame"],
                    seconds=item["seconds"],
                    state=pose.state,
                    reference=pose.reference,
                    reference_streak=pose.reference_streak,
                    reference_streak_seconds=pose.reference_streak_seconds,
                    near_reference_tail=pose.near_reference_tail,
                )
            )
        result[strategy] = dict(
            max_reference_streak=max(row["reference_streak"] for row in rows),
            max_reference_streak_seconds=max(row["reference_streak_seconds"] for row in rows),
            tail_hypothesis_frames=sum(row["near_reference_tail"] for row in rows),
            samples=rows,
        )
    if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(raw).digest():
        raise ValueError("source_changed")
    output.mkdir()
    report = dict(
        schema="sphere-reference-streak-replay-v1",
        source_report_sha256=hashlib.sha256(raw).hexdigest(),
        distinct_recordings=True,
        reference_times_not_meters=True,
        physical_actions=0,
        execution_qualified=False,
        limitation="Repeated reference indicates image-retrieval persistence, not physical motion or arrival.",
        results=result,
    )
    write_json(output / "report.json", report)
    return report


if __name__ == "__main__":
    base = Path(".local-pilot/test228-merge-attempt-20261027")
    result = run(
        base / "place-test1488-cross-session-later-v1/report.json",
        base / "test228-place-multicandidate-diverse-v1/report.json",
        base / "cross-session-streak-replay-v1",
    )
    print(
        json.dumps(
            {
                k: {x: v for x, v in row.items() if x != "samples"}
                for k, row in result["results"].items()
            }
        )
    )
