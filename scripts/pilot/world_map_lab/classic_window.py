"""Foreground client RGB and expiring keyboard commands for an isolated classic PC drive."""

import ctypes
import json
import threading
import time
from ctypes import wintypes
from pathlib import Path

from scripts.pilot.world_map_lab.export_full_game_world import digest


def desired_keys(row):
    if row["vision"] not in ("matched", "tracked") or row["latency_ms"] >= 250:
        return set()
    if not row.get("drive_enabled", True):
        return set(row.get("keys", []))
    if row["phase"] != "following":
        return set()
    pedal = "brake" if row["terminal_brake"] else row["pedal"]
    keys = {"throttle": {"W"}, "brake": {"S"}, "coast": set()}[pedal]
    return keys


class KeyLease:
    """Continue a valid pedal across observations; expire steering and throttle independently."""

    def __init__(self, focused, send, clock=time.monotonic):
        self.focused, self.send, self.clock = focused, send, clock
        self.deadlines = {}
        self.held = set()
        self.lock = threading.Lock()
        self.stopped = False

    def refresh(self, row, captured):
        now = self.clock()
        with self.lock:
            if now - captured >= 0.25:
                self.deadlines.clear()
                self._tick(now)
                return
            self.deadlines = {key: captured + 0.35 for key in desired_keys(row)}
            if "F" in self.deadlines:
                self.deadlines["F"] = min(captured + 0.35, now + 0.11)
            driving = row.get("drive_enabled", True)
            steering = row["steering"] if driving else row.get("walk_turn", 0.0)
            turning = (driving and row["phase"] == "following") or (
                not driving and row.get("journey_phase") in ("approach", "depart")
            )
            if (
                turning
                and row["vision"] in ("matched", "tracked")
                and row["latency_ms"] < 250
                and abs(steering) > 0.025
            ):
                # Analog pursuit on a digital keyboard. Shorter holds produce less turn.
                self.deadlines["D" if steering > 0 else "A"] = min(
                    captured + 0.35, now + 0.2 * min(1, abs(steering) / 0.35)
                )
            self._tick(now)

    def _tick(self, now):
        if self.stopped or not self.focused():
            self.stopped = True
            self.deadlines.clear()
        wanted = {key for key, end in self.deadlines.items() if end > now}
        for key in sorted(self.held - wanted):
            self.send(key, False)
            self.held.remove(key)
        for key in sorted(wanted - self.held):
            self.send(key, True)
            self.held.add(key)

    def tick(self):
        with self.lock:
            self._tick(self.clock())

    def close(self):
        with self.lock:
            self.stopped = True
            self._tick(self.clock())


