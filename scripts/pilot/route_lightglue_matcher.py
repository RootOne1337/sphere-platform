"""Explicit optional pinned matcher for an owned offline fused candidate.

No default selection, download or device input. Temporal pairs use the original
float RootSIFT payload; generic retrieved loops use uint8-q512 DB-equivalent
descriptors L2-normalized after decoding, matching the historical loop recipe.
The caller owns masks/PNG hashes, namespaces, train-only F/native verification,
worker memory/CPU limits and the enclosing reconstruction deadline.
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass
from pathlib import Path

BACKEND = "pinned_rootsift_lightglue_temporal_float_loop_q512_v1"
MAX_VIEWS = 240
MAX_FEATURES = 1024
MAX_PAIRS = 1800
MAX_SECONDS = 360
MAX_PAYLOAD_BYTES = 2 * MAX_VIEWS * (MAX_FEATURES * 132 + 2) * 4
MAX_LOOP_PAIRS = 32
COARSE_POLICY = "world_masked_cell_mean32x18_timebins8_top2_cap32_v1"


@dataclass(frozen=True)
class Payload:
    keypoints: object
    scales: object
    oris: object
    descriptors: object
    image_size: object
    geometry_sha256: str
    float_descriptors_sha256: str
    native_descriptors_sha256: str


def masked_coarse_signature(gray, mask):
    """Excluded HUD pixels cannot contribute to an appearance proposal."""
    import cv2 as cv
    import numpy as np

    if (
        not isinstance(gray, np.ndarray)
        or gray.dtype != np.uint8
        or gray.ndim != 2
        or not isinstance(mask, np.ndarray)
        or mask.dtype != np.uint8
        or mask.shape != gray.shape
    ):
        raise ValueError("lightglue_coarse_image_mask")
    valid = (mask > 0).astype(np.float32)
    coverage = cv.resize(valid, (32, 18), interpolation=cv.INTER_AREA)
    weighted = cv.resize(gray.astype(np.float32) * valid, (32, 18), interpolation=cv.INTER_AREA)
    eligible = coverage >= 0.5
    if int(eligible.sum()) < 16:
        return np.zeros(32 * 18, np.float32)
    values = weighted / np.maximum(coverage, 1e-6)
    weights = coverage * eligible
    mean = float((values * weights).sum() / weights.sum())
    signature = (values - mean) * np.sqrt(weights)
    norm = float(np.linalg.norm(signature))
    return (signature / max(norm, 1e-6)).reshape(-1)


def propose_learned_pairs(signatures, source_seconds):
    """Same temporal lags; bounded generic appearance loops, never old indices."""
    import numpy as np

    values = np.asarray(signatures, np.float32)
    seconds = np.asarray(source_seconds, np.float64)
    if (
        values.shape != (len(seconds), 576)
        or not 10 <= len(values) <= MAX_VIEWS
        or not np.isfinite(values).all()
        or not np.isfinite(seconds).all()
        or seconds[0] < 0
        or seconds[-1] > 600
        or (np.diff(seconds) <= 0).any()
    ):
        raise ValueError("lightglue_coarse_source")
    pairs = {
        (i, i + lag): "temporal"
        for i in range(len(values))
        for lag in (1, 2, 3, 5, 8)
        if i + lag < len(values)
    }
    similarity = values @ values.T
    proposals = set()
    for i in range(len(values)):
        choices = sorted(
            (j for j in range(len(values)) if abs(j - i) >= 16),
            key=lambda j: (-float(similarity[i, j]), j),
        )
        for j in choices[:2]:
            if similarity[i, j] >= 0.3:
                proposals.add(tuple(sorted((i, j))))
    groups = [[] for _ in range(8)]
    for i, j in sorted(proposals, key=lambda pair: (-float(similarity[pair]), *pair)):
        bucket = min(7, int(8 * (seconds[i] - seconds[0]) / (seconds[-1] - seconds[0])))
        groups[bucket].append((i, j))
    chosen = 0
    while chosen < MAX_LOOP_PAIRS and any(groups):
        for group in groups:
            if group and chosen < MAX_LOOP_PAIRS:
                pairs[group.pop(0)] = "appearance_loop_proposal"
                chosen += 1
    if len(pairs) > MAX_PAIRS:
        raise ValueError("lightglue_pair_quota")
    return [(a, b, kind) for (a, b), kind in sorted(pairs.items())]


def feature_payload(geometry, descriptors, image_size, *, loop=False):
    """Keep measured COLMAP-corner XY, SIFT size and radians; no resize/offset.

    Native descriptors are q512-clipped uint8. Loop payloads decode those exact
    bytes then L2 normalize; temporal payloads retain pre-quantization floats.
    """
    import numpy as np

    geometry = np.asarray(geometry)
    descriptors = np.asarray(descriptors)
    size = np.asarray(image_size)
    if (
        geometry.ndim != 2
        or geometry.shape[1] != 4
        or not 24 <= len(geometry) <= MAX_FEATURES
        or descriptors.shape != (len(geometry), 128)
        or not np.isfinite(geometry).all()
        or not np.isfinite(descriptors).all()
        or size.shape != (2,)
        or not np.isfinite(size).all()
        or (size < 32).any()
        or (size > 4096).any()
        or not np.equal(size, np.floor(size)).all()
        or (geometry[:, :2] < 0).any()
        or (geometry[:, :2] > size).any()
        or (geometry[:, 2] <= 0).any()
        or (descriptors < 0).any()
        or not np.allclose(np.linalg.norm(descriptors, axis=1), 1.0, atol=1e-4, rtol=0)
    ):
        raise ValueError("lightglue_payload_layout")
    geometry = np.ascontiguousarray(geometry, dtype="<f4")
    raw_float = np.ascontiguousarray(descriptors, dtype="<f4")
    quantized = np.clip(np.round(raw_float * 512), 0, 255).astype("uint8")
    if loop:
        values = quantized.astype("float32")
        values /= np.maximum(np.linalg.norm(values, axis=1, keepdims=True), 1e-6)
    else:
        values = raw_float.copy()
    return Payload(
        geometry[:, :2].copy(),
        geometry[:, 2].copy(),
        geometry[:, 3].copy(),
        values,
        size.astype("float32"),
        hashlib.sha256(geometry.tobytes()).hexdigest(),
        hashlib.sha256(raw_float.tobytes()).hexdigest(),
        hashlib.sha256(quantized.tobytes()).hexdigest(),
    )


class LocalLightGlueMatcher:
    """One bounded, explicitly selected matcher session; no hidden BF fallback."""

    def __init__(
        self,
        root,
        *,
        device,
        loop_device="cpu",
        memory_fraction=0.20,
        check=lambda: None,
        clock=time.monotonic,
        max_seconds=MAX_SECONDS,
    ):
        if (
            device not in ("cpu", "cuda")
            or loop_device not in ("cpu", "cuda")
            or type(memory_fraction) not in (int, float)
            or not math.isfinite(memory_fraction)
            or not 0 < memory_fraction <= 0.65
            or type(max_seconds) not in (int, float)
            or not 0 < max_seconds <= MAX_SECONDS
            or not math.isfinite(max_seconds)
            or not callable(check)
            or not callable(clock)
        ):
            raise ValueError("lightglue_backend_configuration")
        from scripts.pilot import learned_route_features as pinned

        self.root = Path(root)
        self.check, self.clock, self.max_seconds = check, clock, max_seconds
        self.started = self.clock()
        self.last_clock = self.started
        if not math.isfinite(self.started):
            raise ValueError("lightglue_matcher_clock")
        self.device, self.loop_device, self.memory_fraction = device, loop_device, memory_fraction
        self.features, self.tensor_cache, self.matchers, self.bindings = {}, {}, {}, {}
        self.pairs = self.payload_bytes = 0
        self.closed = False
        self._bounded()
        # This check must precede importing an optional tensor runtime.
        source, weights = pinned.validate_assets(self.root)
        self.source_binding = dict(
            source_commit=pinned.SOURCE,
            weights_sha256=pinned.WEIGHTS,
            local_source=str(source),
            local_weights=str(weights),
            loader_sha256=hashlib.sha256(Path(pinned.__file__).read_bytes()).hexdigest(),
        )
        import torch

        self.torch = torch
        torch.set_num_threads(2)
        if torch.get_num_interop_threads() != 1:
            torch.set_num_interop_threads(1)
        torch.manual_seed(17)
        self._bounded()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def _bounded(self):
        if self.closed:
            raise RuntimeError("lightglue_matcher_closed")
        self.check()
        now = self.clock()
        if not math.isfinite(now) or now < self.last_clock:
            raise RuntimeError("lightglue_matcher_clock")
        self.last_clock = now
        if now - self.started > self.max_seconds:
            raise RuntimeError("lightglue_matcher_timeout")

    def register(self, identity, geometry, descriptors, image_size):
        self._bounded()
        if (
            type(identity) is not int
            or identity <= 0
            or identity in self.features
            or len(self.features) >= MAX_VIEWS
        ):
            raise ValueError("lightglue_feature_namespace")
        # Validate once now; keep owned copies independent of caller mutation.
        payload = feature_payload(geometry, descriptors, image_size)
        import numpy as np

        self.features[identity] = (
            np.ascontiguousarray(geometry, dtype="<f4").copy(),
            np.ascontiguousarray(descriptors, dtype="<f4").copy(),
            tuple(map(int, image_size)),
        )
        self.bindings[identity] = dict(
            features=len(payload.keypoints),
            image_size=list(map(int, image_size)),
            geometry_sha256=payload.geometry_sha256,
            float_descriptors_sha256=payload.float_descriptors_sha256,
            native_descriptors_sha256=payload.native_descriptors_sha256,
        )
        self._bounded()

    def _payload(self, identity, loop):
        key = (identity, loop)
        if key not in self.tensor_cache:
            geometry, descriptors, size = self.features[identity]
            payload = feature_payload(geometry, descriptors, size, loop=loop)
            device = self.loop_device if loop else self.device
            values = {
                name: getattr(payload, name)
                for name in ("keypoints", "scales", "oris", "descriptors", "image_size")
            }
            self.payload_bytes += sum(v.nbytes for v in values.values())
            if self.payload_bytes > MAX_PAYLOAD_BYTES:
                raise RuntimeError("lightglue_payload_memory_quota")
            self.tensor_cache[key] = {
                name: self.torch.from_numpy(value[None].copy()).to(device)
                for name, value in values.items()
            }
        return self.tensor_cache[key]

    def _matcher(self, device):
        if device not in self.matchers:
            from scripts.pilot.learned_route_features import load_matcher

            self._bounded()
            self.matchers[device] = load_matcher(
                self.root, self.memory_fraction, device=device, num_threads=2
            )
            self._bounded()
        return self.matchers[device]

    def match(self, first, second, *, kind):
        self._bounded()
        if (
            first == second
            or first not in self.features
            or second not in self.features
            or kind not in ("temporal", "appearance_loop_proposal")
            or self.pairs >= MAX_PAIRS
        ):
            raise ValueError("lightglue_pair_namespace_or_quota")
        import numpy as np

        loop = kind != "temporal"
        device = self.loop_device if loop else self.device
        with self.torch.inference_mode():
            output = self._matcher(device)(
                dict(image0=self._payload(first, loop), image1=self._payload(second, loop))
            )
            matched = output["matches"][0].cpu().numpy()
        if (
            not isinstance(matched, np.ndarray)
            or matched.ndim != 2
            or matched.shape[1] != 2
            or len(matched) > MAX_FEATURES
            or matched.dtype.kind not in "iu"
            or (matched < 0).any()
            or len(matched)
            and (
                matched[:, 0].max() >= len(self.features[first][0])
                or matched[:, 1].max() >= len(self.features[second][0])
            )
            or len(set(map(int, matched[:, 0]))) != len(matched)
            or len(set(map(int, matched[:, 1]))) != len(matched)
        ):
            raise RuntimeError("lightglue_matching_output_invalid")
        self.pairs += 1
        self._bounded()
        return matched.astype("<u4")

    def receipt(self):
        self._bounded()
        import cv2 as cv
        import numpy as np

        return dict(
            schema="sphere-pinned-fused-lightglue-matcher-v1",
            backend=BACKEND,
            **self.source_binding,
            torch=self.torch.__version__,
            device=self.device,
            opencv=cv.__version__,
            numpy=np.__version__,
            loop_device=self.loop_device,
            torch_threads=self.torch.get_num_threads(),
            torch_interop_threads=self.torch.get_num_interop_threads(),
            gpu_memory_fraction=self.memory_fraction
            if "cuda" in (self.device, self.loop_device)
            else None,
            seed=17,
            maximum_views=MAX_VIEWS,
            maximum_features=MAX_FEATURES,
            maximum_pairs=MAX_PAIRS,
            views=len(self.features),
            matched_pairs=self.pairs,
            payload_bytes=self.payload_bytes,
            temporal_descriptors="float_rootsift_l1_sqrt_l2",
            loop_descriptors="native_uint8_q512_decoded_l2",
            native_descriptors="uint8_clip_round_rootsift_times512",
            pixel_coordinates="colmap_corner_centers_no_extra_offset",
            keypoint_scales="opencv_sift_size",
            keypoint_orientations="radians",
            historical_temporal_device="cuda",
            historical_loop_device="cpu",
            historical_loop_device_changed=self.loop_device != "cpu",
            coarse_proposal_policy=COARSE_POLICY,
            non_temporal_pair_cap=MAX_LOOP_PAIRS,
            feature_bindings=self.bindings,
            downloads=False,
            bf_fallback=False,
            execution_qualified=False,
            physical_actions=0,
        )

    def close(self):
        if not self.closed:
            self.tensor_cache.clear()
            self.matchers.clear()
            self.features.clear()
            if "cuda" in (self.device, self.loop_device):
                self.torch.cuda.empty_cache()
            self.closed = True
