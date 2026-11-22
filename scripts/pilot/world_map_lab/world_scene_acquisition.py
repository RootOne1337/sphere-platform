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
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np
from PIL import Image

from scripts.pilot.world_map_lab.live_destination_atlas import Locator


def read_config(path):
    cfg = json.loads(path.read_bytes())
    for key in ("gpu", "source", "weights", "gallery", "index", "matcher", "folder"):
        cfg[key] = Path(cfg[key]).resolve(strict=True)
    focal = float(cfg["focalAt640"])
    if not math.isfinite(focal) or not 80 <= focal <= 1200:
        raise ValueError("invalid stream lens")
    return cfg


def material_regions(coarse, cues, references):
    if (
        cues["revision"] != coarse["revision"]
        or [view["sha256"] for view in cues["frames"]] != coarse["frameDigests"]
    ):
        raise ValueError("material search does not match the RGB batch and map revision")
    extra = []
    for area in [row for row in cues["areas"] if row["materials"] >= 2][:2]:
        center = [area["x"], area["y"]]
        height = min(references, key=lambda p: math.dist(p[:2], center))[2]
        extra.append(dict(eye=[*center, height], source="material-correspondences"))
    return {
        **coarse,
        "results": [
            {**group, "candidates": extra + group["candidates"]} for group in coarse["results"]
        ],
    }


def acquire(
    cfg,
    frames,
    output,
    planner,
    report,
    *,
    walk_anchor=None,
    walk_folder=None,
    wide_search=False,
    material_index=None,
):
    """Retrieve a fresh world pose, optionally searching near a recent verified walking pose."""
    output.mkdir(parents=True, exist_ok=True)
    if not 1 <= len(frames) <= 24:
        raise ValueError("expected a bounded set of camera views")
    if (wide_search or material_index) and walk_anchor is not None:
        raise ValueError("alternate search is only available for cold recognition")
    if wide_search and material_index:
        raise ValueError("choose one alternate search")
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
    if walk_anchor is None:
        report("global_search")
        encode(cfg["gallery"], "search", "--stream-focal", focal, cfg["index"], coarse, *frames)
        if wide_search:
            spacing, regions, radius = 24, 12, 155
        elif material_index:
            from scripts.pilot.world_map_lab.world_material_search import search

            report("material_search")
            cues = search(material_index, frames)
            (output / "materials.json").write_text(json.dumps(cues), encoding="utf8")
            refs = json.loads((cfg["gallery"] / "survey.json").read_bytes())["eyes"]
            merged = material_regions(json.loads(coarse.read_bytes()), cues, refs)
            coarse = output / "global-with-materials.json"
            coarse.write_text(json.dumps(merged), encoding="utf8")
            spacing, regions, radius = 12, 3, 110
        else:
            spacing, regions, radius = (10, 2, 75) if len(frames) == 1 else (10, 3, 110)
    else:
        anchor = np.asarray(walk_anchor, dtype=float)
        if anchor.shape != (3,) or not np.isfinite(anchor).all() or walk_folder is None:
            raise ValueError("walking recovery needs a verified eye position and walk mesh")
        revision = json.loads((cfg["folder"] / "journey/route.json").read_bytes())["revision"]
        coarse.write_text(
            json.dumps(
                {
                    "revision": revision,
                    "results": [
                        {
                            "frames": [0],
                            "distinctDirections": 1,
                            "candidates": [{"eye": anchor.tolist()}],
                        }
                    ],
                }
            ),
            encoding="utf8",
        )
        spacing, regions, radius = 4, 1, 16
    report("rendering_candidates")
    execute(
        sys.executable,
        "render_world_search_views",
        [
            "--folder",
            cfg["folder"],
            "--planner",
            planner,
            *(["--surface", "walk", "--face-folder", walk_folder] if walk_folder else []),
            "--spacing",
            spacing,
            "--regions",
            regions,
            "--radius",
            radius,
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
            "--survey",
            gallery / "survey.json",
            "--tracking-atlas",
            output / "tracking.npz",
            *frames,
        ],
    )
    return json.loads((output / "geometry.json").read_bytes())


