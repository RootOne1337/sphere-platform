"""Bounded local RGB/prediction pipe. No token, network or Android input API.

The child is an explicitly selected, trusted local Python script, not a sandbox.
It must load/warm its model before calling model_stdio.serve(). Torch and model
dependencies stay in that child's environment, separate from the media worker.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from motor_worker.policy import ActionChunk, PolicyFrame, PolicyRequest, PolicyResult, finite
from motor_worker.protocol import ProtocolError, integer

PROTOCOL = "sphere-policy-stdio-v1"
ADAPTERS = frozenset(("nitrogen-decoded-v1", "open-p2p-150m-decoded-v1"))
LINE_LIMIT = 32768
# Deliberately do not inherit SPHERE_ACCESS_TOKEN, HF_TOKEN, cloud credentials,
# PYTHONPATH, startup hooks or the rest of the parent's secret-bearing environment.
ENV_KEYS = frozenset(
    (
        "SYSTEMROOT",
        "WINDIR",
        "PATH",
        "LOCALAPPDATA",
        "APPDATA",
        "USERPROFILE",
        "TEMP",
        "TMP",
        "HOME",
        "LANG",
        "LC_ALL",
        "HIP_PATH",
        "ROCM_PATH",
        "HIP_VISIBLE_DEVICES",
        "CUDA_VISIBLE_DEVICES",
    )
)


def _json_object(raw: bytes) -> dict:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate_key")
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=unique)
        if type(value) is not dict:
            raise ValueError("not_object")
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ProtocolError("policy_process_invalid_message") from exc


@dataclass(frozen=True)
class ProcessPolicyConfig:
    python: Path
    script: Path
    adapter: str
    arguments: tuple[str, ...] = ()
    startup_timeout: float = 120

    def __post_init__(self) -> None:
        if (
            any(
                not isinstance(v, Path) or not v.is_absolute() or not v.is_file()
                for v in (self.python, self.script)
            )
            or type(self.adapter) is not str
            or self.adapter not in ADAPTERS
            or type(self.arguments) is not tuple
            or len(self.arguments) > 16
            or any(type(v) is not str or len(v) > 4096 or "\0" in v for v in self.arguments)
            or not finite(self.startup_timeout, 0.01, 300)
        ):
            raise ProtocolError("invalid_policy_process_config")


class ProcessPolicy:
    def __init__(self, config: ProcessPolicyConfig):
        self.config = config
        self.process: asyncio.subprocess.Process | None = None
        self.ready = False
        self.closed = False
        self.active = False
        self.last_request = 0
        self.responses = 0
        self.last_inference_ms: float | None = None
        self.retirement: asyncio.Task | None = None
        self.starting = False
        self.spawn_task: asyncio.Task | None = None
        self.read_lock = asyncio.Lock()
        self.samples: deque[dict] = deque(maxlen=64)
        self.failure: str | None = None

    async def _read(self) -> dict:
        try:
            async with self.read_lock:
                raw = await self.process.stdout.readline()
        except ValueError as exc:
            raise ProtocolError("policy_process_message_too_large") from exc
        if not raw:
            raise ProtocolError("policy_process_eof")
        if len(raw) > LINE_LIMIT or not raw.endswith(b"\n"):
            raise ProtocolError("policy_process_message_too_large")
        return _json_object(raw)

    async def start(self) -> None:
        if self.closed or self.starting or self.process is not None:
            raise ProtocolError("policy_process_not_startable")
        self.starting = True
        # Keep ownership of process creation even if the caller is cancelled at
        # spawn time. No shell, detached helper or implicit restart is involved.
        spawn = asyncio.create_task(
            asyncio.create_subprocess_exec(
                str(self.config.python),
                "-u",
                str(self.config.script),
                *self.config.arguments,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=LINE_LIMIT,
                env={k: v for k, v in os.environ.items() if k.upper() in ENV_KEYS},
            )
        )
        self.spawn_task = spawn
        try:
            self.process = await asyncio.shield(spawn)
            if self.closed:
                raise ProtocolError("policy_process_closed_during_startup")
            async with asyncio.timeout(self.config.startup_timeout):
                ready = await self._read()
            if ready != {"protocol": PROTOCOL, "kind": "ready", "adapter": self.config.adapter}:
                raise ProtocolError("policy_process_readiness_mismatch")
            if self.closed:
                raise ProtocolError("policy_process_closed_during_startup")
            self.ready = True
        except BaseException as exc:
            self.failure = (
                str(exc)
                if isinstance(exc, ProtocolError)
                else "policy_process_start_cancelled"
                if isinstance(exc, asyncio.CancelledError)
                else "policy_process_start_timeout"
                if isinstance(exc, TimeoutError)
                else "policy_process_start_failed"
            )
            if self.process is None:
                try:
                    self.process = await asyncio.shield(spawn)
                except (OSError, asyncio.CancelledError):
                    pass
            await self.close()
            if isinstance(exc, (asyncio.CancelledError, ProtocolError)):
                raise
            raise ProtocolError("policy_process_start_failed") from exc
        finally:
            self.starting = False

    async def predict(self, request: PolicyRequest) -> PolicyResult:
        if self.closed or not self.ready or self.active:
            raise ProtocolError("policy_process_unavailable")
        if (
            type(request) is not PolicyRequest
            or type(request.frame) is not PolicyFrame
            or not integer(request.request_id, self.last_request + 1, 2**53 - 1)
            or not finite(request.deadline, 0, float("inf"))
            or not 0 < request.deadline - time.perf_counter() <= 2
        ):
            raise ProtocolError("invalid_policy_process_request")
        self.active = True
        self.last_request = request.request_id
        frame = request.frame
        header = {
            "requestId": request.request_id,
            "epoch": frame.capture_epoch,
            "receiverSequence": frame.receiver_sequence,
            "width": frame.width,
            "height": frame.height,
        }
        started = time.perf_counter()
        try:
            async with asyncio.timeout(max(0, request.deadline - time.perf_counter())):
                self.process.stdin.write(json.dumps(header).encode("utf-8") + b"\n")
                self.process.stdin.write(frame.rgb24)
                await self.process.stdin.drain()
                reply = await self._read()
            if (
                reply.keys()
                != {"requestId", "epoch", "receiverSequence", "prediction", "inferenceWallMs"}
                or type(reply["requestId"]) is not int
                or reply["requestId"] != request.request_id
                or type(reply["receiverSequence"]) is not int
                or reply["receiverSequence"] != frame.receiver_sequence
                or reply["epoch"] != frame.capture_epoch
                or not finite(reply["inferenceWallMs"], 0, 300000)
            ):
                raise ProtocolError("policy_process_result_binding_mismatch")
            chunk = (
                ActionChunk.from_nitrogen(reply["prediction"], ticks_per_second=60)
                if self.config.adapter == "nitrogen-decoded-v1"
                else ActionChunk.from_open_p2p(reply["prediction"])
            )
            if time.perf_counter() >= request.deadline:
                raise ProtocolError("policy_process_result_expired")
            self.responses += 1
            self.last_inference_ms = reply["inferenceWallMs"]
            self.samples.append(
                {
                    "requestId": request.request_id,
                    "receiverSequence": frame.receiver_sequence,
                    "pipeRoundtripMs": round((time.perf_counter() - started) * 1000, 3),
                    "modelReportedWallMs": reply["inferenceWallMs"],
                }
            )
            return PolicyResult(
                request.request_id, frame.capture_epoch, frame.receiver_sequence, chunk
            )
        except BaseException as exc:
            # These ProtocolErrors originate only in our fixed validators;
            # never use child stdout/stderr/exception text as a reason code.
            self.failure = (
                str(exc)
                if isinstance(exc, ProtocolError)
                else "policy_process_request_cancelled"
                if isinstance(exc, asyncio.CancelledError)
                else "policy_process_request_timeout"
                if isinstance(exc, TimeoutError)
                else "policy_process_request_failed"
            )
            # A half-written request, timeout or unknown reply cannot be retried.
            # Retire the child; its late GPU result must never service another frame.
            await self.close()
            if isinstance(exc, (asyncio.CancelledError, ProtocolError)):
                raise
            raise ProtocolError("policy_process_request_failed") from exc
        finally:
            self.active = False

    async def _retire(self) -> None:
        if self.process is None and self.spawn_task is not None:
            try:
                self.process = await asyncio.shield(self.spawn_task)
            except OSError:
                return
        if self.process is None:
            return
        if self.process.returncode is None:
            try:
                self.process.kill()
            except ProcessLookupError:
                pass
        try:
            async with asyncio.timeout(2):
                # A flooded stdout may have paused its pipe transport. Drain
                # after kill so Process.wait can observe all pipe closures.
                async with self.read_lock:
                    while await self.process.stdout.read(65536):
                        pass
                await self.process.wait()
        except TimeoutError as exc:
            raise ProtocolError("policy_process_cleanup_unconfirmed") from exc
        if self.process.stdin:
            self.process.stdin.close()

    async def close(self) -> None:
        self.closed, self.ready = True, False
        if self.retirement is None:
            self.retirement = asyncio.create_task(self._retire())
        await asyncio.shield(self.retirement)

    async def __aenter__(self) -> ProcessPolicy:
        await self.start()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    def report(self) -> dict:
        return {
            "protocol": PROTOCOL,
            "adapter": self.config.adapter,
            "failure": self.failure,
            "responses": self.responses,
            "lastInferenceWallMs": self.last_inference_ms,
            "ready": self.ready,
            "closed": self.closed,
            "cleanupConfirmed": self.closed
            and self.retirement is not None
            and self.retirement.done()
            and not self.retirement.cancelled()
            and self.retirement.exception() is None
            and (self.process is None or self.process.returncode is not None),
            "credentialsInherited": False,
            "physicalActionsSent": 0,
            "modelWeightsVerifiedByBridge": False,
            "sampleTailLimit": 64,
            "samples": list(self.samples),
        }
