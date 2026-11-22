import math
import threading
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from scripts.pilot.world_map_lab import world_scene_acquisition as acquisition
from scripts.pilot.world_map_lab.render_world_search_views import candidate_regions, select_sites
from scripts.pilot.world_map_lab.verify_world_scene_candidates import consistent_views, latest_confirmed_view
from scripts.pilot.world_map_lab.world_scene_acquisition import (
    WorldAcquisition,
    material_regions,
    same_view,
)
from scripts.pilot.world_map_lab.world_scene_retrieval import infer_rotations


@pytest.mark.parametrize(("phase", "foreground"), [
    ("global_search", "collecting_views"), ("verifying_geometry", "verifying_geometry"),
    ("tracking", "collecting_views"),
])
def test_camera_pauses_during_geometry_but_can_collect_during_retrieval(phase, foreground):
    search = WorldAcquisition.__new__(WorldAcquisition)
    search.lock = threading.Lock()
    search.phase = phase
    search.bank = object()
    search.samples = []
    search.in_flight = []

    assert search.status()["phase"] == phase
    awaiting = search.status(seeking_view=True)
    assert awaiting["phase"] == foreground
    assert awaiting["computePhase"] == phase
    assert awaiting["tracking"]
    search.in_flight = [None] * 4
    assert search.status(seeking_view=True)["phase"] == phase
    search.samples = [None] * 10
    assert search.status(seeking_view=True)["phase"] == phase


def test_survey_selects_real_road_faces_on_both_decks():
    faces = np.zeros(3, dtype=[("vertices", "i4"), ("xyz", "f4", (6, 3))])
    for f, (x, z) in zip(faces, [(2, 0), (35, 0), (35, 8)], strict=True):
        f["vertices"] = 3
        f["xyz"][:3] = [[x, 30, z], [x + 2, 30, z], [x + 1, 33, z]]
        f["xyz"][3:] = 1000
    assert select_sites(faces, 64) == [[36, 31, 1.45], [36, 31, 9.45]]


def test_camera_sweep_recovers_lens_and_relative_bearing_without_a_world_position():
    rng = np.random.default_rng(603)
    im = rng.integers(0, 255, (360, 640), dtype=np.uint8)
    im = cv2.cvtColor(cv2.GaussianBlur(im, (3, 3), 0.7), cv2.COLOR_GRAY2BGR)
    intrinsic = np.array([[204, 0, 319.5], [0, 204, 179.5], [0, 0, 1.0]])
    views = []
    for angle in (0, 0.28, 0.52):
        c, s = math.cos(angle), math.sin(angle)
        rotation = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
        views.append(
            cv2.warpPerspective(im, intrinsic @ rotation @ np.linalg.inv(intrinsic), (640, 360))
        )
    groups, focal = infer_rotations(views)
    assert focal == pytest.approx(204, abs=8)
    assert len(groups) == 1 and groups[0][2] == pytest.approx(0.52, abs=0.025)


def test_parked_stream_needs_independent_source_baselines_and_agreement():
    a = dict(
        frame=0,
        delta=0,
        site=7,
        sourceEye=[1, 2, 3],
        pose=dict(eye=[4, 5, 6], supports=100, heading=0.2),
    )
    b = dict(a, site=8, sourceEye=[12, 2, 3])
    assert consistent_views([a, b]) == [a["pose"], b["pose"]]
    assert not consistent_views([a, dict(b, sourceEye=[3, 2, 3])])
    assert not consistent_views([a, dict(b, pose=dict(b["pose"], eye=[5, 5, 6]))])
    assert not consistent_views([a, dict(b, pose=dict(b["pose"], supports=38))])


def test_handoff_uses_latest_agreed_view_even_when_the_first_has_more_matches():
    a = dict(frame=0, delta=0, pose=dict(eye=[4, 5, 6], heading=0.2, supports=100))
    b = dict(frame=3, delta=0.8, pose=dict(eye=[4, 5, 6], heading=1.0, supports=42))
    outlier = dict(frame=4, delta=0.5, pose=dict(eye=[4, 15, 6], heading=0.7, supports=210))
    rows = [a, b, outlier]
    assert latest_confirmed_view(rows, consistent_views(rows)) == b["pose"]
    assert latest_confirmed_view(rows, []) is None


