"""Offline EigenPlaces → SuperPoint/LightGlue → Sphere geometry replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import uuid
from collections import Counter
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from scripts.pilot.compare_learned_replay_geometry import compare_candidates
from scripts.pilot.resource_guard import collect, evaluate

ROOT = Path(__file__).resolve().parents[2]
LIGHTGLUE_SOURCE = "eb42fee2d71449efb0aa5c10549752b5d75384d8"
EIGENPLACES_SOURCE = "a2969f71d5ea31017443af490b15273ca4c50af1"
WEIGHTS = {
    "superpoint_v1.pth": "52b6708629640ca883673b5d5c097c4ddad37d8048b33f09c8ca0d69db12c40e",
    "superpoint_lightglue.pth": "6ff7040d0a497fc6639337946d7538dae07428c18f77a067a0b5a960e7cc551a",
    "global/ResNet18_512_eigenplaces.pth": "b47ea1efb51041604e9c135508764175bbaa98dece47b47da664517317d0aff3",
}


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def verify_source(source, revision):
    git = ["git", "-C", str(source)]
    if subprocess.check_output(
        [*git, "rev-parse", "HEAD"], text=True, timeout=10
    ).strip() != revision or subprocess.check_output(
        [*git, "diff", "HEAD", "--name-only"], timeout=10
    ):
        raise ValueError(f"model source mismatch: {source.name}")


def load_models(assets, device):
    import torch
    from torch import nn
    from torchvision import models, transforms

    lightglue_source = ROOT / ".local-pilot/reconstruction-tools/lightglue"
    eigenplaces_source = assets / "global/EigenPlaces"
    verify_source(lightglue_source, LIGHTGLUE_SOURCE)
    verify_source(eigenplaces_source, EIGENPLACES_SOURCE)
    for name, digest in WEIGHTS.items():
        if sha256(assets / name) != digest:
            raise ValueError(f"weights mismatch: {name}")
    sys.path[:0] = [str(lightglue_source), str(eigenplaces_source)]
    from eigenplaces_model.layers import Flatten, GeM, L2Norm
    from lightglue import LightGlue, SuperPoint
    from lightglue.superpoint import sample_descriptors

    # Upstream inference architecture without its training-time CosPlace initialization.
    retriever = nn.Sequential()
    retriever.add_module(
        "backbone", nn.Sequential(*list(models.resnet18(weights=None).children())[:-2])
    )
    retriever.add_module(
        "aggregation", nn.Sequential(L2Norm(), GeM(), Flatten(), nn.Linear(512, 512), L2Norm())
    )
    weights = assets / "global/ResNet18_512_eigenplaces.pth"
    retriever.load_state_dict(
        torch.load(weights, map_location="cpu", weights_only=True), strict=True
    )
    preprocess = transforms.Compose(
        [
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ]
    )

    def load_superpoint_state(url):
        if url.rsplit("/", 1)[-1] != "superpoint_v1.pth":
            raise ValueError("unexpected SuperPoint checkpoint")
        return torch.load(assets / "superpoint_v1.pth", map_location="cpu", weights_only=True)

    with patch.object(torch.hub, "load_state_dict_from_url", load_superpoint_state):
        detector = SuperPoint(max_num_keypoints=1024).eval().to(device)
    matcher = LightGlue(features=None, flash=False).eval()
    state = torch.load(assets / "superpoint_lightglue.pth", map_location="cpu", weights_only=True)
    for i in range(9):
        state = {
            key.replace(f"self_attn.{i}", f"transformers.{i}.self_attn").replace(
                f"cross_attn.{i}", f"transformers.{i}.cross_attn"
            ): value
            for key, value in state.items()
        }
        # The published checkpoint retains a buffer the pinned upstream module no longer uses.
        state.pop(f"log_assignment.{i}.r", None)
    state.setdefault("confidence_thresholds", matcher.confidence_thresholds)
    matcher.load_state_dict(state, strict=True)
    return retriever.eval().to(device), preprocess, detector, sample_descriptors, matcher.to(device)


def replay(
    localizer,
    models,
    manifest,
    output,
    device,
    stride,
    top_k,
    deadline,
    merge_covisible,
):
    import cv2 as cv
    import numpy as np
    import torch
    from PIL import Image

    retriever, preprocess, detector, sample_descriptors, matcher = models
    arrays = localizer._cache.arrays
    mask = arrays["mask"]
    masked = mask == 0
    dense = []
    hook = detector.convDb.register_forward_hook(lambda _layer, _args, result: dense.append(result))
    local_size = (640, 360)
    scale = 960 / local_size[0]
    image_size = torch.tensor([local_size], device=device, dtype=torch.float32)

    def checkpoint():
        if time.monotonic() >= deadline or (output / "CANCEL").exists():
            raise RuntimeError("offline replay cancelled or timed out")
        findings = evaluate(collect(ROOT), min_ram_gib=4.75)
        if findings:
            raise RuntimeError(f"offline replay resource guard: {findings}")

    def valid_pixels(xy):
        ij = np.rint(xy).astype(np.int64)
        ij = np.clip(ij, 0, [959, 539])
        return np.all((xy >= 0) & (xy < [960, 540]), axis=1) & ~masked[ij[:, 1], ij[:, 0]]

    def global_descriptor(gray):
        # Same grayscale and HUD treatment for reference and query.
        clean = gray.copy()
        clean[masked] = 127
        small = cv.resize(clean, (448, 252), interpolation=cv.INTER_AREA)
        image = Image.fromarray(small).convert("RGB")
        return retriever(preprocess(image)[None].to(device))[0].cpu().numpy()

    def features(gray, reference_xy=None):
        image = cv.resize(gray, local_size, interpolation=cv.INTER_AREA)
        image = torch.from_numpy(image).to(device, dtype=torch.float32)[None, None] / 255
        dense.clear()
        data = detector({"image": image})
        descriptor_map = torch.nn.functional.normalize(dense.pop(), p=2, dim=1)
        if reference_xy is None:
            xy = data["keypoints"][0].cpu().numpy()
            selected = valid_pixels((xy + 0.5) * scale - 0.5)
            return {
                "keypoints": data["keypoints"][:, selected],
                "descriptors": data["descriptors"][:, selected],
                "image_size": image_size,
            }
        keypoints = torch.tensor(
            (reference_xy + 0.5) / scale - 0.5, device=device, dtype=torch.float32
        )[None]
        descriptors = sample_descriptors(keypoints, descriptor_map).transpose(-1, -2).contiguous()
        return {"keypoints": keypoints, "descriptors": descriptors, "image_size": image_size}

    with torch.inference_mode():
        references, globals_ = [], []
        started = time.perf_counter()
        for ref, gray in enumerate(arrays["grays"]):
            if ref % 24 == 0:
                checkpoint()
            start, end = map(int, arrays["offsets"][ref : ref + 2])
            xy = arrays["pixels"][start:end]
            indices = np.flatnonzero(valid_pixels(xy))
            reference = features(gray, xy[indices])
            references.append((indices, {key: value.cpu() for key, value in reference.items()}))
            globals_.append(global_descriptor(gray))
        global_bank = np.stack(globals_)
        print(
            f"Indexed {len(references)} cameras in {time.perf_counter() - started:.1f}s", flush=True
        )

        def query(gray):
            start = time.perf_counter()
            scores = global_bank @ global_descriptor(gray)
            ranks = np.argsort(-scores, kind="stable")[:top_k]
            retrieval_ms = (time.perf_counter() - start) * 1000
            local = features(gray)
            detect_ms = (time.perf_counter() - start) * 1000 - retrieval_ms
            candidates = []
            for ref in ranks:
                indices, bank = references[ref]
                if len(indices) and local["keypoints"].shape[1]:
                    result = matcher(
                        {
                            "image0": local,
                            "image1": {key: value.to(device) for key, value in bank.items()},
                        }
                    )
                    pairs = result["matches"][0].cpu().numpy()
                else:
                    pairs = np.empty((0, 2), dtype=np.int64)
                query_xy = (local["keypoints"][0, pairs[:, 0]].cpu().numpy() + 0.5) * scale - 0.5
                candidates.append(
                    dict(
                        reference_index=int(ref),
                        query_xy=query_xy,
                        reference_indices=indices[pairs[:, 1]],
                    )
                )
            match_ms = (time.perf_counter() - start) * 1000 - retrieval_ms - detect_ms
            cv.setRNGSeed(17)
            result = compare_candidates(localizer, candidates, merge_covisible=merge_covisible)
            return dict(
                result,
                rank_scores=[float(scores[ref]) for ref in ranks],
                retrieval_ms=retrieval_ms,
                detect_ms=detect_ms,
                match_ms=match_ms,
                elapsed_ms=(time.perf_counter() - start) * 1000,
            )

        with (output / "rows.jsonl").open("x", encoding="utf8", buffering=1) as rows:

            def write(label, identity, gray):
                result = dict(label=label, **identity, **query(gray))
                rows.write(json.dumps(result, allow_nan=False) + "\n")
                return result["rank_status"]

            for i in range(0, len(references), 24):
                write("same_capture_control", {"expected_reference": i}, arrays["grays"][i])
            for capture in manifest["captures"]:
                label = capture["label"]
                counts = Counter()
                frames = capture["frames"][::stride]
                for i, frame in enumerate(frames):
                    if i % 24 == 0:
                        checkpoint()
                    path = (manifest["directory"] / frame["filename"]).resolve()
                    if not path.is_relative_to(manifest["directory"]):
                        raise ValueError("query JPEG outside manifest directory")
                    with path.open("rb") as source:
                        encoded = source.read(384 * 1024 + 1)
                    if (
                        len(encoded) > 384 * 1024
                        or hashlib.sha256(encoded).hexdigest() != frame["sha256"]
                    ):
                        raise ValueError("query JPEG binding mismatch")
                    gray = cv.imdecode(np.frombuffer(encoded, np.uint8), cv.IMREAD_GRAYSCALE)
                    if gray is None or gray.shape != mask.shape:
                        raise ValueError("query JPEG dimensions mismatch")
                    counts[write(label, frame, gray)] += 1
                    if (i + 1) % 24 == 0 or i + 1 == len(frames):
                        print(label, i + 1, len(frames), dict(counts), flush=True)
    hook.remove()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--navigation", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--stride", type=int, choices=(1, 2, 5), default=1)
    parser.add_argument("--top-k", type=int, choices=(3, 5), default=3)
    parser.add_argument("--merge-covisible", action="store_true")
    args = parser.parse_args()
    findings = evaluate(collect(ROOT), min_ram_gib=4.75)
    if findings:
        raise RuntimeError(f"offline replay resource guard: {findings}")
    deadline = time.monotonic() + 540
    manifest = json.loads(args.queries.read_bytes())
    if (
        manifest["schema"] != "sphere-learned-replay-queries-v1"
        or sum(len(capture["frames"]) for capture in manifest["captures"]) > 1200
    ):
        raise ValueError("query manifest format or frame limit")
    manifest["directory"] = args.queries.resolve().parent
    receipt = json.loads((args.navigation / "receipt.json").read_bytes())
    if sha256(args.navigation / "reference-lk.npz") != receipt["cache_sha256"]:
        raise ValueError("reference cache binding mismatch")

    import cv2 as cv
    import torch

    from motor_worker.route_reference_lk import ReferenceLKLocalizer, ReferenceLKRoute

    cv.setNumThreads(2)
    torch.set_num_threads(2)
    gpu_budget = 0
    if args.device == "cuda":
        free, total = torch.cuda.mem_get_info()
        gpu_budget = 1024**3
        if free < 2 * gpu_budget:
            raise RuntimeError("insufficient GPU memory headroom")
        torch.cuda.set_per_process_memory_fraction(gpu_budget / total)
    args.output.mkdir(exist_ok=False)
    intent = dict(
        route_sha256=receipt["sha256"],
        geometry_sha256=receipt["geometry_sha256"],
        reference_cache_sha256=receipt["cache_sha256"],
        queries_sha256=sha256(args.queries),
        weights=WEIGHTS,
        lightglue_source=LIGHTGLUE_SOURCE,
        eigenplaces_source=EIGENPLACES_SOURCE,
        device=args.device,
        stride=args.stride,
        top_k=args.top_k,
        merge_covisible=args.merge_covisible,
        gpu_budget_bytes=gpu_budget,
        timings="offline per-frame, no stream/queue",
        scope="geometric proposals only",
        physical_actions=0,
    )
    (args.output / "intent.json").write_text(json.dumps(intent, indent=2), encoding="utf8")
    models = load_models(args.assets, args.device)
    ids = [str(uuid.uuid4()) for _ in range(3)]
    with closing(
        ReferenceLKRoute.load(args.navigation / "route.json", sha256=receipt["sha256"])
    ) as route:
        with closing(
            ReferenceLKLocalizer(
                route, capture_epoch=ids[0], episode_id=ids[1], goal_revision=ids[2]
            )
        ) as localizer:
            replay(
                localizer,
                models,
                manifest,
                args.output,
                args.device,
                args.stride,
                args.top_k,
                deadline,
                args.merge_covisible,
            )
    (args.output / "COMPLETE").touch(exist_ok=False)


if __name__ == "__main__":
    main()
