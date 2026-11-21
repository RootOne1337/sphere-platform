"""Count unique query features with saved 2D–3D associations by image band.

Multiple matching candidates are deduplicated per query feature. Image bands
are not semantic classes and this is not a geometric accuracy measurement.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.reconstruct_route import checkpoint


def unique_query_band_counts(query, pixels):
    import numpy as np

    q, xy = np.asarray(query), np.asarray(pixels, dtype=float)
    if (
        q.ndim != 1
        or q.dtype.kind not in "iu"
        or xy.shape != (len(q), 2)
        or not np.isfinite(xy).all()
        or (q < 0).any()
        or (xy < 0).any()
        or (xy[:, 0] >= 960).any()
        or (xy[:, 1] >= 540).any()
    ):
        raise ValueError("match_coverage_invalid")
    unique = {}
    for k, v in zip(q, xy):
        key = int(k)
        if key in unique and not np.allclose(unique[key], v, atol=1e-5):
            raise ValueError("match_coverage_query_position_mismatch")
        unique[key] = v
    bands = [0, 0, 0]
    for v in unique.values():
        bands[min(int(v[1] // 180), 2)] += 1
    return bands


def run(probe_dir, output):
    import numpy as np

    probe_dir, output = Path(probe_dir), Path(output)
    checkpoint(output.parent)
    if output.exists():
        raise FileExistsError(output)
    probe_path = probe_dir / "report.json"
    raw = probe_path.read_bytes()
    probe = json.loads(raw)
    if (
        probe.get("saved_correspondences") is not True
        or probe.get("physical_actions") != 0
        or probe.get("execution_qualified") is not False
    ):
        raise ValueError("match_coverage_scope_invalid")
    output.mkdir()
    write_json(
        output / "intent.json", {"scope": "offline_saved_match_coverage", "physical_actions": 0}
    )
    samples = []
    for index, s in enumerate(probe["samples"]):
        if index % 4 == 0:
            checkpoint(output)
        name = s["correspondence_file"]
        path = probe_dir / name
        if (
            Path(name).name != name
            or path.is_symlink()
            or not path.is_file()
            or path.stat().st_size > 8 * 1024 * 1024
            or hashlib.sha256(path.read_bytes()).hexdigest() != s["correspondence_sha256"]
        ):
            raise ValueError("match_coverage_correspondence_integrity")
        with np.load(path, allow_pickle=False) as f:
            bands = unique_query_band_counts(f["query_id"], f["pixels"])
        samples.append(
            {
                "source_index": s["source_index"],
                "seconds": s["seconds"],
                "unique_query_y_bands": bands,
            }
        )
    if probe_path.read_bytes() != raw:
        raise ValueError("match_coverage_source_changed")
    total = [sum(s["unique_query_y_bands"][i] for s in samples) for i in range(3)]
    result = {
        "schema": "sphere-saved-match-coverage-v1",
        "samples": samples,
        "unique_query_y_bands": total,
        "deduplication": "per_frame_query_feature",
        "semantic_static_mask": False,
        "same_recording": True,
        "ground_truth": False,
        "physical_actions": 0,
        "execution_qualified": False,
        "probe_report_sha256": hashlib.sha256(raw).hexdigest(),
    }
    write_json(output / "report.json", result)
    return result
