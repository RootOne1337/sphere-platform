from collections import namedtuple
from types import SimpleNamespace

from scripts.pilot.world_map_lab.ariane_geometry import restore_split_materials


Face = namedtuple("Face", "a b c material")


def test_bin_mesh_repairs_materials_with_matching_face_multiplicity():
    faces = [Face(0, 1, 2, 0), Face(0, 2, 3, 0)]
    splits = [Face(3, 2, 0, 1), Face(1, 0, 2, 0)]
    mesh = SimpleNamespace(triangles=faces, materials=[None, None], extensions={"mat_split": splits})
    assert restore_split_materials(mesh).triangles == [faces[0], Face(0, 2, 3, 1)]

    mesh.triangles = faces
    mesh.extensions["mat_split"] = [splits[0], Face(0, 1, 3, 0)]
    assert restore_split_materials(mesh).triangles is faces
