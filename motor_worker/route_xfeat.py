"""CPU XFeat measurements against a source-bound Reference-LK cache."""

import hashlib
import time
from collections import deque

import cv2 as cv
import numpy as np

from motor_worker.protocol import ProtocolError
from motor_worker.route_confirmation import _BoundedConfirmationMixin
from motor_worker.route_localization import trace_step_scale
from motor_worker.route_reference_lk import ReferenceLKLocalizer, SIZE


XFEAT_POLICY = "source_bound_xfeat_onnx_anchored_v1"
MODEL_SHA256 = "9612f3f7145d3ea1bde8dddd80265c2cd5b84a8aad61d9dad6020795c3ae5da1"
_MODEL_SIZE = (960, 512)
_SCALE = np.asarray(SIZE, np.float32) / _MODEL_SIZE


def _model_coordinates(pixels, shape):
    return pixels * np.asarray((shape[1] / 959, shape[0] / 511), np.float32) - .5


def _cubic(distance):
    x = np.abs(distance)
    return np.where(x <= 1, ((1.25 * x - 2.25) * x) * x + 1,
                    np.where(x < 2, ((-.75 * x + 3.75) * x - 6.) * x + 3., 0.))


def _sample_descriptors(maps, pixels):
    sx, sy = _model_coordinates(pixels, maps.shape).T
    ix, iy = np.floor((sx, sy)).astype(np.int32)
    offsets = (-1, 0, 1, 2)
    wx = [_cubic(sx - (ix + offset)).astype(np.float32) for offset in offsets]
    wy = [_cubic(sy - (iy + offset)).astype(np.float32) for offset in offsets]
    features = np.zeros((len(pixels), maps.shape[-1]), np.float32)
    for weight_y, offset_y in zip(wy, offsets):
        y = iy + offset_y
        for weight_x, offset_x in zip(wx, offsets):
            x = ix + offset_x
            inside = (x >= 0) & (x < maps.shape[1]) & (y >= 0) & (y < maps.shape[0])
            features[inside] += maps[y[inside], x[inside]] * (weight_x[inside] * weight_y[inside])[:, None]
    return features / np.maximum(np.linalg.norm(features, axis=1, keepdims=True), 1e-12)


