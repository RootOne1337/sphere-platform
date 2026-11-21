"""Cold-start a HUD-free session from the source map and track new RGB frames against it."""

import argparse
import hashlib
import json
import math
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from scripts.pilot.world_map_lab.live_destination_atlas import Locator


def read_config(path):
    cfg = json.loads(path.read_bytes())
    for key in ("gpu", "source", "weights", "gallery", "index", "matcher", "folder"):
        cfg[key] = Path(cfg[key]).resolve(strict=True)
    focal = float(cfg["focalAt640"])
    if not math.isfinite(focal) or not 80 <= focal <= 1200:
        raise ValueError("invalid stream lens")
    return cfg


def acquire(cfg, frames, output, planner, report):
    """Global retrieval, local road sampling, image-to-mesh verification. No start coordinate."""
    output.mkdir(parents=True, exist_ok=True)
    if not 1 <= len(frames) <= 24:
        raise ValueError("expected a bounded set of camera views")
    prefix = "scripts.pilot.world_map_lab."

    def execute(executable, module, args):
        with (output / "search.log").open("ab") as log:
            subprocess.run(
                [str(executable), "-u", "-m", prefix + module, *map(str, args)],
                cwd=Path(__file__).resolve().parents[3],
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                check=True,
                timeout=480,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

    def encode(gallery, *command):
        execute(
            cfg["gpu"],
            "world_scene_retrieval",
            [
                "--source",
                cfg["source"],
                "--weights",
                cfg["weights"],
                "--gallery",
                gallery,
                *command,
            ],
        )

    coarse, fine = output / "global.json", output / "local.json"
    gallery, index = output / "views", output / "local.npy"
    focal = str(cfg["focalAt640"])
    report("global_search")
    encode(cfg["gallery"], "search", "--stream-focal", focal, cfg["index"], coarse, *frames)
    report("rendering_candidates")
    execute(
        sys.executable,
        "render_world_search_views",
        [
            "--folder",
            cfg["folder"],
            "--planner",
            planner,
            "--spacing",
            10,
            "--regions",
            3,
            "--radius",
            110,
            "--candidates",
            coarse,
            "--output",
            gallery,
        ],
    )
    report("local_search")
    encode(gallery, "index", index)
    encode(gallery, "search", "--stream-focal", focal, index, fine, *frames)
    report("verifying_geometry")
    execute(
        sys.executable,
        "verify_world_scene_candidates",
        [
            "--planner",
            planner,
            "--scene",
            cfg["folder"] / "journey/route.json",
            "--results",
            fine,
            "--stream-focal",
            focal,
            "--candidates",
            12,
            "--views",
            6,
            "--interpreter",
            cfg["gpu"],
            "--matcher",
            cfg["matcher"],
            "--output",
            output / "geometry.json",
            "--tracking-atlas",
            output / "tracking.npz",
            *frames,
        ],
    )
    return json.loads((output / "geometry.json").read_bytes())


class WorldAcquisition:
    """At most one GPU job. Historical results only seed a fresh per-frame geometric solve."""

    def __init__(self, config, directory, planner, revision):
        self.cfg = read_config(config)
        self.signature = hashlib.sha256(config.read_bytes()).hexdigest()
        manifest = json.loads((self.cfg["gallery"] / "survey.json").read_bytes())
        if manifest["revision"] != revision:
            raise ValueError("world search revision mismatch")
        self.directory = directory / self.signature
        self.directory.mkdir(parents=True, exist_ok=True)
        self.planner, self.revision = planner, revision
        self.bank = None
        self.lock = threading.Lock()
        self.phase = "collecting_views"
        self.samples = []
        self.last_seen = self.last_sample = self.first_sample = self.retry = -math.inf
        self.busy = False
        existing = self.directory / "tracking.npz"
        if existing.exists():
            self.bank = Locator(existing, revision)

    def status(self):
        with self.lock:
            return dict(phase=self.phase, samples=len(self.samples), tracking=self.bank is not None)

    def observe(self, raw, gray, observed):
        with self.lock:
            bank = self.bank
        if bank is not None and observed is not None:
            pose = bank.locate_features(gray, *observed)
            if pose and bank.covers([[*pose["eye"][:2], pose["eye"][2] - 1.45]]):
                return pose
        now = time.monotonic()
        with self.lock:
            if self.busy or now < self.retry:
                return None
            if now - self.last_seen > 5:
                self.samples.clear()
            self.last_seen = now
            if now - self.last_sample < 0.55:
                return None
            self.last_sample = now
            thumb = cv2.resize(gray, (64, 36), interpolation=cv2.INTER_AREA).astype(np.int16)
            # Ignore undersampled overlays and frozen or near-identical video frames.
            if np.std(thumb) < 8:
                return None
            if not self.samples:
                self.first_sample = now
                self.phase = "collecting_views"
            if all(np.mean(np.abs(thumb - old)) >= 5 for old, _ in self.samples):
                self.samples.append((thumb, raw))
            if len(self.samples) >= 14 or (self.samples and now - self.first_sample >= 24):
                frames = [im for _, im in self.samples]
                self.samples.clear()
                self.busy = True
                threading.Thread(target=self._run, args=(frames,), daemon=True).start()
        return None

    def _phase(self, phase):
        with self.lock:
            self.phase = phase

    def _run(self, images):
        state = "no_verified_position"
        try:
            with tempfile.TemporaryDirectory(dir=self.directory, prefix="survey-") as tmp:
                folder = Path(tmp)
                frames = []
                for i, raw in enumerate(images):
                    path = folder / f"frame-{i:02}.jpg"
                    path.write_bytes(raw)
                    frames.append(path)
                try:
                    result = acquire(self.cfg, frames, folder, self.planner, self._phase)
                    if (
                        result.get("trackingAtlas")
                        and result.get("pose")
                        and not result["ambiguous"]
                    ):
                        bank = Locator(folder / "tracking.npz", self.revision)
                        (folder / "tracking.npz").replace(self.directory / "tracking.npz")
                        with self.lock:
                            self.bank = bank
                        state = "tracking"
                finally:
                    for name in ("search.log", "global.json", "local.json", "geometry.json"):
                        if (folder / name).exists():
                            (folder / name).replace(self.directory / ("last-" + name))
        except Exception as exc:
            print(f"World search failed: {type(exc).__name__}: {exc}", flush=True)
            state = "search_error"
        finally:
            with self.lock:
                self.phase, self.busy, self.retry = state, False, time.monotonic() + 10


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--planner", default="http://127.0.0.1:8817")
    p.add_argument("frames", type=Path, nargs="+")
    args = p.parse_args()
    result = acquire(
        read_config(args.config),
        args.frames,
        args.output,
        args.planner,
        lambda phase: print(phase, flush=True),
    )
    print(json.dumps({k: v for k, v in result.items() if k != "comparisons"}))
