"""Bounded background verification experiment; never predicts a current pose.

The foreground still solves absolute map PnP on every current image. One SIFT
query may run in parallel, but must agree with the foreground on that SAME
query image. Its old pose is never returned as a current observation. Failure,
ambiguity, deadline, gap or scene loss revokes tracking and reconfirmation is
descriptor based. This class is not selected by the live API by default.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from motor_worker.route_localization import RouteLocalizer, extract_features
from motor_worker.route_tracking import AnchoredRouteLocalizer


class BackgroundVerifiedRouteLocalizer(AnchoredRouteLocalizer):
    START_DESCRIPTOR_AGE = .5

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        verifier_kwargs = {key: value for key, value in kwargs.items() if key != 'recovery_candidate_limit'}
        self._verifier = RouteLocalizer(*args, **verifier_kwargs)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='route-verify')
        self._pending = None
        self._closed = False

    def close(self, *, wait=False):
        """Stop publishing immediately; retain at most one in-flight query."""
        self._closed = self.retired = True
        self._anchors = self._descriptor_at = None
        self._discard_pending()
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def _discard_pending(self):
        if self._pending is not None:
            self._pending['discard'] = True
            self._pending['future'].cancel()
            if self._pending['future'].done():
                self._pending = None

    def _verify_query(self, frame, previous, confirmations):
        verifier = self._verifier
        verifier.previous = previous
        verifier.confirmations = confirmations
        verifier.last_received = frame.received_at
        solved = verifier._solve(*extract_features(frame, verifier.mask))
        return solved, self.clock()

    def _submit(self, solution):
        if self._pending is not None or self._closed:
            return
        # Arrays are replaced, not modified by the next foreground observation.
        frame, gray = self._frame, self._gray
        future = self._executor.submit(self._verify_query, frame, self.previous, self.confirmations)
        self._pending = dict(frame=frame, gray=gray, solution=solution, future=future, discard=False)
        self.last_diagnostic['backgroundSubmitted'] = True

    def _agrees_on_query(self, global_solution, flow_solution):
        """Project tracked *map IDs* into the exact query, not just pose angles."""
        np = self.np
        center, rotation = global_solution[:2]
        ids, pixels = flow_solution[4:]
        camera = (self.xyz[ids]-center)@rotation.T
        positive = np.isfinite(camera).all(axis=1) & (camera[:, 2] > 1e-5)
        if len(ids) < 24 or positive.mean() < .75:
            return False
        projected = camera[positive]@self.K.T
        projected = projected[:, :2]/projected[:, 2, None]
        errors = np.linalg.norm(projected-pixels[positive], axis=1)
        return bool(np.isfinite(errors).all() and np.median(errors) <= 3 and (errors <= 6).mean() >= .75)

    def _consume(self):
        pending = self._pending
        if pending is None:
            return True
        future = pending['future']
        if pending['discard']:
            if future.done():
                self._pending = None
                return True
            self.last_diagnostic['method'] = 'background_global_draining'
            return False
        if not future.done():
            return True  # Old anchors still have their original 0.8 s deadline.
        self._pending = None
        try:
            solved, completed = future.result()
        except Exception:
            self.last_diagnostic['method'] = 'background_global_failed'
            return False
        query_time = pending['frame'].received_at
        age = self.clock()-query_time
        self.last_diagnostic['backgroundQueryAgeSeconds'] = age
        if (solved is None or not 0 <= completed-query_time <= .25 or not 0 <= age <= .25
                or not self._agrees_on_query(solved, pending['solution'])):
            self.last_diagnostic['method'] = 'background_global_rejected'
            return False
        ids, pixels = solved[4:]
        selected = self.np.linspace(0, len(ids)-1, min(len(ids), self.MAX_ANCHORS), dtype=int)
        self._anchors = (pending['gray'], pixels[selected].astype(self.np.float32).reshape(-1, 1, 2),
                         ids[selected].copy())
        # Timestamp belongs to the query, never the later completion/consumption.
        self._descriptor_at = query_time
        self.last_diagnostic['backgroundAccepted'] = True
        return True

    def _solve(self, *_unused):
        if not self._consume():
            self._solution = None
            return None
        age = None if self._descriptor_at is None else self._frame.received_at-self._descriptor_at
        may_track = (self._anchors is not None and self.confirmations >= 3
                     and age is not None and 0 < age < self.MAX_DESCRIPTOR_AGE)
        if self._pending is not None and not may_track:
            self.last_diagnostic['method'] = 'background_global_deadline'
            self._solution = None
            return None
        solved = self._flow() if may_track else None
        if solved is None:
            if self._pending is not None:
                self.last_diagnostic['method'] = 'background_flow_lost'
            else:
                self.last_diagnostic['method'] = 'descriptor_pnp'
                solved = self._solve_descriptors()
        else:
            self.last_diagnostic['method'] = 'map_anchored_flow'
            if age >= self.START_DESCRIPTOR_AGE:
                self._submit(solved)
        self.last_diagnostic.update(descriptorAgeSeconds=age, mandatoryGlobalCheck=not may_track)
        self._solution = solved
        return solved

    def observe(self, frame, **kwargs):
        try:
            pose = super().observe(frame, **kwargs)
        except Exception:
            self._discard_pending()
            raise
        if pose.state == 'unknown':
            self._discard_pending()
        return pose
