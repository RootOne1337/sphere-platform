"""Regression checks for coordinate binding, pose agreement and rejecting unobservable scenes."""

import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
pytest.importorskip("av")

from scripts.pilot.world_map_lab.check_game_views import cost, edges  # noqa: E402
from scripts.pilot.world_map_lab.detail_scene_service import scene_files  # noqa: E402
from scripts.pilot.world_map_lab.indexed_landmarks import IndexedLandmarks  # noqa: E402
from scripts.pilot.world_map_lab.neighborhood_search import NeighborhoodSearch  # noqa: E402
from scripts.pilot.world_map_lab.replay_game_map import select_agreement  # noqa: E402
from scripts.pilot.world_map_lab.serve_world_navmesh import movie_range  # noqa: E402
from scripts.pilot.world_map_lab.track_landmarks import LandmarkTrack  # noqa: E402
from scripts.pilot.world_map_lab.verify_stationary_view import rendered_agreement  # noqa: E402


def test_independent_edges_prefer_aligned_facade():
    image = np.full((192, 320, 3), 120, np.uint8)
    for i in range(9, 291, 32):
        cv2.rectangle(image, (i, 37), (i + 16, 126), (225, 225, 225), 2)
    cv2.line(image, (0, 158), (306, 128), (0, 0, 0), 3)
    truth = edges(image)
    assert cost(truth, truth) < cost(truth, edges(np.roll(image, 9, axis=1)))


def test_observer_requires_points_and_disjoint_support():
    observer = IndexedLandmarks(SimpleNamespace(views=[]))
    assert observer(np.zeros((192, 320, 3), np.uint8), 0, 3) is None
    assert observer.bank(100) is None
    track = LandmarkTrack(observer.atlas)
    assert track.track(None, 0.2, 0, 3) is None
    track.points = np.zeros((50, 3))
    track.anchor = 0
    assert track.track(None, 1.01, 0, 3) is None


def test_global_proposals_must_agree_in_position_and_orientation():
    best = (np.array([0.01, 0, 0]), np.eye(3), 2.0, 55, 0.3)
    second = (np.zeros(3), np.eye(3), 2.1, 40, 0.5)
    assert select_agreement([second, best]) is best
    assert select_agreement([best, (np.ones(3), *second[1:])]) is None
    assert select_agreement([best, (second[0], np.diag([1, -1, -1]), *second[2:])]) is None
    assert select_agreement([]) is None


def test_neighborhood_retrieval_accepts_strided_features():
    rng = np.random.default_rng(180)
    desc = rng.random((1600, 128), dtype=np.float32)
    desc /= np.linalg.norm(desc, axis=1, keepdims=True)
    bank = SimpleNamespace(
        atlas=SimpleNamespace(desc=desc),
        views=[{"s": 3, "range": (0, 800)}, {"s": 19, "range": (800, 1600)}],
    )
    retrieval = NeighborhoodSearch([(bank, 1)])
    assert retrieval.suggest((None, desc[800:]), limit=1) == [12]
    assert retrieval.suggest(None) == []


def test_cannot_reset_at_a_blank_view():
    assert not rendered_agreement(None, np.zeros((216, 384, 3), np.uint8), np.zeros(3), np.eye(3))


def test_report_is_bound_to_revision_and_media_content(tmp_path):
    root = tmp_path / "first-person"
    root.mkdir()
    document = root / "report.html"
    document.write_bytes(b"<html></html>")
    sha = hashlib.sha256(document.read_bytes()).hexdigest()
    receipt = root / "published.json"
    receipt.write_text(json.dumps({"revision": "r", "files": {"report.html": sha}}))
    world = {"drive": SimpleNamespace(meta={"placementRevision": "r"})}
    assert scene_files(tmp_path, world) == {"/first-person/report.html": document}
    assert (
        scene_files(tmp_path, {"drive": SimpleNamespace(meta={"placementRevision": "other"})}) == {}
    )
    document.write_bytes(b"changed")
    assert scene_files(tmp_path, world) == {}


def test_movie_seeking():
    assert movie_range("bytes=500-", 1000) == (500, 999)
    assert movie_range("bytes=-84", 1000) == (916, 999)
    assert movie_range("bytes=0-2000", 1000) == (0, 999)
    for header in ("bytes=-0", "bytes=1000-1001", "bytes=90-1", "bytes=0-1,2-3"):
        with pytest.raises(ValueError):
            movie_range(header, 1000)
