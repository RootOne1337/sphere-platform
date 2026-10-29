"""Finite experimental pedestrian pursuit of an observed camera trace.

No Android authority, collision map, metre scale, recorded-key replay or model.
The caller must separately own a fresh, calibrated stick and enforce native ACKs.
This is an operator-supervised test of a camera-relative control assumption.
"""
from __future__ import annotations

from collections import deque
import math

from motor_worker.route_localization import RoutePose, SparseRoute, MIN_TRACE_STEP_UNITS, trace_step_scale


class WalkRouteFollower:
    MAX_STICK = .35
    MAX_SECONDS = 60
    MAX_RELOCALIZE_SECONDS = 2.
    MAX_RELOCALIZATIONS = 3

    def __init__(self, route: SparseRoute, *, clock):
        import numpy as np

        if type(route) is not SparseRoute:
            raise ValueError('walk_route_required')
        self.route, self.clock, self.np = route, clock, np
        self.trace = np.asarray(route.camera_trace, dtype=float)
        self.steps = np.linalg.norm(np.diff(self.trace, axis=0), axis=1)
        self.step = trace_step_scale(self.steps)
        self.arc = np.r_[0., np.cumsum(self.steps)]
        self.total = float(self.arc[-1])
        self.began = clock()
        self.sequence, self.last_at = 0, None
        self.started, self.terminal = False, None
        self.high_water, self.arrival = 0., 0
        self.vector = np.zeros(2)
        self.history = deque(maxlen=64)
        self.binding = None
        self.last_good = None
        self.relocalizing = None
        self.relocalizations = 0

    def _reply(self, phase, reason, progress=None, **extra):
        return dict(schema='sphere-walk-plan-v1', phase=phase, reason=reason,
                    stick=[float(v) for v in self.vector],
                    progressFraction=None if progress is None else float(progress/self.total),
                    maxStick=self.MAX_STICK, maxSeconds=self.MAX_SECONDS,
                    groundRoute=False, executionQualified=False,
                    cameraBodyAssumption=True, **extra)

    def _stop(self, reason, phase='stopped', progress=None):
        self.terminal = reason
        self.vector[:] = 0
        return self._reply(phase, reason, progress)

    def observe(self, pose: RoutePose):
        np, now = self.np, self.clock()
        if self.terminal:
            return self._stop(self.terminal)
        if not math.isfinite(now) or now < self.began or now-self.began >= self.MAX_SECONDS:
            return self._stop('walk_time_limit')
        if type(pose) is not RoutePose:
            return self._stop('walk_pose_invalid')
        binding = (pose.route_id, pose.world_revision, pose.capture_epoch)
        if self.binding is None:
            self.binding = binding
        if (pose.route_id != self.route.id or pose.world_revision != self.route.world_revision
                or binding != self.binding or pose.receiver_sequence <= self.sequence
                or not 0 <= now-pose.received_at <= .25
                or not pose.received_at <= pose.completed_at <= now
                or self.last_at is not None and not 0 < pose.received_at-self.last_at <= .5):
            return self._stop('walk_pose_binding_or_age')
        dt = .1 if self.last_at is None else pose.received_at-self.last_at
        self.sequence, self.last_at = pose.receiver_sequence, pose.received_at
        if pose.state != 'localized':
            self.vector[:] = 0
            if self.started:
                self.arrival=0
                if self.relocalizing is None:
                    self.relocalizations+=1
                    if self.relocalizations>self.MAX_RELOCALIZATIONS:
                        return self._stop('walk_relocalization_budget')
                    self.relocalizing=dict(began=pose.received_at,confirmations=0)
                self.relocalizing['confirmations']=0
                if pose.received_at-self.relocalizing['began']>=self.MAX_RELOCALIZE_SECONDS:
                    return self._stop('walk_relocalization_timeout')
                return self._reply('waiting','walk_relocalizing_neutral',self.high_water)
            return self._reply('waiting', 'walk_confirming_start')
        try:
            center, rotation = np.asarray(pose.center, float), np.asarray(pose.rotation, float).reshape(3, 3)
            progress, cross = float(pose.progress_units), float(pose.cross_track_units)
            if (center.shape != (3,) or not np.isfinite(center).all() or not np.isfinite(rotation).all()
                    or not np.allclose(rotation @ rotation.T, np.eye(3), atol=.01)
                    or abs(np.linalg.det(rotation)-1) > .01
                    or not 0 <= progress <= self.total or not 0 <= cross <= self.step*3
                    or pose.inliers < 24):
                return self._stop('walk_pose_or_corridor_unqualified')
        except (ValueError, TypeError):
            return self._stop('walk_pose_invalid')
        if self.relocalizing is not None:
            # No movement or pose extrapolation while the current image is
            # unqualified. Resume only after three new localized observations
            # in a small neighborhood of the last known position and heading.
            self.vector[:]=0
            if pose.received_at-self.relocalizing['began']>=self.MAX_RELOCALIZE_SECONDS:
                return self._stop('walk_relocalization_timeout')
            old_center,old_rotation=self.last_good
            turn=float(np.arccos(np.clip((np.trace(rotation@old_rotation.T)-1)/2,-1,1)))
            if (np.linalg.norm(center-old_center)>self.step*4 or turn>.7
                    or progress<self.high_water-self.step*2 or progress>self.high_water+self.step*4):
                return self._stop('walk_relocalization_drift')
            self.relocalizing['confirmations']+=1
            if self.relocalizing['confirmations']<3:
                return self._reply('waiting','walk_relocalizing_neutral',progress)
            self.relocalizing=None;self.history.clear()
        if not self.started:
            if (progress > min(self.total*.15, self.step*2)
                    or float(np.linalg.norm(center-self.trace[0])) > self.step*3):
                return self._stop('walk_start_outside_recorded_beginning')
            self.started = True
            self.high_water = progress
        elif progress < self.high_water-self.step*2:
            return self._stop('walk_progress_reversed')
        elif progress > self.high_water+self.step*4:
            return self._stop('walk_progress_jump')
        self.high_water = max(self.high_water, progress)
        self.last_good=(center.copy(),rotation.copy())
        self.history.append((pose.received_at, self.high_water))
        while len(self.history) > 1 and self.history[1][0] <= pose.received_at-3:
            self.history.popleft()
        if (pose.received_at-self.history[0][0] >= 3
                and self.high_water-self.history[0][1] < self.step*.35):
            return self._stop('walk_no_route_progress')
        # A closed loop has an endpoint near the start. Distance alone must
        # never count as arrival; ordered progress must reach the final segment.
        near_end = (progress >= self.total-self.step*.7
                    and np.linalg.norm(center-self.trace[-1]) <= self.step)
        self.arrival = self.arrival+1 if near_end else 0
        if self.arrival:
            self.vector[:] = 0
            if self.arrival >= 3:
                return self._stop('walk_camera_trace_end_confirmed', 'arrived', progress)
            return self._reply('waiting', 'walk_confirming_end', progress)
        # Short arc-length lookahead follows the ordered trace, never a direct
        # chord to the destination or the timing of recorded input.
        target_arc = min(self.total, progress+self.step*1.5)
        moving=np.flatnonzero(self.steps>=MIN_TRACE_STEP_UNITS)
        at=min(len(moving)-1,int(np.searchsorted(self.arc[moving+1],target_arc,side='left')))
        index=int(moving[at])
        fraction = float(np.clip((target_arc-self.arc[index])/self.steps[index],0.,1.))
        target = self.trace[index]*(1-fraction)+self.trace[index+1]*fraction
        camera_delta = rotation @ (target-center)
        direction = camera_delta[[0, 2]]
        length = float(np.linalg.norm(direction))
        if not math.isfinite(length) or length < self.step*.05:
            return self._stop('walk_target_direction_unknown')
        # +x is stick-right, +y is screen-down: camera-forward is stick-up.
        direction = direction/length * np.array([1., -1.])
        turn_scale = max(.55, abs(float(direction[1])))
        approach = min(1., max(.55, (self.total-progress)/(self.step*2)))
        desired = direction*self.MAX_STICK*turn_scale*approach
        delta = desired-self.vector
        change = float(np.linalg.norm(delta))
        maximum = min(.2, dt*1.2)
        if change > maximum:
            delta *= maximum/change
        self.vector += delta
        return self._reply('following', 'walk_camera_relative_pursuit', progress,
                           targetCamera=[float(v) for v in camera_delta])
