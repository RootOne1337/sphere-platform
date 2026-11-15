
"""Re-measure asynchronous RoMa correspondences on the current video frame."""
from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
import math

import cv2 as cv
import numpy as np

from motor_worker.route_localization import SIZE, trace_step_scale
from motor_worker.route_xfeat import ReferenceLKXFeatLocalizer
from motor_worker.route_xfeat_fast import _FastMeasuredSolve, FAST_XFEAT_POLICY

ROMA_POLICY = "rocm_roma_v2_cached_288_current_lk_pnp_v1"


@dataclass(frozen=True)
class _Seed:
    started: float
    at: float
    gray: object
    pairs: tuple
    prior: object


class _RomaSolve(_FastMeasuredSolve):
    def __init__(self, *args, roma_process, reference_images, **kwargs):
        self.roma_process = roma_process
        self.reference_images = reference_images
        self._rgb = OrderedDict()
        self._last_ordinary = None
        self._pending_roma = None
        self._roma_anchor = None
        self._roma_next_at = 0.
        super().__init__(*args, **kwargs)

    def close(self):
        process, self.roma_process = self.roma_process, None
        if process is not None:
            process.close()
        self._rgb.clear()
        self._roma_anchor = self._pending_roma = None
        super().close()

    @property
    def roma_status(self):
        return self.roma_process.status if self.roma_process is not None else "unavailable"

    def _features(self, frame):
        self._roma_frame = frame
        return super()._features(frame)

    def _reference_rgb(self, index):
        if index not in self._rgb:
            path = self.reference_images / self.route.reference_names[index]
            if (path.is_symlink() or getattr(path, "is_junction", lambda: False)()
                    or not 0 < path.stat().st_size <= 8 * 1024**2):
                raise ValueError("invalid RoMa reference image")
            raw = path.read_bytes()
            if sha256(raw).hexdigest() != self.route.source_png_sha256[index]:
                raise ValueError("changed RoMa reference image")
            image = cv.imdecode(np.frombuffer(raw, np.uint8), cv.IMREAD_COLOR)
            if image is None:
                raise ValueError("RoMa reference decode")
            rgb = cv.cvtColor(cv.resize(image, SIZE, interpolation=cv.INTER_AREA), cv.COLOR_BGR2RGB)
            if sha256(rgb).hexdigest() != self.route.reference_rgb_sha256[index]:
                raise ValueError("changed RoMa reference pixels")
            self._rgb[index] = rgb
        self._rgb.move_to_end(index)
        if len(self._rgb) > 8:
            self._rgb.popitem(last=False)
        return self._rgb[index]

    def _queue_roma(self, frame):
        if (not self.roma_process.available or frame.received_at < self._roma_next_at
                or not self._fresh(frame)):
            return
        rank = self.last_diagnostic.get("candidateReferenceIndices") or ()
        prior = self._last_ordinary
        if prior is not None and 0 < frame.received_at - prior.received_at <= 1.8:
            selected = (next((index for index in rank if abs(index-prior.segment) <= 8), prior.segment),)
        elif len(rank) >= 2:
            selected = (rank[0], next((index for index in rank[1:] if 2 <= abs(index-rank[0]) <= 8), rank[1]))
            prior = None
        else:
            return
        references, measures = [], []
        arrays = self._cache.arrays
        try:
            for index in selected:
                start, end = arrays["offsets"][index:index+2]
                references.append((index, self._reference_rgb(index), arrays["pixels"][start:end].copy()))
                measures.append((index, arrays["xyz"][start:end].copy()))
        except (OSError, ValueError, cv.error):
            self.roma_process.disable()
            return
        if not self._fresh(frame):
            return
        query = np.frombuffer(frame.rgb24, np.uint8).reshape(540, 960, 3)
        if self.roma_process.submit(query, tuple(references)):
            self._pending_roma = (frame.receiver_sequence, frame.received_at,
                                  self.last_source_sha, self._gray.copy(), prior, tuple(measures))
            self._roma_next_at = frame.received_at + .38

    def _try_roma_seed(self, frame):
        reply = self.roma_process.poll()
        if reply is None or self._pending_roma is None:
            return None
        sequence, at, digest, gray, prior, candidates = self._pending_roma
        self._pending_roma = None
        if (not 0 < frame.received_at - at <= .70 or sequence >= frame.receiver_sequence
                or digest == self.last_source_sha
                or self._last_ordinary is not None and self._last_ordinary.received_at >= at):
            return None
        pairs = tuple((index, xyz[reply[slot][0]], reply[slot][1])
                      for slot, (index, xyz) in enumerate(candidates))
        return _Seed(at, at, gray, pairs, prior)

    def _remeasure(self, old_gray, points, pixels):
        if len(points) < 32:
            return None
        old = pixels.astype(np.float32).reshape(-1, 1, 2)
        options = dict(winSize=(21, 21), maxLevel=3)
        current, status, error = cv.calcOpticalFlowPyrLK(old_gray, self._gray, old, None, **options)
        if current is None or status is None or error is None or not np.isfinite(current).all():
            return None
        back, returned, _ = cv.calcOpticalFlowPyrLK(self._gray, old_gray, current, None, **options)
        if back is None or returned is None or not np.isfinite(back).all():
            return None
        xy = current.reshape(-1, 2)
        keep = ((xy >= 1) & (xy < np.asarray(SIZE) - 1)).all(axis=1)
        x, y = np.rint(xy).astype(np.int32).clip([0, 0], [959, 539]).T
        keep &= (status.ravel() == 1) & (returned.ravel() == 1) & (error.ravel() <= 12) & (self.mask[y, x] > 0)
        keep &= np.linalg.norm((back-old).reshape(-1, 2), axis=1) <= 1.
        if int(keep.sum()) < 32:
            return None
        world, image = points[keep], xy[keep].astype(np.float64)
        fit = self._verify_correspondences(world, image)
        if fit is None or fit[2] < 32:
            return None
        return fit, world[fit[4]], image[fit[4]]

    def _measure_seed(self, seed, frame):
        if not 0 < frame.received_at - seed.at <= .48 or frame.received_at - seed.started > .80:
            return None
        verified, step = [], trace_step_scale(self.lengths)
        for index, points, pixels in seed.pairs:
            if not self._fresh(frame):
                return None
            motion = self._remeasure(seed.gray, points, pixels)
            if motion is None:
                return None
            fit, world, image = motion
            near = self._nearest(fit[0])
            if near is None or near[2] > step * 3 or abs(near[0]-index) > 14:
                return None
            verified.append((fit, near, (index, world, image)))
        if not verified or not self._fresh(frame):
            return None
        verified.sort(key=lambda row: -row[0][2])
        best, near, data = verified[0]
        if seed.prior is not None:
            if (np.linalg.norm(best[0] - seed.prior.center) > 6 * step
                    or abs(near[1] - seed.prior.progress_units) > 6 * step):
                return None
        elif len(verified) != 2:
            return None
        if len(verified) == 2:
            other, other_near, other_data = verified[1]
            novel = len({tuple(row) for row in other_data[1]} - {tuple(row) for row in data[1]})
            if (novel < 8 or np.linalg.norm(best[0]-other[0]) > step
                    or abs(near[1]-other_near[1]) > step
                    or np.trace(best[1] @ other[1].T) < 1 + 2 * math.cos(math.radians(6))):
                return None
        return best, tuple(row[2] for row in verified)

    def _candidates_ranked(self):
        if self.confirmations < 3:
            self._queue_roma(self._roma_frame)

    def _solve(self, *args):
        frame = self._roma_frame
        anchor, self._roma_anchor = self._roma_anchor, None
        for seed in (self._try_roma_seed(frame), anchor):
            if seed is None:
                continue
            measured = self._measure_seed(seed, frame)
            if measured is not None:
                fit, pairs = measured
                self._roma_anchor = _Seed(seed.started, frame.received_at, self._gray.copy(), pairs, seed.prior)
                self.current = pairs[0][1], pairs[0][2], False
                self.last_diagnostic["method"] = "roma_v2_lk_pnp"
                return fit
        answer = super()._solve(*args)
        if answer is None:
            self._queue_roma(frame)
        return answer


class RomaVehicleLocalizer(ReferenceLKXFeatLocalizer, _RomaSolve):
    verification_policy = f"{ReferenceLKXFeatLocalizer.verification_policy}:{FAST_XFEAT_POLICY}:{ROMA_POLICY}"

    def observe(self, frame, **binding):
        pose = super().observe(frame, **binding)
        if pose.state == "localized" and self.last_diagnostic.get("method") != "roma_v2_lk_pnp":
            self._last_ordinary = pose
        if pose.reason in {"route_binding_retired", "route_scene_geometry_or_age_unqualified",
                           "route_pose_discontinuity", "route_observation_gap"}:
            self._roma_anchor = self._pending_roma = None
            self._last_ordinary = None
        return pose
