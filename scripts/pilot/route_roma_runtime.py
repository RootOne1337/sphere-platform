
"""Optional, local RoMa service for the controlled RGB vehicle pilot.

A route owns one GPU subprocess and at most one outstanding query. Neither the
GPU process nor messages on its private pipes have Android input authority.
"""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass
from hashlib import file_digest
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
from unittest.mock import patch

import numpy as np

CONFIG = ".local-pilot/route-roma-runtime.json"
WRAPPERS = {
    "roma_warp.py": "9902e41dd043251cb139a466c4687496c0d34d8e467a394865ea8344b10e24ec",
    "roma_v2_warp.py": "0afc06885a2e9338f11e9f4ade29b582935ce58faaf6b8650167ae3e1714fa47",
}
MAX_MESSAGE = 10 * 1024**2


@dataclass(frozen=True)
class Runtime:
    python: Path
    directory: Path


def configured_runtime(root):
    """The operator supplies an absolute local interpreter and reviewed model directory."""
    path = root / CONFIG
    try:
        if path.is_symlink() or not 0 < path.stat().st_size <= 4096:
            return None
        value = json.loads(path.read_bytes())
        if type(value) is not dict or set(value) != {"python", "directory"}:
            return None
        runtime = Runtime(Path(value["python"]), Path(value["directory"]))
        if not runtime.python.is_absolute() or not runtime.directory.is_absolute() or not runtime.python.is_file():
            return None
        if any(not (runtime.directory / name).is_file() for name in WRAPPERS):
            return None
        return runtime
    except (OSError, TypeError, ValueError):
        return None


def _read(stream):
    header = stream.read(4)
    if len(header) != 4:
        raise EOFError("RoMa process closed")
    size = struct.unpack("!I", header)[0]
    if not 0 < size <= MAX_MESSAGE:
        raise ValueError("RoMa IPC size")
    payload = stream.read(size)
    if len(payload) != size:
        raise EOFError("RoMa IPC truncated")
    return payload


def _write(stream, payload):
    if not 0 < len(payload) <= MAX_MESSAGE:
        raise ValueError("RoMa IPC size")
    stream.write(struct.pack("!I", len(payload)))
    stream.write(payload)
    stream.flush()


def _array_payload(**fields):
    stream = io.BytesIO()
    np.savez(stream, **fields)
    return stream.getvalue()


