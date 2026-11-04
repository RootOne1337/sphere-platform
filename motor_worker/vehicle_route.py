"""Finite, camera-relative vehicle pursuit; plans only, never native input.

The recorded trace is not a metric road or a collision map. A caller must own
calibrated pedal/steering/camera contacts, enforce fresh plans and actual ACKs,
and confirm the camera-to-vehicle assumption. Speed is a fresh HUD observation,
not a consequence inferred from throttle or replayed recording timestamps.
"""

from __future__ import annotations

import math
from collections import deque

from motor_worker.route_confirmation import (
    CONFIRMATION_POLICY,
    SOFT_VISUAL_MISSES,
    ConfirmationEvidence,
)
from motor_worker.route_localization import (
    MIN_TRACE_STEP_UNITS,
    RoutePose,
    SparseRoute,
    trace_step_scale,
)
from motor_worker.route_reference_lk import ReferenceLKRoute


class VehicleRouteFollower:
    MAX_STEERING = .35
    # Recovery is a stationary, bounded wait. No stale pose gains movement
    # permission while the browser has already released both native contacts.
    MAX_RELOCALIZE_SECONDS = 15.

    def __init__(self, route, speed_reference, *, clock, reference_rotations,
                 start_mode='beginning', max_seconds=120, max_speed_kmh=15):
        import numpy as np

        if type(route) not in (SparseRoute, ReferenceLKRoute) or not callable(getattr(speed_reference, 'sample', None)):
            raise ValueError('vehicle_route_or_speed_reference_required')
        if start_mode not in {'beginning', 'recognized_route'}:
            raise ValueError('vehicle_start_mode')
        if type(max_seconds) is not int or not 60 <= max_seconds <= 1800:
            raise ValueError('vehicle_duration_invalid')
        if type(max_speed_kmh) is not int or not 1 <= max_speed_kmh <= 50:
            raise ValueError('vehicle_speed_cap_invalid')
        views = np.asarray(reference_rotations, float)
        if (views.shape != (len(route.camera_trace), 3, 3) or not np.isfinite(views).all()
                or not np.allclose(views @ views.transpose(0, 2, 1), np.eye(3), atol=1e-5)
                or not np.allclose(np.linalg.det(views), 1, atol=1e-5)):
            raise ValueError('vehicle_reference_rotations_required')
        self.route, self.speed_reference, self.clock, self.np = route, speed_reference, clock, np
        self.views, self.start_mode, self.max_seconds = views, start_mode, max_seconds
        self.max_speed_kmh = max_speed_kmh
        self.trace = np.asarray(route.camera_trace, float)
        self.steps = np.linalg.norm(np.diff(self.trace, axis=0), axis=1)
        self.step = trace_step_scale(self.steps)
        self.arc = np.r_[0., np.cumsum(self.steps)]
        self.total = float(self.arc[-1])
        self.began = clock()
        self.binding = None
        self.sequence = 0
        self.last_at = None
        self.last_center = None
        self.started = False
        self.confirmations = 0
        self._confirmation = ConfirmationEvidence()
        self.waiting_since = None
        self.high_water = 0.
        self.steering = 0.
        self.pedal = 'coast'
        self.pedal_at = self.began - .4
        self.target_speed = None
        self.observed_speed = None
        self.speed_sample = None
        self.terminal = None
        self.arrival = 0
        self.motion_seconds = 0.
        self.history = deque(maxlen=64)

    def _reply(self, phase, reason, progress=None, *, target_view=None, speed_accepted=False):
        return dict(schema='sphere-vehicle-plan-v1', phase=phase, reason=reason,
                    pedal=self.pedal, steering=float(self.steering),
                    progressFraction=None if progress is None else float(progress / self.total),
                    maxSteering=self.MAX_STEERING, maxSeconds=self.max_seconds,
                    maxSpeedKmh=self.max_speed_kmh,
                    maxDecisionAgeMs=450, maxAnswerHoldMs=350,
                    groundRoute=False, executionQualified=False, cameraBodyAssumption=True,
                    targetSpeedKmh=self.target_speed, observedSpeedKmh=self.observed_speed,
                    speedAccepted=speed_accepted,
                    confirmationPolicy=CONFIRMATION_POLICY,
                    confirmationValidCount=len(self._confirmation.votes),
                    confirmationObservationCount=len(self._confirmation.slots),
                    targetViewCamera=None if target_view is None else list(map(float, target_view)))

    def _neutral(self, reason, *, terminal=False, arrived=False):
        self.steering, self.pedal = 0., 'coast'
        if terminal:
            self._confirmation.clear()
            self.terminal = (reason, 'arrived' if arrived else 'stopped')
        phase = self.terminal[1] if self.terminal else 'waiting'
        reason = self.terminal[0] if self.terminal else reason
        return self._reply(phase, reason, self.high_water if self.started else None)

    def _wait(self, reason, now, *, preserve_confirmation=False):
        if not preserve_confirmation:
            self._confirmation.clear()
            self.confirmations = 0
        self.speed_sample = None
        if self.started:
            if self.waiting_since is None:
                self.waiting_since = now
            elif now - self.waiting_since >= self.MAX_RELOCALIZE_SECONDS:
                return self._neutral('vehicle_relocalization_timeout', terminal=True)
        return self._neutral(reason)

    def _speed(self, pose, speed, now):
        if type(speed) is not dict:
            return None
        value, confidence = speed.get('speed_kmh'), speed.get('confidence')
        if (speed.get('status') != 'accepted' or type(value) not in (int, float)
                or not math.isfinite(value) or not 0 <= value <= 350
                or type(confidence) not in (int, float) or not math.isfinite(confidence)
                or not 80 <= confidence <= 100
                or speed.get('epoch') != pose.capture_epoch
                or speed.get('sequence') != pose.receiver_sequence
                or speed.get('received_at') != pose.received_at
                or speed.get('source_rgb_sha256') != pose.source_rgb_sha256
                or not 0 <= now - speed['received_at'] <= .25):
            return None
        return float(value)

    def _at_arc(self, value):
        np = self.np
        moving = np.flatnonzero(self.steps >= MIN_TRACE_STEP_UNITS)
        at = min(len(moving) - 1, int(np.searchsorted(self.arc[moving + 1], value, side='left')))
        index = int(moving[at])
        fraction = float(np.clip((value - self.arc[index]) / self.steps[index], 0., 1.))
        return index, fraction

    def observe(self, pose, speed, *, motion_active=None):
        np, now = self.np, self.clock()
        if self.terminal:
            return self._neutral(self.terminal[0])
        if not math.isfinite(now) or now < self.began or now - self.began >= self.max_seconds:
            return self._neutral('vehicle_time_limit', terminal=True)
        if motion_active is not None and type(motion_active) is not bool:
            return self._neutral('vehicle_motion_feedback_invalid', terminal=True)
        if type(pose) is not RoutePose:
            return self._neutral('vehicle_pose_invalid', terminal=True)
        if (type(pose.receiver_sequence) is not int or not 1 <= pose.receiver_sequence <= 1000000
                or any(type(v) not in (int, float) or not math.isfinite(v)
                       for v in (pose.received_at, pose.completed_at))
                or type(pose.inliers) is not int or not 0 <= pose.inliers <= 4096
                or pose.geometry != (960, 540)
                or type(pose.source_rgb_sha256) is not str or len(pose.source_rgb_sha256) != 64
                or any(c not in '0123456789abcdef' for c in pose.source_rgb_sha256)):
            return self._neutral('vehicle_pose_invalid', terminal=True)
        binding = (pose.route_id, pose.world_revision, pose.capture_epoch)
        if self.binding is None:
            self.binding = binding
        if (pose.route_id != self.route.id or pose.world_revision != self.route.world_revision
                or binding != self.binding or pose.receiver_sequence <= self.sequence
                or not pose.received_at <= pose.completed_at <= now
                or not 0 <= now - pose.received_at <= self.MAX_RELOCALIZE_SECONDS
                or self.last_at is not None and pose.received_at <= self.last_at):
            return self._neutral('vehicle_pose_binding_or_age', terminal=True)
        dt = .1 if self.last_at is None else pose.received_at - self.last_at
        self.last_at, self.sequence = pose.received_at, pose.receiver_sequence
        if now - pose.received_at > .25 or dt > .5:
            return self._wait('vehicle_fresh_pose_required', now)
        if pose.state not in {'localized', 'confirming'} or pose.inliers < 24:
            soft = pose.state == 'unknown' and pose.reason in SOFT_VISUAL_MISSES
            if soft:
                self._confirmation.prepare(binding, pose.receiver_sequence, pose.received_at)
                self._confirmation.append(pose.source_rgb_sha256, valid=False)
                self.confirmations = len(self._confirmation.votes)
            return self._wait('vehicle_confirming_position', now, preserve_confirmation=soft)
        try:
            center = np.asarray(pose.center, float)
            rotation = np.asarray(pose.rotation, float).reshape(3, 3)
            progress, cross = float(pose.progress_units), float(pose.cross_track_units)
            if (center.shape != (3,) or not np.isfinite(center).all()
                    or not np.isfinite(rotation).all()
                    or not np.allclose(rotation @ rotation.T, np.eye(3), atol=.01)
                    or abs(np.linalg.det(rotation) - 1) > .01
                    or not 0 <= progress <= self.total or not 0 <= cross <= self.step * 3):
                raise ValueError('invalid_pose')
        except (ValueError, TypeError):
            return self._neutral('vehicle_pose_or_corridor_unqualified', terminal=True)
        if self.started:
            discontinuity = None
            if progress < self.high_water - self.step * 2 or progress > self.high_water + self.step * 6:
                discontinuity = 'vehicle_progress_discontinuity'
            elif self.last_center is not None and np.linalg.norm(center - self.last_center) > self.step * 6:
                discontinuity = 'vehicle_pose_discontinuity'
            if discontinuity:
                if pose.state == 'confirming':
                    # Reject the tentative jump without replacing the last
                    # verified position or allowing it to vote for movement.
                    return self._wait('vehicle_confirming_position', now)
                return self._neutral(discontinuity, terminal=True)
        if not self.started and self.start_mode == 'beginning':
            first_arc = min(self.total * .15, float(np.interp(
                self.route.source_seconds[0] + 5., self.route.source_seconds, self.arc)))
            if progress > first_arc or np.linalg.norm(center - self.trace[0]) > first_arc + self.step * 3:
                if pose.state == 'confirming':
                    return self._wait('vehicle_confirming_position', now)
                return self._neutral('vehicle_start_outside_recorded_beginning', terminal=True)
        if not self.started:
            # Only a still-eligible startup vote may constrain the next centre.
            # A provisional pose must never permanently stop an idle run.
            votes = self._confirmation.votes
            if votes and pose.received_at - votes[-1][0] <= 1.0:
                if np.linalg.norm(center - votes[-1][3]) > self.step * 6:
                    return self._wait('vehicle_confirming_position', now)
        self.observed_speed = self._speed(pose, speed, now)
        acceleration = 0.
        if self.observed_speed is not None:
            if self.speed_sample is not None:
                old_at, old_speed = self.speed_sample
                interval = pose.received_at - old_at
                if .05 <= interval <= .5:
                    acceleration = float(np.clip((self.observed_speed - old_speed) / interval, -40., 40.))
            self.speed_sample = (pose.received_at, self.observed_speed)
        ticks = round(float(np.interp(progress, self.arc, self.route.source_seconds)) * 90000)
        try:
            target = self.speed_reference.sample(ticks)
        except (ValueError, TypeError, RuntimeError):
            return self._neutral('vehicle_reference_speed_invalid', terminal=True)
        if (type(target) not in (int, float) or not math.isfinite(target) or not 0 <= target <= 350
                or self.observed_speed is None):
            self.target_speed = (min(float(self.max_speed_kmh), float(target)) if type(target) in (int, float)
                                 and math.isfinite(target) and 0 <= target <= 350 else None)
            return self._wait('vehicle_speed_unconfirmed', now)
        # Preview slower source speeds before a corner, indexed by localized
        # progress. Never advance the recorded clock because live time passed.
        preview = getattr(self.speed_reference, 'preview', None)
        try:
            future_speed = preview(ticks, horizon_ticks=45000) if callable(preview) else None
        except (ValueError, TypeError, RuntimeError):
            return self._neutral('vehicle_reference_speed_invalid', terminal=True)
        self.target_speed = float(min(target, future_speed)) if (
            type(future_speed) in (int, float) and math.isfinite(future_speed)
            and 0 <= future_speed <= 350) else float(target)
        # A speed preview may finish braking inside the final reference
        # interval. Require that interval AND endpoint proximity AND low speed;
        # otherwise a zero target can deadlock just outside an arbitrary
        # fraction of the final keyframe spacing.
        near_end = (progress >= self.total - self.step
                    and np.linalg.norm(center - self.trace[-1]) <= self.step)
        # A recording can start with several stationary frames. Spatial
        # lookahead, not elapsed live time, supplies its measured departure
        # speed. No known positive nearby sample means remain stopped.
        if self.target_speed <= 1. and not near_end:
            departure_arc = min(self.total, progress + self.step * 1.5)
            departure_at = float(np.interp(departure_arc, self.arc, self.route.source_seconds))
            try:
                departure = self.speed_reference.sample(round(departure_at * 90000))
            except (ValueError, TypeError, RuntimeError):
                return self._neutral('vehicle_reference_speed_invalid', terminal=True)
            if (departure_at - ticks / 90000. <= 5.
                    and type(departure) in (int, float) and math.isfinite(departure)
                    and 1 < departure <= 350):
                self.target_speed = min(10., float(departure))
        self.target_speed = min(float(self.max_speed_kmh), self.target_speed)
        if self.waiting_since is not None and now - self.waiting_since >= self.MAX_RELOCALIZE_SECONDS:
            return self._neutral('vehicle_relocalization_timeout', terminal=True)
        self._confirmation.prepare(binding, pose.receiver_sequence, pose.received_at)
        current_vote = self._confirmation.append(pose.source_rgb_sha256, valid=True, payload=center)
        self.confirmations = len(self._confirmation.votes)
        if not current_vote:
            return self._wait('vehicle_confirming_position', now, preserve_confirmation=True)
        # A geometrically verified confirming pose with its current HUD can
        # provide evidence, but only a CURRENT localized pose authorizes input.
        if pose.state != 'localized':
            return self._neutral('vehicle_confirming_current_position')
        if not self.started or self.waiting_since is not None:
            if self.confirmations < 3:
                return self._neutral('vehicle_confirming_current_position')
            self.waiting_since = None
            self.started = True
        self.last_center = center.copy()
        self.high_water = max(self.high_water, progress)
        if near_end and self.observed_speed <= .5:
            self.arrival += 1
            if self.arrival >= 3:
                return self._neutral('vehicle_camera_trace_end_confirmed', terminal=True, arrived=True)
            return self._neutral('vehicle_confirming_end')
        self.arrival = 0
        if near_end:
            self.target_speed = 0.
        look_seconds = .25 + min(self.observed_speed / 350., .3)
        source_at = ticks / 90000.
        look_arc = min(self.total, max(progress + self.step, float(np.interp(
            source_at + look_seconds, self.route.source_seconds, self.arc))))
        index, fraction = self._at_arc(look_arc)
        target_position = self.trace[index] * (1 - fraction) + self.trace[index + 1] * fraction
        camera_delta = rotation @ (target_position - center)
        if np.linalg.norm(camera_delta[[0, 2]]) < self.step * .01 and not near_end:
            return self._neutral('vehicle_target_direction_unknown', terminal=True)
        yaw = float(math.atan2(camera_delta[0], camera_delta[2])) if not near_end else 0.
        # A large error calls for operator review, not a sharp blind U-turn.
        if abs(yaw) > math.pi / 3 and not near_end:
            return self._wait('vehicle_heading_outside_pursuit_cone', now)
        desired = float(np.clip(yaw * .6, -self.MAX_STEERING, self.MAX_STEERING))
        self.steering += float(np.clip(desired - self.steering, -1.2 * dt, 1.2 * dt))
        if abs(yaw) > .25:
            self.target_speed = min(self.target_speed, max(5., self.max_speed_kmh * .25 / abs(yaw)))
        view_index, view_fraction = self._at_arc(look_arc)
        forward = ((1 - view_fraction) * self.views[view_index, 2]
                   + view_fraction * self.views[view_index + 1, 2])
        if np.linalg.norm(forward) < .1:
            return self._neutral('vehicle_target_view_unknown', terminal=True)
        # With the explicit attached-camera assumption, steering changes both
        # vehicle course and its view. Independent free-camera drags would
        # invalidate the camera/course relation and are never emitted here.
        # A fresh HUD trend anticipates the measured processing/hold latency.
        # It predicts speed only, never position or a pose through missing RGB.
        # Without two nearby same-source readings the trend is exactly zero.
        predicted_speed = max(0., self.observed_speed + acceleration * min(.35, now - pose.received_at + .15))
        error = self.target_speed - predicted_speed
        observed_error = self.target_speed - self.observed_speed
        desired_pedal = self.pedal
        if self.target_speed <= .25:
            desired_pedal = 'brake' if self.observed_speed > .5 else 'coast'
        elif self.pedal == 'brake':
            desired_pedal = 'coast' if error >= -min(1., self.target_speed * .2) else 'brake'
        elif observed_error < -min(3., max(.5, self.target_speed * .25)):
            desired_pedal = 'brake'
        elif self.pedal == 'throttle':
            desired_pedal = 'coast' if error <= 0. else 'throttle'
        elif error >= min(1.5, max(.25, self.target_speed * .1)):
            desired_pedal = 'throttle'
        else:
            desired_pedal = 'coast'
        # Immediate deceleration/neutral is allowed; ordinary gas/coast noise
        # cannot create alternating DOWNs at the localization frame rate.
        if (desired_pedal != self.pedal and
                (desired_pedal in {'brake', 'coast'} or now - self.pedal_at >= .4)):
            self.pedal, self.pedal_at = desired_pedal, now
        if motion_active and dt <= .5:
            self.motion_seconds += min(dt, .25)
        if not self.history or self.motion_seconds - self.history[-1][0] >= .075:
            self.history.append((self.motion_seconds, self.high_water))
        while len(self.history) > 1 and self.history[1][0] <= self.motion_seconds - 3:
            self.history.popleft()
        if (self.motion_seconds - self.history[0][0] >= 3.
                and self.high_water - self.history[0][1] < self.step * .35
                and self.observed_speed >= 3.):
            return self._neutral('vehicle_motion_without_route_progress', terminal=True)
        return self._reply('following', 'vehicle_continuous_pursuit', progress,
                           target_view=None, speed_accepted=True)
