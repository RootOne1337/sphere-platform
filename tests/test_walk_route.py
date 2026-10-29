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
        return self.follower.observe(replace(pose,**changes))

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

    def test_camera_rotation_changes_command_without_replaying_any_keys(self):
        # Camera looking along +X: the world +Z route is to camera-left.
        result=self.observe(rotation=(0.,0.,-1.,0.,1.,0.,1.,0.,0.))
        self.assertLess(result['stick'][0],0)
        self.assertAlmostEqual(result['stick'][1],0)

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

    def test_initial_confirmation_is_neutral_but_lost_tracking_after_movement_is_terminal(self):
        self.assertEqual(self.observe(state='confirming')['stick'],[0.,0.])
        self.now+=.2;self.observe()
        self.now+=.2
        lost=self.observe(state='unknown',center=None,rotation=None,progress_units=None)
        self.assertEqual(lost['reason'],'walk_localization_lost')
        self.assertEqual(lost['stick'],[0.,0.])

    def test_pose_age_epoch_sequence_and_large_progress_jump_stop(self):
        for changes in ({'received_at':9.,'completed_at':9.},{'receiver_sequence':0},
                        {'rotation':(1.,)*9},{'center':(float('nan'),0.,0.)}):
            with self.subTest(changes=changes):
                self.follower=WalkRouteFollower(self.route,clock=lambda:self.now)
                self.assertEqual(self.observe(**changes)['phase'],'stopped')
        self.follower=WalkRouteFollower(self.route,clock=lambda:self.now)
        self.observe();self.now+=.2
        self.assertEqual(self.observe(25.)['reason'],'walk_progress_jump')

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