class RecentWalkProbe:
    """Try current geometry near a recent walking fix before searching the entire map."""

    def __init__(self, directory, revision):
        self.file = directory / "recent-walk-fix.json"
        self.revision = revision
        self.tracker = None
        self.surface = None
        self.seed = None
        self.attempt = 0
        self.deadline = 0.0
        self.seed_until = 0.0
        self.retry = 0.0
        self.last_saved = -math.inf
        try:
            data = json.loads(self.file.read_bytes())
            if (
                data["revision"] == revision
                and 0 <= time.time() - data["capturedUnix"] <= 1200
                and len(data["pose"]["eye"]) == 3
                and all(math.isfinite(x) for x in (*data["pose"]["eye"], data["pose"]["heading"]))
            ):
                self.seed = data["pose"]
                self.seed_until = data["capturedUnix"] + 1200
        except (OSError, ValueError, TypeError, KeyError):
            pass

    def observe(self, raw, cfg, road):
        if self.seed is None or time.time() > self.seed_until:
            return None
        from scripts.pilot.world_map_lab.pedestrian_surface import FootSurface
        from scripts.pilot.world_map_lab.walking_mesh_tracker import WalkingMeshTracker

        now = time.monotonic()
        if self.tracker is None:
            if now < self.retry:
                return None
            self.surface = FootSurface(cfg["folder"], road, check_visibility=False)
            self.tracker = WalkingMeshTracker(cfg, road.base)
            self.deadline = now + 45
            cleanup = threading.Timer(60, self.tracker.close)
            cleanup.daemon = True
            cleanup.start()
        tracker = self.tracker
        if now >= self.deadline or tracker.closed or tracker.failed:
            self.retry = now + (0 if tracker.closed and not tracker.failed else 20)
            tracker.close()
            self.surface.close()
            self.tracker = self.surface = None
            return None
        if not tracker.ready.is_set():
            return None
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        pose = tracker.locate(image)
        if pose and math.dist(pose["eye"], self.seed["eye"]) < 10:
            ground = self.surface.ground_support(pose["eye"], 1.55)
            if ground is not None:
                if self.attempt == 1:
                    print(
                        f"Recent walking position confirmed at {pose['supports']} points",
                        flush=True,
                    )
                self.seed = pose
                self.seed_until = time.time() + 1200
                if now - self.last_saved >= 5:
                    try:
                        pending = self.file.with_suffix(".pending")
                        pending.write_text(
                            json.dumps(
                                {
                                    "revision": self.revision,
                                    "capturedUnix": time.time(),
                                    "pose": pose,
                                }
                            )
                        )
                        pending.replace(self.file)
                        self.last_saved = now
                    except OSError:
                        pass
                self.attempt = 0
                self.deadline = now + 18
                tracker.submit(image, pose)
                return pose
        if now - tracker.last_submit >= 0.4:
            angles = (0, 0.35, -0.35, 0.8, -0.8, 1.55, -1.55, 2.35, -2.35, math.pi)
            acquired = dict(
                self.seed, heading=self.seed["heading"] + angles[self.attempt % len(angles)]
            )
            tracker.submit(image, acquired)
            self.attempt += 1
        return None


