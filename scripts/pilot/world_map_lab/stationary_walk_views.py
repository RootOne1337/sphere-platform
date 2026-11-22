"""Recover a stopped pedestrian's view from previously verified RGB/3-D observations."""

import math

import cv2
import numpy as np


class StationaryWalkViews:
    def __init__(self, bank):
        self.bank = bank
        self.detector = cv2.SIFT_create(nfeatures=900, contrastThreshold=0.018)
        self.matcher = cv2.BFMatcher(cv2.NORM_L2)
        self.references = [self.features(im) for im in bank.views]

    def features(self, gray):
        keys, desc = self.detector.detectAndCompute(gray, None)
        return np.float32([k.pt for k in keys]).reshape(-1, 2), desc

    def locate(self, gray, anchor):
        live, desc = self.features(gray)
        if desc is None or len(desc) < 24:
            return None
        proposals = []
        for view, (pixels, ref_desc) in enumerate(self.references):
            if ref_desc is None or len(ref_desc) < 24:
                continue
            neighbors = self.matcher.knnMatch(ref_desc, desc, k=2)
            matches = sorted(
                (a for a, b in neighbors if a.distance < 0.74 * b.distance),
                key=lambda m: m.distance,
            )
            unique = {m.trainIdx: m for m in reversed(matches)}
            if len(unique) < 24:
                continue
            a = pixels[[m.queryIdx for m in unique.values()]]
            b = live[list(unique)]
            transform, mask = cv2.findHomography(a, b, cv2.RANSAC, 2.2)
            if transform is None or mask is None:
                continue
            valid = mask.ravel().astype(bool)
            if (
                valid.sum() < max(24, 0.60 * len(valid))
                or np.ptp(b[valid, 0]) < 120
                or np.ptp(b[valid, 1]) < 60
            ):
                continue
            proposals.append((int(valid.sum()), view, transform))
        for _, view, transform in sorted(proposals, key=lambda item: -item[0]):
            start, end = self.bank.track_offsets[view : view + 2]
            pixels = self.bank.track_pixels[start:end]
            predicted = cv2.perspectiveTransform(pixels.reshape(-1, 1, 2), transform).reshape(-1, 2)
            width, height = gray.shape[1], gray.shape[0]
            inside = np.isfinite(predicted).all(1) & (
                (predicted > 10) & (predicted < [width - 11, height - 11])
            ).all(1)
            if np.count_nonzero(inside) < 36:
                continue
            warp = cv2.warpPerspective(self.bank.views[view], transform, (width, height))
            ref = np.ascontiguousarray(predicted[inside])
            options = dict(winSize=(17, 17), maxLevel=2)
            moved, ok, error = cv2.calcOpticalFlowPyrLK(warp, gray, ref, None, **options)
            if moved is None:
                continue
            back, again, _ = cv2.calcOpticalFlowPyrLK(gray, warp, moved, None, **options)
            if back is None:
                continue
            keep = ok.ravel().astype(bool) & again.ravel().astype(bool) & (error.ravel() < 14)
            keep &= (np.linalg.norm(back - ref, axis=1) < 0.65) & (
                np.linalg.norm(moved - ref, axis=1) < 3.0
            )
            if keep.sum() < 36:
                continue
            # Fit the measured world points to the independently tracked live pixels.
            # The view homography proposes correspondences and never supplies the pose.
            answer = self.bank.solve_with_camera(
                self.bank.k, self.bank.track_xyz[start:end][inside][keep], moved[keep], None
            )
            if answer and math.dist(answer["eye"], anchor) <= 1.25:
                return answer
        return None
