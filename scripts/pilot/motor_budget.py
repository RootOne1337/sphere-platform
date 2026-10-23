"""Offline motor-worker capacity arithmetic, never a GPU or gameplay benchmark.

Uses a conservative synchronized round: one current observation per device,
including a partially filled final batch at the supplied full-batch cost.
No third-party imports, network, model loading, device commands or file writes.
"""

from __future__ import annotations

import argparse
import json
import math


def _positive(value: float, name: str) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return value


def plan_budget(
    devices: int,
    observation_hz: float,
    *,
    batch_size: int = 1,
    gpus: int = 1,
    batch_ms: float | None = None,
    utilization: float = 0.7,
    source_fps: float | None = None,
    video_mbps: float | None = None,
) -> dict:
    if isinstance(devices, bool) or not isinstance(devices, int) or not 1 <= devices <= 10000:
        raise ValueError("devices must be an integer from 1 to 10000")
    if isinstance(gpus, bool) or not isinstance(gpus, int) or not 1 <= gpus <= 256:
        raise ValueError("gpus must be an integer from 1 to 256")
    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or not 1 <= batch_size <= devices
    ):
        raise ValueError("batch_size must be an integer from 1 to devices")
    _positive(observation_hz, "observation_hz")
    if isinstance(utilization, bool) or not math.isfinite(utilization) or not 0 < utilization < 1:
        raise ValueError("utilization must be finite and strictly between 0 and 1")
    for name, value in (
        ("batch_ms", batch_ms),
        ("source_fps", source_fps),
        ("video_mbps", video_mbps),
    ):
        if value is not None:
            _positive(value, name)
    period_ms = 1000 / observation_hz
    if not math.isfinite(period_ms) or period_ms <= 0:
        raise ValueError("observation_hz produces an unrepresentable period")
    batches = math.ceil(devices / batch_size)
    # Optimistic independent, identical GPU assignment. The most loaded GPU
    # still pays for its final partial batch; idle cards cannot merge VRAM.
    max_devices_per_gpu = math.ceil(devices / gpus)
    batches_per_gpu = math.ceil(max_devices_per_gpu / batch_size)
    observations = devices * observation_hz
    round_ms = None if batch_ms is None else batches_per_gpu * batch_ms
    derived = [observations, period_ms * utilization, observations * 256 * 256 * 3 * 8 / 1_000_000]
    if round_ms is not None:
        derived.extend([round_ms, round_ms / period_ms])
    if source_fps is not None:
        derived.append(devices * source_fps)
    if video_mbps is not None:
        derived.append(devices * video_mbps)
    if not all(math.isfinite(x) for x in derived):
        raise ValueError("requested calculation exceeds finite numeric range")
    return {
        "kind": "CALCULATION_NOT_A_BENCHMARK",
        "devices": devices,
        "gpusAssumed": gpus,
        "maximumDevicesPerGpuAssumed": max_devices_per_gpu,
        "maximumObservationsPerSecondPerGpu": max_devices_per_gpu * observation_hz,
        "observationHzPerDevice": observation_hz,
        "aggregateObservationsPerSecond": observations,
        "observationPeriodMs": period_ms,
        "batchSizeAssumed": batch_size,
        "batchesPerSynchronizedRound": batches,
        "maximumBatchesPerGpuPerRound": batches_per_gpu,
        "utilizationBudget": utilization,
        "maximumBatchMsForThisRoundBudget": period_ms * utilization / batches_per_gpu,
        "batchMsSupplied": batch_ms,
        "roundServiceMsAtSuppliedCost": round_ms,
        "roundDutyAtSuppliedCost": None if round_ms is None else round_ms / period_ms,
        "inferenceArithmeticFitsBudget": None
        if round_ms is None
        else round_ms <= period_ms * utilization,
        "sourceFpsPerDeviceSupplied": source_fps,
        "sourceRateMeetsRequestedObservationRate": None
        if source_fps is None
        else source_fps >= observation_hz,
        "aggregateDecodeFramesPerSecondIfEverySourceFrameDecoded": None
        if source_fps is None
        else devices * source_fps,
        "videoMbpsPerDeviceSupplied": video_mbps,
        "aggregateVideoPayloadMbps": None if video_mbps is None else devices * video_mbps,
        "rawRgb256ObservationPayloadMbps": derived[2],
        "assumptions": [
            "One latest observation per device per synchronized round; final partial batch costs a full batch.",
            "GPUs assumed identical and independent with balanced assignment; VRAM is not pooled. This is not a measured multi-GPU scheduler.",
            "Supplied batch time must include preprocessing/model/postprocessing allocated to the worker; values are not measured here.",
            "Batching is a proposed adapter capability; upstream InferenceSession server is not a fleet batch scheduler.",
            "Decode, network, queue tails, other GPU work, VRAM and game competence are not certified by a fit result.",
            "Source FPS at least observation Hz is necessary, not proof that every frame contains a fresh capture.",
            "RGB payload excludes framing/transport overhead; encoded video bitrate is an independent supplied assumption.",
        ],
        "gameplayReady": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--devices", type=int, required=True)
    parser.add_argument("--observation-hz", type=float, required=True)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gpus", type=int, default=1)
    parser.add_argument("--batch-ms", type=float)
    parser.add_argument("--utilization", type=float, default=0.7)
    parser.add_argument("--source-fps", type=float)
    parser.add_argument("--video-mbps", type=float)
    args = parser.parse_args()
    try:
        report = plan_budget(**vars(args))
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
