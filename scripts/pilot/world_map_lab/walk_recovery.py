"""Reacquire a stationary outdoor walker from fresh views when short-term mesh tracks expire."""

import math
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from scripts.pilot.world_map_lab.live_destination_atlas import Locator
from scripts.pilot.world_map_lab.world_scene_acquisition import acquire


class WalkingRecovery:
    def __init__(self, cfg, planner, walk_folder, output, revision):
        self.cfg, self.planner, self.walk_folder = cfg, planner, Path(walk_folder)
        self.output, self.revision = Path(output), revision
        self.output.mkdir(exist_ok=True, parents=True)
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.pending = None
        self.discard_pending = False
        self.samples = []
        self.last_frame = -math.inf
        self.last_attempt = -math.inf
        self.failures = 0

    def invalidate(self):
        self.samples.clear()
        self.discard_pending = self.pending is not None

    def moving(self):
        self.invalidate()
        self.failures = 0

    def observe(self, frame, anchor, *, scene_changed=False):
        now = time.monotonic()
        if self.pending is not None:
            if not self.pending.done():
                return None
            future, self.pending = self.pending, None
            try:
                folder, fix = future.result()
                if self.discard_pending:
                    self.discard_pending = False
                    return None
                if fix and (scene_changed or anchor is None or math.dist(fix["eye"], anchor) < 16):
                    bank = Locator(folder / "tracking.npz", self.revision)
                    self.failures = 0
                    self.samples.clear()
                    return bank, fix
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                print(f"walking acquisition failed: {exc}", flush=True)
            self.failures += 1
        if now - self.last_frame < 0.4:
            return None
        self.last_frame = now
        thumb = cv2.resize(frame, (48, 27), interpolation=cv2.INTER_AREA).astype(np.int16)
        if thumb.std() < 8 or any(
            np.abs(thumb - earlier).mean() < 6 for earlier, _ in self.samples
        ):
            return None
        ok, image = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 94])
        if ok:
            self.samples.append((thumb, image))
        if len(self.samples) >= 5 and now - self.last_attempt > 12:
            folder = Path(tempfile.mkdtemp(prefix="views-", dir=self.output))
            frames = []
            for i, (_, data) in enumerate(self.samples):
                path = folder / f"look-{i:02}.jpg"
                path.write_bytes(data.tobytes())
                frames.append(path)
            self.samples.clear()
            self.last_attempt = now
            seed = None if scene_changed or self.failures >= 2 else anchor
            self.discard_pending = False
            self.pending = self.executor.submit(self._acquire, folder, frames, seed)
        return None

    def _acquire(self, folder, frames, anchor):
        def report(phase):
            print(f"walking recovery {folder.name} {phase}", flush=True)

        result = acquire(
            self.cfg,
            frames,
            folder,
            self.planner,
            report,
            walk_anchor=anchor,
            walk_folder=self.walk_folder,
        )
        fix = result["pose"] if not result["ambiguous"] else None
        return folder, fix

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)
