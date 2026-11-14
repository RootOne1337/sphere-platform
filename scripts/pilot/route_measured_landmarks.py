"""Bind runtime descriptors to measured native 3D tracks, without triangulation.

This optional offline builder has no file, network, executor or device authority.
Its output is compatible with route_landmark_builder's candidate rows, but it
does not approve the supplied cameras or qualify a map for navigation.
"""
from __future__ import annotations

import math
import time
from collections import Counter, defaultdict

MAX_VIEWS = 256
MAX_NATIVE_POINTS = 100_000
MAX_NATIVE_OBSERVATIONS = 2_000_000
MAX_NATIVE_IMAGE_ROWS = 2_000_000
MAX_RUNTIME_FEATURES_PER_VIEW = 4096
MAX_SPATIAL_COMPARISONS = 8_000_000
MAX_BUILD_SECONDS = 60
SIZE = (960, 540)
ASSOCIATION_RADIUS_PX = 1.
MAX_REPROJECTION_PX = 3.
MAX_DESCRIPTOR_DISTANCE = .7
MIN_PARALLAX_DEGREES = 1.
MIN_VIEWS = 3


def _associate(measured, runtime, *, checkpoint, comparisons):
    """Reciprocal, uniquely closest pixels; reject spatial ties, never greedily alias."""
    import numpy as np

    cells = defaultdict(list)
    for j, xy in enumerate(runtime):
        cells[(math.floor(xy[0]), math.floor(xy[1]))].append(j)
    left = [None] * len(measured)
    right = [None] * len(runtime)
    left_tie = np.zeros(len(measured), bool)
    right_tie = np.zeros(len(runtime), bool)
    epsilon = 1e-12
    for i, xy in enumerate(measured):
        cx, cy = math.floor(xy[0]), math.floor(xy[1])
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in cells.get((cx + dx, cy + dy), ()):
                    comparisons[0] += 1
                    if comparisons[0] > MAX_SPATIAL_COMPARISONS:
                        raise ValueError('measured_landmark_spatial_comparison_quota')
                    if comparisons[0] % 4096 == 0:
                        checkpoint()
                    delta = runtime[j] - xy
                    distance = float(delta @ delta)
                    if distance > ASSOCIATION_RADIUS_PX ** 2:
                        continue
                    if left[i] is None or distance < left[i][0] - epsilon:
                        left[i] = (distance, j)
                        left_tie[i] = False
                    elif abs(distance - left[i][0]) <= epsilon:
                        left_tie[i] = True
                    if right[j] is None or distance < right[j][0] - epsilon:
                        right[j] = (distance, i)
                        right_tie[j] = False
                    elif abs(distance - right[j][0]) <= epsilon:
                        right_tie[j] = True
    return [(i, best[1], math.sqrt(best[0])) for i, best in enumerate(left)
            if best is not None and not left_tie[i] and not right_tie[best[1]]
            and right[best[1]][1] == i]


