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
    MAX_RECOVERY_SECONDS = 6.

    def __init__(self, route: SparseRoute, *, clock, start_mode='beginning', camera_tracking=False,camera_control='continuous_drag_v1',reference_rotations=None):
        import numpy as np

        if type(route) is not SparseRoute:
            raise ValueError('walk_route_required')
        if start_mode not in {'beginning', 'recognized_route'}:
            raise ValueError('walk_start_mode')
        self.start_mode = start_mode
        if type(camera_tracking) is not bool:
            raise ValueError('walk_camera_tracking')
        self.camera_tracking = camera_tracking
        if camera_control not in {'pulse_v1','continuous_drag_v1'}:raise ValueError('walk_camera_control')
        self.camera_control=camera_control
        self.reference_rotations=reference_rotations
        if reference_rotations is not None and (len(reference_rotations)!=len(route.camera_trace)
                or any(np.asarray(r).shape!=(3,3) or not np.isfinite(r).all()
                       or not np.allclose(np.asarray(r)@np.asarray(r).T,np.eye(3),atol=1e-5)
                       or not np.isclose(np.linalg.det(r),1,atol=1e-5) for r in reference_rotations)):
            raise ValueError('walk_reference_rotations_invalid')
        self.alignment = None
        self.route, self.clock, self.np = route, clock, np
        self.trace = np.asarray(route.camera_trace, dtype=float)
        self.steps = np.linalg.norm(np.diff(self.trace, axis=0), axis=1)
        self.step = trace_step_scale(self.steps)
        self.arc = np.r_[0., np.cumsum(self.steps)]
        self.total = float(self.arc[-1])
        # Keyframe spacing is a reconstruction choice, not an operator's start
        # tolerance. Bound acquisition to BOTH the first five recorded seconds
        # and the first 15% of the observed arc, independently of frame density.
        self.start_arc = min(self.total*.15, float(np.interp(
            route.source_seconds[0]+5., route.source_seconds, self.arc)))
        self.began = clock()
        self.sequence, self.last_at = 0, None
        self.started, self.terminal = False, None
        self.terminal_phase, self.terminal_progress = 'stopped', None
        self.high_water, self.arrival = 0., 0
        self.vector = np.zeros(2)
        self.history = deque(maxlen=64)
        self.binding = None
        self.last_good = None
        self.relocalizing = None
        self.relocalizations = 0
        self.recovery_seconds = 0.
        self.acquisition = 0

    def _reply(self, phase, reason, progress=None, **extra):
        return dict(schema='sphere-walk-plan-v1', phase=phase, reason=reason,
                    stick=[float(v) for v in self.vector],
                    progressFraction=None if progress is None else float(progress/self.total),
                    maxStick=self.MAX_STICK, maxSeconds=self.MAX_SECONDS,
                    groundRoute=False, executionQualified=False,
                    cameraBodyAssumption=True, **extra)

    def _stop(self, reason, phase='stopped', progress=None):
        if self.terminal is None:
            self.terminal, self.terminal_phase, self.terminal_progress = reason, phase, progress
        self.vector[:] = 0
        return self._reply(self.terminal_phase, self.terminal, self.terminal_progress)

    def _wait_for_localization(self, at, *, confidence_only=False):
        self.acquisition = 0
        self.vector[:] = 0
        if not self.started:
            return self._reply('waiting', 'walk_confirming_start')
        self.arrival = 0
        if self.relocalizing is None:
            self.relocalizing = dict(began=at, confirmations=0, counted=False)
        if not confidence_only and not self.relocalizing.get('counted', True):
            self.relocalizations += 1
            self.relocalizing['counted'] = True
            if self.relocalizations > self.MAX_RELOCALIZATIONS:
                return self._stop('walk_relocalization_budget')
        self.relocalizing['confirmations'] = 0
        if at-self.relocalizing['began'] >= self.MAX_RELOCALIZE_SECONDS:
            return self._stop('walk_relocalization_timeout')
        if self.recovery_seconds+at-self.relocalizing['began'] >= self.MAX_RECOVERY_SECONDS:
            return self._stop('walk_recovery_time_budget')
        return self._reply('waiting', 'walk_relocalizing_neutral', self.high_water)

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
                or not 0 <= now-pose.received_at <= self.MAX_RELOCALIZE_SECONDS
                or not pose.received_at <= pose.completed_at <= now
                or self.last_at is not None and not 0 < pose.received_at-self.last_at <= 2.):
            return self._stop('walk_pose_binding_or_age')
        dt = .1 if self.last_at is None else pose.received_at-self.last_at
        self.sequence, self.last_at = pose.receiver_sequence, pose.received_at
        if now-pose.received_at > .25:
            # This reply carries no movement permission. A slow descriptor/PnP
            # response is delivery loss, not proof that the map/epoch changed.
            # Consume its sequence, retain the last GOOD geometry, and require
            # three NEW fresh poses through the existing bounded recovery path.
            return self._wait_for_localization(now,confidence_only=True)
        if dt>.5:
            self.vector[:]=0;self.acquisition=0
            if self.started:
                waiting=self._wait_for_localization(pose.received_at,confidence_only=True)
                if waiting['phase']=='stopped':return waiting
        if pose.state != 'localized':
            # A neutral transport gap still requires three fresh geometric
            # confirmations, but is not evidence that the place was lost.
            transport=pose.reason in {'route_observation_gap','route_frame_expired_during_localization'}
            return self._wait_for_localization(pose.received_at,confidence_only=transport)
        try:
            center, rotation = np.asarray(pose.center, float), np.asarray(pose.rotation, float).reshape(3, 3)
            progress, cross = float(pose.progress_units), float(pose.cross_track_units)
            if (center.shape != (3,) or not np.isfinite(center).all() or not np.isfinite(rotation).all()
                    or not np.allclose(rotation @ rotation.T, np.eye(3), atol=.01)
                    or abs(np.linalg.det(rotation)-1) > .01
                    or not 0 <= progress <= self.total or not 0 <= cross <= self.step*3):
                return self._stop('walk_pose_or_corridor_unqualified')
        except (ValueError, TypeError):
            return self._stop('walk_pose_invalid')
        # The localizer can report a valid pose with 20--23 correspondences,
        # below the controller's stricter 24-inlier threshold. One weak image
        # is temporary observation loss, not a permanent route failure. Keep
        # the threshold and require the same three-pose bounded reacquisition.
        if pose.inliers < 24:
            return self._wait_for_localization(pose.received_at, confidence_only=True)
        if self.relocalizing is not None:
            # No movement or pose extrapolation while the current image is
            # unqualified. Resume only after three new localized observations
            # in a small neighborhood of the last known position and heading.
            self.vector[:]=0
            if pose.received_at-self.relocalizing['began']>=self.MAX_RELOCALIZE_SECONDS:
                return self._stop('walk_relocalization_timeout')
            recovery_seconds=self.recovery_seconds+pose.received_at-self.relocalizing['began']
            if recovery_seconds>=self.MAX_RECOVERY_SECONDS:
                return self._stop('walk_recovery_time_budget')
            old_center,old_rotation=self.last_good
            turn=float(np.arccos(np.clip((np.trace(rotation@old_rotation.T)-1)/2,-1,1)))
            if (np.linalg.norm(center-old_center)>self.step*4 or turn>.7
                    or progress<self.high_water-self.step*2 or progress>self.high_water+self.step*4):
                return self._stop('walk_relocalization_drift')
            self.relocalizing['confirmations']+=1
            if self.relocalizing['confirmations']<3:
                return self._reply('waiting','walk_relocalizing_neutral',progress)
            self.recovery_seconds=recovery_seconds
            self.relocalizing=None;self.history.clear()
            # A neutral recovery sent no camera commands. Start a new bounded
            # alignment attempt from the newly verified pose, not an old timer.
            self.alignment=None
        if not self.started:
            if self.start_mode == 'beginning' and (progress > self.start_arc
                    or float(np.linalg.norm(center-self.trace[0])) > self.start_arc+self.step*3):
                return self._stop('walk_start_outside_recorded_beginning')
            if self.start_mode == 'recognized_route':
                # Re-acquire from fresh image geometry, never a remembered key
                # offset or the previous run's progress. The localizer already
                # rejects ambiguous segments; require stable localized poses.
                if self.last_good is not None:
                    old_center, old_rotation = self.last_good
                    turn=float(np.arccos(np.clip((np.trace(rotation@old_rotation.T)-1)/2,-1,1)))
                    if (np.linalg.norm(center-old_center)>self.step*4 or turn>.7
                            or abs(progress-self.high_water)>self.step*4):
                        self.acquisition=0
                self.last_good=(center.copy(),rotation.copy());self.high_water=progress
                self.acquisition+=1;self.vector[:]=0
                if self.acquisition<3:
                    return self._reply('waiting','walk_confirming_current_position',progress)
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
        stalled = (pose.received_at-self.history[0][0] >= 3
                   and self.high_water-self.history[0][1] < self.step*.35)
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
        view={}
        if self.reference_rotations is not None:
            # Interpolate by localized ARC progress, never by live elapsed time.
            i=pose.segment
            t=float(np.clip((progress-self.arc[i])/max(self.steps[i],MIN_TRACE_STEP_UNITS),0.,1.))
            forward=(1-t)*self.reference_rotations[i][2]+t*self.reference_rotations[i+1][2]
            if np.linalg.norm(forward)<.1:return self._stop('walk_target_direction_unknown')
            look=rotation@(forward/np.linalg.norm(forward))
            view=dict(targetViewCamera=[float(v) for v in look],referenceView=True)
        if self.camera_tracking:
            look=np.asarray(view.get('targetViewCamera',camera_delta))
            yaw=abs(float(math.atan2(look[0],look[2])))
            pitch=abs(float(math.atan2(look[1],math.hypot(look[0],look[2])))) if view else 0.
            threshold=((.08 if self.alignment is not None else (.40 if view else .20)) if self.camera_control=='continuous_drag_v1' else .14)
            error=max(yaw,pitch)
            if yaw>threshold or pitch>(.06 if self.alignment is not None else .25):
                self.vector[:] = 0
                if self.alignment is None:
                    self.alignment = dict(began=now, improved=now, best=error)
                elif error < self.alignment['best']-.005:
                    self.alignment.update(improved=now, best=error)
                if now-self.alignment['began'] > 8:
                    return self._stop('walk_camera_alignment_timeout')
                if now-self.alignment['improved'] > 3:
                    return self._stop('walk_camera_not_converging')
                # Deliberately stationary, only while fresh poses confirm that
                # camera alignment is converging. The browser owns all input.
                return self._reply('following', 'walk_camera_alignment_required', progress,
                                   targetCamera=[float(v) for v in camera_delta],**view)
            if self.alignment is not None:
                self.alignment = None
                self.history.clear();self.history.append((pose.received_at, self.high_water))
                stalled = False
        if stalled:
            return self._stop('walk_no_route_progress')
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
                           targetCamera=[float(v) for v in camera_delta],**view)
