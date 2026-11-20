"""Check a stopped camera proposal against independently rendered nearby poses."""

import math

import cv2
import numpy as np

from scripts.pilot.world_map_lab.check_game_views import cost, edges


def rendered_agreement(scene, rgb, center, rotation):
    height, width = 216, 384
    actual = edges(cv2.resize(rgb, (width, height), interpolation=cv2.INTER_AREA))
    if sum(np.count_nonzero(channel) for channel in actual[0]) < 400:
        return False
    yaw = math.atan2(rotation[2, 1], rotation[2, 0])
    pitch = math.asin(np.clip(rotation[2, 2], -1, 1))
    right = np.array([math.sin(yaw), -math.cos(yaw), 0])
    forward = np.array([math.cos(yaw), math.sin(yaw), 0])
    roll = math.atan2(rotation[0] @ np.cross(rotation[2], right), rotation[0] @ right)
    scores = []
    for lateral, along, turn in [
        (0, 0, 0),
        (-1.5, 0, 0),
        (1.5, 0, 0),
        (0, -2.5, 0),
        (0, 2.5, 0),
        (0, 0, -5),
        (0, 0, 5),
    ]:
        image, _, _ = scene.frame(
            scene.mesh,
            center + right * lateral + forward * along,
            math.degrees(yaw) + turn,
            math.degrees(pitch),
            scene.HFOV,
            w=width,
            h=height,
            roll=math.degrees(roll),
        )[0]
        scores.append(cost(actual, edges(image)))
    return bool(scores[0] < 3.2 and scores[0] < 0.86 * min(scores[1:]))
