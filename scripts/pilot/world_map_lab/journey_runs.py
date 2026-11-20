"""Manage one local RGB simulation at a time and retain each attempt's telemetry."""

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path


class JourneyRuns:
    def __init__(self, folder, port, adapter):
        self.root = folder / "journey/runs"
        self.folder = folder
        self.port = port
        self.adapter = adapter
        self.lock = threading.Lock()
        self.process = None
        self.current = None

    def directory(self, ident):
        if not isinstance(ident, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,70}", ident):
            raise ValueError("invalid attempt")
        return self.root / ident

    def start(self, route, model):
        if (
            model not in ("faggio", "premier")
            or route.get("status") != "complete"
            or not route.get("legs")
        ):
            raise ValueError("a connected route and a known vehicle are required")
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                raise RuntimeError("Уже идёт проверка маршрута")
            ident = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
            dest = self.directory(ident)
            dest.mkdir(parents=True)
            (dest / "route.json").write_text(
                json.dumps(route, separators=(",", ":")), encoding="utf8"
            )
            (dest / "settings.json").write_text(json.dumps({"model": model}), encoding="utf8")
            args = [
                sys.executable,
                "-u",
                "-m",
                "scripts.pilot.world_map_lab.check_journey_rgb",
                "--url",
                f"http://127.0.0.1:{self.port}",
                "--folder",
                str(self.folder),
                "--run-dir",
                str(dest),
                "--model",
                model,
                "--realtime",
            ]
            if self.adapter:
                args.extend(["--adapter", str(self.adapter)])
            with (dest / "run.log").open("wb") as log:
                self.process = subprocess.Popen(
                    args,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    cwd=Path(__file__).resolve().parents[3],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    env={**os.environ, "PYTHONUTF8": "1"},
                )
            self.current = ident
            return {"id": ident, "state": "starting"}

    def state(self, ident):
        dest = self.directory(ident)
        if not (dest / "route.json").is_file():
            raise KeyError("unknown attempt")
        path = dest / "terminal.json" if (dest / "terminal.json").is_file() else dest / "state.json"
        value = (
            json.loads(path.read_bytes()) if path.is_file() else {"state": "starting", "row": None}
        )
        if (ident != self.current or self.process.poll() is not None) and value["state"] in (
            "starting",
            "running",
        ):
            value["state"] = "worker_failed"
        return {"id": ident, **value}

    def stop(self, ident):
        dest = self.directory(ident)
        if ident != self.current:
            raise KeyError("unknown active attempt")
        (dest / "stop").touch()
        return self.state(ident)

    def close(self):
        if self.current and self.process.poll() is None:
            self.stop(self.current)
