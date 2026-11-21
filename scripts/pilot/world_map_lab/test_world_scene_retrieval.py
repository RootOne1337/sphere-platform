import math
import threading
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from scripts.pilot.world_map_lab.render_world_search_views import candidate_regions, select_sites
from scripts.pilot.world_map_lab.verify_world_scene_candidates import consistent_views
from scripts.pilot.world_map_lab.world_scene_acquisition import WorldAcquisition
from scripts.pilot.world_map_lab.world_scene_retrieval import infer_rotations


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


def test_global_worker_never_exposes_a_cached_fix_on_an_unrecognized_frame():
    worker = WorldAcquisition.__new__(WorldAcquisition)
    worker.lock = threading.Lock()
    worker.busy = True
    worker.bank = SimpleNamespace(locate_features=lambda *_: None)
    frame = np.zeros((360, 640), np.uint8)
    assert worker.observe(b"frame", frame, (None, None)) is None
    pose = dict(eye=[1, 2, 3], heading=0, supports=80)
    worker.bank = SimpleNamespace(locate_features=lambda *_: pose, covers=lambda _: False)
    assert worker.observe(b"frame", frame, (None, None)) is None
    worker.bank.covers = lambda _: True
    assert worker.observe(b"frame", frame, (None, None)) == pose


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