def test_global_worker_never_exposes_a_cached_fix_on_an_unrecognized_frame():
    worker = WorldAcquisition.__new__(WorldAcquisition)
    worker.lock = threading.Lock()
    worker.collect = lambda *_: None
    worker.bank = SimpleNamespace(locate_features=lambda *_: None, locate_near_verified_view=lambda *_: None)
    frame = np.zeros((360, 640), np.uint8)
    assert worker.observe(b"frame", frame, (None, None)) is None
    pose = dict(eye=[1, 2, 3], heading=0, supports=80)
    worker.bank = SimpleNamespace(locate_features=lambda *_: pose, covers=lambda _: False)
    assert worker.observe(b"frame", frame, (None, None)) is None
    worker.bank.covers = lambda _: True
    assert worker.observe(b"frame", frame, (None, None)) == pose

    # A dense, geometrically confirmed reference still requires a fresh camera match.
    worker.bank.locate_features = lambda *_: None
    worker.bank.locate_near_verified_view = lambda current: pose if current is frame else None
    assert worker.match_verified_view(frame) == pose
    assert worker.match_verified_view(frame.copy()) is None


def test_local_animation_and_uniform_lighting_do_not_count_as_camera_rotation():
    rng = np.random.default_rng(11)
    before = rng.integers(15, 220, size=(36, 64), dtype=np.int16)
    after = before + 12
    after[:, :16] = 0
    assert same_view(before, after)
    assert not same_view(before, np.roll(before, 7, axis=1))


def test_shift_across_a_thin_horizon_is_a_distinct_view():
    first = np.full((36, 64), 100, dtype=np.int16)
    second = first.copy()
    second[12:24, 8:40] += 15
    assert not same_view(first, second)

    second = first.copy()
    second[12:24, 8:24] += 15
    assert same_view(first, second)


def test_single_view_search_starts_early_and_keeps_new_views_during_a_job(tmp_path, monkeypatch):
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    (gallery / "survey.json").write_text('{"revision":"test"}')
    config = tmp_path / "config.json"
    config.write_text("{}")
    monkeypatch.setattr(acquisition, "read_config", lambda _: {"gallery": gallery})
    now = [0.0]
    monkeypatch.setattr(acquisition.time, "monotonic", lambda: now[0])
    jobs = []
    monkeypatch.setattr(
        acquisition.threading,
        "Thread",
        lambda *, target, args, daemon: SimpleNamespace(start=lambda: jobs.append(args[0])),
    )
    worker = WorldAcquisition(config, tmp_path, "unused", "test")
    raw_first = np.random.default_rng(15).integers(0, 255, (36, 64), dtype=np.uint8)
    before = cv2.resize(raw_first, (1920, 1080), interpolation=cv2.INTER_NEAREST)
    after = np.roll(before, 205, axis=1)

    def frame(t, pixels):
        now[0] = t
        _, jpeg = cv2.imencode(".jpg", pixels)
        worker.collect(jpeg.tobytes(), pixels)

    frame(0, before)
    frame(3, before)
    assert not jobs
    frame(4, before)
    assert len(jobs) == 1 and len(jobs[0]) == 1
    frame(5, after)
    frame(6, before)
    assert len(worker.samples) == 1 and len(jobs) == 1
    worker.searched = worker.in_flight
    worker.in_flight = []
    worker.busy = False
    frame(9, before)
    assert len(jobs) == 2 and len(jobs[1]) == 1
    assert jobs[0][0] != jobs[1][0]


def test_material_proposals_keep_world_candidates_and_bind_to_the_image_batch():
    coarse = {
        "revision": "world",
        "frameDigests": ["image-a"],
        "results": [{"frames": [0], "candidates": [{"eye": [31, 42, 8]}]}],
    }
    cues = {
        "revision": "world",
        "frames": [{"sha256": "image-a"}],
        "areas": [
            {"x": 9, "y": 12, "materials": 1},
            {"x": 31, "y": 34, "materials": 2},
        ],
    }
    merged = material_regions(coarse, cues, [[1, 2, 3], [30, 40, 8]])
    assert merged["results"][0]["candidates"] == [
        {"eye": [31, 34, 8], "source": "material-correspondences"},
        {"eye": [31, 42, 8]},
    ]
    assert len(coarse["results"][0]["candidates"]) == 1
    cues["frames"][0]["sha256"] = "image-b"
    with pytest.raises(ValueError, match="image|RGB"):
        material_regions(coarse, cues, [[1, 2, 3]])


def test_refinement_budget_goes_to_distinct_supported_regions():
    def group(n, xs):
        return dict(
            frames=list(range(n)),
            distinctDirections=n,
            candidates=[dict(eye=[x, 0, 2]) for x in xs],
        )

    survey = dict(results=[group(1, [5000]), group(3, [10, 240]), group(4, [8, 120])])
    assert candidate_regions(survey, 3) == [[8, 0, 2], [120, 0, 2], [240, 0, 2]]
    assert candidate_regions(dict(results=[group(1, [5000])]), 3) == [[5000, 0, 2]]
