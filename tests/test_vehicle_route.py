"""Closed-loop controller and binding tests; synthetic plant is not a game."""

import hashlib
import math
import unittest
from dataclasses import replace
from types import SimpleNamespace

from motor_worker.route_localization import RoutePose
from motor_worker.vehicle_route import ConservativeTempoReference, VehicleRouteFollower
from tests import test_motor_route_localization as fixtures


class VehicleRouteTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.SparseLocalizationTests('test_blank_real_rgb_has_no_pose')
        fixture.setUp()
        self.route = fixture.route
        self.np = fixture.np
        self.now, self.sequence = 10., 0
        self.reference = SimpleNamespace(sample=lambda ticks: 12., preview=lambda ticks, **kw: 12.)
        self.follower = self.make()

    def make(self, **kw):
        return VehicleRouteFollower(self.route, self.reference, clock=lambda: self.now,
            reference_rotations=(self.np.eye(3),) * len(self.route.camera_trace), **kw)

    def observe(self, progress=0., speed=4., *, delay=0., speed_changes=None, **changes):
        self.sequence += 1
        at = self.now - delay
        pose = RoutePose('localized', 'test', self.route.id, self.route.world_revision,
            'e' * 32, self.sequence, at, self.now, hashlib.sha256(str(self.sequence).encode()).hexdigest(), (960, 540),
            center=(0., 0., progress), rotation=(1., 0., 0., 0., 1., 0., 0., 0., 1.),
            segment=min(6, int(progress / 5)), progress_units=progress, cross_track_units=0.,
            inliers=50, median_error_px=.5)
        motion = changes.pop('motion_active', False)
        pose = replace(pose, **changes)
        reading = dict(status='accepted', speed_kmh=speed, confidence=95., epoch=pose.capture_epoch,
                       sequence=pose.receiver_sequence, received_at=pose.received_at,
                       source_rgb_sha256=pose.source_rgb_sha256)
        reading.update(speed_changes or {})
        return self.follower.observe(pose, reading, motion_active=motion)

    def acquire(self, progress=0., speed=4.):
        replies = []
        for _ in range(5):
            replies.append(self.observe(progress, speed))
            self.now += .1
        return replies[-1]

    def test_acquires_three_fresh_poses_and_holds_throttle_across_updates(self):
        replies = []
        for i in range(30):
            replies.append(self.observe(i * .1, speed=4., motion_active=i > 4))
            self.now += .1
        self.assertEqual([r['phase'] for r in replies[:3]], ['waiting', 'waiting', 'following'])
        self.assertTrue(all(r['pedal'] == 'throttle' for r in replies[5:]))
        self.assertTrue(all(r['targetViewCamera'] is None for r in replies))
        self.assertFalse(replies[-1]['executionQualified'])

    def test_current_pnp_and_hud_votes_survive_single_soft_misses_without_blind_input(self):
        results = []
        for index in range(5):
            result = self.observe(speed=0., state='localized' if index == 4 else
                                  'confirming' if index % 2 == 0 else 'unknown',
                                  reason='relative_camera_pose_not_clearance_or_arrival' if index % 2 == 0
                                  else 'route_pose_not_verified', inliers=174 if index % 2 == 0 else 0)
            results.append(result)
            self.now += .1
        self.assertTrue(all(row['pedal'] == 'coast' for row in results[:4]))
        self.assertEqual((results[4]['phase'], results[4]['pedal']), ('following', 'throttle'))
        self.assertEqual(results[4]['confirmationValidCount'], 3)
        missed = self.observe(state='unknown', reason='route_pose_not_verified', inliers=0)
        self.assertEqual((missed['phase'], missed['pedal'], missed['steering']), ('waiting', 'coast', 0.))

    def test_repeated_rgb_cannot_supply_vehicle_votes_and_current_miss_never_drives(self):
        for _ in range(9):
            result = self.observe(speed=0., source_rgb_sha256='a' * 64)
            self.assertEqual(result['pedal'], 'coast')
            self.assertLess(result['confirmationValidCount'], 3)
            self.now += .1

    def test_invalid_current_hud_and_hard_pose_loss_clear_initial_evidence(self):
        for loss in ('bad_hud', 'route_pose_discontinuity', 'route_progress_ambiguous'):
            with self.subTest(loss=loss):
                self.follower = self.make()
                for _ in range(2):
                    self.observe(speed=0., state='confirming')
                    self.now += .1
                if loss == 'bad_hud':
                    result = self.observe(speed=0., speed_changes={'status': 'unknown'})
                else:
                    result = self.observe(state='unknown', reason=loss, inliers=0)
                self.assertEqual((result['pedal'], result['confirmationValidCount']), ('coast', 0))
                self.now += .1
                result = self.observe(speed=0.)
                self.assertEqual((result['pedal'], result['confirmationValidCount']), ('coast', 1))
                self.now += .1

    def test_only_current_localized_pose_can_act_even_after_three_verified_confirming_votes(self):
        for _ in range(3):
            result = self.observe(speed=0., state='confirming')
            self.assertEqual(result['pedal'], 'coast')
            self.now += .1
        self.assertEqual(result['confirmationValidCount'], 3)
        self.assertEqual(self.observe(speed=0.)['pedal'], 'throttle')

    def test_curve_steers_and_holds_gas_without_free_camera_or_pause(self):
        self.acquire()
        rotation = (math.cos(.3), 0., math.sin(.3), 0., 1., 0., -math.sin(.3), 0., math.cos(.3))
        values = []
        for i in range(10):
            values.append(self.observe(1 + i * .1, speed=2., rotation=rotation))
            self.now += .1
        self.assertTrue(all(r['phase'] == 'following' for r in values))
        self.assertTrue(all(r['pedal'] == 'throttle' for r in values))
        self.assertGreater(values[-1]['steering'], .1)
        self.assertTrue(all(r['targetViewCamera'] is None for r in values))
        self.assertTrue(all(abs(b['steering'] - a['steering']) <= .120001
                            for a, b in zip(values, values[1:])))

    def test_same_pose_with_fresh_150_and_350_ms_updates_keeps_drive(self):
        self.acquire()
        for dt in (.15, .35, .15, .35):
            self.now += dt
            self.assertEqual(self.observe(1., speed=4.)['pedal'], 'throttle')

    def test_expired_pose_neutral_then_three_new_fresh_poses_recover(self):
        self.acquire()
        self.now += .4
        self.assertEqual(self.observe(.1, delay=.3)['pedal'], 'coast')
        for i in range(3):
            self.now += .1
            result = self.observe(.1, speed=4.)
            self.assertEqual(result['phase'], 'following' if i == 2 else 'waiting')
        self.assertEqual(result['pedal'], 'throttle')

    def test_gap_does_not_latch_motion_and_epoch_change_retires(self):
        self.acquire()
        self.now += .6
        wait = self.observe(.1)
        self.assertEqual((wait['phase'], wait['pedal'], wait['steering']), ('waiting', 'coast', 0.))
        self.now += .1
        changed = self.observe(.1, capture_epoch='f' * 32)
        self.assertEqual((changed['phase'], changed['pedal']), ('stopped', 'coast'))

    def test_unknown_stale_mismatched_or_bad_speed_never_authorizes_gas(self):
        for changed in ({'status': 'unknown'}, {'speed_kmh': None}, {'speed_kmh': True},
                        {'speed_kmh': float('nan')}, {'speed_kmh': 351}, {'confidence': 49}, {'confidence': 70},
                        {'sequence': 0}, {'epoch': 'x'}, {'received_at': 0.},
                        {'source_rgb_sha256': 'b' * 64}):
            with self.subTest(changed=changed):
                self.follower = self.make()
                self.sequence = 0
                self.assertEqual(self.observe(speed_changes=changed)['pedal'], 'coast')
                self.now += .1

    def test_speed_hysteresis_brakes_overspeed_and_never_alternates_pedals_same_frame(self):
        self.acquire()
        overspeed = self.observe(speed=20.)
        self.assertEqual(overspeed['pedal'], 'brake')
        self.now += .1
        # A strongly falling fresh HUD trend releases braking before a delayed
        # value crosses the target, rather than overshooting below it.
        self.assertEqual(self.observe(speed=13.5)['pedal'], 'coast')
        self.now += .1
        self.assertEqual(self.observe(speed=12.5)['pedal'], 'coast')
        for speed in (11.8, 12.1, 12., 11.9, 12.2):
            self.now += .1
            self.assertEqual(self.observe(speed=speed)['pedal'], 'coast')

    def test_fresh_acceleration_releases_throttle_before_delayed_speed_overshoots(self):
        self.acquire(speed=4.)
        self.now += .2
        result = self.observe(speed=10.)
        self.assertEqual(result['targetSpeedKmh'], 12.)
        self.assertEqual(result['observedSpeedKmh'], 10.)
        self.assertEqual(result['pedal'], 'coast')

    def test_three_second_unknown_pause_recovers_in_same_session_but_fifteen_seconds_is_bounded(self):
        self.acquire()
        for _ in range(16):
            self.now += .2
            result = self.observe(1., state='unknown')
            self.assertEqual((result['phase'], result['pedal'], result['steering']), ('waiting', 'coast', 0.))
        for i in range(3):
            self.now += .1
            result = self.observe(1.)
            self.assertEqual(result['phase'], 'following' if i == 2 else 'waiting')
        self.assertEqual(result['pedal'], 'throttle')
        self.now += .1
        self.observe(1., state='unknown')
        for _ in range(76):
            self.now += .2
            result = self.observe(1., state='unknown')
            if result['phase'] == 'stopped':
                break
        self.assertEqual((result['phase'], result['reason'], result['pedal']),
                         ('stopped', 'vehicle_relocalization_timeout', 'coast'))

    def test_repeated_unfit_heading_does_not_reset_relocalization_timeout(self):
        self.acquire()
        backwards = (-1., 0., 0., 0., 1., 0., 0., 0., -1.)
        reasons = set()
        for _ in range(80):
            self.now += .2
            result = self.observe(1., speed=0., rotation=backwards)
            self.assertEqual((result['pedal'], result['steering']), ('coast', 0.))
            reasons.add(result['reason'])
            if result['phase'] == 'stopped':
                break
        self.assertIn('vehicle_heading_outside_pursuit_cone', reasons)
        self.assertEqual((result['phase'], result['reason']),
                         ('stopped', 'vehicle_relocalization_timeout'))

    def test_valid_heading_rejoins_after_repeated_unfit_heading(self):
        self.acquire()
        backwards = (-1., 0., 0., 0., 1., 0., 0., 0., -1.)
        for _ in range(20):
            self.now += .2
            result = self.observe(1., speed=0., rotation=backwards)
            self.assertEqual((result['phase'], result['pedal'], result['steering']),
                             ('waiting', 'coast', 0.))
        for _ in range(4):
            self.now += .2
            result = self.observe(1., speed=0.)
            if result['phase'] == 'following':
                break
        self.assertEqual((result['phase'], result['pedal']), ('following', 'throttle'))
        self.assertIsNone(self.follower.waiting_since)

    def test_user_speed_cap_is_binding_and_invalid_cap_rejected(self):
        self.reference.sample = lambda _: 90.
        self.reference.preview = lambda *a, **k: 90.
        self.follower = self.make(max_speed_kmh=10)
        result = self.acquire()
        self.assertEqual((result['targetSpeedKmh'], result['maxSpeedKmh']), (10., 10))
        for cap in (0, 51, True, 15.):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                self.make(max_speed_kmh=cap)

    def test_fifty_speed_cap_is_supported_and_default_remains_fifteen(self):
        self.assertEqual(self.make().max_speed_kmh, 15)
        self.reference.sample = lambda _: 90.
        self.reference.preview = lambda *args, **kwargs: 90.
        self.follower = self.make(max_speed_kmh=50)
        self.assertEqual(self.acquire()['targetSpeedKmh'], 50.)

    def test_waiting_with_unknown_live_speed_still_reports_a_capped_target(self):
        self.reference.sample = lambda _: 90.
        self.follower = self.make(max_speed_kmh=10)
        result = self.observe(speed_changes={'status': 'unknown', 'speed_kmh': None})
        self.assertEqual((result['phase'], result['pedal'], result['targetSpeedKmh']),
                         ('waiting', 'coast', 10.))

    def test_reference_zero_departure_uses_nearby_spatial_positive_sample_not_elapsed_time(self):
        self.reference.sample = lambda ticks: 0. if ticks == 0 else 20.
        self.reference.preview = lambda *a, **k: 0.
        self.follower = self.make()
        result = self.acquire(speed=0.)
        self.assertEqual((result['targetSpeedKmh'], result['pedal']), (10., 'throttle'))
        self.reference.sample = lambda _: 0.
        self.follower = self.make()
        result = self.acquire(speed=0.)
        self.assertEqual(result['pedal'], 'coast')

    def test_reference_preview_slowdown_is_spatial_and_does_not_advance_with_live_clock(self):
        self.reference.preview = lambda ticks, **kw: 6.
        self.follower = self.make()
        result = self.acquire(speed=9.)
        self.assertEqual(result['targetSpeedKmh'], 6.)
        self.assertEqual(result['pedal'], 'brake')
        self.now += .1
        self.assertEqual(self.observe(speed=10.)['pedal'], 'brake')

    def test_low_positive_target_can_depart_and_long_explicit_test_is_finite(self):
        self.follower = self.make(max_speed_kmh=1, max_seconds=1200)
        result = self.acquire(speed=0.)
        self.assertEqual((result['targetSpeedKmh'], result['pedal']), (1., 'throttle'))
        self.assertEqual(result['maxSeconds'], 1200)
        self.now = self.follower.began + 1200
        self.assertEqual(self.observe()['reason'], 'vehicle_time_limit')
        for invalid in (True, 59, 1801):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.make(max_seconds=invalid)

    def test_midroute_restart_requires_mode_and_three_current_confirmations(self):
        self.assertEqual(self.observe(20.)['phase'], 'stopped')
        self.follower = self.make(start_mode='recognized_route')
        result = self.acquire(20.)
        self.assertEqual(result['phase'], 'following')
        self.assertGreater(result['progressFraction'], .5)

    def test_tentative_pose_at_finish_does_not_retire_start_session(self):
        tentative = self.observe(34., state='confirming')
        self.assertEqual((tentative['phase'], tentative['pedal']), ('waiting', 'coast'))
        self.assertEqual(tentative['confirmationValidCount'], 0)
        for i in range(3):
            self.now += .1
            result = self.observe(speed=0.)
            self.assertEqual(result['pedal'], 'throttle' if i == 2 else 'coast')

    def test_expired_startup_vote_does_not_block_a_new_position(self):
        self.follower = self.make(start_mode='recognized_route')
        self.assertEqual(self.observe(34., state='confirming')['pedal'], 'coast')
        for _ in range(7):
            self.now += .2
            self.observe(state='unknown', reason='route_pose_not_verified', inliers=0)
        for i in range(3):
            self.now += .1
            result = self.observe(speed=0.)
            self.assertEqual(result['pedal'], 'throttle' if i == 2 else 'coast')

    def test_two_second_observation_gap_reacquires_nearby_with_three_new_votes(self):
        self.assertEqual(self.acquire()['pedal'], 'throttle')
        self.now += 2.426
        gap = self.observe(.5, speed=0.)
        self.assertEqual((gap['phase'], gap['pedal']), ('waiting', 'coast'))
        for i in range(3):
            self.now += .1
            result = self.observe(.5, speed=0.)
            self.assertEqual(result['pedal'], 'throttle' if i == 2 else 'coast')

    def test_running_session_still_stops_on_large_jump_after_gap(self):
        self.assertEqual(self.acquire()['pedal'], 'throttle')
        self.now += 2.426
        self.assertEqual(self.observe(34., speed=0.)['phase'], 'waiting')
        self.now += .1
        jumped = self.observe(34., speed=0.)
        self.assertEqual((jumped['phase'], jumped['pedal']), ('stopped', 'coast'))
        self.assertEqual(jumped['reason'], 'vehicle_progress_discontinuity')

    def _acquire_moving_dense_trace(self):
        count = 161
        self.route = replace(self.route, camera_trace=tuple((0., 0., i * .2) for i in range(count)),
            source_seconds=tuple(i * .1 for i in range(count)), source_frame_indices=tuple(range(count)),
            reference_rgb_sha256=tuple(f'{i:064x}' for i in range(count)))
        self.follower = self.make()
        self.acquire()
        for i in range(1, 6):
            self.assertEqual(self.observe(i * .2)['phase'], 'following')
            self.now += .1
        for _ in range(7):
            result = self.observe(state='unknown', reason='route_pose_not_verified', inliers=0)
            self.assertEqual((result['phase'], result['pedal']), ('waiting', 'coast'))
            self.now += .1

    def test_short_forward_coast_reacquires_only_after_three_current_poses(self):
        self._acquire_moving_dense_trace()
        for i in range(3):
            result = self.observe(2.5 + i * .1, speed=4., state='confirming' if i < 2 else 'localized')
            if i < 2:
                self.assertEqual((result['phase'], result['pedal']), ('waiting', 'coast'))
                self.assertAlmostEqual(self.follower.high_water, 1.)
            self.now += .1
        self.assertEqual((result['phase'], result['pedal']), ('following', 'throttle'))
        self.assertAlmostEqual(self.follower.high_water, 2.7)

    def test_short_pause_does_not_allow_an_unreachable_forward_jump(self):
        self._acquire_moving_dense_trace()
        result = self.observe(4., speed=4.)
        self.assertEqual((result['phase'], result['reason'], result['pedal']),
                         ('stopped', 'vehicle_progress_discontinuity', 'coast'))
        self.assertAlmostEqual(self.follower.high_water, 1.)

    def test_tentative_jump_after_loss_waits_and_nearby_pose_can_recover(self):
        self.assertEqual(self.acquire()['pedal'], 'throttle')
        self.now += 2.426
        self.assertEqual(self.observe(state='unknown', inliers=0)['pedal'], 'coast')
        self.now += .1
        tentative = self.observe(34., state='confirming', speed=0.)
        self.assertEqual((tentative['phase'], tentative['pedal']), ('waiting', 'coast'))
        self.assertEqual(tentative['confirmationValidCount'], 0)
        for i in range(3):
            self.now += .1
            result = self.observe(.5, speed=0.)
            self.assertEqual(result['pedal'], 'throttle' if i == 2 else 'coast')

    def test_repeated_tentative_jumps_do_not_extend_reacquisition_deadline(self):
        self.assertEqual(self.acquire()['pedal'], 'throttle')
        for _ in range(77):
            result = self.observe(34., state='confirming', speed=0.)
            self.assertEqual(result['pedal'], 'coast')
            self.assertEqual(result['confirmationValidCount'], 0)
            self.now += .2
        self.assertEqual(result['reason'], 'vehicle_relocalization_timeout')

    def test_close_endpoint_requires_ordered_progress_and_low_observed_speed(self):
        self.follower = self.make(start_mode='recognized_route')
        result = self.acquire(34., speed=15.)
        self.assertEqual((result['phase'], result['pedal']), ('following', 'brake'))
        self.now += .1
        rolling = self.observe(34., speed=1.)
        self.assertEqual((rolling['phase'], rolling['pedal']), ('following', 'brake'))
        for _ in range(3):
            self.now += .1
            result = self.observe(34., speed=0.)
        self.assertEqual((result['phase'], result['pedal']), ('arrived', 'coast'))
        self.assertEqual(result['targetSpeedKmh'], 0.)

    def test_endpoint_confirmation_restarts_after_loss_or_repeated_frame(self):
        for interruption in ('ambiguous', 'confirming', 'repeated_rgb'):
            with self.subTest(interruption=interruption):
                self.follower = self.make(start_mode='recognized_route')
                for frame in range(1, 5):
                    result = self.observe(34., speed=0., source_rgb_sha256=str(frame) * 64)
                    self.now += .1
                self.assertEqual((result['reason'], self.follower.arrival), ('vehicle_confirming_end', 2))
                if interruption == 'ambiguous':
                    result = self.observe(34., speed=0., state='unknown', reason='route_progress_ambiguous', inliers=0)
                elif interruption == 'confirming':
                    result = self.observe(34., speed=0., state='confirming')
                else:
                    result = self.observe(34., speed=0., source_rgb_sha256='4' * 64)
                self.assertEqual((result['phase'], result['pedal'], self.follower.arrival), ('waiting', 'coast', 0))
                self.now += .1
                if interruption != 'confirming':
                    for _ in range(2):
                        result = self.observe(34., speed=0., state='confirming')
                        self.now += .1
                for expected in (1, 2, 3):
                    result = self.observe(34., speed=0.)
                    self.now += .1
                    self.assertEqual(result['phase'], 'arrived' if expected == 3 else 'waiting')

    def test_large_heading_correction_does_not_blindly_turn_or_drag_camera(self):
        self.acquire()
        self.now += .1
        result = self.observe(1., rotation=(0., 0., 1., 0., 1., 0., -1., 0., 0.))
        self.assertEqual((result['phase'], result['pedal'], result['steering']), ('waiting', 'coast', 0.))
        self.assertIsNone(result['targetViewCamera'])

    def test_rejoin_does_not_aim_across_a_nearby_right_angle(self):
        trace = ((0., 0., 0.), (0., 0., .65), (0., 0., 1.3),
                 *((i * .65, 0., 1.3) for i in range(1, 6)))
        self.route = replace(self.route, camera_trace=trace, source_seconds=tuple(map(float, range(len(trace)))))
        self.follower = self.make()
        yaw = math.radians(-3.)
        rotation = (math.cos(yaw), 0., -math.sin(yaw), 0., 1., 0., math.sin(yaw), 0., math.cos(yaw))
        for _ in range(3):
            plan = self.observe(speed=0., center=(-1.25, 0., 0.), cross_track_units=1.25, rotation=rotation)
            self.now += .1
        self.assertEqual((plan['phase'], plan['reason'], plan['pedal'], plan['steering']),
                         ('waiting', 'vehicle_heading_outside_pursuit_cone', 'coast', 0.))

    def test_unknown_source_speed_is_unknown_not_replaced_by_last_known_target(self):
        self.acquire()
        self.reference.sample = lambda _: None
        self.now += .1
        result = self.observe(1.)
        self.assertEqual((result['phase'], result['pedal']), ('waiting', 'coast'))
        self.assertIsNone(result['targetSpeedKmh'])

    def test_conservative_tempo_is_scale_independent_and_policy_capped(self):
        reference = ConservativeTempoReference(self.route)
        scaled = replace(self.route, camera_trace=tuple(tuple(100 * x for x in point)
                                                       for point in self.route.camera_trace))
        other = ConservativeTempoReference(scaled)
        self.assertEqual(reference.targets, other.targets)
        self.assertTrue(all(0 <= target <= 5 for target in reference.targets))
        self.assertEqual(reference.targets[-1], 0.)
        self.assertEqual(reference.preview(0, 90000 * 600), 0.)
        with self.assertRaises(ValueError):
            VehicleRouteFollower(self.route, other, clock=lambda: self.now,
                reference_rotations=(self.np.eye(3),) * len(self.route.camera_trace))

    def test_conservative_tempo_requires_live_hud_and_never_exceeds_five(self):
        self.reference = ConservativeTempoReference(self.route)
        self.follower = self.make(max_speed_kmh=50)
        result = self.observe(speed_changes={'status': 'unknown'})
        self.assertEqual((result['phase'], result['pedal']), ('waiting', 'coast'))
        self.now += .1
        result = self.acquire(speed=0.)
        self.assertEqual(result['phase'], 'following')
        self.assertLessEqual(result['targetSpeedKmh'], 5.)

    def test_falling_hud_speed_cannot_reapply_throttle_at_or_above_cap(self):
        self.follower = self.make(max_speed_kmh=5)
        self.acquire(speed=5.)
        for speed in (6.2, 5.5, 5.1, 5.):
            result = self.observe(speed=speed)
            self.assertEqual(result['phase'], 'following')
            self.assertNotEqual(result['pedal'], 'throttle')
            self.now += .1
        self.now += .1
        result = self.observe(speed=10.)
        self.assertEqual(result['pedal'], 'brake')
        self.assertLessEqual(result['targetSpeedKmh'], 5.)

    def test_invalid_pose_metadata_and_failed_reference_stop_without_movement(self):
        for changed in ({'receiver_sequence': True}, {'received_at': None},
                        {'completed_at': float('nan')}, {'geometry': (1920, 1080)},
                        {'inliers': True}, {'source_rgb_sha256': 'invalid'}):
            with self.subTest(changed=changed):
                self.follower = self.make()
                result = self.observe(**changed)
                self.assertEqual((result['phase'], result['pedal']), ('stopped', 'coast'))
        self.follower = self.make()
        def unavailable(_):
            raise ValueError('changed reference')
        self.reference.sample = unavailable
        self.assertEqual(self.observe()['reason'], 'vehicle_reference_speed_invalid')

    def test_delayed_bicycle_plant_holds_commands_turns_and_recovers_two_dropped_corrections(self):
        self._drive_delayed_bicycle_plant()

    def test_delayed_bicycle_plant_rejoins_from_either_side_with_small_heading_error(self):
        for sign in (-1, 1):
            with self.subTest(side=sign):
                self._drive_delayed_bicycle_plant(initial_x=sign * 1.25, initial_yaw=sign * math.radians(8.))
                observations = self.plant_result['observations']
                first_steer = next(row['steering'] for row in observations if row['steering'])
                self.assertLess(sign * first_steer, 0.)
                self.assertLess(min(row['crossTrack'] for row in observations if 3 <= row['progress'] <= 9), .35)

    def _drive_delayed_bicycle_plant(self, *, initial_x=0., initial_yaw=0.):
        # This known synthetic plant exercises temporal/control integration.
        # It supplies oracle poses, not image localization or game calibration.
        np = self.np
        samples = np.linspace(0., math.pi / 2, 100)
        dense = np.concatenate([
            np.column_stack([np.zeros(40), np.linspace(0., 12., 40)]),
            np.column_stack([8. * (1. - np.cos(samples)), 12. + 8. * np.sin(samples)]),
            np.column_stack([np.linspace(8., 24., 60), np.full(60, 20.)])])
        dense_arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(dense, axis=0), axis=1))]
        arc = np.linspace(0., dense_arc[-1], 64)
        xz = np.column_stack([np.interp(arc, dense_arc, dense[:, 0]), np.interp(arc, dense_arc, dense[:, 1])])
        trace = np.column_stack([xz[:, 0], np.zeros(64), xz[:, 1]])
        speeds = np.where((arc > 10.) & (arc < 27.), 7., 12.)
        speeds = np.minimum(speeds, np.sqrt(np.maximum(0., arc[-1] - arc) * 3.) * 3.6)
        speeds[0] = 0.
        seconds = np.r_[0., np.cumsum(np.diff(arc) / np.maximum(1., (speeds[:-1] + speeds[1:]) / 7.2))]
        self.route = replace(self.route, camera_trace=tuple(tuple(map(float, row)) for row in trace),
            source_seconds=tuple(map(float, seconds)), source_frame_indices=tuple(range(64)),
            reference_rgb_sha256=tuple(f'{i:064x}' for i in range(64)))
        self.reference = SimpleNamespace(
            sample=lambda ticks: float(np.interp(ticks / 90000., seconds, speeds)),
            preview=lambda ticks, horizon_ticks: float(min(np.interp(ticks / 90000., seconds, speeds),
                np.interp((ticks + horizon_ticks) / 90000., seconds, speeds))))
        self.now = 10.
        follower = self.make(max_seconds=120, max_speed_kmh=15)
        # Actuation runs at 20 Hz. Pose corrections run at 5 Hz with 150 ms
        # latency. Two consecutive corrections are lost; source frames stay
        # fresh and a decision may be held at most 450 ms, never indefinitely.
        state = np.array([initial_x, 0., initial_yaw, 0.])  # x,z,body yaw, speed m/s in THIS plant.
        history = [state.copy()] * 4
        plan, deadline = None, -1.
        pedals, errors, reasons, curve_speeds = [], [], [], []
        neutral_due_to_deadline = 0
        sequence = 0
        observations = []
        for tick in range(2400):
            self.now = 10. + tick * .05
            if tick % 4 == 0 and tick not in {120, 124}:
                old = history[-4]
                center = np.array([old[0], 0., old[1]])
                offset = center - trace[:-1]
                delta = np.diff(trace, axis=0)
                fraction = np.clip(np.einsum('ij,ij->i', offset, delta) / np.einsum('ij,ij->i', delta, delta), 0., 1.)
                distances = np.linalg.norm(offset - fraction[:, None] * delta, axis=1)
                segment = int(np.argmin(distances))
                progress = float(arc[segment] + fraction[segment] * (arc[segment + 1] - arc[segment]))
                yaw = old[2]
                rotation = (math.cos(yaw), 0., -math.sin(yaw), 0., 1., 0., math.sin(yaw), 0., math.cos(yaw))
                sequence += 1
                received = self.now - .15
                pose = RoutePose('localized', 'synthetic_oracle', self.route.id,
                    self.route.world_revision, 'e' * 32, sequence, received, self.now,
                    f'{sequence:064x}', (960, 540), center=tuple(center), rotation=rotation,
                    segment=segment, progress_units=progress, cross_track_units=float(distances[segment]),
                    inliers=50, median_error_px=.5)
                speed = dict(status='accepted', speed_kmh=float(old[3] * 3.6), confidence=95.,
                    epoch=pose.capture_epoch, sequence=sequence, received_at=received,
                    source_rgb_sha256=pose.source_rgb_sha256)
                plan = follower.observe(pose, speed, motion_active=bool(plan and plan['pedal'] == 'throttle'))
                deadline = min(received + .45, self.now + .35)
                reasons.append(plan['reason'])
                errors.append(float(distances[segment]))
                observations.append(dict(seconds=self.now - 10., x=float(old[0]), z=float(old[1]),
                    speedKmh=float(old[3] * 3.6), crossTrack=float(distances[segment]),
                    progress=progress, phase=plan['phase'], reason=plan['reason'],
                    pedal=plan['pedal'], steering=plan['steering'], targetSpeedKmh=plan['targetSpeedKmh']))
                if 13. < progress < 24.:
                    curve_speeds.append(float(old[3] * 3.6))
                if plan['phase'] in {'stopped', 'arrived'}:
                    break
            active = plan is not None and plan['phase'] == 'following' and self.now <= deadline
            pedal = plan['pedal'] if active else 'coast'
            steering = plan['steering'] if active else 0.
            if plan and plan['phase'] == 'following' and self.now > deadline:
                neutral_due_to_deadline += 1
            pedals.append(pedal)
            acceleration = 1.8 if pedal == 'throttle' else -3. if pedal == 'brake' else -.2
            state[3] = float(np.clip(state[3] + acceleration * .05, 0., 6.))
            state[2] += state[3] / 1.5 * math.tan(steering * 1.6) * .05
            state[0] += math.sin(state[2]) * state[3] * .05
            state[1] += math.cos(state[2]) * state[3] * .05
            history.append(state.copy())
        self.assertEqual(plan['phase'], 'arrived', dict(reasons=reasons[-8:], state=state.tolist(),
            progress=progress, total=float(arc[-1]), plan=plan))
        self.assertIn('vehicle_fresh_pose_required', reasons)
        self.assertLess(max(errors), 1.5)
        self.assertTrue(curve_speeds)
        self.assertLess(max(curve_speeds), 11.)
        self.assertGreater(neutral_due_to_deadline, 0)
        self.assertLess(neutral_due_to_deadline, 15)
        # Many actuator ticks reuse the same held command, rather than down/up
        # on every correction. Transitions are actual speed control decisions.
        transitions = sum(a != b for a, b in zip(pedals, pedals[1:]))
        self.assertLess(transitions, len(pedals) / 6)
        self.plant_result = dict(scope='SYNTHETIC_ORACLE_POSE_BICYCLE_NOT_GAME_ACCEPTANCE',
            controller='VehicleRouteFollower', physicalActions=0, sourceMetricCalibration=False,
            imageLocalizationTested=False, syntheticUnits='metres_in_this_plant_only',
            actuatorHz=20, correctionHz=5, correctionLatencyMs=150, droppedCorrections=2,
            decisionHoldMaxMs=450, maxSpeedKmh=15, phase=plan['phase'],
            elapsedSeconds=self.now - 10., maxCrossTrack=float(max(errors)),
            curveMaxSpeedKmh=float(max(curve_speeds)), neutralExpiredActuatorTicks=neutral_due_to_deadline,
            pedalTransitions=transitions, actuatorTicks=len(pedals),
            confirmedRecoveryWaits=sum(r == 'vehicle_confirming_current_position' for r in reasons),
            referencePath=xz.tolist(), referenceSpeedKmh=speeds.tolist(), observations=observations)