def keyboard_sender():
    class Key(ctypes.Structure):
        _fields_ = [
            ("vk", wintypes.WORD),
            ("scan", wintypes.WORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("extra", ctypes.c_size_t),
        ]

    class Mouse(ctypes.Structure):
        _fields_ = [
            ("x", wintypes.LONG),
            ("y", wintypes.LONG),
            ("data", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("extra", ctypes.c_size_t),
        ]

    class Payload(ctypes.Union):
        _fields_ = [("key", Key), ("mouse", Mouse)]

    class Input(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("payload", Payload)]

    send = ctypes.WinDLL("user32", use_last_error=True).SendInput
    send.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
    send.restype = wintypes.UINT
    scans = {"W": 0x11, "S": 0x1F, "A": 0x1E, "D": 0x20, "F": 0x21}

    def event(key, down):
        data = Input(1, Payload(key=Key(0, scans[key], 8 if down else 10, 0, 0)))
        if send(1, ctypes.byref(data), ctypes.sizeof(data)) != 1:
            raise OSError(ctypes.get_last_error(), "GTA keyboard input was not accepted")

    return event


def drive_window(pilot, folder, actuate, movie_path=None, *, keys_file=None):
    import mss
    import numpy as np
    import psutil
    import win32api
    import win32gui
    import win32process

    folder = folder.resolve(strict=True)
    record = json.loads((folder / "sphere-full-world.json").read_bytes())
    exe = folder / "gta_sa.exe"
    if (
        record["gameExecutableSha256"] != digest(exe)
        or record["routeSha256"] != pilot.route_hash
        or digest(folder / "sphere-route.json") != pilot.route_hash
    ):
        raise ValueError("native game and camera policy do not share this staged route")
    print("Waiting for the staged game to be foreground. Escape stops the run.", flush=True)
    window = None
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if win32api.GetAsyncKeyState(27) & 0x8000:
            return
        hwnd = win32gui.GetForegroundWindow()
        if hwnd:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                if Path(psutil.Process(pid).exe()) == exe:
                    window = hwnd
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        time.sleep(0.10)
    if not window:
        raise TimeoutError("the staged game's window was not available")

    def focused():
        return (
            win32gui.GetForegroundWindow() == window
            and not win32gui.IsIconic(window)
            and not win32api.GetAsyncKeyState(27) & 0x8000
        )

    def grab(capture):
        x, y = win32gui.ClientToScreen(window, (0, 0))
        _, _, w, h = win32gui.GetClientRect(window)
        if min(w, h) <= 0 or not focused():
            return None
        screen = np.asarray(capture.grab(dict(left=x, top=y, width=w, height=h)))
        return screen if focused() else None

    origin = time.monotonic()
    send = keyboard_sender() if actuate else None
    events = keys_file.open("x", encoding="utf8") if actuate and keys_file else None

    def send_key(key, down):
        send(key, down)
        if events:
            print(
                json.dumps(dict(t=time.monotonic() - origin, key=key, down=down)),
                file=events,
                flush=True,
            )

    lease = KeyLease(focused, send_key) if actuate else None
    done = threading.Event()
    errors = []

    def watchdog():
        try:
            while not done.wait(0.015):
                lease.tick()
                if lease.stopped:
                    done.set()
                    return
        except Exception as exc:
            errors.append(exc)
            done.set()

    def record():
        from fractions import Fraction

        import av

        try:
            with (
                movie_path.open("xb") as file,
                av.open(file, "w", format="mp4", options={"movflags": "+faststart"}) as out,
                mss.mss() as capture,
            ):
                stream = None
                tick = -1
                while not done.is_set() and focused():
                    stamp = time.monotonic()
                    n = int((stamp - origin) * 30)
                    if n <= tick:
                        done.wait(max(0.001, origin + (tick + 1) / 30 - stamp))
                        continue
                    bgra = grab(capture)
                    if bgra is None:
                        break
                    h, w = bgra.shape[:2]
                    if stream is None:
                        stream = out.add_stream("libx264", rate=30)
                        stream.width = w - w % 2
                        stream.height = h - h % 2
                        stream.pix_fmt = "yuv420p"
                        stream.options = {"preset": "veryfast", "crf": "19"}
                    if (w - w % 2, h - h % 2) != (stream.width, stream.height):
                        raise ValueError("native viewport resized during capture")
                    frame = av.VideoFrame.from_ndarray(
                        bgra[: stream.height, : stream.width], format="bgra"
                    )
                    frame.pts = n
                    frame.time_base = Fraction(1, 30)
                    for packet in stream.encode(frame):
                        out.mux(packet)
                    tick = n
                if stream is not None:
                    for packet in stream.encode():
                        out.mux(packet)
        except Exception as exc:
            errors.append(exc)
            done.set()

    recorder = threading.Thread(target=record, daemon=True) if movie_path else None
    worker = threading.Thread(target=watchdog, daemon=True) if lease else None
    if worker:
        worker.start()
    if recorder:
        recorder.start()
    try:
        with mss.mss() as capture:
            while not done.is_set() and focused() and time.monotonic() - origin < 1800:
                stamp = time.monotonic()
                bgra = grab(capture)
                if bgra is None:
                    break
                rgb = np.ascontiguousarray(bgra[:, :, 2::-1])
                row = pilot.frame(rgb, stamp - origin, stamp)
                if lease:
                    lease.refresh(row, stamp)
                yield row
                if row.get("goal_seen"):
                    break
                if row.get("controller_finished"):
                    break
                done.wait(max(0.0, stamp + 0.20 - time.monotonic()))
    finally:
        done.set()
        if worker:
            worker.join()
        if lease:
            lease.close()
        if events:
            events.close()
        if recorder:
            recorder.join()
    if errors:
        raise RuntimeError("native input or capture worker stopped") from errors[0]
