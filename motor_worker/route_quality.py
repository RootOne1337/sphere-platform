"""Offline degraded-observation experiment, never autonomous qualification.

Uses held-out frames of a recording, or a separately recorded repeat. Simulated
downscale/JPEG is not equivalent to the game's own low-quality renderer.
"""

import hashlib
import time
from pathlib import Path

from motor_worker.landmarks import RouteViewMatcher
from motor_worker.policy import PolicyFrame, finite
from motor_worker.protocol import ProtocolError, integer
from motor_worker.route_memory import TaughtRoute
from motor_worker.teach import decoded_capture
from motor_worker.teach_capture import validate_capture, validate_inputs


def analyze_quality(directory, route, *, render_scale=1.0, jpeg_quality=100):
    if (type(route) is not TaughtRoute or not finite(render_scale, .25, 1)
            or not integer(jpeg_quality, 20, 100)):
        raise ProtocolError("invalid_route_quality_profile")
    import cv2 as cv
    import numpy as np

    manifest = validate_capture(directory)
    validate_inputs(directory, manifest)
    p = route.profile
    if p.width*manifest["height"] != p.height*manifest["width"]:
        raise ProtocolError("route_quality_aspect_mismatch")
    matcher = RouteViewMatcher(p, clock=lambda: 0)
    if any(v.pipeline_sha256 != matcher.pipeline_sha256 for v in route.views):
        raise ProtocolError("route_quality_pipeline_not_current")
    taught = {(v.source_epoch, v.source_sequence) for v in route.views}
    counts = {"matched_single_view": 0, "ambiguous": 0, "unknown": 0}
    samples, elapsed, skipped, last_tick = 0, [], 0, None
    for frame, meta in decoded_capture(directory, manifest):
        tick = meta["rtp_ticks"]
        if last_tick is not None and tick-last_tick < 18000:
            continue
        last_tick = tick
        if (manifest["capture_epoch"], meta["sequence"]) in taught:
            skipped += 1
            continue
        if samples >= 1500:
            raise ProtocolError("route_quality_sample_quota")
        started = time.perf_counter()
        rgb = frame.reformat(width=p.width, height=p.height, format="rgb24").to_ndarray()
        if render_scale < 1:
            small = cv.resize(rgb, (max(1, round(p.width*render_scale)), max(1, round(p.height*render_scale))),
                              interpolation=cv.INTER_AREA)
            rgb = cv.resize(small, (p.width, p.height), interpolation=cv.INTER_LINEAR)
        if jpeg_quality < 100:
            ok, encoded = cv.imencode(".jpg", cv.cvtColor(rgb, cv.COLOR_RGB2BGR),
                                     [cv.IMWRITE_JPEG_QUALITY, jpeg_quality])
            if not ok or encoded.nbytes > 2*1024*1024:
                raise ProtocolError("route_quality_encode_failed")
            rgb = cv.cvtColor(cv.imdecode(encoded, cv.IMREAD_COLOR), cv.COLOR_BGR2RGB)
        observation = PolicyFrame(manifest["capture_epoch"], meta["sequence"], 0, p.width, p.height, rgb.tobytes())
        hits, ambiguous = 0, False
        for at in range(0, len(route.views), 16):
            match = matcher.compare(observation, route.views[at:at+16])
            hits += int(match.status == "matched")
            ambiguous |= match.reason == "ambiguous_route_views"
        counts["ambiguous" if ambiguous or hits > 1 else "matched_single_view" if hits == 1 else "unknown"] += 1
        elapsed.append((time.perf_counter()-started)*1000)
        samples += 1
    if not samples:
        raise ProtocolError("route_quality_no_heldout_samples")
    # Each distribution has at most1500 scalar samples, no images/predictions.
    manifest_sha = hashlib.sha256((Path(directory)/"manifest.json").read_bytes()).hexdigest()
    return dict(kind="OFFLINE_ROUTE_VIEW_QUALITY_NOT_NAVIGATION", samples=samples, counts=counts,
                source_manifest_sha256=manifest_sha, route_id=route.id,
                same_demonstration=manifest_sha == route.source_manifest_sha256,
                reference_frames_excluded=skipped, sampling_media_hz=5,
                runtime_geometry=[p.width, p.height], simulated_render_scale=render_scale,
                simulated_jpeg_quality=jpeg_quality, approximate_degradation_only=True,
                transform_and_compare_ms=dict(p50=float(np.percentile(elapsed, 50)),
                                              p95=float(np.percentile(elapsed, 95)), maximum=max(elapsed)),
                source_capture_age_known=False, scene_verified=False, physical_actions=0,
                arrival_accepted=False, runtime_quality_qualified=False, fleet_accepted=False)
