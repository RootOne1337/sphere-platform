"""Current-image PnP stays mandatory while the one global query runs."""
from concurrent.futures import Future

from motor_worker.route_background_tracking import BackgroundVerifiedRouteLocalizer
from tests import test_motor_route_tracking as base


class ControlledExecutor:
    def __init__(self):
        self.calls = []
        self.closed = False

    def submit(self, *args):
        future = Future()
        self.calls.append((future, args))
        return future

    def shutdown(self, **kwargs):
        self.closed = True


class BackgroundTrackingTests(base.AnchoredTrackingTests):
    def setUp(self):
        super().setUp()
        original = self.tracker
        self.tracker = BackgroundVerifiedRouteLocalizer(original.route, capture_epoch=base.EPOCH,
            episode_id=base.EPISODE, goal_revision=base.GOAL, clock=lambda: self.now)
        self.tracker._extract = original._extract
        self.tracker._executor.shutdown(wait=True)
        self.executor = self.tracker._executor = ControlledExecutor()

    def tearDown(self):
        self.tracker.close(wait=True)

    def pending(self):
        self.confirm()
        for _ in range(3):
            pose, _ = self.observe()
            self.assertEqual(pose.state, 'localized')
        self.assertIsNotNone(self.tracker._pending)
        return self.tracker._pending

    def test_only_one_job_and_current_flow_remains_required(self):
        self.pending()
        self.now -= .1
        pose, center = self.observe()
        self.assertEqual(pose.state, 'localized')
        self.assertEqual(len(self.executor.calls), 1)
        self.assertEqual(self.global_calls, 3)
        self.np.testing.assert_allclose(pose.center, center, atol=.04)

    def test_success_reanchors_old_query_then_solves_current_image(self):
        pending = self.pending()
        pending['future'].set_result((pending['solution'], self.now+.12))
        pose, center = self.observe()
        self.assertEqual(pose.state, 'localized')
        self.assertTrue(self.tracker.last_diagnostic['backgroundAccepted'])
        self.assertEqual(self.tracker._descriptor_at, pending['frame'].received_at)
        self.assertEqual(pose.receiver_sequence, self.index)
        self.np.testing.assert_allclose(pose.center, center, atol=.04)

    def test_late_completion_is_not_a_new_fresh_timestamp(self):
        pending = self.pending()
        pending['future'].set_result((pending['solution'], self.now+.26))
        pose, _ = self.observe()
        self.assertEqual(pose.state, 'unknown')
        self.assertIsNone(self.tracker._descriptor_at)

    def test_inconsistent_global_geometry_revokes_tracking(self):
        pending = self.pending()
        solution = pending['solution']
        wrong = (solution[0]+self.np.array([3., 0., 0.]), *solution[1:])
        pending['future'].set_result((wrong, self.now+.1))
        pose, _ = self.observe()
        self.assertEqual(pose.state, 'unknown')
        self.assertEqual(self.tracker.confirmations, 0)

    def test_no_result_by_original_deadline_revokes_tracking(self):
        pending = self.pending()
        pending['future'].set_running_or_notify_cancel()
        self.now += .02
        pose, _ = self.observe()
        self.assertEqual(pose.state, 'unknown')
        self.assertTrue(pending['discard'])
        self.assertIsNone(self.tracker._anchors)
        # A late result after revocation cannot restore old confirmation.
        pending['future'].set_result((pending['solution'], self.now))
        pose, _ = self.observe()
        self.assertEqual(pose.state, 'confirming')
        self.assertEqual(self.global_calls, 4)

    def test_worker_exception_revokes_and_requires_descriptor_confirmation(self):
        pending = self.pending()
        pending['future'].set_exception(RuntimeError('fixture_global_failure'))
        pose, _ = self.observe()
        self.assertEqual(pose.state, 'unknown')
        self.assertIsNone(self.tracker._anchors)
        pose, _ = self.observe()
        self.assertEqual(pose.state, 'confirming')

    def test_close_retires_and_cancels_pending_work(self):
        pending = self.pending()
        self.tracker.close()
        self.assertTrue(pending['future'].cancelled())
        self.assertTrue(self.executor.closed)
        pose, _ = self.observe()
        self.assertEqual(pose.reason, 'route_binding_retired')
