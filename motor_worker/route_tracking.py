"""Opt-in anchored optical-flow experiment; no prediction or input authority.

Between descriptor checks, track only previously verified map landmarks and solve
absolute PnP again on the current RGB. Forward/backward LK and the base geometry,
age, corridor, ambiguity and discontinuity checks all remain necessary. A failed
mandatory global check cannot be bypassed by optical flow. Map geometry is fixed.
"""

from __future__ import annotations

from motor_worker.route_localization import SIZE, RouteLocalizer, extract_features


class AnchoredRouteLocalizer(RouteLocalizer):
    """Diagnostic, disabled by default at every existing caller.

    Initial/recovery confirmation uses three descriptor-based observations.
    Anchors expire after 0.8 s without a successful descriptor check, even if LK
    looks consistent. Nothing extrapolates through a gap or full occlusion.
    """

    MAX_DESCRIPTOR_AGE = .8
    MAX_ANCHORS = 256

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._anchors = None
        self._gray = None
        self._solution = None
        self._frame = None
        self._descriptor_at = None
        self.last_diagnostic = {}

    def _features(self, frame):
        cv, np = self.cv, self.np
        rgb = np.frombuffer(frame.rgb24, np.uint8).reshape(frame.height, frame.width, 3)
        self._gray = cv.resize(cv.cvtColor(rgb, cv.COLOR_RGB2GRAY), SIZE, interpolation=cv.INTER_AREA)
        # Descriptor extraction is deferred until a global check is necessary.
        return (), ()

    def _extract(self):
        return extract_features(self._frame, self.mask)

    def _flow(self):
        cv, np = self.cv, self.np
        old_gray, old_pixels, ids = self._anchors
        options = dict(winSize=(21, 21), maxLevel=3,
                       criteria=(cv.TERM_CRITERIA_EPS | cv.TERM_CRITERIA_COUNT, 30, .01))
        forward, status, error = cv.calcOpticalFlowPyrLK(old_gray, self._gray, old_pixels, None, **options)
        if forward is None or status is None or error is None:
            return None
        if not np.isfinite(forward).all():
            return None
        backward, back_status, _ = cv.calcOpticalFlowPyrLK(self._gray, old_gray, forward, None, **options)
        if backward is None or back_status is None:
            return None
        points = forward.reshape(-1, 2)
        discrepancy = np.linalg.norm(backward.reshape(-1, 2)-old_pixels.reshape(-1, 2), axis=1)
        inside = ((points[:, 0] >= 0) & (points[:, 0] < SIZE[0])
                  & (points[:, 1] >= 0) & (points[:, 1] < SIZE[1]))
        allowed = np.zeros(len(points), bool)
        xy = np.rint(points[inside]).astype(int)
        xy = np.minimum(xy, np.array(SIZE)-1)
        allowed[inside] = self.mask[xy[:, 1], xy[:, 0]] != 0
        keep = ((status.reshape(-1) == 1) & (back_status.reshape(-1) == 1)
                & np.isfinite(discrepancy) & (discrepancy <= 1.)
                & np.isfinite(error.reshape(-1)) & (error.reshape(-1) <= 12.) & allowed)
        self.last_diagnostic.update(flowCandidates=len(ids), flowRetained=int(keep.sum()))
        if int(keep.sum()) < 24:
            return None
        ids, points = ids[keep], points[keep].astype(np.float64)
        verified = self._verify_correspondences(self.xyz[ids], points)
        if verified is None:
            return None
        center, rotation, count, error, mask = verified
        return center, rotation, count, error, ids[mask], points[mask]

    def _solve(self, *_unused):
        age = (None if self._descriptor_at is None
               else self._frame.received_at-self._descriptor_at)
        may_track = (self._anchors is not None and self.confirmations >= 3
                     and age is not None and 0 < age < self.MAX_DESCRIPTOR_AGE)
        self.last_diagnostic.update(descriptorAgeSeconds=age, mandatoryGlobalCheck=not may_track)
        solved = self._flow() if may_track else None
        if solved is not None:
            self.last_diagnostic["method"] = "map_anchored_flow"
        else:
            self.last_diagnostic["method"] = "descriptor_pnp"
            solved = super()._solve(*self._extract())
        self._solution = solved
        return solved

    def observe(self, frame, *, episode_id, goal_revision, scene):
        self._frame, self._solution, self._gray = frame, None, None
        self.last_diagnostic = dict(method="not_attempted")
        try:
            pose = super().observe(frame, episode_id=episode_id, goal_revision=goal_revision, scene=scene)
            if pose.state in {"confirming", "localized"} and self._solution is not None:
                ids, pixels = self._solution[4:]
                # Bounded storage: one gray image plus existing map landmark IDs.
                selected = self.np.linspace(0, len(ids)-1, min(len(ids), self.MAX_ANCHORS), dtype=int)
                self._anchors = (self._gray, pixels[selected].astype(self.np.float32).reshape(-1, 1, 2),
                                 ids[selected].copy())
                if self.last_diagnostic["method"] == "descriptor_pnp":
                    self._descriptor_at = frame.received_at
            else:
                self._anchors, self._descriptor_at = None, None
            self.last_diagnostic["state"] = pose.state
            return pose
        except Exception:
            self._anchors, self._descriptor_at = None, None
            self.confirmations, self.previous = 0, None
            self.recent_confirmed_sources.clear()
            raise
        finally:
            self._frame, self._solution, self._gray = None, None, None
