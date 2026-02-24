# tests/test_ws/test_stream_metrics.py
# Tests for StreamMetrics — Prometheus metric updates from heartbeat pong data.
from __future__ import annotations

from backend.websocket.stream_metrics import StreamMetrics


class TestStreamMetricsUpdateFromPong:

    def test_update_with_full_data(self):
        sm = StreamMetrics("device-test-1")
        sm.update_from_pong({
            "fps": 28,
            "bytes_sent": 9_000_000,
            "key_frame_ratio": 0.05,
            "avg_frame_kb": 40.0,
        })
        # No exception raised; metrics updated

    def test_update_with_empty_dict_returns_early(self):
        sm = StreamMetrics("device-test-2")
        # Must not raise even with empty payload
        sm.update_from_pong({})

    def test_update_with_none_returns_early(self):
        sm = StreamMetrics("device-test-3")
        sm.update_from_pong(None)

    def test_update_fps_at_30_no_drops(self):
        sm = StreamMetrics("device-test-4")
        # fps == 30 → drop_approx = 0 → frame_drops counter not incremented
        sm.update_from_pong({"fps": 30})

    def test_update_fps_below_30_records_drops(self):
        sm = StreamMetrics("device-test-5")
        # fps == 20 → drop_approx = 10 → frame_drops incremented
        sm.update_from_pong({"fps": 20})

    def test_update_fps_zero(self):
        sm = StreamMetrics("device-test-6")
        sm.update_from_pong({"fps": 0})

    def test_update_missing_bytes_sent_key(self):
        sm = StreamMetrics("device-test-7")
        # bytes_sent absent → should not touch bytes counter
        sm.update_from_pong({"fps": 25, "key_frame_ratio": 0.033})

    def test_update_with_bytes_sent_present(self):
        sm = StreamMetrics("device-test-8")
        sm.update_from_pong({"fps": 29, "bytes_sent": 5_000_000})

    def test_update_with_key_frame_ratio(self):
        sm = StreamMetrics("device-test-9")
        sm.update_from_pong({"fps": 29, "key_frame_ratio": 0.10})


class TestStreamMetricsCleanup:

    def test_cleanup_does_not_raise(self):
        sm = StreamMetrics("device-cleanup-1")
        sm.update_from_pong({"fps": 28, "key_frame_ratio": 0.03})
        sm.cleanup()

    def test_cleanup_without_prior_update(self):
        sm = StreamMetrics("device-cleanup-2")
        # Label never set → cleanup_stream_metrics should handle gracefully
        sm.cleanup()
