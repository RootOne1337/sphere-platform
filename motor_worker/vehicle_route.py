"""Finite, camera-relative vehicle pursuit; plans only, never native input.

The recorded trace is not a metric road or a collision map. A caller must own
calibrated pedal/steering/camera contacts, enforce fresh plans and actual ACKs,
and confirm the camera-to-vehicle assumption. Live tempo is measured from
either fresh HUD pixels or independent camera positions in the route scale.
"""

from __future__ import annotations

import math
from collections import deque

from motor_worker.route_confirmation import (
    CONFIRMATION_POLICY,
    SOFT_VISUAL_MISSES,
    ConfirmationEvidence,
    source_arc_motion_envelope,
)
from motor_worker.route_localization import (
    MIN_TRACE_STEP_UNITS,
    RoutePose,
    SparseRoute,
    trace_step_scale,
)
from motor_worker.route_reference_lk import ReferenceLKRoute


class ConservativeTempoReference:
    """Explicit low-speed policy for a trace without recorded HUD readings.

    Trace distance divided by source time is only a relative tempo. Its units
    have no conversion to km/h: the 2--5 km/h values below are policy limits,
    which must be controlled against a fresh live HUD reading.
    """

    MAX_SPEED_KMH = 5.

    def __init__(self, route):
        import numpy as np

        if type(route) not in (SparseRoute, ReferenceLKRoute):
            raise ValueError('vehicle_route_required')
        trace = np.asarray(route.camera_trace, dtype=float)
        times = np.asarray(route.source_seconds, dtype=float)
        if (trace.ndim != 2 or trace.shape != (len(times), 3) or len(times) < 2
                or not np.isfinite(trace).all() or not np.isfinite(times).all()
                or np.any(np.diff(times) <= 0)):
            raise ValueError('vehicle_tempo_reference_invalid')
        rates = np.linalg.norm(np.diff(trace, axis=0), axis=1) / np.diff(times)
        positive = rates[rates > 1e-12]
        if not len(positive) or not np.isfinite(rates).all():
            raise ValueError('vehicle_tempo_reference_invalid')
        self.source_rate = float(np.median(positive))
        self.route = route
        self.times = tuple(map(float, times))
        self.targets = tuple(float(2. + 3. * min(1., rate / self.source_rate)) if rate > 1e-12 else 0.
                             for rate in rates) + (0.,)

    def sample(self, ticks):
        import bisect

        if type(ticks) not in (int, float) or not math.isfinite(ticks):
            raise ValueError('vehicle_tempo_time_invalid')
        index = max(0, min(len(self.targets) - 1, bisect.bisect_right(self.times, ticks / 90000.) - 1))
        return self.targets[index]

    def preview(self, ticks, horizon_ticks):
        if (type(horizon_ticks) not in (int, float) or not math.isfinite(horizon_ticks)
                or horizon_ticks < 0):
            raise ValueError('vehicle_tempo_time_invalid')
        end = (ticks + horizon_ticks) / 90000.
        return min([self.sample(ticks), self.sample(ticks + horizon_ticks)] +
                   [self.targets[i] for i, time in enumerate(self.times) if ticks / 90000. < time <= end])


