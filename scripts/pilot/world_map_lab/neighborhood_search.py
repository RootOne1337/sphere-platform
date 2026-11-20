"""Retrieve route neighborhoods in a single visual index before fine geometric checks."""

import cv2
import numpy as np


class NeighborhoodSearch:
    def __init__(self, indexes, span=12):
        self.span = span
        desc, cells = [], []
        for index, stride in indexes:
            for view in index.views:
                start, end = view["range"]
                ids = np.arange(start, end, stride)
                desc.append(index.atlas.desc[ids])
                cells.append(np.full(len(ids), int(view["s"] // span), dtype=np.int32))
        self.cells = np.concatenate(cells)
        self.count = int(self.cells.max()) + 1
        self.matcher = cv2.FlannBasedMatcher(dict(algorithm=1, trees=4), dict(checks=48))
        self.matcher.add([np.ascontiguousarray(np.vstack(desc), np.float32)])
        self.matcher.train()

    def suggest(self, features, limit=4):
        if features is None:
            return []
        _, descriptors = features
        query = descriptors[:: max(1, int(np.ceil(len(descriptors) / 420)))]
        votes = np.zeros(self.count)
        for row in self.matcher.knnMatch(np.ascontiguousarray(query), k=6):
            seen = set()
            for match in row:
                if match.distance > 0.54:
                    continue
                cell = self.cells[match.trainIdx]
                if cell in seen:
                    continue
                seen.add(cell)
                votes[cell] += (0.58 - match.distance) ** 2
        smoothed = np.convolve(np.pad(votes, 1), [0.2, 1.0, 0.2], mode="valid")
        return [
            int(i) * self.span for i in np.argsort(-smoothed, kind="stable")[:limit] if votes[i] > 0
        ]
