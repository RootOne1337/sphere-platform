"""Retrieve source-map street views from RGB; verify candidates separately before control."""

import argparse
import hashlib
import inspect
import json
import math
import os
import sys
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

WEIGHTS_SHA256 = "b938bf1bc15cd2ec0feacfe3a1bb553fe8ea9ca46a7e1d8d00217f29aef60cd9"


class Encoder:
    def __init__(self, source, weights):
        import torch

        with weights.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != WEIGHTS_SHA256:
                raise ValueError("unexpected image encoder weights")
        os.environ.setdefault("XFORMERS_DISABLED", "1")
        sys.path.insert(0, str(source.resolve(strict=True)))
        from dinov2.hub.backbones import dinov2_vits14

        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        torch.set_num_threads(3)
        self.net = dinov2_vits14(pretrained=False)
        self.net.load_state_dict(torch.load(weights, weights_only=True, map_location="cpu"))
        self.net.eval().to(self.device)
        self.mean = torch.tensor([0.485, 0.456, 0.406], device=self.device)[None, :, None, None]
        self.std = torch.tensor([0.229, 0.224, 0.225], device=self.device)[None, :, None, None]

    def encode(self, images):
        torch = self.torch
        inputs = []
        for im in images:
            rgb = cv2.cvtColor(
                cv2.resize(im, (196, 112), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB
            )
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            norm = cv2.createCLAHE(2.0, (6, 4)).apply(gray)
            inputs.extend((rgb, cv2.cvtColor(norm, cv2.COLOR_GRAY2RGB)))
        with torch.inference_mode():
            x = (
                torch.as_tensor(np.stack(inputs), device=self.device)
                .permute(0, 3, 1, 2)
                .contiguous()
                .float()
                / 255
            )
            f = self.net.forward_features((x - self.mean) / self.std)
            p = f["x_norm_patchtokens"].reshape(-1, 8, 14, 384)
            chunks = [f["x_norm_clstoken"], p[:, 2:6, :7].mean((1, 2)), p[:, 2:6, 7:].mean((1, 2))]
            vec = torch.cat([torch.nn.functional.normalize(z) for z in chunks], dim=1)
            return torch.nn.functional.normalize(vec.reshape(len(images), -1)).cpu().numpy()


def infer_rotations(images):
    detector = cv2.SIFT_create(nfeatures=1700, contrastThreshold=0.017)
    features = []
    for im in images:
        g = cv2.cvtColor(cv2.resize(im, (640, 360)), cv2.COLOR_BGR2GRAY)
        mask = np.zeros_like(g)
        mask[40:295] = 255
        kp, d = detector.detectAndCompute(g, mask)
        features.append((np.float32([k.pt for k in kp]), d))
    pairs = []
    for i, (u, d) in enumerate(features):
        for j in range(i):
            v, e = features[j]
            if d is None or e is None or min(len(d), len(e)) < 24:
                continue
            good = [
                a for a, b in cv2.BFMatcher().knnMatch(e, d, k=2) if a.distance < 0.73 * b.distance
            ]
            if len(good) < 24:
                continue
            x = np.float32([v[k.queryIdx] for k in good])
            y = np.float32([u[k.trainIdx] for k in good])
            H, m = cv2.findHomography(x, y, cv2.RANSAC, 1.4)
            if H is None or m.sum() < 24:
                continue
            x, y = x[m.ravel() > 0], y[m.ravel() > 0]
            if cv2.contourArea(cv2.convexHull(x)) < 1750:
                continue
            pairs.append((j, i, x, y))

    # Calibrate by rotation-only reprojection on overlapping frames from this stationary look.
    def fit(f, x, y):
        def rays(p):
            q = np.c_[p - [319.5, 179.5], np.full(len(p), f)]
            return q / np.linalg.norm(q, axis=1)[:, None]

        a, b = rays(x), rays(y)
        u, _, v = np.linalg.svd(b.T @ a)
        r = u @ np.diag([1, 1, np.linalg.det(u @ v)]) @ v
        q = a @ r.T
        err = np.median(
            np.linalg.norm(q[:, :2] / np.maximum(q[:, 2:], 0.01) * f + [319.5, 179.5] - y, axis=1)
        )
        return float(err), math.atan2(r[0, 2], r[2, 2])

    lenses = []
    for _, _, x, y in pairs:
        if np.linalg.norm(np.median(y - x, axis=0)) > 32:
            f = min(range(120, 601, 4), key=lambda focal: fit(focal, x, y)[0])
            if 120 < f < 600:
                lenses.append(f)
    focal = float(np.median(lenses)) if lenses else None
    graph = [[] for _ in images]
    for j, i, x, y in pairs:
        error, angle = fit(focal or 320, x, y)
        if error <= 1.25:
            graph[j].append((i, angle))
            graph[i].append((j, -angle))
    groups = []
    visited = set()
    for i in range(len(images)):
        if i in visited:
            continue
        angles = {i: 0.0}
        queue = deque([i])
        visited.add(i)
        while queue:
            j = queue.popleft()
            for k, angle in graph[j]:
                if k not in visited:
                    visited.add(k)
                    angles[k] = math.remainder(angles[j] + angle, 2 * math.pi)
                    queue.append(k)
        groups.append(angles)
    return groups, focal


def encoding_signature(manifest):
    return hashlib.sha256(
        manifest + WEIGHTS_SHA256.encode() + inspect.getsource(Encoder).encode()
    ).hexdigest()


def index(args, encoder):
    manifest = (args.gallery / "survey.json").read_bytes()
    survey = json.loads(manifest)
    width, height = survey["width"], survey["height"]
    n = len(survey["eyes"])
    cache = args.output.with_suffix(".partial.npy")
    signature = encoding_signature(manifest)
    stamp = args.output.with_suffix(".progress.json")
    previous = json.loads(stamp.read_bytes()) if stamp.exists() else {}
    if previous and previous.get("signature") != signature:
        raise ValueError("different gallery in progress")
    start = previous.get("completed", 0)
    if args.output.exists():
        saved = np.load(args.output, allow_pickle=False, mmap_mode="r")
        if start == n and saved.shape == (n, 8, 2304) and saved.dtype == np.float16:
            print("Already indexed", n * 8, flush=True)
            return
        raise ValueError("existing scene index is incomplete")
    if not 0 <= start <= n:
        raise ValueError("invalid survey progress")
    out = np.lib.format.open_memmap(
        cache, mode="r+" if start else "w+", dtype=np.float16, shape=(n, 8, 2304)
    )
    for i in range(start, n):
        file = args.gallery / f"{i:05}.jpg"
        deadline = time.monotonic() + args.wait_seconds
        while not file.exists() and time.monotonic() < deadline:
            time.sleep(0.25)
        sheet = cv2.imread(str(file))
        if sheet is None or sheet.shape[:2] != (height * 2, width * 4):
            raise ValueError("missing survey view " + str(i))
        images = [
            sheet[(j // 4) * height : (j // 4 + 1) * height, (j % 4) * width : (j % 4 + 1) * width]
            for j in range(8)
        ]
        out[i] = encoder.encode(images)
        if (i + 1) % 50 == 0 or i + 1 == n:
            out.flush()
            tmp = stamp.with_suffix(".tmp")
            tmp.write_text(json.dumps(dict(signature=signature, completed=i + 1)), encoding="utf8")
            tmp.replace(stamp)
    del out
    cache.replace(args.output)
    print("Indexed", n * 8, encoder.device, flush=True)


def retrieve(args, encoder):
    manifest = (args.gallery / "survey.json").read_bytes()
    survey = json.loads(manifest)
    vectors = np.load(args.index, allow_pickle=False, mmap_mode="r")
    stamp = json.loads(args.index.with_suffix(".progress.json").read_bytes())
    signature = encoding_signature(manifest)
    if (
        stamp["signature"] != signature
        or stamp["completed"] != len(survey["eyes"])
        or vectors.shape[:2] != (len(survey["eyes"]), 8)
    ):
        raise ValueError("incomplete or mismatched scene index")
    images = [cv2.imread(str(f)) for f in args.frames]
    if any(im is None for im in images):
        raise ValueError("missing query image")
    groups, focal = infer_rotations(images)
    focal = focal or getattr(args, "stream_focal", None)
    crops = []
    for im in images:
        h, w = im.shape[:2]
        # Sources have vertical FOV 62 degrees. Retain the whole view when a single
        # frame does not supply enough information to estimate the lens.
        factor = min(1.0, (focal or 320) / (180 / math.tan(math.radians(31))))
        x = int((1 - factor) * w / 2)
        y = int((1 - factor) * h / 2)
        crops.append(im[y : h - y, x : w - x])
    query = np.vstack([encoder.encode(crops[i : i + 12]) for i in range(0, len(crops), 12)])
    parts = [
        np.asarray(vectors[i : i + 64], np.float32) @ query.T for i in range(0, len(vectors), 64)
    ]
    sim = np.concatenate(parts)
    sim = (sim - sim.mean(axis=(0, 1))) / np.maximum(sim.std(axis=(0, 1)), 1e-5)
    result = []
    for group in groups:
        # One vote per direction; duplicate images must not outvote the rest of a panorama.
        headings = {}
        for k, a in group.items():
            headings.setdefault(round(a * 8 / math.pi) % 16, (k, a))
        scores = []
        for heading in np.arange(32) * 2 * math.pi / 32:
            evidence = []
            for k, a in headings.values():
                t = (heading + a) * 4 / math.pi
                i = math.floor(t)
                w = t - i
                evidence.append((1 - w) * sim[:, i % 8, k] + w * sim[:, (i + 1) % 8, k])
            scores.append(np.mean(evidence, axis=0))
        ranks = np.stack(scores)
        quality = ranks.max(axis=0)
        candidates = []
        for idx in np.argsort(-quality):
            eye = survey["eyes"][idx]
            if any(
                math.dist(eye[:2], v["eye"][:2]) < min(70.0, survey["spacing"] * 0.75)
                for v in candidates
            ):
                continue
            candidates.append(
                dict(
                    site=int(idx),
                    eye=eye,
                    yaw=float(ranks[:, idx].argmax() * math.pi / 16),
                    score=round(float(quality[idx]), 4),
                )
            )
            if len(candidates) >= 12:
                break
        result.append(
            dict(
                frames=list(group),
                relativeYaw=group,
                distinctDirections=len(headings),
                candidates=candidates,
            )
        )
    args.output.write_text(
        json.dumps(
            dict(
                revision=survey["revision"],
                sourceViews=len(vectors) * 8,
                frameDigests=[hashlib.sha256(p.read_bytes()).hexdigest() for p in args.frames],
                focalAt640=focal,
                results=result,
            )
        ),
        encoding="utf8",
    )
    print([(len(r["frames"]), r["candidates"][:2]) for r in result], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--gallery", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("index")
    build.add_argument("output", type=Path)
    build.add_argument("--wait-seconds", type=float, default=0)
    search = commands.add_parser("search")
    search.add_argument("index", type=Path)
    search.add_argument("output", type=Path)
    search.add_argument("--stream-focal", type=float, help="calibrated focal length at 640 px wide")
    search.add_argument("frames", type=Path, nargs="+")
    args = parser.parse_args()
    encoder = Encoder(args.source, args.weights)
    if args.command == "index":
        index(args, encoder)
    else:
        retrieve(args, encoder)