class VehicleRouteFollower:
    # The same pursuit policy uses five internal units for a quarter of the
    # typical recorded rate. Publish ratios only in the visual mode.
    VISUAL_UNITS_PER_SOURCE_RATE = 20.
    THROTTLE_PULSE_MS = 120
    MAX_STEERING = .35
    PURSUIT_CONE = math.pi / 3
    REJOIN_SPEED_KMH = 5.
    # Recovery is a stationary, bounded wait. No stale pose gains movement
    # permission while the browser has already released both native contacts.
    MAX_RELOCALIZE_SECONDS = 15.
    MAX_FORWARD_COAST_SECONDS = 2.
    CONTROL_CORRIDOR_STEPS = 3.
    LOCALIZED_CORRIDOR_STEPS = 5.

    def __init__(self, route, speed_reference, *, clock, reference_rotations,
                 start_mode='beginning', max_seconds=120, max_speed_kmh=15, visual_speed=False):
        import numpy as np

        if type(route) not in (SparseRoute, ReferenceLKRoute) or not callable(getattr(speed_reference, 'sample', None)):
            raise ValueError('vehicle_route_or_speed_reference_required')
        if isinstance(speed_reference, ConservativeTempoReference) and speed_reference.route is not route:
            raise ValueError('vehicle_tempo_route_mismatch')
        if type(visual_speed) is not bool or visual_speed and not isinstance(speed_reference, ConservativeTempoReference):
            raise ValueError('vehicle_visual_tempo_unavailable')
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
        self.visual_speed = visual_speed
        self.pulse_throttle = isinstance(speed_reference, ConservativeTempoReference)
        self.visual_positions = deque(maxlen=8)
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
        self.last_qualified_at = None
        self.recent_progress_rates = deque(maxlen=5)
        self._forward_recovery = False
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
        result = dict(schema='sphere-vehicle-plan-v1', phase=phase, reason=reason,
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
        if self.pulse_throttle:
            result['throttlePulseMs'] = self.THROTTLE_PULSE_MS
        if self.visual_speed:
            result.update(speedAccepted=False, targetSpeedKmh=None, observedSpeedKmh=None,
                          tempoAccepted=speed_accepted, targetTempo=self._tempo_ratio(self.target_speed),
                          observedTempo=self._tempo_ratio(self.observed_speed) if speed_accepted else None)
        return result

    def _tempo_ratio(self, value):
        return None if value is None else float(value / self.VISUAL_UNITS_PER_SOURCE_RATE)

    def _visual_speed(self, pose, center, progress):
        positions = self.visual_positions
        at = pose.received_at
        while positions and at - positions[0][0] > .5:
            positions.popleft()
        if positions and (at - positions[-1][0] > .35
                          or progress < positions[-1][2] - self.step):
            positions.clear()
        if any(row[3] == pose.source_rgb_sha256 for row in positions):
            return None
        positions.append((at, center, progress, pose.source_rgb_sha256))
        # Two distinct poses measure a rate. The independent three-vote
        # geometry gate below still controls whether that rate can move input.
        if len(positions) < 2:
            return None
        rates = [
            (at - previous_at, max(abs(progress - previous_progress),
                                   self.np.linalg.norm(center - previous_center)) / (at - previous_at))
            for previous_at, previous_center, previous_progress, _ in positions
            if .12 <= at - previous_at <= .5
        ]
        if not rates:
            return None
        # Keep recent measured acceleration visible when the longer window
        # still contains several poses from before the gas pulse.
        rate = float(self.np.median([value for _, value in rates]))
        if rates[-1][0] <= .25:
            rate = max(rate, rates[-1][1])
        return min(350., rate * self.VISUAL_UNITS_PER_SOURCE_RATE / self.speed_reference.source_rate)

    def _neutral(self, reason, *, terminal=False, arrived=False):
        self.steering, self.pedal = 0., 'coast'
        if terminal:
            self._confirmation.clear()
            self.terminal = (reason, 'arrived' if arrived else 'stopped')
        phase = self.terminal[1] if self.terminal else 'waiting'
        reason = self.terminal[0] if self.terminal else reason
        return self._reply(phase, reason, self.high_water if self.started else None)

    def _wait(self, reason, now, *, preserve_confirmation=False):
        # Arrival requires a continuous series of qualified endpoint poses.
        self.arrival = 0
        if not preserve_confirmation:
            self._confirmation.clear()
            self.confirmations = 0
            self._forward_recovery = False
        self.speed_sample = None
        if self.started:
            if self.waiting_since is None:
                self.waiting_since = now
            elif now - self.waiting_since >= self.MAX_RELOCALIZE_SECONDS:
                return self._neutral('vehicle_relocalization_timeout', terminal=True)
        return self._neutral(reason)

    @staticmethod
    def _speed_is_current(pose, speed, now):
        return (type(speed) is dict and speed.get('epoch') == pose.capture_epoch
                and speed.get('sequence') == pose.receiver_sequence
                and speed.get('received_at') == pose.received_at
                and speed.get('source_rgb_sha256') == pose.source_rgb_sha256
                and 0 <= now - pose.received_at <= .25)

    @staticmethod
    def _speed(speed):
        if speed is None:
            return None
        value, confidence = speed.get('speed_kmh'), speed.get('confidence')
        if (speed.get('status') != 'accepted' or type(value) not in (int, float)
                or not math.isfinite(value) or not 0 <= value <= 350
                or type(confidence) not in (int, float) or not math.isfinite(confidence)
                or not 80 <= confidence <= 100):
            return None
        return float(value)

    def _at_arc(self, value):
        np = self.np
        moving = np.flatnonzero(self.steps >= MIN_TRACE_STEP_UNITS)
        at = min(len(moving) - 1, int(np.searchsorted(self.arc[moving + 1], value, side='left')))
        index = int(moving[at])
        fraction = float(np.clip((value - self.arc[index]) / self.steps[index], 0., 1.))
        return index, fraction

    def _point_at_arc(self, value):
        index, fraction = self._at_arc(value)
        return self.trace[index] * (1. - fraction) + self.trace[index + 1] * fraction

    def _within_forward_coast(self, center, progress, received_at):
        if (self.waiting_since is None or self.last_qualified_at is None
                or len(self.recent_progress_rates) < 3 or progress <= self.high_water):
            return False
        elapsed = received_at - self.last_qualified_at
        if not 0 < elapsed <= self.MAX_FORWARD_COAST_SECONDS:
            return False
        # Require agreement with both recent measured progress and the local
        # recorded trace. Neither supplies a pose or permission to move.
        epsilon = self.step * 2.
        recorded = source_arc_motion_envelope(self.arc, self.route.source_seconds,
                                               self.high_water, epsilon, elapsed)
        if recorded is None:
            return False
        reach = min(self.step * 16., self.total * .10, recorded['limit'],
                    epsilon + max(self.recent_progress_rates) * elapsed)
        return max(progress - self.high_water, self.np.linalg.norm(center - self.last_center)) <= reach

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
            self.visual_positions.clear()
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
            if type(pose.cross_track_units) not in (int, float):
                raise ValueError('invalid_pose')
            progress, cross = float(pose.progress_units), float(pose.cross_track_units)
            if (center.shape != (3,) or not np.isfinite(center).all()
                    or not np.isfinite(rotation).all()
                    or not np.allclose(rotation @ rotation.T, np.eye(3), atol=.01)
                    or abs(np.linalg.det(rotation) - 1) > .01
                    or not 0 <= progress <= self.total
                    or not 0 <= cross <= self.step * self.LOCALIZED_CORRIDOR_STEPS):
                raise ValueError('invalid_pose')
        except (ValueError, TypeError):
            return self._neutral('vehicle_pose_or_corridor_unqualified', terminal=True)
        if cross > self.step * self.CONTROL_CORRIDOR_STEPS:
            # A measured pose may leave the narrower control corridor. Keep
            # the last qualified position and require fresh in-corridor votes.
            self.recent_progress_rates.clear()
            self.visual_positions.clear()
            self.target_speed = self.observed_speed = None
            return self._wait('vehicle_outside_control_corridor', now)
        within_forward_coast = False
        if self.started:
            discontinuity = None
            if progress < self.high_water - self.step * 2 or progress > self.high_water + self.step * 6:
                discontinuity = 'vehicle_progress_discontinuity'
            elif self.last_center is not None and np.linalg.norm(center - self.last_center) > self.step * 6:
                discontinuity = 'vehicle_pose_discontinuity'
            if discontinuity or self._forward_recovery:
                within_forward_coast = self._within_forward_coast(center, progress, pose.received_at)
            if discontinuity:
                if within_forward_coast:
                    if not self._forward_recovery:
                        # Keep qualified post-loss observations that fit the same
                        # envelope, even if they were inside the ordinary limit.
                        for index, (at, sequence, digest, measured) in enumerate(self._confirmation.slots):
                            if digest is not None and (at < self.waiting_since or not self._within_forward_coast(
                                    measured[0], measured[1], at)):
                                self._confirmation.slots[index] = (at, sequence, None, None)
                        self._forward_recovery = True
                elif pose.state == 'confirming':
                    # Reject the tentative jump without replacing the last
                    # verified position or allowing it to vote for movement.
                    return self._wait('vehicle_confirming_position', now)
                elif self.visual_speed:
                    # A contradictory localized pose is still rejected. Hold
                    # the last verified anchor so a new in-corridor series
                    # can recover during the existing neutral wait.
                    self.visual_positions.clear()
                    return self._wait('vehicle_waiting_for_consistent_position', now)
                else:
                    return self._neutral(discontinuity, terminal=True)
        if not self.started and self.start_mode == 'beginning':
            first_arc = min(self.total * .15, float(np.interp(
                self.route.source_seconds[0] + 5., self.route.source_seconds, self.arc)))
            if progress > first_arc or np.linalg.norm(center - self.trace[0]) > first_arc + self.step * 3:
                if pose.state == 'confirming':
                    return self._wait('vehicle_confirming_position', now)
                return self._neutral('vehicle_start_outside_recorded_beginning', terminal=True)
        if not self.started or self._forward_recovery:
            # Only a still-eligible startup vote may constrain the next centre.
            # A provisional pose must never permanently stop an idle run.
            votes = self._confirmation.votes
            if votes and pose.received_at - votes[-1][0] <= 1.0:
                if np.linalg.norm(center - votes[-1][3][0]) > self.step * 6:
                    return self._wait('vehicle_confirming_position', now)
        current_speed = speed if not self.visual_speed and self._speed_is_current(pose, speed, now) else None
        self.observed_speed = self._visual_speed(pose, center, progress) if self.visual_speed else self._speed(current_speed)
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
        target_valid = type(target) in (int, float) and math.isfinite(target) and 0 <= target <= 350
        if not target_valid or self.observed_speed is None:
            self.target_speed = min(float(self.max_speed_kmh), float(target)) if target_valid else None
            # A current, ambiguous HUD digit grants no input and casts no vote.
            # On an established run, let older verified votes age normally.
            soft_hud_miss = (self.started and pose.state == 'localized' and target_valid
                             and current_speed is not None and current_speed.get('status') == 'glyph_ambiguous'
                             and current_speed.get('speed_kmh') is None)
            if soft_hud_miss:
                self._confirmation.prepare(binding, pose.receiver_sequence, pose.received_at)
                self._confirmation.append(pose.source_rgb_sha256, valid=False)
                self.confirmations = len(self._confirmation.votes)
            return self._wait('vehicle_visual_tempo_unconfirmed' if self.visual_speed else 'vehicle_speed_unconfirmed',
                              now, preserve_confirmation=self.visual_speed or soft_hud_miss)
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
        current_vote = self._confirmation.append(pose.source_rgb_sha256,
            valid=not self._forward_recovery or within_forward_coast, payload=(center, progress))
        self.confirmations = len(self._confirmation.votes)
        if not current_vote:
            return self._wait('vehicle_confirming_position', now, preserve_confirmation=True)
        # A geometrically verified confirming pose with its current HUD can
        # provide evidence, but only a CURRENT localized pose authorizes input.
        if pose.state != 'localized':
            self.arrival = 0
            return self._neutral('vehicle_confirming_current_position')
        if not self.started or self.waiting_since is not None:
            if self.confirmations < 3:
                return self._neutral('vehicle_confirming_current_position')
            self.started = True
        if self.waiting_since is not None:
            self.recent_progress_rates.clear()
        elif self.last_qualified_at is not None:
            interval = pose.received_at - self.last_qualified_at
            if 0 < interval <= .5:
                self.recent_progress_rates.append(max(0., progress - self.high_water) / interval)
        self.last_qualified_at = pose.received_at
        self._forward_recovery = False
        self.last_center = center.copy()
        self.high_water = max(self.high_water, progress)
        if near_end:
            self.target_speed = 0.
        if near_end and self.observed_speed <= .5:
            self.waiting_since = None
            self.arrival += 1
            if self.arrival >= 3:
                return self._neutral('vehicle_camera_trace_end_confirmed', terminal=True, arrived=True)
            return self._neutral('vehicle_confirming_end')
        self.arrival = 0
        look_seconds = .25 + min(self.observed_speed / 350., .3)
        source_at = ticks / 90000.
        look_arc = min(self.total, max(progress + self.step, float(np.interp(
            source_at + look_seconds, self.route.source_seconds, self.arc))))
        camera_delta = rotation @ (self._point_at_arc(look_arc) - center)
        if np.linalg.norm(camera_delta[[0, 2]]) < self.step * .01 and not near_end:
            return self._neutral('vehicle_target_direction_unknown', terminal=True)
        yaw = float(math.atan2(camera_delta[0], camera_delta[2])) if not near_end else 0.
        if not near_end and cross > .5 * self.step and self.observed_speed <= self.REJOIN_SPEED_KMH:
            # A close target can be almost sideways even when the vehicle
            # faces along the route. At low speed, choose a farther point
            # on the same straight portion. Keep the original cone and
            # corridor limits, and avoid cutting across a bend.
            rejoin_arc = min(self.total, progress + min(3. * self.step, self.step + cross))
            if rejoin_arc > look_arc:
                rejoin_point = self._point_at_arc(rejoin_arc)
                chord = rejoin_point - self._point_at_arc(progress)
                if np.linalg.norm(chord) >= .995 * (rejoin_arc - progress):
                    rejoin_delta = rotation @ (rejoin_point - center)
                    rejoin_yaw = math.atan2(rejoin_delta[0], rejoin_delta[2])
                    if rejoin_delta[2] > self.step * .01 and abs(rejoin_yaw) <= self.PURSUIT_CONE:
                        look_arc, yaw = rejoin_arc, rejoin_yaw
                        self.target_speed = min(self.target_speed, self.REJOIN_SPEED_KMH)
        # A large error calls for operator review, not a sharp blind U-turn.
        if abs(yaw) > self.PURSUIT_CONE and not near_end:
            # Steering admission failed after recording a qualified position vote.
            return self._wait('vehicle_heading_outside_pursuit_cone', now, preserve_confirmation=True)
        self.waiting_since = None
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
        if desired_pedal == 'throttle' and self.observed_speed >= self.max_speed_kmh:
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
