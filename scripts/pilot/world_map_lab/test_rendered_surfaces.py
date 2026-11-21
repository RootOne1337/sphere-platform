"""Check that a camera ray is matched to the closest original model in world coordinates."""

import sqlite3

import numpy as np
from scipy.spatial.transform import Rotation

from scripts.pilot.world_map_lab.check_rendered_surfaces import (
    ExteriorScene,
    background_evidence,
    sky_gradient,
)


def test_nearest_transformed_mesh_outside_pivot(monkeypatch):
    with sqlite3.connect(":memory:") as db:
        db.executescript(
            "create table spatial(id,minx,maxx,miny,maxy,minz,maxz);"
            "create table instance(id,model,x,y,z,qx,qy,qz,qw);"
            "create table model(id,name);"
        )
        scene = ExteriorScene(db)
        vertices = np.array([[100, 0, 0], [102, 0, 0], [100, 2, 0]], dtype=float)
        monkeypatch.setattr(
            scene,
            "triangles",
            lambda _: (vertices[:1], vertices[1:2] - vertices[:1], vertices[2:] - vertices[:1]),
        )
        quat = Rotation.from_euler("z", 90, degrees=True).as_quat()
        for ident, altitude in [(1, 0.0), (2, 3.0)]:
            db.execute("insert into model values(?,?)", (ident, str(ident)))
            db.execute(
                "insert into instance values(?,?,?,?,?,?,?,?,?)",
                (ident, ident, 10, 20, altitude, *quat),
            )
            db.execute(
                "insert into spatial values(?,?,?,?,?,?,?)",
                (ident, 8, 10, 120, 122, altitude, altitude),
            )
        eye = np.array([9.5, 120.5, 10.0])
        down = np.array([0, 0, -1])
        assert scene.first_hit(eye, down, 20) == {"model": "2", "rangeM": 7.0}
        assert scene.first_hit(eye, down, 6) is None
        assert scene.first_hit(eye, -down, 20) is None


def test_asphalt_texture_is_distinct_from_sky_of_the_same_colour():
    baseline = np.full((37, 3), 60.0)
    sky = np.full((37, 13, 3), 60)
    asphalt = sky.copy()
    asphalt[:, ::2] -= 4
    assert background_evidence(sky, baseline) == (1.0, 1.0)
    colour, uniform = background_evidence(asphalt, baseline)
    assert colour == 1.0 and uniform < 0.7


def test_timecycle_sky_gradient_requires_colour_order_and_spatial_uniformity():
    rows = np.column_stack((np.full(37, 60), np.linspace(116, 108, 37), np.linspace(170, 155, 37)))
    patch = np.repeat(rows[:, None, :], 13, axis=1)
    assert sky_gradient(patch, 1.0)
    assert not sky_gradient(patch[::-1], 1.0)
    assert not sky_gradient(patch[..., ::-1], 1.0)
    assert not sky_gradient(patch, 0.75)
