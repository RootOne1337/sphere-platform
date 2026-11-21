import cv2
import numpy as np
import pytest

from scripts.pilot.world_map_lab.classic_lens import focal_from_map, stationary_focal
from scripts.pilot.world_map_lab.classic_transfers import MixedJourney
from scripts.pilot.world_map_lab.classic_window import KeyLease, desired_keys
from scripts.pilot.world_map_lab.classic_world_binding import allocate
from scripts.pilot.world_map_lab.classic_world_limits import merge_limits


def test_keyboard_holds_across_decisions_and_expires_during_slow_search():
    now, focus, events = [1.0], [True], []
    lease = KeyLease(lambda: focus[0], lambda key, down: events.append((key, down)), lambda: now[0])
    row = dict(
        phase="following",
        vision="matched",
        latency_ms=40.0,
        pedal="throttle",
        terminal_brake=False,
        steering=-0.1,
    )
    lease.refresh(row, 0.96)
    assert events == [("A", True), ("W", True)]
    now[0] += 0.09
    lease.tick()
    assert events[-1] == ("A", False)
    now[0] += 0.11
    lease.refresh(dict(row, steering=0.0), 1.16)
    assert events.count(("W", True)) == 1 and ("W", False) not in events
    now[0] = 1.52
    lease.tick()
    assert events[-1] == ("W", False)
    lease.refresh(dict(row, latency_ms=275), 1.25)
    assert not lease.held
    lease.refresh(row, 1.50)
    focus[0] = False
    lease.tick()
    assert not lease.held and lease.stopped
    focus[0] = True
    lease.refresh(row, 1.52)
    assert not lease.held


def test_delayed_delivery_cannot_extend_throttle_even_if_reported_processing_was_fast():
    now, events = [1.0], []
    lease = KeyLease(lambda: True, lambda key, down: events.append((key, down)), lambda: now[0])
    row = dict(
        phase="following",
        vision="matched",
        latency_ms=25,
        pedal="throttle",
        terminal_brake=False,
        steering=0.0,
    )
    lease.refresh(row, 0.99)
    now[0] = 1.32
    lease.refresh(row, 1.01)
    assert events == [("W", True), ("W", False)]


def test_keep_existing_capacity_and_refuse_ambiguous_override():
    original = "[IPL]\n# Buildings = 10\nBuildings = 90 ; keep\nDummies = 10\n\n[Other]\nx = 4\n"
    needs = {
        "IPL": {"Buildings": 75, "Dummies": 20},
        "IMG LIMITS": {"Max number of IMG archives": 15},
    }
    merged = merge_limits(original, needs)
    assert "Buildings = 90 ; keep" in merged and "Dummies = 20" in merged
    assert "[Other]\nx = 4" in merged and "[IMG LIMITS]\nMax number of IMG archives = 15" in merged
    assert merge_limits(merged, needs) == merged
    with pytest.raises(ValueError, match="duplicate"):
        merge_limits("[IPL]\nBuildings=9\nBuildings=25\n", needs)


def test_rebind_only_conflicts_and_reject_exhaustion():
    models = {"a": 1000, "b": 1001, "c": 1002}
    assert allocate(models, {1000, 1003}) == {"a": 1004, "b": 1001, "c": 1002}
    with pytest.raises(ValueError, match="16-bit"):
        allocate(models, set(range(1000, 32768)))


def test_visual_transfers_require_measured_changes_and_only_one_press_each():
    paths = [[[0, -4, 0], [0, 0, 0]], [[0, 0, 0], [12, 0, 0]], [[12, 0, 0], [12, 4, 0]]]
    state = MixedJourney(paths)
    clock = 0.0
    presses = []
    reset = []

    def sample(x, y, heading=(0, 1), phase="following", age=15):
        nonlocal clock
        clock += 0.20
        rot = np.eye(3)
        rot[2] = [*heading, 0]
        row = dict(
            phase=phase,
            vision="matched",
            pedal="throttle",
            steering=0.1,
            terminal_brake=False,
            latency_ms=age,
            capture_s=clock,
        )
        driving = state.stage == "drive"
        state.step(row, (np.array([x, y, 1.5]), rot, 0, 45, 0.4), lambda: reset.append(clock))
        row["drive_enabled"] = driving and state.stage == "drive"
        keys = desired_keys(row)
        if "F" in keys:
            presses.append(clock)
        return keys

    sample(0, -4)
    assert sample(0, -4) == {"W"}
    for y in (-3, -2, -1, -1, -1, -1, -1, -1):
        sample(0, y)
    assert state.stage == "boarding" and len(presses) == 1
    for _ in range(9):
        assert not sample(0, -1)
    for _ in range(9):
        sample(0.1, 0, (1, 0))
    assert state.stage == "drive" and len(reset) == 1
    for x in range(1, 13):
        sample(x, 0, (1, 0))
    for _ in range(9):
        sample(12, 0, (1, 0), phase="arrived")
    assert state.stage == "exiting" and len(presses) == 2
    for _ in range(10):
        sample(12, 1, (0, 1))
    assert state.stage == "depart"
    for y in (2, 3, 4, 4, 4, 4, 4, 4):
        sample(12, y)
    assert state.stage == "goal_observed" and len(presses) == 2


@pytest.mark.parametrize("hfov", [75.0, 102.0, 115.58])
def test_native_lens_identifies_camera_and_rejects_single_plane(hfov):
    rng = np.random.default_rng(726)
    w, h = 768, 432
    f = w / (2 * np.tan(np.deg2rad(hfov) / 2))
    k = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1.0]], float)
    depth = rng.uniform(7, 19, 240)
    points = np.column_stack(
        (
            rng.uniform(-0.44 * w, 0.44 * w, 240) * depth / f,
            rng.uniform(-0.44 * h, 0.44 * h, 240) * depth / f,
            depth,
        )
    ).astype("float32")
    px = cv2.projectPoints(points, np.zeros(3), np.zeros(3), k, None)[0][:, 0, :]
    px += rng.normal(0, 0.2, px.shape).astype("float32")
    assert abs(focal_from_map(points, px, w, h) - hfov) < 1.0
    assert abs(stationary_focal(points, px, w, h) - hfov) < 1.0
    held = (np.floor(px[:, 0] / 42) + np.floor(px[:, 1] / 38)).astype(int) % 4 == 0
    bad = points.copy()
    bad[held] = bad[held][::-1]
    assert stationary_focal(bad, px, w, h) is None
    points[:, 2] = 10
    flat = cv2.projectPoints(points, np.zeros(3), np.zeros(3), k, None)[0][:, 0, :]
    assert focal_from_map(points, flat, w, h) is None


def test_long_walk_uses_nearby_floor_when_endpoint_is_uphill():
    paths = [[[0, 0, 0], [0, 30, 4]], [[0, 30, 4], [20, 30, 4]], [[20, 30, 4], [20, 35, 4]]]
    state = MixedJourney(paths)
    rot = np.eye(3)
    rot[2] = [0, 1, 0]
    for i in range(3):
        eye = np.array([0.0, i * 0.1, 1.5 + i * 0.1 * 4 / 30])
        row = dict(phase="waiting", vision="matched", latency_ms=35, capture_s=i * 0.2)
        state.step(row, (eye, rot, i * 0.1, 60, 0.4), lambda: None)
    assert state.saw_start and row["keys"] == ["W"]
