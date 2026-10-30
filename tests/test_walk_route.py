"""Control geometry and stop conditions, not a claim about game accuracy."""
from dataclasses import replace
import unittest

from motor_worker.route_localization import RoutePose
from motor_worker.walk_route import WalkRouteFollower
from tests import test_motor_route_localization as fixtures


class WalkRouteTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.SparseLocalizationTests('test_blank_real_rgb_has_no_pose');fixture.setUp()
        self.route=fixture.route
        self.now,self.sequence=10.,0
        self.follower=WalkRouteFollower(self.route,clock=lambda:self.now)

    def observe(self, progress=0., **changes):
        self.sequence+=1
        pose=RoutePose('localized','relative_camera_pose_not_clearance_or_arrival',self.route.id,
            self.route.world_revision,'e'*32,self.sequence,self.now,self.now,'a'*64,(960,540),
            center=(0.,0.,progress),rotation=(1.,0.,0.,0.,1.,0.,0.,0.,1.),segment=min(6,int(progress/5)),
            progress_units=progress,cross_track_units=0.,inliers=50,median_error_px=.5)
        motion=changes.pop('motion_active',None)
        return self.follower.observe(replace(pose,**changes),motion_active=motion)

    def test_neutral_camera_wait_does_not_consume_translation_stall_budget(self):
        for _ in range(45):
            reply=self.observe(motion_active=False);self.now+=.1
            self.assertNotEqual(reply['phase'],'stopped')
        self.assertEqual(self.follower.motion_seconds,0.)
        for i in range(20):
            reply=self.observe(progress=i*.15,motion_active=True);self.now+=.1
            self.assertNotEqual(reply['phase'],'stopped')
        self.assertAlmostEqual(self.follower.motion_seconds,2.)

    def test_applied_motion_without_route_progress_still_stops_at_high_query_rate(self):
        self.observe(motion_active=False)
        for _ in range(200):
            self.now+=.02;reply=self.observe(motion_active=True)
            if reply['phase']=='stopped':break
        self.assertEqual(reply['reason'],'walk_no_route_progress')
        self.assertLess(self.follower.motion_seconds,3.2)

    def test_stationary_turn_then_short_walk_is_not_three_seconds_of_blocked_motion(self):
        self.observe(motion_active=False)
        for _ in range(25):self.now+=.1;self.observe(motion_active=False)
        for _ in range(10):
            self.now+=.1;reply=self.observe(motion_active=True)
        self.assertEqual(reply['phase'],'following')
        self.assertAlmostEqual(self.follower.motion_seconds,1.)

    def test_forward_is_screen_up_and_rate_and_magnitude_are_bounded(self):
        first=self.observe()
        self.assertEqual(first['phase'],'following')
        self.assertEqual(first['stick'][0],0.)
        self.assertLess(first['stick'][1],0.)
        self.assertLessEqual(abs(first['stick'][1]),.12+1e-9)
        self.now+=.2
        second=self.observe(.4)
        self.assertLessEqual(abs(second['stick'][1]),.35)
        self.assertFalse(second['executionQualified'])
        self.assertFalse(second['groundRoute'])

    def test_negotiated_passage_budget_can_exceed_sixty_seconds_but_is_finite(self):
        self.follower=WalkRouteFollower(self.route,clock=lambda:self.now,max_seconds=300)
        began=self.now
        for _ in range(310):self.now+=.2;reply=self.observe(motion_active=False)
        self.assertEqual(reply['phase'],'following');self.assertEqual(reply['maxSeconds'],300)
        self.now=began+300;self.assertEqual(self.observe()['reason'],'walk_time_limit')
        for invalid in (True,59,601,1e6):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                WalkRouteFollower(self.route,clock=lambda:self.now,max_seconds=invalid)

    def test_recorded_camera_pitch_is_distinct_from_slope_of_camera_trace(self):
        import numpy as np
        import math
        a=.35;R=np.array([[1,0,0],[0,math.cos(a),-math.sin(a)],[0,math.sin(a),math.cos(a)]])
        self.follower=WalkRouteFollower(self.route,clock=lambda:self.now,camera_tracking=True,
                                       reference_rotations=(R,)*len(self.route.camera_trace))
        wrong=self.observe();self.assertEqual(wrong['reason'],'walk_camera_alignment_required')
        self.assertGreater(wrong['targetViewCamera'][1],.3);self.assertEqual(wrong['stick'],[0.,0.])
        self.now+=.2
        aligned=self.observe(rotation=tuple(R.flat))
        np.testing.assert_allclose(aligned['targetViewCamera'],[0,0,1],atol=1e-8)
        self.assertEqual(aligned['reason'],'walk_camera_relative_pursuit');self.assertLess(aligned['stick'][1],0)

    def test_moderate_recorded_view_turn_can_coexist_with_walking(self):
        import numpy as np
        import math
        a=.25;R=np.array([[math.cos(a),0,-math.sin(a)],[0,1,0],[math.sin(a),0,math.cos(a)]])
        self.follower=WalkRouteFollower(self.route,clock=lambda:self.now,camera_tracking=True,
                                       reference_rotations=(R,)*len(self.route.camera_trace))
        result=self.observe();self.assertTrue(result['referenceView'])
        self.assertEqual(result['reason'],'walk_camera_relative_pursuit');self.assertLess(result['stick'][1],0)

    def test_camera_rotation_changes_command_without_replaying_any_keys(self):
        # Camera looking along +X: the world +Z route is to camera-left.
        result=self.observe(rotation=(0.,0.,-1.,0.,1.,0.,1.,0.,0.))
        self.assertLess(result['stick'][0],0)
        self.assertAlmostEqual(result['stick'][1],0)

    def test_one_weak_localized_image_requires_three_strong_poses_then_resumes(self):
        self.observe()
        self.now += .1
        weak = self.observe(.2, inliers=21)
        self.assertEqual(weak['reason'], 'walk_relocalizing_neutral')
        self.assertEqual(weak['stick'], [0., 0.])
        for progress in [.2, .3]:
            self.now += .1
            self.assertEqual(self.observe(progress)['stick'], [0., 0.])
        self.now += .1
        resumed = self.observe(.4)
        self.assertEqual(resumed['reason'], 'walk_camera_relative_pursuit')
        self.assertLess(resumed['stick'][1], 0.)

    def test_persistently_weak_images_stop_and_invalid_geometry_never_recovers(self):
        self.observe()
        for _ in range(24):
            self.now += .1
            weak = self.observe(inliers=21)
        self.assertEqual(weak['reason'], 'walk_relocalization_timeout')
        self.assertEqual(weak['stick'], [0., 0.])
        self.follower = WalkRouteFollower(self.route, clock=lambda: self.now)
        invalid = self.observe(inliers=21, rotation=(0.,)*9)
        self.assertEqual(invalid['reason'], 'walk_pose_or_corridor_unqualified')

    def test_four_brief_weak_images_do_not_consume_lost_position_budget(self):
        self.observe()
        for _ in range(4):
            self.now+=.1
            self.assertEqual(self.observe(inliers=21)['stick'],[0.,0.])
            for _ in range(3):self.now+=.1;reply=self.observe()
            self.assertEqual(reply['phase'],'following')
        self.assertEqual(self.follower.relocalizations,0)
        self.assertGreater(self.follower.recovery_seconds,1.)

    def test_four_neutral_transport_gaps_require_new_poses_without_spending_position_losses(self):
        self.observe()
        for _ in range(4):
            self.now+=.6
            reply=self.observe(state='unknown',reason='route_observation_gap')
            self.assertEqual(reply['stick'],[0.,0.])
            for i in range(3):
                self.now+=.1;reply=self.observe()
                if i<2:self.assertEqual(reply['stick'],[0.,0.])
            self.assertEqual(reply['phase'],'following')
        self.assertEqual(self.follower.relocalizations,0)

    def test_repeated_weak_images_have_a_total_wait_budget_and_real_loss_still_counts(self):
        self.observe()
        for _ in range(24):
            self.now+=.1;self.observe(inliers=21)
            for _ in range(3):self.now+=.1;reply=self.observe()
            if reply['phase']=='stopped':break
        self.assertEqual(reply['reason'],'walk_recovery_time_budget')
        self.assertEqual(reply['stick'],[0.,0.])
        self.follower=WalkRouteFollower(self.route,clock=lambda:self.now)
        self.observe();self.now+=.1;self.observe(inliers=21)
        self.now+=.1;self.observe(state='unknown')
        self.assertEqual(self.follower.relocalizations,1)

    def test_camera_tracking_aligns_while_stationary_then_resumes_and_keeps_real_stall_limit(self):
        import math
        self.follower=WalkRouteFollower(self.route,clock=lambda:self.now,camera_tracking=True)
        for i in range(22):
            yaw=1.-i*.045
            rotation=(math.cos(yaw),0.,-math.sin(yaw),0.,1.,0.,math.sin(yaw),0.,math.cos(yaw))
            reply=self.observe(rotation=rotation)
            if yaw>.08:
                self.assertEqual(reply['reason'],'walk_camera_alignment_required')
                self.assertEqual(reply['stick'],[0.,0.])
            self.now+=.2
        self.assertEqual(reply['reason'],'walk_camera_relative_pursuit')
        self.assertLess(reply['stick'][1],0)
        for _ in range(18):
            reply=self.observe();self.now+=.2
        self.assertEqual(reply['reason'],'walk_no_route_progress')

    def test_camera_tracking_never_waits_indefinitely_for_an_unresponsive_camera(self):
        self.follower=WalkRouteFollower(self.route,clock=lambda:self.now,camera_tracking=True)
        for _ in range(18):
            reply=self.observe(rotation=(0.,0.,-1.,0.,1.,0.,1.,0.,0.));self.now+=.2
        self.assertEqual(reply['reason'],'walk_camera_not_converging')
        self.assertEqual(reply['stick'],[0.,0.])

    def test_start_midroute_and_end_pauses_do_not_break_pursuit(self):
        import numpy as np
        route=replace(self.route,camera_trace=((0.,0.,0.),(0.,0.,0.),(0.,0.,5.),(0.,0.,10.),
            (0.,0.,10.),(0.,0.,15.),(0.,0.,20.),(0.,0.,20.)))
        self.follower=WalkRouteFollower(route,clock=lambda:self.now)
        with np.errstate(divide='raise',invalid='raise'):
            first=self.observe()
            self.assertEqual(first['phase'],'following')
            self.assertLess(first['stick'][1],0.)
            self.now+=.2
            # Lookahead lands exactly at the final, stationary camera plateau.
            following=self.observe(16.)
            self.assertEqual(following['phase'],'following')
            self.assertTrue(np.isfinite(following['stick']).all())
        self.assertEqual(self.follower.step,5.)

    def test_sideways_start_corrects_toward_the_observed_trace(self):
        result=self.observe(center=(2.,0.,0.),cross_track_units=2.)
        self.assertLess(result['stick'][0],0)
        self.assertLess(result['stick'][1],0)

    def test_far_start_never_moves_and_cannot_resume_by_newer_pose(self):
        result=self.observe(15.)
        self.assertEqual(result['reason'],'walk_start_outside_recorded_beginning')
        self.now+=.2
        self.assertEqual(self.observe()['stick'],[0.,0.])
        self.assertEqual(self.observe()['phase'],'stopped')

    def test_start_tolerance_is_recording_time_and_arc_based_not_keyframe_density(self):
        import hashlib
        for count in (21, 101):
            with self.subTest(count=count):
                route=replace(self.route,camera_trace=tuple((0.,0.,i*10/(count-1)) for i in range(count)),
                    source_seconds=tuple(i*50/(count-1) for i in range(count)),
                    reference_rgb_sha256=tuple(hashlib.sha256(str(i).encode()).hexdigest() for i in range(count)),
                    source_frame_indices=tuple(range(count)))
                self.follower=WalkRouteFollower(route,clock=lambda:self.now)
                self.assertAlmostEqual(self.follower.start_arc,1.)
                result=self.observe(.6)
                self.assertEqual(result['phase'],'following')
                self.follower=WalkRouteFollower(route,clock=lambda:self.now)
                self.assertEqual(self.observe(2.)['reason'],'walk_start_outside_recorded_beginning')

    def test_explicit_resume_acquires_middle_then_follows_remaining_trace(self):
        self.follower=WalkRouteFollower(self.route,clock=lambda:self.now,start_mode='recognized_route')
        for _ in range(2):
            result=self.observe(15.)
            self.assertEqual(result['reason'],'walk_confirming_current_position')
            self.assertEqual(result['stick'],[0.,0.]);self.now+=.1
        result=self.observe(15.)
        self.assertEqual(result['phase'],'following');self.assertLess(result['stick'][1],0)
        self.assertAlmostEqual(result['progressFraction'],15/35)
        for progress in (20.,25.,30.,35.,35.,35.):
            self.now+=.2;result=self.observe(progress)
        self.assertEqual(result['phase'],'arrived')

    def test_resume_requires_three_new_stable_poses_after_unknown_or_jump(self):
        self.follower=WalkRouteFollower(self.route,clock=lambda:self.now,start_mode='recognized_route')
        self.observe(15.);self.now+=.1
        self.assertEqual(self.observe(15.,state='unknown')['stick'],[0.,0.]);self.now+=.1
        for _ in range(2):
            self.assertEqual(self.observe(15.)['phase'],'waiting');self.now+=.1
        # Another distant place cannot complete the old confirmation streak.
        self.assertEqual(self.observe(15.,center=(25.,0.,15.))['phase'],'waiting');self.now+=.1
        self.assertEqual(self.observe(15.,center=(25.,0.,15.))['phase'],'waiting')

    def test_resume_never_moves_from_unlocalized_wrong_map_or_outside_corridor(self):
        for changes in ({'state':'unknown'}, {'state':'confirming'},
                        {'world_revision':'f'*32}, {'cross_track_units':100.}):
            with self.subTest(changes=changes):
                self.follower=WalkRouteFollower(self.route,clock=lambda:self.now,start_mode='recognized_route')
                reply=self.observe(15.,**changes)
                self.assertEqual(reply['stick'],[0.,0.]);self.assertNotEqual(reply['phase'],'following')

    def test_initial_confirmation_and_short_localization_loss_are_neutral(self):
        self.assertEqual(self.observe(state='confirming')['stick'],[0.,0.])
        self.now+=.2;self.observe()
        self.now+=.2
        lost=self.observe(state='unknown',center=None,rotation=None,progress_units=None)
        self.assertEqual(lost['reason'],'walk_relocalizing_neutral')
        self.assertEqual(lost['phase'],'waiting')
        self.assertEqual(lost['stick'],[0.,0.])

    def test_recovery_requires_three_new_localized_poses_before_any_movement(self):
        self.observe();self.now+=.2;self.observe(state='unknown')
        for _ in range(2):
            self.now+=.2;reply=self.observe(.5)
            self.assertEqual(reply['stick'],[0.,0.]);self.assertEqual(reply['phase'],'waiting')
        self.now+=.2;reply=self.observe(.5)
        self.assertEqual(reply['phase'],'following');self.assertLess(reply['stick'][1],0.)

    def test_current_confirming_geometry_keeps_neutral_recovery_alive_after_two_wall_seconds(self):
        self.observe();self.now+=.1;self.observe(state='unknown',reason='route_frame_expired_during_localization')
        for _ in range(8):
            self.now+=.3;reply=self.observe(.5,state='confirming')
            self.assertEqual(reply['phase'],'waiting');self.assertEqual(reply['stick'],[0.,0.])
        for i in range(3):
            self.now+=.1;reply=self.observe(.5)
            if i<2:self.assertEqual(reply['stick'],[0.,0.])
        self.assertEqual(reply['phase'],'following');self.assertGreater(self.follower.recovery_seconds,2.)

    def test_compatible_confirming_images_cannot_extend_total_neutral_budget(self):
        self.observe();self.now+=.1;self.observe(state='unknown')
        for _ in range(65):
            self.now+=.1;reply=self.observe(.5,state='confirming')
            if reply['phase']=='stopped':break
        self.assertEqual(reply['reason'],'walk_recovery_time_budget');self.assertEqual(reply['stick'],[0.,0.])

    def test_wrong_place_confirmation_cannot_keep_the_recovery_timer_alive(self):
        self.observe();self.now+=.1;self.observe(state='unknown')
        for _ in range(25):
            self.now+=.1;reply=self.observe(.5,state='confirming',center=(100.,0.,0.))
            if reply['phase']=='stopped':break
        self.assertEqual(reply['reason'],'walk_relocalization_timeout')

    def test_current_compatible_geometry_is_considered_before_gap_idle_timeout(self):
        self.observe();self.now+=.1;self.observe(state='unknown')
        self.now+=1.4;self.observe(state='unknown')
        self.now+=.7;reply=self.observe(.5,state='confirming')
        self.assertEqual(reply['phase'],'waiting');self.assertEqual(reply['stick'],[0.,0.])
        self.assertLessEqual(abs(reply['stick'][1]),.2)

    def test_unconfirmed_frames_do_not_reset_the_recovery_deadline(self):
        self.observe();self.now+=.2;self.observe(state='unknown')
        for i in range(11):
            self.now+=.2
            reply=self.observe(.1,state='confirming' if i%2 else 'unknown',center=None,rotation=None,inliers=0)
            self.assertEqual(reply['stick'],[0.,0.])
        self.assertEqual(reply['reason'],'walk_relocalization_timeout')
        self.now+=.2;self.assertEqual(self.observe(.1)['phase'],'stopped')

    def test_reappearing_far_position_or_heading_never_resumes(self):
        for changes in ({'center':(21.,0.,0.),'cross_track_units':0.},
                        {'rotation':(0.,0.,-1.,0.,1.,0.,1.,0.,0.)},
                        {'progress_units':21.}):
            self.follower=WalkRouteFollower(self.route,clock=lambda:self.now)
            self.observe();self.now+=.2;self.observe(state='unknown');self.now+=.2
            reply=self.observe(**changes)
            self.assertEqual(reply['reason'],'walk_relocalization_drift');self.assertEqual(reply['stick'],[0.,0.])

    def test_repeated_loss_has_a_finite_budget_even_with_successful_recovery(self):
        self.observe()
        for _ in range(3):
            self.now+=.2;self.assertEqual(self.observe(state='unknown')['phase'],'waiting')
            for _ in range(3):self.now+=.2;reply=self.observe(.1)
            self.assertEqual(reply['phase'],'following')
        self.now+=.2;reply=self.observe(state='unknown')
        self.assertEqual(reply['reason'],'walk_relocalization_budget');self.assertEqual(reply['stick'],[0.,0.])

    def test_short_observation_gap_requires_three_new_poses_instead_of_replaying_movement(self):
        self.observe();self.now+=.7
        reply=self.observe(state='unknown')
        self.assertEqual(reply['reason'],'walk_relocalizing_neutral');self.assertEqual(reply['stick'],[0.,0.])
        for _ in range(2):
            self.now+=.1;self.assertEqual(self.observe(.1)['phase'],'waiting')
        self.now+=.1;self.assertEqual(self.observe(.1)['phase'],'following')

    def test_long_stream_gap_remains_terminal(self):
        self.observe();self.now+=2.01;reply=self.observe(state='unknown')
        self.assertEqual(reply['reason'],'walk_pose_binding_or_age');self.assertEqual(reply['stick'],[0.,0.])

    def test_pose_age_epoch_sequence_and_large_progress_jump_stop(self):
        for changes in ({'received_at':7.,'completed_at':7.},{'receiver_sequence':0},
                        {'rotation':(1.,)*9},{'center':(float('nan'),0.,0.)}):
            with self.subTest(changes=changes):
                self.follower=WalkRouteFollower(self.route,clock=lambda:self.now)
                self.assertEqual(self.observe(**changes)['phase'],'stopped')
        self.follower=WalkRouteFollower(self.route,clock=lambda:self.now)
        self.observe();self.now+=.2
        self.assertEqual(self.observe(25.)['reason'],'walk_progress_jump')

    def test_single_expired_pose_is_neutral_then_three_new_fresh_poses_resume(self):
        self.observe();self.now+=.5
        reply=self.observe(.1,received_at=self.now-.3,completed_at=self.now)
        self.assertEqual(reply['reason'],'walk_relocalizing_neutral')
        self.assertEqual(reply['stick'],[0.,0.]);self.assertEqual(reply['phase'],'waiting')
        self.assertEqual(self.follower.high_water,0.)
        for _ in range(2):
            self.now+=.1;reply=self.observe(.1)
            self.assertEqual(reply['phase'],'waiting');self.assertEqual(reply['stick'],[0.,0.])
        self.now+=.1;reply=self.observe(.1)
        self.assertEqual(reply['phase'],'following');self.assertLess(reply['stick'][1],0.)

    def test_expired_pose_never_contributes_geometry_or_acquisition(self):
        self.follower=WalkRouteFollower(self.route,clock=lambda:self.now,start_mode='recognized_route')
        reply=self.observe(30.,received_at=self.now-.3,completed_at=self.now)
        self.assertEqual(reply['phase'],'waiting');self.assertEqual(reply['stick'],[0.,0.])
        self.assertIsNone(self.follower.last_good)
        self.assertEqual(self.follower.acquisition,0)
        self.now+=.1;reply=self.observe(.1)
        self.assertEqual(reply['phase'],'waiting');self.assertEqual(self.follower.acquisition,1)

    def test_expired_pose_with_changed_source_or_reused_sequence_is_still_terminal(self):
        for changes in ({'capture_epoch':'f'*32},{'receiver_sequence':1},{'world_revision':'f'*32}):
            self.follower=WalkRouteFollower(self.route,clock=lambda:self.now)
            self.observe(receiver_sequence=1);self.now+=.5
            reply=self.observe(received_at=self.now-.3,completed_at=self.now,**changes)
            self.assertEqual(reply['reason'],'walk_pose_binding_or_age');self.assertEqual(reply['phase'],'stopped')

    def test_repeated_slow_replies_do_not_extend_recovery_forever(self):
        self.observe();self.now+=.5
        self.observe(received_at=self.now-.3,completed_at=self.now)
        for _ in range(11):
            self.now+=.2;reply=self.observe(received_at=self.now-.3,completed_at=self.now)
            self.assertEqual(reply['stick'],[0.,0.])
        self.assertEqual(reply['reason'],'walk_relocalization_timeout')

    def test_camera_timeout_does_not_count_a_neutral_recovery_as_failed_turning(self):
        import math
        self.follower=WalkRouteFollower(self.route,clock=lambda:self.now,camera_tracking=True)
        yaw=.5;rotation=(math.cos(yaw),0.,-math.sin(yaw),0.,1.,0.,math.sin(yaw),0.,math.cos(yaw))
        self.assertEqual(self.observe(rotation=rotation)['reason'],'walk_camera_alignment_required')
        self.now+=1.5
        self.assertEqual(self.observe(rotation=rotation,received_at=self.now-.3,completed_at=self.now)['phase'],'waiting')
        for _ in range(3):self.now+=.2;reply=self.observe(rotation=rotation)
        self.assertEqual(reply['reason'],'walk_camera_alignment_required')
        for _ in range(5):
            self.now+=.2
            self.assertEqual(self.observe(rotation=rotation)['reason'],'walk_camera_alignment_required')

    def test_stall_and_time_limit_do_not_try_blind_recovery(self):
        result=self.observe()
        for _ in range(17):
            self.now+=.2;result=self.observe()
        self.assertEqual(result['reason'],'walk_no_route_progress')
        self.assertEqual(result['stick'],[0.,0.])
        self.follower=WalkRouteFollower(self.route,clock=lambda:self.now)
        self.now+=60
        self.assertEqual(self.observe()['reason'],'walk_time_limit')

    def test_end_requires_ordered_progress_and_three_localized_observations(self):
        self.observe()
        for progress in (5.,10.,15.,20.,25.,30.):
            self.now+=.2;self.observe(progress)
        self.now+=.2
        self.assertEqual(self.observe(35.)['reason'],'walk_confirming_end')
        self.now+=.2;self.assertEqual(self.observe(35.)['phase'],'waiting')
        self.now+=.2
        result=self.observe(35.)
        self.assertEqual(result['phase'],'arrived')
        self.assertEqual(result['stick'],[0.,0.])
        self.now+=.1
        terminal=self.observe(state='unknown')
        self.assertEqual(terminal['phase'],'arrived')
        self.assertEqual(terminal['progressFraction'],result['progressFraction'])
        self.assertEqual(terminal['stick'],[0.,0.])

    def test_closed_loop_start_is_not_an_arrival(self):
        points=((0.,0.,0.),(0.,0.,5.),(5.,0.,5.),(10.,0.,5.),
                (10.,0.,0.),(5.,0.,0.),(2.,0.,0.),(0.,0.,0.))
        self.route=replace(self.route,camera_trace=points)
        self.follower=WalkRouteFollower(self.route,clock=lambda:self.now)
        self.assertEqual(self.observe()['phase'],'following')

    def test_closed_loop_controller_corrects_a_lateral_start_in_a_simulated_free_corridor(self):
        # A tiny kinematic simulator supplies independent current poses. It is
        # deliberately not a replay of the recorded command/time sequence.
        import numpy as np
        position=np.array([2.,0.,0.])
        result=None
        for _ in range(180):
            progress=float(np.clip(position[2],0,35))
            result=self.observe(progress,center=tuple(position),cross_track_units=abs(float(position[0])))
            if result['phase'] in {'arrived','stopped'}:break
            x,y=result['stick']
            position+=np.array([x,0.,-y])*12*.1
            self.now+=.1
        self.assertEqual(result['phase'],'arrived',result)
        self.assertLess(abs(position[0]),.5)
        self.assertGreater(position[2],31.)


if __name__=='__main__':unittest.main()