def same_view(a, b):
    # Ignore uniform lighting shifts and moving objects confined to a few tiles.
    diff = a - b
    diff = np.abs(diff - np.median(diff))
    tiles = diff.reshape(6, 6, 8, 8).mean(axis=(1, 3))
    return np.median(tiles) < 5


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
        self.recent_walk = RecentWalkProbe(self.directory, revision)
        self.bank = None
        self.lock = threading.Lock()
        self.phase = "collecting_views"
        self.samples = []
        self.in_flight = []
        self.searched = []
        self.last_seen = self.last_sample = self.first_sample = self.retry = -math.inf
        self.busy = False
        self.last_detail = -math.inf
        self.detailed_samples = False
        existing = self.directory / "tracking.npz"
        if existing.exists():
            self.bank = Locator(existing, revision)

    def covers(self, path):
        with self.lock:
            bank = self.bank
        return bank is not None and bank.covers(path)

    def status(self):
        with self.lock:
            return dict(
                phase=self.phase,
                samples=len(self.samples),
                tracking=self.bank is not None,
                detailWidth=1920,
            )

    def observe(self, raw, gray, observed, *, walk_road=None):
        with self.lock:
            bank = self.bank
        if bank is not None and observed is not None:
            pose = bank.locate_features(gray, *observed)
            if pose and bank.covers([[*pose["eye"][:2], pose["eye"][2] - 1.45]]):
                return pose
        if walk_road is not None:
            pose = self.recent_walk.observe(raw, self.cfg, walk_road)
            if pose:
                return pose
        self.collect(raw, gray)
        return None

    def collect(self, raw, gray):
        now = time.monotonic()
        with self.lock:
            if now - self.last_seen > 5:
                self.samples.clear()
                self.searched.clear()
            self.last_seen = now
            with Image.open(BytesIO(raw)) as image:
                detailed = image.width >= 1280
            if detailed:
                self.detailed_samples = True
                self.last_detail = now
            elif now - self.last_detail < 2:
                return None
            elif self.detailed_samples and now - self.last_detail > 5:
                self.detailed_samples = False
            if now - self.last_sample < (0.3 if detailed else 0.55):
                return None
            self.last_sample = now
            thumb = cv2.resize(gray, (64, 36), interpolation=cv2.INTER_AREA).astype(np.int16)
            # Ignore undersampled overlays and frozen or near-identical video frames.
            if np.std(thumb) < 8:
                return None
            if (
                len(self.samples) < 10
                and not any(same_view(thumb, old) for old in self.in_flight)
                and not any(same_view(thumb, old) for old in self.searched)
                and not any(same_view(thumb, old) for old, _ in self.samples)
            ):
                if not self.samples:
                    self.first_sample = now
                    if not self.busy:
                        self.phase = "collecting_views"
                self.samples.append((thumb, raw))
            count = len(self.samples)
            elapsed = now - self.first_sample
            if not self.busy and now >= self.retry and (count >= 4 or (count and elapsed >= 4)):
                self.in_flight = [view for view, _ in self.samples]
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
        print(f"World search started: {len(images)} distinct frames", flush=True)
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
                    print(
                        "World search finished:",
                        {
                            key: result.get(key)
                            for key in ("candidatesChecked", "framesWithPose", "ambiguous")
                        },
                        flush=True,
                    )
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
                    with ZipFile(folder / "frames.zip", "w") as archive:
                        for frame in frames:
                            archive.write(frame, frame.name)
                    for name in (
                        "frames.zip",
                        "search.log",
                        "global.json",
                        "local.json",
                        "geometry.json",
                    ):
                        if (folder / name).exists():
                            (folder / name).replace(self.directory / ("last-" + name))
        except Exception as exc:
            print(f"World search failed: {type(exc).__name__}: {exc}", flush=True)
            state = "search_error"
        finally:
            with self.lock:
                if state != "search_error":
                    self.searched = (self.searched + self.in_flight)[-20:]
                self.in_flight = []
                self.phase, self.busy = state, False
                self.retry = time.monotonic() + (10 if state == "search_error" else 0)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--planner", default="http://127.0.0.1:8817")
    alternate = p.add_mutually_exclusive_group()
    alternate.add_argument(
        "--wide-search",
        action="store_true",
        help="Verify more image-retrieved map areas with a coarser survey",
    )
    alternate.add_argument(
        "--material-index",
        type=Path,
        help="Rank areas using an additional index built from source-map textures",
    )
    p.add_argument("frames", type=Path, nargs="+")
    args = p.parse_args()
    result = acquire(
        read_config(args.config),
        args.frames,
        args.output,
        args.planner,
        lambda phase: print(phase, flush=True),
        wide_search=args.wide_search,
        material_index=args.material_index,
    )
    print(json.dumps({k: v for k, v in result.items() if k != "comparisons"}))
