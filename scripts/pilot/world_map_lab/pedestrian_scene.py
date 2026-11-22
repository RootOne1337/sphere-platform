"""Detect abrupt view replacement before reusing an outdoor walking pose or input."""

import cv2
import numpy as np


class WalkingSceneGuard:
    def __init__(self):
        self.previous = None
        self.paused = False

    def observe(self, frame):
        tile = cv2.resize(frame, (8, 6), interpolation=cv2.INTER_AREA).astype(np.int16)
        if self.previous is not None:
            delta = tile - self.previous
            channel_change = np.abs(delta).mean(axis=2)
            overall = np.linalg.norm(delta.mean(axis=(0, 1)))
            if overall >= 95 and np.mean(channel_change >= 44) >= 0.80:
                self.paused = True
        self.previous = tile
        return self.paused

    def confirm_world_pose(self):
        self.paused = False


def plausible_walk_height(eye_z, floor_levels):
    return any(0.85 < eye_z - floor < 2.55 for floor in floor_levels)
