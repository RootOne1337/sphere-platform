"""Opt-in loopback DA3/Rerun preview. No Android credentials, input or frame archive.

Run with the locally qualified GPU interpreter and pinned assets. This is a
two-view relative-scale preview, not SLAM, a persistent map or a motor planner.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import io
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

SOURCE = "3d835ec1a5802d64a8b8b15f817a1ab54809bfe4"
WEIGHTS = "364492e38a3a06d221ac75da7f6621ada3f2361cd24fde11ba79091e9f40efcf"
MAX_BODY = 512 * 1024


def unproject(depth, confidence, intrinsics, extrinsics, rgb):
    """DA3 world-to-camera convention. Deliberately omit fixed HUD borders.

    This conservative preview mask is not semantic dynamic-object removal.
    """
    import numpy as np

    height, width = depth.shape
    yy, xx = np.mgrid[0:height:2, 0:width:2]
    z, conf = depth[::2, ::2], confidence[::2, ::2]
    valid = np.isfinite(z) & (z > 0) & np.isfinite(conf)
    valid &= (xx > width * 0.18) & (xx < width * 0.85) & (yy > height * 0.24) & (yy < height * 0.82)
    # Suppress the central third-person avatar; this does not classify other players.
    valid &= ~((xx > width * 0.4) & (xx < width * 0.62) & (yy > height * 0.55))
    if not valid.any():
        return np.empty((0, 3)), np.empty((0, 3), dtype=np.uint8)
    valid &= conf >= np.quantile(conf[valid], 0.4)
    rays = np.stack([xx, yy, np.ones_like(xx)], axis=-1) @ np.linalg.inv(intrinsics).T
    camera = rays * z[..., None]
    points = (camera - extrinsics[:3, 3]) @ extrinsics[:3, :3]
    valid &= np.isfinite(points).all(axis=-1)
    return points[valid].astype(np.float32), rgb[::2, ::2][valid]


class Geometry:
    def __init__(self, root: Path, assets: Path, device: str):
        from scripts.pilot.resource_guard import collect, evaluate

        if evaluate(collect(root)):
            raise RuntimeError("resource_guard")
        actual = subprocess.check_output(["git", "-C", str(assets / "upstream"), "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "-C", str(assets / "upstream"), "diff", "--name-only"], text=True).strip()
        with (assets / "model.safetensors").open("rb") as file:
            digest = hashlib.file_digest(file, "sha256").hexdigest()
        if actual != SOURCE or dirty or digest != WEIGHTS:
            raise RuntimeError("pinned_assets_mismatch")
        sys.path[:0] = [str(assets / "packages"), str(assets / "upstream/src")]
        os.environ.update(HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", RERUN_ANALYTICS_ENABLED="false", OMP_NUM_THREADS="4")
        import numpy as np
        import rerun as rr
        import rerun.blueprint as rrb
        import torch
        from depth_anything_3.cfg import create_object
        from depth_anything_3.utils.io.input_processor import InputProcessor
        from omegaconf import OmegaConf
        from safetensors.torch import load_model

        if rr.__version__ != "0.40.0":
            raise RuntimeError("rerun_version_mismatch")
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("gpu_unavailable")
        torch.set_num_threads(4)
        torch.manual_seed(17)
        config = json.loads((assets / "config.json").read_text(encoding="utf-8"))
        self.model = create_object(OmegaConf.create(config["config"])).eval()
        wrapper = torch.nn.Module()
        wrapper.add_module("model", self.model)
        load_model(wrapper, str(assets / "model.safetensors"), strict=True, device="cpu")
        self.model.to(device)
        self.root, self.device, self.np, self.rr, self.torch = root, device, np, rr, torch
        self.processor = InputProcessor()
        self.blueprint = rrb.Blueprint(rrb.Horizontal(
            rrb.Spatial3DView(origin="world", name="Relative two-view geometry"),
            rrb.Vertical(rrb.Spatial2DView(origin="world/camera0", name="Previous view"),
                         rrb.Spatial2DView(origin="world/camera1", name="Current view")), column_shares=[2, 1]),
            collapse_panels=True)
        self.previous = None
        self.windows = 0

    def reset(self, recording_id):
        self.previous = None
        self.windows = 0
        self.rr.init("sphere-teaching-scene", recording_id=recording_id, spawn=False, strict=True)
        self.rr.connect_grpc("rerun+http://127.0.0.1:3330/proxy")
        self.rr.send_blueprint(self.blueprint)
        self.rr.log("world", self.rr.ViewCoordinates.RIGHT_HAND_Y_DOWN, static=True)

    def frame(self, data, sequence):
        from PIL import Image

        from scripts.pilot.resource_guard import collect, evaluate

        if evaluate(collect(self.root)):
            raise RuntimeError("resource_guard")
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "JPEG" or image.width > 560 or image.height > 560 or min(image.size) < 14:
                raise ValueError("invalid_image_geometry")
            current = image.convert("RGB").copy()
        if self.previous is None:
            self.previous = current
            return {"windows": 0, "points": 0, "inference_ms": 0, "frame_sequence": sequence, "state": "first_view"}
        if current.size != self.previous.size:
            self.previous = None
            raise ValueError("geometry_changed_reconnect_required")
        images, _, _ = self.processor([self.previous, current], process_res=280, sequential=True)
        batch = images[None].float().to(self.device)
        torch, np, rr = self.torch, self.np, self.rr
        if self.device == "cuda":
            torch.cuda.synchronize()
        started = time.perf_counter()
        with torch.inference_mode():
            prediction = self.model(batch, ref_view_strategy="first")
        if self.device == "cuda":
            torch.cuda.synchronize()
        elapsed = (time.perf_counter() - started) * 1000
        arrays = {key: prediction[key][0].detach().float().cpu().numpy() for key in ("depth", "depth_conf", "extrinsics", "intrinsics")}
        if not all(np.isfinite(value).all() for value in arrays.values()):
            raise ValueError("nonfinite_geometry")
        colors = np.clip((images.numpy().transpose(0, 2, 3, 1) * np.array([.229, .224, .225]) + np.array([.485, .456, .406])) * 255, 0, 255).astype(np.uint8)
        rr.set_time("window", sequence=self.windows)
        rr.log("world/preview", rr.Clear(recursive=True))
        count = 0
        for i in range(2):
            points, rgb = unproject(arrays["depth"][i], arrays["depth_conf"][i], arrays["intrinsics"][i], arrays["extrinsics"][i], colors[i])
            rr.log(f"world/preview/cloud{i}", rr.Points3D(points, colors=rgb, radii=0.008))
            count += len(points)
            ext = arrays["extrinsics"][i]
            rotation = ext[:3, :3].T
            rr.log(f"world/camera{i}", rr.Transform3D(translation=-rotation @ ext[:3, 3], mat3x3=rotation))
            rr.log(f"world/camera{i}", rr.Pinhole(image_from_camera=arrays["intrinsics"][i], resolution=[colors[i].shape[1], colors[i].shape[0]], camera_xyz=rr.ViewCoordinates.RDF, image_plane_distance=0.15))
            rr.log(f"world/camera{i}/image", rr.Image(colors[i]))
        self.previous = current
        self.windows += 1
        return {"windows": self.windows, "points": count, "inference_ms": round(elapsed, 2), "frame_sequence": sequence, "state": "relative_window_not_map"}


class PreviewServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 4

    def __init__(self, origin, geometry):
        super().__init__(("127.0.0.1", 3332), Handler)
        self.origin, self.geometry = origin, geometry
        self.lock = threading.Lock()
        self.session = None


class Handler(BaseHTTPRequestHandler):
    server_version = "SphereScenePreview"

    def log_message(self, *_):
        pass  # No images, session keys or query values in access logs.

    def respond(self, status, value):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if self.headers.get("Origin") == self.server.origin:
            self.send_header("Access-Control-Allow-Origin", self.server.origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def trusted(self):
        return self.headers.get("Origin") == self.server.origin and self.headers.get("Host") in {"127.0.0.1:3332", "localhost:3332"}

    def do_OPTIONS(self):
        if not self.trusted():
            return self.respond(403, {"error": "origin_denied"})
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self.server.origin)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Sphere-Preview, X-Scene-Session, X-Scene-Key")
        self.send_header("Access-Control-Max-Age", "60")
        self.end_headers()

    def do_POST(self):
        self.connection.settimeout(12)
        if not self.trusted() or self.headers.get("X-Sphere-Preview") != "1":
            return self.respond(403, {"error": "origin_denied"})
        if not self.server.lock.acquire(blocking=False):
            return self.respond(409, {"error": "busy_no_queue"})
        try:
            self.handle_post()
        except (ValueError, KeyError, TypeError):
            self.respond(400, {"error": "invalid_request"})
        except Exception:
            self.server.session = None
            self.server.geometry.previous = None
            self.respond(503, {"error": "geometry_failed_session_closed"})
        finally:
            self.server.lock.release()

    def handle_post(self):
        path = urlsplit(self.path)
        now = time.monotonic()
        session = self.server.session
        if session and (now - session["last"] > 20 or now - session["born"] > 600):
            self.server.session = session = None
            self.server.geometry.previous = None
        if path.path == "/session":
            if session:
                return self.respond(409, {"error": "preview_already_owned"})
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 256 or self.headers.get("Content-Type") != "application/json":
                raise ValueError()
            body = json.loads(self.rfile.read(size))
            import uuid
            uuid.UUID(body["device_id"])
            session = {"id": secrets.token_hex(16), "key": secrets.token_hex(32), "born": now, "last": now, "sequence": -1}
            self.server.geometry.reset(session["id"])
            self.server.session = session
            return self.respond(200, {key: session[key] for key in ("id", "key")})
        if not session or not hmac.compare_digest(self.headers.get("X-Scene-Session", ""), session["id"]) or not hmac.compare_digest(self.headers.get("X-Scene-Key", ""), session["key"]):
            return self.respond(403, {"error": "session_denied"})
        if path.path == "/stop":
            self.server.session = None
            self.server.geometry.previous = None
            self.server.geometry.rr.disconnect()
            return self.respond(200, {"stopped": True})
        if path.path != "/frame":
            return self.respond(404, {"error": "not_found"})
        sequence = int(parse_qs(path.query)["sequence"][0])
        if not session["sequence"] < sequence < 10**9:
            raise ValueError()
        size = int(self.headers.get("Content-Length", "0"))
        if not 1 <= size <= MAX_BODY or self.headers.get("Content-Type") != "image/jpeg":
            raise ValueError()
        data = self.rfile.read(size)
        if len(data) != size:
            raise ValueError()
        result = self.server.geometry.frame(data, sequence)
        session.update(sequence=sequence, last=time.monotonic())
        self.respond(200, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    assets = args.assets.resolve()
    geometry = Geometry(root, assets, args.device)
    executable = assets / "packages/rerun_cli/rerun.exe"
    if not executable.is_file():
        raise RuntimeError("qualified_rerun_cli_missing")
    import socket
    for port in (3330, 3331, 3332):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    child = subprocess.Popen([str(executable), "--serve-web", "--bind", "127.0.0.1", "--port", "3330", "--web-viewer-port", "3331", "--server-memory-limit", "64MB", "--memory-limit", "128MB"],
                             env={**os.environ, "RERUN_APP_ONLY": "true"}, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), stdout=subprocess.DEVNULL)
    server = PreviewServer("http://127.0.0.1:3015", geometry)
    try:
        print(json.dumps({"ready": True, "bind": "127.0.0.1", "ports": [3330, 3331, 3332], "viewerPid": child.pid, "mode": "two_view_preview"}), flush=True)
        server.serve_forever(poll_interval=.5)
    finally:
        server.server_close()
        geometry.rr.disconnect()
        child.terminate()
        child.wait(timeout=10)


if __name__ == "__main__":
    main()
