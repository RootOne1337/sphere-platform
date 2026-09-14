"""Build a compact factual snapshot from a running or finished private soak directory."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def distribution(values):
    values = sorted(values)
    if not values:
        return {"count": 0}
    return {"count": len(values), "min": values[0], "max": values[-1],
            "p50": values[math.ceil(len(values)*0.50)-1],
            "p95": values[math.ceil(len(values)*0.95)-1]}


def summarize(directory):
    status = json.loads((directory / "status.json").read_text(encoding="utf-8"))
    events = []
    incomplete_lines = 0
    with (directory / "events.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            try:
                events.append(json.loads(line))
            except ValueError:
                incomplete_lines += 1
    commands = [e["seconds"] for e in events if e["event"] == "command"]
    frames = [e["first_frame_seconds"] for e in events if e["event"] == "viewer_verified"]
    devices = {}
    for device in status["devices"]:
        samples = [e for e in events if e["event"] == "sample" and e["device"] == device]
        devices[device] = {
            "observed_pids": sorted({e["apk_pid"] for e in samples}),
            "memory_pss_kib_by_phase": {
                phase: distribution([e["pss_kib"] for e in samples if e["phase"] == phase and "pss_kib" in e])
                for phase in {e["phase"] for e in samples}},
            "projection_active_after_own_viewers_closed": sum(
                e.get("projection_active", False) for e in samples if e["phase"] == "after_viewer_close"),
        }
    return {"status": status, "command_seconds": distribution(commands),
            "first_frame_seconds": distribution(frames), "devices": devices,
            "incidents": [e for e in events if e["event"] in {
                "failed", "diagnostic_unavailable", "pipeline_cleanup_unknown", "batch_cleanup_unknown"}],
            "incomplete_event_lines": incomplete_lines,
            "scope": "Observed explicit pilot devices only; nearest-rank percentiles. Running is not passed. "
                     "Other operator viewers can keep projection active. Raw logs retain additional evidence."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    summary = summarize(args.directory)
    destination = args.directory / "summary.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    temporary.replace(destination)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
