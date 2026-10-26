import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from scripts.pilot.preview_route_trace import (
    pose_at,
    project_ahead,
    project_surface_candidates,
    run,
    validate_geometry,
)


def camera(ticks, x=0, z=0):
    return dict(
        ticks_90k=ticks,
        center=[x, 0, z],
        camera_to_world=[[1, 0, 0, x], [0, 1, 0, 0], [0, 0, 1, z]],
        intrinsics=dict(width=960, height=540, fx=500, fy=500, cx=480, cy=270),
    )


class TracePreviewTests(unittest.TestCase):
    def test_surface_segments_are_clipped_to_screen_and_stop_at_missing_support(self):
        cameras = [camera(i * 30000, z=i) for i in range(5)]
        rows = [
            dict(
                ticks=c["ticks_90k"],
                accepted=True,
                normal=[0, -1, 0],
                offset=1,
                centerOnCandidatePlane=[0, 1, i],
            )
            for i, c in enumerate(cameras)
        ]
        result = project_surface_candidates(cameras, rows, 0)
        self.assertGreaterEqual(len(result["segments"]), 2)
        self.assertTrue(
            all(0 <= v < 1 for pair in result["segments"] for point in pair for v in point)
        )
        rows[2]["accepted"] = False
        result = project_surface_candidates(cameras, rows, 0)
        self.assertEqual(result["segments"], [])
        self.assertEqual(result["reason"], "stopped_at_missing_surface_support")

    def test_surface_discontinuity_and_wrong_camera_binding_cannot_create_a_join(self):
        cameras = [camera(i * 30000, z=i) for i in range(5)]
        rows = [
            dict(
                ticks=c["ticks_90k"],
                accepted=True,
                normal=[0, -1, 0],
                offset=1,
                centerOnCandidatePlane=[0, 1, i],
            )
            for i, c in enumerate(cameras)
        ]
        rows[2]["centerOnCandidatePlane"] = [999, 1, 2]
        self.assertEqual(
            project_surface_candidates(cameras, rows, 0)["reason"],
            "stopped_at_surface_discontinuity",
        )
        rows[1]["ticks"] += 1
        with self.assertRaises(ValueError):
            project_surface_candidates(cameras, rows, 0)

    def test_pose_interpolation_is_in_world_and_never_extrapolates(self):
        import numpy as np

        cameras = [camera(0), camera(90000, 2, 4)]
        rotation, center, source = pose_at(cameras, 45000)
        self.assertTrue(np.allclose(center, [1, 0, 2]))
        self.assertTrue(np.allclose(rotation.T @ rotation, np.eye(3)))
        self.assertEqual(source, "same_recording_interpolated_pose")
        self.assertIsNone(pose_at(cameras, -1))
        self.assertIsNone(pose_at(cameras, 90001))
        self.assertEqual(pose_at(cameras, 90000)[2], "reconstruction_reference_pose")

    def test_rotation_uses_so3_instead_of_averaging_matrix_entries(self):
        import numpy as np

        a, b = camera(0), camera(90000)
        b["camera_to_world"] = [[0, 0, 1, 0], [0, 1, 0, 0], [-1, 0, 0, 0]]
        R, _, _ = pose_at([a, b], 45000)
        self.assertAlmostEqual(np.linalg.det(R), 1)
        self.assertAlmostEqual(R[0, 2], 2**-0.5)

    def test_unknown_intervals_and_behind_camera_never_get_a_connected_line(self):
        self.assertIsNone(pose_at([camera(0), camera(180000, z=2)], 90000))
        self.assertEqual(project_ahead([camera(0), camera(90000, z=-2)], 0)["points"], [])
        cameras = [camera(0), camera(30000, z=1), camera(60000, x=100, z=2), camera(90000, z=3)]
        self.assertEqual(len(project_ahead(cameras, 0)["points"]), 1)

    def test_projected_future_is_derived_from_geometry_not_a_left_right_template(self):
        straight = project_ahead([camera(0), camera(45000, z=1), camera(90000, z=2)], 0)
        turn = project_ahead([camera(0), camera(45000, x=0.2, z=1), camera(90000, x=0.6, z=2)], 0)
        self.assertEqual(straight["points"], [[0.5, 0.5], [0.5, 0.5]])
        self.assertGreater(turn["points"][-1][0], turn["points"][0][0])

    def test_changed_source_or_invalid_camera_is_refused(self):
        import hashlib

        capture = SimpleNamespace(originals={"manifest.json": b"original"}, geometry=(960, 540))
        geometry = dict(
            schema="sphere-recovered-scene-v1",
            cameras=[camera(0), camera(90000, z=1)],
            source_manifest_sha256=hashlib.sha256(b"original").hexdigest(),
        )
        self.assertEqual(len(validate_geometry(geometry, capture)), 2)
        geometry["cameras"][1]["camera_to_world"][0][0] = 2
        with self.assertRaises(ValueError):
            validate_geometry(geometry, capture)
        geometry["cameras"][1] = camera(90000, z=1)
        geometry["source_manifest_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            validate_geometry(geometry, capture)

    def test_actual_mp4_preserves_input_timestamps_without_frame_synthesis(self):
        import av
        import numpy as np

        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "input"
            source.mkdir()
            (source / "manifest.json").write_bytes(b"original")
            (source / "video.h264").write_bytes(b"source_not_modified")
            capture = SimpleNamespace(
                root=source,
                originals={"manifest.json": b"original"},
                geometry=(960, 540),
                frames=[{}, {}, {}, {}, {}],
            )
            geometry = dict(
                schema="sphere-recovered-scene-v1",
                cameras=[camera(0), camera(45000, z=1), camera(90000, z=2)],
                source_manifest_sha256=hashlib.sha256(b"original").hexdigest(),
            )
            geometry_path = root / "geometry.json"
            geometry_path.write_text(json.dumps(geometry))

            def decoded(_capture):
                for index, ticks in enumerate((0, 1530, 3060, 45000, 90000)):
                    yield (
                        dict(index=index, relative_ticks_90k=ticks),
                        av.VideoFrame.from_ndarray(
                            np.zeros((540, 960, 3), np.uint8), format="rgb24"
                        ),
                    )

            module = "scripts.pilot.preview_route_trace"
            with (
                patch(module + ".collect", return_value={}),
                patch(module + ".evaluate", return_value=[]),
                patch(module + ".validate_browser", return_value=capture),
                patch(module + ".decoded_browser", side_effect=decoded),
            ):
                report = run(source, geometry_path, root / "preview")
            with av.open(str(root / "preview/preview.mp4")) as video:
                frames = list(video.decode(video=0))
            self.assertEqual(len(frames), 5)
            self.assertEqual(
                [float(frame.pts * frame.time_base) for frame in frames], [0, 0.017, 0.034, 0.5, 1]
            )
            self.assertEqual(report["syntheticFrames"], 0)
            self.assertFalse(report["groundRoute"])
            self.assertFalse(report["liveLocalization"])
            self.assertEqual((source / "video.h264").read_bytes(), b"source_not_modified")


if __name__ == "__main__":
    unittest.main()