def build(reconstruction, ordered_images, observations, matrices, K, *, checkpoint):
    """Return native XYZ + actual runtime descriptor medoids and an audit receipt.

    ``observations`` is the unmodified output of runtime ``extract_features``
    for each ordered reference image: (OpenCV 960x540 pixels, RootSIFT float128).
    ``matrices`` and K must describe the very same native cameras in that pixel
    convention. Source row IDs are checked against reciprocal native tracks.

    No projected feature is used as a detected measurement: each attachment
    needs an actual uniquely closest runtime detection, reprojection in both
    measurement sets, >=3 distinct views, parallax, and descriptor consistency.
    """
    import numpy as np

    from scripts.pilot.camera_pixel_conventions import colmap_calibration_to_opencv

    started = time.monotonic()

    def bounded():
        if time.monotonic() - started > MAX_BUILD_SECONDS:
            raise ValueError('measured_landmark_time_quota')
        checkpoint()

    bounded()
    if (not 3 <= len(ordered_images) <= MAX_VIEWS or len(observations) != len(ordered_images)
            or len(matrices) != len(ordered_images) or len(reconstruction.cameras) != 1
            or len(reconstruction.points3D) > MAX_NATIVE_POINTS):
        raise ValueError('measured_landmark_input_quota')
    camera = next(iter(reconstruction.cameras.values()))
    if camera.model_name not in {'PINHOLE', 'SIMPLE_PINHOLE'}:
        raise ValueError('measured_landmark_camera_model')
    source_size = (int(camera.width), int(camera.height))
    if source_size[0] * SIZE[1] != source_size[1] * SIZE[0]:
        raise ValueError('measured_landmark_camera_aspect')
    expected_K = colmap_calibration_to_opencv(camera.calibration_matrix(), source_size, SIZE)
    K = np.asarray(K, dtype=np.float64)
    if K.shape != (3, 3) or not np.allclose(K, expected_K, rtol=0, atol=1e-9):
        raise ValueError('measured_landmark_camera_pixel_convention')
    scale = np.asarray(SIZE, np.float64) / source_size
    by_id = {im.image_id: n for n, im in enumerate(ordered_images)}
    if len(by_id) != len(ordered_images) or set(by_id) != set(reconstruction.reg_image_ids()):
        raise ValueError('measured_landmark_image_namespace')
    native_image_rows = sum(len(reconstruction.images[im.image_id].points2D) for im in ordered_images)
    if native_image_rows > MAX_NATIVE_IMAGE_ROWS:
        raise ValueError('measured_landmark_native_image_row_quota')
    matrices = [np.asarray(m, np.float64) for m in matrices]
    pixels, descriptors, centers = [], [], []
    for view, image in enumerate(ordered_images):
        bounded()
        if (image.image_id not in reconstruction.images
                or reconstruction.images[image.image_id].name != image.name
                or matrices[view].shape != (3, 4) or not np.isfinite(matrices[view]).all()
                or (np.abs(matrices[view]) > 1e8).any()
                or not np.allclose(matrices[view], reconstruction.images[image.image_id].cam_from_world().matrix(), rtol=0, atol=1e-10)
                or not np.allclose(matrices[view][:, :3] @ matrices[view][:, :3].T, np.eye(3), rtol=0, atol=1e-6)):
            raise ValueError('measured_landmark_pose_binding')
        xy, desc = (np.asarray(value) for value in observations[view])
        if (xy.ndim != 2 or xy.shape[1] != 2 or desc.shape != (len(xy), 128)
                or len(xy) > MAX_RUNTIME_FEATURES_PER_VIEW or not np.isfinite(xy).all()
                or not np.isfinite(desc).all() or (xy < 0).any()
                or (xy[:, 0] >= SIZE[0]).any() or (xy[:, 1] >= SIZE[1]).any()
                or (desc < 0).any() or (desc > 1.0001).any()
                or (np.abs(np.linalg.norm(desc, axis=1) - 1) > .001).any()):
            raise ValueError('measured_landmark_runtime_features')
        pixels.append(xy.astype(np.float64, copy=False))
        descriptors.append(desc.astype(np.float64, copy=False))
        centers.append(-matrices[view][:, :3].T @ matrices[view][:, 3])
    source_by_view = [[] for _ in ordered_images]
    native_bindings = {}
    total_observations = 0
    native_xyz = {}
    for n, (point_id, point) in enumerate(reconstruction.points3D.items()):
        if n % 256 == 0:
            bounded()
        xyz = np.asarray(point.xyz, np.float64)
        if xyz.shape != (3,) or not np.isfinite(xyz).all() or (np.abs(xyz) > 1e8).any():
            raise ValueError('measured_landmark_native_xyz')
        native_xyz[point_id] = xyz
        seen = set()
        for element in point.track.elements:
            total_observations += 1
            if total_observations > MAX_NATIVE_OBSERVATIONS:
                raise ValueError('measured_landmark_native_observation_quota')
            identity, row_id = element.image_id, element.point2D_idx
            if identity not in by_id or identity in seen:
                raise ValueError('measured_landmark_native_track_ambiguous')
            seen.add(identity)
            image = reconstruction.images[identity]
            if not 0 <= row_id < len(image.points2D):
                raise ValueError('measured_landmark_native_row_binding')
            feature = image.points2D[row_id]
            source_xy = np.asarray(feature.xy, np.float64)
            if (not feature.has_point3D() or feature.point3D_id != point_id
                    or source_xy.shape != (2,) or not np.isfinite(source_xy).all()):
                raise ValueError('measured_landmark_native_track_reciprocity')
            native_bindings[(identity, row_id)] = point_id
            # COLMAP pixel corners resize first; then OpenCV integer centers.
            measured_xy = source_xy * scale - .5
            if ((measured_xy < 0).any() or measured_xy[0] >= SIZE[0] or measured_xy[1] >= SIZE[1]):
                continue
            source_by_view[by_id[identity]].append((point_id, row_id, measured_xy))
    examined_rows = 0
    for image in ordered_images:
        bounded()
        for row_id, feature in enumerate(reconstruction.images[image.image_id].points2D):
            examined_rows += 1
            if examined_rows % 4096 == 0:
                bounded()
            if feature.has_point3D() and native_bindings.get((image.image_id, row_id)) != feature.point3D_id:
                raise ValueError('measured_landmark_native_reverse_track_reciprocity')
    associations = defaultdict(list)
    spatial_points = set()
    comparisons = [0]
    geometry_rejected = 0
    spatial_per_view = []
    for view, native in enumerate(source_by_view):
        bounded()
        xy = np.asarray([entry[2] for entry in native], np.float64).reshape(-1, 2)
        paired = _associate(xy, pixels[view], checkpoint=bounded, comparisons=comparisons)
        spatial_per_view.append(len(paired))
        for native_index, runtime_index, distance in paired:
            point_id, row_id, measured_xy = native[native_index]
            spatial_points.add(point_id)
            q = matrices[view][:, :3] @ native_xyz[point_id] + matrices[view][:, 3]
            if q[2] <= 1e-5 or not np.isfinite(q).all():
                geometry_rejected += 1
                continue
            projected = K @ q
            projected = projected[:2] / projected[2]
            measured_error = float(np.linalg.norm(projected - measured_xy))
            runtime_error = float(np.linalg.norm(projected - pixels[view][runtime_index]))
            if max(measured_error, runtime_error) > MAX_REPROJECTION_PX:
                geometry_rejected += 1
                continue
            associations[point_id].append(dict(view=view, image_id=int(ordered_images[view].image_id),
                native_row=int(row_id), runtime_index=int(runtime_index), association_px=distance,
                native_runtime_xy=measured_xy.tolist(), runtime_detected_xy=pixels[view][runtime_index].tolist(),
                measured_reprojection_px=measured_error, runtime_reprojection_px=runtime_error))
    candidates = []
    no_runtime_association = len(native_xyz) - len(spatial_points)
    rejected = Counter(no_runtime_association=no_runtime_association,
                       no_geometric_runtime_support=len(spatial_points)-len(associations))
    for n, (point_id, attached) in enumerate(associations.items()):
        if n % 128 == 0:
            bounded()
        if len(attached) < MIN_VIEWS:
            rejected['fewer_than_three_runtime_views'] += 1
            continue
        samples = np.asarray([descriptors[o['view']][o['runtime_index']] for o in attached])
        # Distances computed without an NxNx128 allocation (<=256 views).
        squared = np.sum(samples * samples, axis=1)
        pairwise = np.sqrt(np.maximum(0, squared[:, None] + squared[None, :] - 2 * samples @ samples.T))
        indices = np.arange(len(attached))
        # Every non-stable step removes >=1 actual observation. The terminal
        # descriptor is an actual medoid of the FINAL supported subset.
        for iteration in range(len(attached)):
            if iteration % 4 == 0:
                bounded()
            medoid = int(indices[np.argmin(pairwise[np.ix_(indices, indices)].sum(axis=1))])
            retained = indices[pairwise[medoid, indices] <= MAX_DESCRIPTOR_DISTANCE]
            if len(retained) < MIN_VIEWS or len(retained) == len(indices):
                indices = retained
                break
            indices = retained
        if len(indices) < MIN_VIEWS:
            rejected['descriptor_inconsistent'] += 1
            continue
        chosen = [attached[i] for i in indices]
        views = tuple(sorted(o['view'] for o in chosen))
        rays = native_xyz[point_id] - np.asarray([centers[view] for view in views])
        lengths = np.linalg.norm(rays, axis=1)
        if (lengths <= 1e-8).any():
            rejected['parallax'] += 1
            continue
        rays = rays / lengths[:, None]
        if float((rays @ rays.T).min()) > math.cos(math.radians(MIN_PARALLAX_DEGREES)):
            rejected['parallax'] += 1
            continue
        provenance = dict(native_point_id=int(point_id), observations=sorted(chosen, key=lambda o:o['view']),
            medoid_observation=attached[medoid], maximum_descriptor_distance=float(pairwise[medoid, indices].max()))
        row = (len(chosen), tuple(float(v) for v in native_xyz[point_id]),
               samples[medoid].astype(np.float32, copy=True), views)
        candidates.append((row, provenance))
    candidates.sort(key=lambda item: (-item[0][0], item[1]['native_point_id']))
    valid = [row for row, _ in candidates]
    per_view = Counter(view for row in valid for view in row[3])
    bounded()
    report = dict(schema='sphere-measured-runtime-landmark-build-v1', method='native-track-reciprocal-runtime-pixel-association-v1',
        tracks=len(native_xyz), accepted=len(valid), rejected=len(native_xyz)-len(valid),
        native_observations=total_observations, native_image_rows=native_image_rows,
        spatial_associations=sum(spatial_per_view),
        spatial_associations_per_view=spatial_per_view, geometry_rejected_observations=geometry_rejected,
        rejected_tracks=dict(rejected), spatial_comparisons=comparisons[0],
        no_runtime_association_count=no_runtime_association,
        min_views=MIN_VIEWS, max_error_px=MAX_REPROJECTION_PX, association_radius_px=ASSOCIATION_RADIUS_PX,
        min_parallax_degrees=MIN_PARALLAX_DEGREES, maximum_descriptor_distance=MAX_DESCRIPTOR_DISTANCE,
        candidate_support_per_view=[int(per_view[i]) for i in range(len(ordered_images))],
        native_xyz_reused=True, poses_modified=False, triangulation_performed=False,
        runtime_features_rebuilt=False, pixel_coordinates='opencv_integer_centers_v1',
        pixel_transform='native_colmap_xy * runtime_size / source_size - 0.5',
        landmark_provenance=[item[1] for item in candidates], execution_qualified=False)
    return valid, report
