"""Versioned visual route bundles and conservative sequential observation.

No screen coordinates become world coordinates and no imported route can inject
input. Geometry/scene/goal qualification remains the executor's responsibility.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from motor_worker.landmarks import RouteKeyframe, RouteViewMatcher, RouteViewProfile
from motor_worker.policy import PolicyFrame, epoch_valid, finite
from motor_worker.protocol import ProtocolError, integer, message


def _payload(data):
    return (json.dumps(data, separators=(",", ":"), allow_nan=False)+"\n").encode()


def _read(path, limit):
    if path.is_symlink() or not path.is_file():
        raise ProtocolError("route_file_unavailable")
    with path.open("rb") as source:
        raw = source.read(limit+1)
    if len(raw) > limit:
        raise ProtocolError("route_file_quota")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ProtocolError("route_file_encoding") from None


@dataclass(frozen=True)
class TaughtRoute:
    id: str
    world_revision: str
    source_episode: str
    mode: str
    source_manifest_sha256: str
    profile: RouteViewProfile
    views: tuple[RouteKeyframe, ...]
    source_ticks: tuple[int, ...]

    def __post_init__(self):
        if (not all(epoch_valid(v) for v in (self.id, self.world_revision, self.source_episode))
                or type(self.mode) is not str or self.mode not in {"pedestrian", "vehicle"}
                or type(self.source_manifest_sha256) is not str
                or len(self.source_manifest_sha256) != 64
                or any(c not in "0123456789abcdef" for c in self.source_manifest_sha256)
                or type(self.profile) is not RouteViewProfile
                or type(self.views) is not tuple or not 2 <= len(self.views) <= 64
                or any(type(v) is not RouteKeyframe for v in self.views)
                or len({v.id for v in self.views}) != len(self.views)
                or any(v.profile_revision != self.profile.revision for v in self.views)
                or len({v.pipeline_sha256 for v in self.views}) != 1
                or type(self.source_ticks) is not tuple or len(self.source_ticks) != len(self.views)
                or any(not integer(t, 0, 300*90000) for t in self.source_ticks)
                or any(a >= b for a, b in zip(self.source_ticks, self.source_ticks[1:]))):
            raise ProtocolError("invalid_taught_route")

    def save(self, directory):
        root = Path(directory)
        if not root.is_absolute() or root.parent.resolve(strict=True) != root.parent:
            raise ProtocolError("route_path_must_be_resolved_absolute")
        root.mkdir()
        entries = []
        for view, tick in zip(self.views, self.source_ticks):
            raw = view.encode().encode()
            with (root/(view.id+".json")).open("xb") as dest:
                dest.write(raw)
            entries.append(dict(id=view.id, source_ticks=tick, sha256=hashlib.sha256(raw).hexdigest()))
        raw = _payload(dict(schema_version=1, id=self.id, world_revision=self.world_revision,
                            source_episode=self.source_episode, mode=self.mode,
                            source_manifest_sha256=self.source_manifest_sha256,
                            profile=json.loads(self.profile.encode()), views=entries,
                            execution_qualified=False, world_pose_known=False))
        with (root/"route.json").open("xb") as dest:
            dest.write(raw)
        with (root/"COMPLETE").open("xb") as dest:
            dest.write(hashlib.sha256(raw).hexdigest().encode()+b"\n")

    @classmethod
    def load(cls, directory):
        root = Path(directory)
        if root.is_symlink() or not root.is_dir():
            raise ProtocolError("route_directory_unavailable")
        raw = _read(root/"route.json", 64*1024)
        complete = _read(root/"COMPLETE", 65)
        if complete != hashlib.sha256(raw.encode()).hexdigest()+"\n":
            raise ProtocolError("route_manifest_integrity")
        data = message(raw, 64*1024, strict_numbers=True)
        keys = {"schema_version", "id", "world_revision", "source_episode", "mode", "source_manifest_sha256",
                "profile", "views", "execution_qualified", "world_pose_known"}
        if (data.keys() != keys or not integer(data["schema_version"], 1, 1)
                or data["execution_qualified"] is not False or data["world_pose_known"] is not False
                or type(data["views"]) is not list or not 2 <= len(data["views"]) <= 64):
            raise ProtocolError("invalid_taught_route_schema")
        views, ticks = [], []
        for entry in data["views"]:
            if (type(entry) is not dict or entry.keys() != {"id", "source_ticks", "sha256"}
                    or not epoch_valid(entry["id"])):
                raise ProtocolError("invalid_route_entry")
            content = _read(root/(entry["id"]+".json"), 256*1024)
            if hashlib.sha256(content.encode()).hexdigest() != entry["sha256"]:
                raise ProtocolError("route_reference_integrity")
            view = RouteKeyframe.parse(content)
            if view.id != entry["id"]:
                raise ProtocolError("route_reference_identity")
            views.append(view)
            ticks.append(entry["source_ticks"])
        expected = {"route.json", "COMPLETE", *(v.id+".json" for v in views)}
        for p in root.iterdir():
            if p.name not in expected:
                raise ProtocolError("route_unexpected_file")
        return cls(data["id"], data["world_revision"], data["source_episode"], data["mode"],
                   data["source_manifest_sha256"], RouteViewProfile.parse(json.dumps(data["profile"])),
                   tuple(views), tuple(ticks))


@dataclass(frozen=True)
class RouteEstimate:
    state: str
    reason: str
    checkpoint: int | None
    next_checkpoint: int | None
    capture_epoch: str
    receiver_sequence: int
    received_at: float


class RouteProgress:
    """Three consistent adjacent views; no blind timed replay or jump to far views.

    Startup requires the first taught checkpoint. Re-localization is local only.
    Seeing the last checkpoint means end_view, never confirmed arrival.
    """

    def __init__(self, route, *, capture_epoch, episode_id, goal_revision, clock):
        if (type(route) is not TaughtRoute
                or not all(epoch_valid(v) for v in (capture_epoch, episode_id, goal_revision))
                or not callable(clock)):
            raise ProtocolError("invalid_route_progress_binding")
        self.route, self.epoch, self.episode, self.goal = route, capture_epoch, episode_id, goal_revision
        self.clock = clock
        self.matcher = RouteViewMatcher(route.profile, clock=clock)
        if any(v.pipeline_sha256 != self.matcher.pipeline_sha256 for v in route.views):
            raise ProtocolError("route_pipeline_not_current")
        self.index = self.candidate = None
        self.confirmations = self.sequence = 0
        self.last_received = self.last_now = None
        self.terminal = None

    def observe(self, frame, *, episode_id, goal_revision, scene):
        now = self.clock()
        if (type(frame) is not PolicyFrame or not finite(now, 0, float("inf"))
                or type(scene) is not str or scene not in {"active", "menu", "disconnected", "unknown"}):
            self.candidate, self.confirmations = None, 0
            raise ProtocolError("invalid_route_progress_observation")
        if self.terminal is None:
            if frame.capture_epoch != self.epoch or episode_id != self.episode or goal_revision != self.goal:
                self.terminal = "route_episode_goal_or_capture_changed"
            elif frame.receiver_sequence <= self.sequence or self.last_now is not None and now < self.last_now:
                self.terminal = "route_observation_order"
            elif self.last_received is not None and frame.received_at <= self.last_received:
                self.terminal = "route_observation_clock_order"
            elif scene == "disconnected":
                self.terminal = "game_disconnected"
        gap = self.last_received is not None and frame.received_at - self.last_received > 0.5
        self.sequence, self.last_received, self.last_now = frame.receiver_sequence, frame.received_at, now

        def result(state, reason):
            return RouteEstimate(state, reason, self.index,
                                 None if state != "tracking" or self.index is None
                                 or self.index+1 == len(self.route.views) else self.index+1,
                                 frame.capture_epoch, frame.receiver_sequence, frame.received_at)

        def unknown(reason):
            self.candidate, self.confirmations = None, 0
            return result("unknown", reason)

        if self.terminal:
            return unknown(self.terminal)
        if scene != "active":
            return unknown("game_scene_not_verified")
        if gap:
            return unknown("route_observation_gap")
        indices = tuple(range(0, min(3, len(self.route.views)))) if self.index is None else tuple(
            range(max(0, self.index-1), min(len(self.route.views), self.index+2)))
        match = self.matcher.compare(frame, tuple(self.route.views[i] for i in indices))
        if match.status != "matched":
            return unknown(match.reason)
        found = next(i for i in indices if self.route.views[i].id == match.keyframe_id)
        if self.index is None and found != 0:
            return unknown("route_start_not_verified")
        if self.index is not None and found < self.index:
            return unknown("route_backward_view_requires_relocalization")
        self.confirmations = self.confirmations+1 if found == self.candidate else 1
        self.candidate = found
        if self.confirmations < 3:
            return result("confirming", "route_view_temporal_confirmation")
        self.index = found
        return result("end_view" if found == len(self.route.views)-1 else "tracking", "visual_route_context_not_pose")
