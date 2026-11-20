"""Regressions for startup, concurrent status readers, and short route segments."""

import json
from pathlib import Path

import numpy as np

from scripts.pilot.world_map_lab.check_journey_rgb import Lane, publish_status
from scripts.pilot.world_map_lab.journey_runs import JourneyRuns


def test_short_leg_has_nonzero_approach_speed():
    lane = Lane({"mode": "drive", "path": [[1, 1, 0], [1.63, 1, 0]]})
    stations, caps = lane.curve_limits()
    assert np.isfinite(caps).all()
    assert np.interp(0.2, stations, caps) > 0
    assert caps[-1] == 0


def test_polling_windows_reader_does_not_abort_worker(tmp_path, monkeypatch):
    replace = Path.replace
    attempts = []

    def busy(src, dest):
        attempts.append(dest)
        if len(attempts) < 3:
            raise PermissionError("previous snapshot is open")
        return replace(src, dest)

    monkeypatch.setattr(Path, "replace", busy)
    publish_status(tmp_path, "running", {"frame": 8})
    assert (
        len(attempts) == 3
        and json.loads((tmp_path / "state.json").read_bytes())["row"]["frame"] == 8
    )


def test_terminal_result_survives_locked_snapshot_and_service_restart(tmp_path, monkeypatch):
    manager = JourneyRuns(tmp_path, 8817, None)
    dest = manager.directory("test")
    dest.mkdir(parents=True)
    (dest / "route.json").write_text("{}")
    publish_status(dest, "running", {"frame": 7})

    def locked(*_):
        raise PermissionError

    monkeypatch.setattr(Path, "replace", locked)
    publish_status(dest, "arrived", {"frame": 8})
    assert manager.state("test") == {"id": "test", "state": "arrived", "row": {"frame": 8}}


def test_image_standstill_distinguishes_stationary_and_translating_textures():
    import base64

    import cv2
    import numpy as np

    from scripts.pilot.world_map_lab.check_journey_rgb import H, W, image_standstill

    image = np.random.default_rng(614).integers(0, 256, (H, W), dtype=np.uint8)

    def encode(array):
        return base64.b64encode(array.tobytes()).decode()

    depth = np.full((H, W), 12 * 128, dtype="<u2")
    previous = (encode(image), encode(depth), [1, 0, 4, 0, 0])
    camera = [1, -0.6, 4, 0, 0]
    assert image_standstill(previous, encode(image), camera, 200)
    moved = cv2.warpAffine(image, np.float32([[1, 0, -10], [0, 1, 0]]), (W, H))
    assert not image_standstill(previous, encode(moved), camera, 200)
    assert not image_standstill(previous, encode(image), [1, 0, 4, 0, 0], 200)
    assert not image_standstill(None, encode(image), camera, 200)
