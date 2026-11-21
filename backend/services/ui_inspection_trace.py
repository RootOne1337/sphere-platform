"""Bounded scalar diagnostics for one UI snapshot, never command/XML/error text."""

import re
import time
from dataclasses import dataclass, field


@dataclass
class UiInspectionTrace:
    started: float = field(default_factory=time.monotonic)
    stage: str = "geometry_before"
    stage_started: float = field(default_factory=time.monotonic)
    stage_ms: dict[str, int] = field(default_factory=dict)
    rpc_count: int = 0
    failed_stage: str | None = None
    reason: str | None = None
    native_exit_code: int | None = None
    cleanup_confirmed: bool = False
    lock_release_confirmed: bool = False

    def enter(self, stage: str) -> None:
        now = time.monotonic()
        self.stage_ms[self.stage] = max(0, int((now - self.stage_started) * 1000))
        self.stage, self.stage_started = stage, now

    def fail(self, reason: str) -> None:
        # A failed cleanup must not overwrite the original read failure, or
        # turn an otherwise valid snapshot into a failed tree read.
        if self.failed_stage is None and self.stage != "cleanup":
            self.failed_stage, self.reason = self.stage, reason

    def native_failure(self, error: object) -> None:
        reason = "native_command_failed"
        exit_code = None
        if isinstance(error, str) and len(error) <= 256:
            match = re.fullmatch(r"Shell command exited with code ([1-9][0-9]{0,2})", error)
            if match and int(match[1]) <= 255:
                reason, exit_code = "native_exit_nonzero", int(match[1])
            elif error == "device_input_busy":
                reason = "native_input_busy"
            elif error == "input_handoff_unknown":
                reason = "native_input_outcome_unknown"
        self.fail(reason)
        if self.stage != "cleanup" and self.failed_stage == self.stage:
            self.native_exit_code = exit_code

    @property
    def elapsed_ms(self) -> int:
        return max(0, int((time.monotonic() - self.started) * 1000))

    def headers(self, snapshot_id: str) -> dict[str, str]:
        headers = {
            "Cache-Control": "no-store",
            "X-Sphere-Ui-Snapshot": snapshot_id,
            "X-Sphere-Ui-Stage": self.failed_stage or "complete",
            "X-Sphere-Ui-Reason": self.reason or "ok",
            "X-Sphere-Ui-Cleanup": "confirmed" if self.cleanup_confirmed else "unconfirmed",
            "X-Sphere-Ui-Lock-Release": "confirmed" if self.lock_release_confirmed else "unconfirmed",
            "X-Sphere-Ui-Elapsed-Ms": str(self.elapsed_ms),
            "X-Sphere-Ui-Rpc-Count": str(self.rpc_count),
        }
        if self.native_exit_code is not None:
            headers["X-Sphere-Ui-Native-Exit-Code"] = str(self.native_exit_code)
        return headers
