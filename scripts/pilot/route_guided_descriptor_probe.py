"""Offline refinement of a geometrically verified current-frame descriptor pose."""

from __future__ import annotations

import math

from motor_worker.route_descriptor_recovery import ReferenceLKRecoveryLocalizer
from motor_worker.route_localization import SIZE, trace_step_scale


def refine_descriptor_pose(localizer, seed, query_xy, query_desc, *, still_current=lambda: True):
    """Keep a stock winner unless independent image matches strengthen its PnP."""
    np = localizer.np
    center, rotation, count, _, seed_ids, seed_xy = seed
    nearest = localizer._nearest(center)
    if nearest is None or len(query_xy) > 2048 or len(seed_ids) != count:
        return seed
    seed_id_set = set(map(int, seed_ids))
    seed_xy_set = {tuple(point) for point in seed_xy}
    if len(seed_id_set) != count or len(seed_xy_set) != count:
        return seed

    segment = nearest[0]
    visible = localizer.visibility[max(0, segment - 5):segment + 7]
    ids = np.flatnonzero(np.any(visible, axis=0))
    if not 1 <= len(ids) <= 1024:
        return seed
    camera = (localizer.xyz[ids] - center) @ rotation.T
    front = camera[:, 2] > 1e-5
    ids, camera = ids[front], camera[front]
    homogeneous = camera @ localizer.K.T
    projected = homogeneous[:, :2] / homogeneous[:, 2:]

    proposed = []
    for index, point in enumerate(query_xy):
        if index % 64 == 0 and not still_current():
            return seed
        xy = tuple(point)
        if xy in seed_xy_set or not (0 <= point[0] < SIZE[0] and 0 <= point[1] < SIZE[1]):
            continue
        nearby = ids[np.sum((projected - point) ** 2, axis=1) <= 36.]
        if not len(nearby):
            continue
        distances = np.linalg.norm(localizer.descriptors[nearby] - query_desc[index], axis=1)
        order = np.argsort(distances, kind="stable")
        best = order[0]
        distance = float(distances[best])
        if not math.isfinite(distance) or distance > .6:
            continue
        if len(order) > 1 and not distance < .75 * distances[order[1]]:
            continue
        point_id = int(nearby[best])
        if point_id not in seed_id_set:
            proposed.append((distance, index, point_id))

    combined_ids, combined_xy = list(seed_ids), list(seed_xy)
    for _, index, point_id in sorted(proposed):
        point = query_xy[index]
        xy = tuple(point)
        if point_id in seed_id_set or xy in seed_xy_set:
            continue
        seed_id_set.add(point_id)
        seed_xy_set.add(xy)
        combined_ids.append(point_id)
        combined_xy.append(point)
        if len(combined_ids) - count == 64:
            break
    if len(combined_ids) <= count or not still_current():
        return seed

    ids = np.asarray(combined_ids, dtype=int)
    image = np.asarray(combined_xy)
    verified = localizer._verify_correspondences(localizer.xyz[ids], image)
    if verified is None or not still_current():
        return seed
    new_center, new_rotation, new_count, new_error, mask = verified
    if new_count <= count or not mask[:count].all():
        return seed
    max_distance = .05 * trace_step_scale(localizer.lengths)
    rotation_agreement = (np.trace(new_rotation @ rotation.T) - 1.) / 2.
    if (np.linalg.norm(new_center - center) > max_distance
            or rotation_agreement < math.cos(math.radians(2.))):
        return seed
    return new_center, new_rotation, new_count, new_error, ids[mask], image[mask]


class GuidedDescriptorLocalizer(ReferenceLKRecoveryLocalizer):
    """Exercise refinement after the reviewed fallback on the same observation."""

    verification_policy = ReferenceLKRecoveryLocalizer.verification_policy + ":guided_probe_6px_v1"

    def _solve_subset(self, pixels, descriptors, indices):
        self._probe_query = (pixels, descriptors)
        return super()._solve_subset(pixels, descriptors, indices)

    def _solve_descriptors(self):
        self._probe_query = None
        try:
            seed = super()._solve_descriptors()
            if seed is None or self._probe_query is None or not self._has_receiver_budget(.02):
                return seed
            result = refine_descriptor_pose(self, seed, *self._probe_query,
                                            still_current=lambda: self._has_receiver_budget(0))
            self.last_diagnostic.update(guidedSeedInliers=seed[2], guidedResultInliers=result[2])
            return result
        finally:
            self._probe_query = None
