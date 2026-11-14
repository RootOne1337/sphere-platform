"""Finite loopback-only viewer for four fixed recorded-trace preview assets.

No directory listing, generic file access, device credentials, upload, job or
input endpoints. This is intentionally separate from a future LIVE observer.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

FILES = ("index.html", "viewer.js", "timeline.json", "preview.mp4")


def byte_range(value: str | None, size: int) -> tuple[int, int, bool]:
    if value is None:
        return 0, size - 1, False
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
    if not match or not any(match.groups()):
        raise ValueError("invalid_range")
    a, b = match.groups()
    first = int(a) if a else max(0, size - int(b))
    last = min(size - 1, int(b)) if a and b else size - 1
    if not 0 <= first <= last < size:
        raise ValueError("invalid_range")
    return first, last, True


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler):
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


def previous_capability(path: Path, port: int) -> str:
    """Preserve an expired viewer URL for the ongoing local review, not its TTL."""
    if path.is_symlink() or path.stat().st_size > 4096:
        raise ValueError("invalid_previous_viewer_state")
    previous = json.loads(path.read_bytes())
    url = urlsplit(previous.get("url", ""))
    if (
        url.scheme != "http"
        or url.hostname != "127.0.0.1"
        or url.port != port
        or previous.get("port") != port
        or previous.get("deviceActions") != 0
        or not re.fullmatch(r"/[A-Za-z0-9_-]{32}/", url.path)
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("invalid_previous_viewer_state")
    return url.path[1:-1]


def serve(
    directory: Path, port: int, seconds: int, state: Path, previous_state: Path | None = None
):
    root = directory.resolve(strict=True)
    if not 1024 <= port <= 65535 or not 60 <= seconds <= 3600 or state.exists():
        raise ValueError("viewer_budget_or_existing_state")
    report = json.loads((root / "report.json").read_bytes())
    if (
        report.get("scope") != "RECORDED_CAMERA_TRACE_NOT_NAVIGATION"
        or report.get("liveLocalization") is not False
    ):
        raise ValueError("recorded_preview_required")
    for name in FILES:
        file = root / name
        if (
            file.is_symlink()
            or file.resolve(strict=True).parent != root
            or not 0 < file.stat().st_size < 256 * 1024**2
        ):
            raise ValueError("viewer_asset_bound")
    token = (
        previous_capability(previous_state, port) if previous_state else secrets.token_urlsafe(24)
    )
    prefix = "/" + token + "/"
    deadline = time.monotonic() + seconds

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.asset(False)

        def do_HEAD(self):
            self.asset(True)

        def asset(self, head):
            host = self.headers.get("Host")
            path = urlsplit(self.path).path
            if (
                host not in (f"127.0.0.1:{port}", f"localhost:{port}")
                or time.monotonic() >= deadline
                or not path.startswith(prefix)
                or path[len(prefix) :] not in ("", *FILES)
            ):
                self.send_error(404)
                return
            file = root / (path[len(prefix) :] or "index.html")
            size = file.stat().st_size
            try:
                start, end, partial = byte_range(self.headers.get("Range"), size)
            except ValueError:
                self.send_error(416)
                return
            self.send_response(206 if partial else 200)
            self.send_header(
                "Content-Type", mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            )
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "private, no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'",
            )
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if head:
                return
            try:
                with file.open("rb") as stream:
                    stream.seek(start)
                    remaining = end - start + 1
                    while remaining and time.monotonic() < deadline:
                        data = stream.read(min(65536, remaining))
                        if not data:
                            break
                        self.wfile.write(data)
                        remaining -= len(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
                pass

    with Server(("127.0.0.1", port), Handler) as server:
        server.timeout = 1
        url = f"http://127.0.0.1:{port}{prefix}"
        with state.open("x", encoding="utf-8") as output:
            json.dump(
                dict(pid=os.getpid(), url=url, port=port, seconds=seconds, deviceActions=0), output
            )
        print(json.dumps(dict(ready=True, url=url, finiteSeconds=seconds)), flush=True)
        while time.monotonic() < deadline:
            server.handle_request()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=3348)
    parser.add_argument("--seconds", type=int, default=1800)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument(
        "--previous-state",
        type=Path,
        help="Reuse the URL of an expired owned viewer; bind still refuses an occupied port",
    )
    args = parser.parse_args()
    serve(args.directory, args.port, args.seconds, args.state, args.previous_state)


if __name__ == "__main__":
    main()