class RomaProcess:
    """A bounded single outstanding request, including process warm-up."""

    def __init__(self, runtime, *, match_timeout=2, cache_query=False):
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="route-roma")
        self._process = None
        self._pending = None
        self._began = time.monotonic()
        self._match_timeout = match_timeout
        self.failure = None
        self.status = "warming"
        from scripts.pilot.route_owned_process import spawn_owned

        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(map(str, (runtime.directory, runtime.directory / "deps")))
        environment["SPHERE_ROMA_REUSE_QUERY"] = "1" if cache_query else "0"
        try:
            self._process = spawn_owned(
                [str(runtime.python), str(Path(__file__).resolve()), str(runtime.directory)],
                env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._pending = self._pool.submit(_read, self._process.stdout)
        except BaseException:
            self.close()
            raise

    @property
    def available(self):
        return self.status == "ready" and self._pending is None

    def submit(self, query, references):
        if not self.available or not 1 <= len(references) <= 2:
            return False
        self.status = "matching"
        self._began = time.monotonic()
        self._pending = self._pool.submit(self._exchange, query.copy(), references)
        return True

    def _exchange(self, query, references):
        fields = {"query": query, "indices": np.array([row[0] for row in references], dtype=np.int32)}
        for slot, (_, rgb, pixels) in enumerate(references):
            fields[f"rgb{slot}"] = rgb
            fields[f"pixels{slot}"] = pixels
        _write(self._process.stdin, _array_payload(**fields))
        reply = {}
        with np.load(io.BytesIO(_read(self._process.stdout)), allow_pickle=False) as archive:
            for slot, (_, _, pixels) in enumerate(references):
                indices, xy = archive[f"indices{slot}"], archive[f"xy{slot}"]
                if (indices.dtype.kind not in "iu" or indices.ndim != 1
                        or xy.shape != (len(indices), 2) or len(indices) > len(pixels)
                        or np.any(indices < 0) or np.any(indices >= len(pixels))
                        or len(np.unique(indices)) != len(indices) or not np.isfinite(xy).all()):
                    raise ValueError("invalid correspondence reply")
                reply[slot] = indices, xy
        return reply

    def poll(self):
        pending = self._pending
        if pending is None:
            return None
        if not pending.done():
            if time.monotonic() - self._began > (
                45 if self.status == "warming" else self._match_timeout
            ):
                self.failure = f"{self.status} timeout"
                self.disable()
            return None
        self._pending = None
        try:
            result = pending.result()
            if self.status == "warming":
                if result != b"ready":
                    raise ValueError("RoMa warm-up failed")
                self.status = "ready"
                return None
            self.status = "ready"
            return result
        except Exception as exc:
            self.failure = type(exc).__name__
            self.disable()
            return None

    def disable(self):
        self.status = "unavailable"
        self._pending = None
        process = self._process
        if process is not None:
            try:
                if process.job is not None:
                    process.close()
                elif process.poll() is None:
                    process.kill()
            except OSError:
                pass

    def close(self):
        self.disable()
        process, self._process = self._process, None
        if process is not None:
            process.wait(timeout=2)
            process.stdin.close()
            process.stdout.close()
        self._pending = None
        self._pool.shutdown(wait=False, cancel_futures=True)


class CachedMatcher:
    """Cache frozen reference encodings for the pinned V2 single-scale graph."""

    def __init__(self, directory):
        for name, digest in WRAPPERS.items():
            path = directory / name
            with path.open("rb") as stream:
                if file_digest(stream, "sha256").hexdigest() != digest:
                    raise ValueError("RoMa wrapper revision changed")
        from roma_v2_warp import RoMaV2Warp
        import torch

        torch.set_num_threads(2)
        self.engine = RoMaV2Warp(device="cuda", coarse_res=288)
        self.cache = OrderedDict()

    @staticmethod
    def _clone(value):
        if isinstance(value, dict):
            return {key: CachedMatcher._clone(tensor) for key, tensor in value.items()}
        if isinstance(value, list):
            return [CachedMatcher._clone(tensor) for tensor in value]
        return value.clone()

    def match(self, key, rgb, query, *, query_key=None):
        calls = [0, 0]

        def wrap(layer, kind):
            forward = layer.forward

            def infer(tensor):
                calls[kind] += 1
                if calls[kind] != 1 and (calls[kind] != 2 or query_key is None):
                    return forward(tensor)
                local_key = kind, calls[kind], key if calls[kind] == 1 else query_key
                if local_key not in self.cache:
                    self.cache[local_key] = self._clone(forward(tensor))
                self.cache.move_to_end(local_key)
                if len(self.cache) > 20:
                    self.cache.popitem(last=False)
                return self._clone(self.cache[local_key])

            return infer

        model = self.engine.model
        with ExitStack() as stack:
            for kind, layer in enumerate((model.f, model.refiner_features)):
                stack.enter_context(patch.object(layer, "forward", wrap(layer, kind)))
            warp = self.engine.match(rgb, query)
        if calls != [2, 2]:
            raise RuntimeError("unexpected RoMa inference graph")
        return warp


def _sample(field, points):
    import cv2 as cv

    scale = np.asarray(field.shape[1::-1]) / 2
    grid = ((points + 1) * scale - .5).astype(np.float32)
    return cv.remap(field, grid[:, 0:1], grid[:, 1:2], cv.INTER_LINEAR,
                    borderMode=cv.BORDER_REPLICATE).reshape((len(grid),) + field.shape[2:])


def _correspondences(warp, pixels):
    size = np.array([960, 540], dtype=float)
    source = 2 * (pixels + .5) / size - 1
    target = _sample(warp["forward"], source)
    reverse = _sample(warp["backward"], target)
    confidence = np.minimum(_sample(warp["forward_confidence"], source),
                            _sample(warp["backward_confidence"], target))
    xy = (target + 1) * size / 2 - .5
    keep = ((xy >= 0) & (xy < size)).all(axis=1)
    keep &= (confidence >= .55) & (np.linalg.norm((reverse - source) * size / 2, axis=1) <= 2.)
    eligible = np.flatnonzero(keep)
    ranked = eligible[np.argsort(-confidence[eligible], kind="stable")]
    _, first = np.unique(np.rint(xy[ranked]).astype(int) // 2, return_index=True, axis=0)
    best = ranked[np.sort(first)]
    return best, xy[best]


def _serve(directory):
    from hashlib import sha256

    # Native libraries may log on fd 1. Keep the framed protocol on a separate handle.
    wire = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    matcher = CachedMatcher(directory)
    blank = np.zeros((540, 960, 3), dtype=np.uint8)
    matcher.match("warm-up", blank, blank)
    cache_query = os.environ.get("SPHERE_ROMA_REUSE_QUERY") == "1"
    _write(wire, b"ready")
    while True:
        try:
            request = _read(sys.stdin.buffer)
        except EOFError:
            return
        with np.load(io.BytesIO(request), allow_pickle=False) as archive:
            query = archive["query"]
            if query.shape != (540, 960, 3) or query.dtype != np.uint8:
                raise ValueError("RoMa query geometry")
            query_key = sha256(query).digest() if cache_query else None
            indices = archive["indices"]
            if indices.ndim != 1 or not 1 <= len(indices) <= 2:
                raise ValueError("RoMa candidates")
            result = {}
            for slot, index in enumerate(indices):
                rgb, pixels = archive[f"rgb{slot}"], archive[f"pixels{slot}"]
                if rgb.shape != query.shape or rgb.dtype != np.uint8 or not 1 <= len(pixels) <= 4096:
                    raise ValueError("RoMa reference geometry")
                warp = matcher.match((int(index), sha256(rgb).digest()), rgb, query, query_key=query_key)
                result[f"indices{slot}"], result[f"xy{slot}"] = _correspondences(warp, pixels)
            _write(wire, _array_payload(**result))


if __name__ == "__main__":
    _serve(Path(sys.argv[1]).resolve(strict=True))