class XFeatCPU:
    def __init__(self, model):
        if type(model) is not bytes or len(model) > 4 * 1024**2 or hashlib.sha256(model).hexdigest() != MODEL_SHA256:
            raise ProtocolError("route_xfeat_model_unverified")
        try:
            import onnxruntime as ort
        except ImportError as error:
            raise ProtocolError("route_xfeat_runtime_unavailable") from error
        if ort.__version__ != "1.20.1":
            raise ProtocolError("route_xfeat_runtime_unavailable")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.session = ort.InferenceSession(model, sess_options=options, providers=["CPUExecutionProvider"])

    def _heads(self, gray):
        data = cv.resize(gray.astype(np.float32), _MODEL_SIZE, interpolation=cv.INTER_LINEAR)
        maps, logits, reliability = self.session.run(
            ["descriptors", "logits", "reliability"], {"gray": data[None, None]})
        features = maps[0] / np.maximum(np.linalg.norm(maps[0], axis=0, keepdims=True), 1e-12)
        return np.ascontiguousarray(features.transpose(1, 2, 0)), logits[0], reliability[0, 0]

    def at_measured_pixels(self, gray, pixels):
        features, _, _ = self._heads(gray)
        return _sample_descriptors(features, (pixels / _SCALE).astype(np.float32))

    def query(self, gray, mask):
        features, logits, reliability = self._heads(gray)
        width, height = _MODEL_SIZE
        scores = np.exp(logits - logits.max(axis=0))
        local = (scores[:64] / scores.sum(axis=0)).transpose(1, 2, 0)
        heat = local.reshape(height // 8, width // 8, 8, 8).transpose(0, 2, 1, 3).reshape(height, width)
        maxima = (heat == cv.dilate(heat, np.ones((5, 5), np.uint8))) & (heat > .05)
        ys, xs = np.nonzero(maxima)
        pixels = np.column_stack((xs, ys)).astype(np.float32)
        if not len(pixels):
            return pixels, np.empty((0, 64), np.float32)
        p = _model_coordinates(pixels, reliability.shape)
        reliable = cv.remap(reliability, p[:, 0, None], p[:, 1, None],
                            cv.INTER_LINEAR, borderMode=cv.BORDER_CONSTANT).reshape(-1)
        u, v = np.rint(_model_coordinates(pixels, heat.shape)).astype(int).T
        ranked = heat[v.clip(0, height - 1), u.clip(0, width - 1)] * reliable
        top = np.argsort(-ranked, kind="stable")[:2300]
        pixels = pixels[top[ranked[top] > 0]]
        image = (pixels * _SCALE).astype(np.float32)
        x, y = np.rint(image).astype(int).clip([0, 0], [959, 539]).T
        allowed = mask[y, x] > 0
        return image[allowed], _sample_descriptors(features, pixels[allowed])


class _XFeatMeasuredSolve(ReferenceLKLocalizer):
    def __init__(self, route, *, model, **options):
        super().__init__(route, **options)
        try:
            self.engine = XFeatCPU(model)
            self.bank = []
            arrays = self._cache.arrays
            for at in range(0, len(route.source_seconds), 2):
                first, end = arrays["offsets"][at:at + 2]
                descriptors = self.engine.at_measured_pixels(arrays["grays"][at], arrays["pixels"][first:end])
                self.bank.append((at, arrays["xyz"][first:end], descriptors))
            self.owners = np.repeat(np.arange(len(self.bank), dtype=np.int32), [len(row[2]) for row in self.bank])
            self.search = cv.FlannBasedMatcher(dict(algorithm=1, trees=4), dict(checks=40))
            self.search.add([np.concatenate([row[2] for row in self.bank])])
            self.search.train()
            self.matcher = cv.BFMatcher(cv.NORM_L2)
            self.anchor = self.anchor_direct = self.current = None
            self.direct_progress = deque(maxlen=2)
        except BaseException:
            self.close()
            raise

    def _flow(self):
        gray, old, world, _ = self.anchor
        options = dict(winSize=(21, 21), maxLevel=3,
                       criteria=(cv.TERM_CRITERIA_EPS | cv.TERM_CRITERIA_COUNT, 30, .01))
        forward, status, error = cv.calcOpticalFlowPyrLK(gray, self._gray, old, None, **options)
        if forward is None or status is None or error is None or not np.isfinite(forward).all():
            return None
        backward, reverse, _ = cv.calcOpticalFlowPyrLK(self._gray, gray, forward, None, **options)
        if backward is None or reverse is None:
            return None
        pixels = forward.reshape(-1, 2)
        inside = ((pixels >= 0) & (pixels < SIZE)).all(axis=1)
        allowed = np.zeros(len(pixels), bool)
        x, y = np.rint(pixels[inside]).astype(int).clip([0, 0], [959, 539]).T
        allowed[inside] = self.mask[y, x] > 0
        cycle = np.linalg.norm((backward - old).reshape(-1, 2), axis=1)
        keep = (status.ravel() == 1) & (reverse.ravel() == 1) & (cycle <= 1) & (error.ravel() <= 12) & allowed
        points, image = world[keep], pixels[keep].astype(np.float64)
        self.last_diagnostic["flowRetained"] = len(points)
        answer = self._verify_correspondences(points, image)
        if answer is None or answer[2] < 24:
            return None
        nearest = self._nearest(answer[0])
        if nearest is None or self._flow_stalled(nearest[1]):
            return None
        self.current = points[answer[4]], image[answer[4]], False
        return answer

    def _flow_stalled(self, progress):
        if len(self.direct_progress) != 2 or self.previous is None:
            return False
        (older, old_at), (newer, new_at) = self.direct_progress
        horizon = self.last_received - self.previous[3]
        interval = new_at - old_at
        if not (0 < interval <= .65 and 0 < horizon <= .3):
            return False
        expected = (newer - older) / interval * horizon
        actual = progress - self.previous[2]
        return (abs(expected) > .2 * trace_step_scale(self.lengths)
                and actual * np.sign(expected) < .35 * abs(expected))

    def _exact(self, world, reference, pixels, descriptors):
        if len(reference) < 24:
            return None
        pairs = self.matcher.knnMatch(reference, descriptors, k=2)
        ratio = [m for m, n in pairs if m.distance < .85 * n.distance and m.distance < .66]
        if len(ratio) < 24:
            return None
        indices = list(dict.fromkeys(m.trainIdx for m in ratio))
        reverse = {indices[m.queryIdx]: m.trainIdx for m in self.matcher.match(descriptors[indices], reference)}
        keep = [m for m in ratio if reverse[m.trainIdx] == m.queryIdx]
        if len(keep) < 24:
            return None
        points = world[[m.queryIdx for m in keep]]
        image = pixels[[m.trainIdx for m in keep]].astype(np.float64)
        answer = self._verify_correspondences(points, image)
        if answer is None:
            return None
        nearest = self._nearest(answer[0])
        if nearest is None or nearest[2] > 5 * trace_step_scale(self.lengths):
            return None
        return answer, points[answer[4]], image[answer[4]]

    def _solve(self, *_unused):
        self.current = None
        if (self.confirmations >= 3 and self.anchor is not None and self.anchor_direct is not None
                and 0 < self.last_received - self.anchor[-1] <= .3
                and self.last_received - self.anchor_direct <= .65):
            self.last_diagnostic["method"] = "xfeat_anchored_flow"
            flow = self._flow()
            if flow is not None:
                return flow

        began = time.perf_counter()
        pixels, descriptors = self.engine.query(self._gray, self.mask)
        diagnostic = self.last_diagnostic
        diagnostic.update(method="xfeat_measured", queryFeatures=len(pixels),
                          featureExtractionMs=(time.perf_counter() - began) * 1000)
        if len(descriptors) < 24:
            return None
        matches = np.fromiter((m.trainIdx for group in self.search.knnMatch(descriptors, k=8)
                               for m in group if m.distance < .72), np.int32)
        if not len(matches):
            return None
        votes = np.bincount(self.owners[matches], minlength=len(self.bank))
        ranked = [int(j) for j in np.argsort(-votes, kind="stable")[:8] if votes[j] >= 8]
        diagnostic["candidateReferenceIndices"] = [self.bank[j][0] for j in ranked]
        candidates = {}
        for j in ranked:
            if self.clock() - self.last_received > .25:
                return None
            _, world, reference = self.bank[j]
            measured = self._exact(world, reference, pixels, descriptors)
            if measured is not None:
                answer, points, image = measured
                candidates[id(answer)] = (answer, points, image)
        diagnostic["verifiedCandidateCount"] = len(candidates)
        best = self._rank_proposals([row[0] for row in candidates.values()]) if candidates else None
        if best is not None:
            _, points, image = candidates[id(best)]
            self.current = points, image, True
        return best

    def close(self):
        self.anchor = self.current = self.engine = self.bank = self.search = self.matcher = None
        super().close()


class ReferenceLKXFeatLocalizer(_BoundedConfirmationMixin, _XFeatMeasuredSolve):
    """Use the same pose verification and temporal authority as Reference-LK."""

    verification_policy = _BoundedConfirmationMixin.verification_policy + ":" + XFEAT_POLICY

    def observe(self, frame, **binding):
        self.current = None
        pose = super().observe(frame, **binding)
        if pose.state in {"localized", "confirming"} and self.current is not None:
            points, image, direct = self.current
            self.anchor = self._gray.copy(), image.astype(np.float32).reshape(-1, 1, 2), points, frame.received_at
            if direct:
                self.anchor_direct = frame.received_at
                self.direct_progress.append((pose.progress_units, frame.received_at))
        elif pose.reason not in {"route_pose_not_verified", "route_progress_ambiguous"}:
            self.anchor = self.anchor_direct = None
            self.direct_progress.clear()
        return pose
