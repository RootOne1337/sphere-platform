"""Bounded native aggregates. Peer identity comes from the authenticated runtime."""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from backend.websocket.direct_probe_protocol import InvalidDirectProbe, session_id

NATIVE_HISTORY_MIN_AGENT_CODE = 10255
NATIVE_REPORT_BYTES = 2048
NATIVE_REPORT_LIMIT = 2913  # 32 setup samples, <=2880 sparse samples and one closure.
Elapsed = Annotated[int, Field(ge=0, le=8 * 3600 * 1000 + 30000)]
Count = Annotated[int, Field(ge=0, le=256)]
Counter = Annotated[int, Field(ge=0, le=2**53 - 1)]
Stage = Literal[
    "offer_received", "factory_ready", "peer_ready", "remote_description_set", "answer_created",
    "local_description_set", "gathering", "gathered", "answer_sent", "channel_received", "channel_open",
    "remote_description_failed", "answer_creation_failed", "local_description_failed", "peer_setup_failed",
    "answer_delivery_failed", "connection_failed", "closed", "expired",
]
TERMINAL_STAGES = frozenset({
    "remote_description_failed", "answer_creation_failed", "local_description_failed", "peer_setup_failed",
    "answer_delivery_failed", "connection_failed", "closed", "expired",
})


class NativeIceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    local_candidates: Count
    remote_candidates: Count
    pairs: Count
    checking_pairs: Count
    failed_pairs: Count
    succeeded_pairs: Count
    requests_sent: Counter | None
    requests_received: Counter | None
    responses_sent: Counter | None
    responses_received: Counter | None
    dtls_state: Literal["new", "connecting", "connected", "closed", "failed"] | None

    @model_validator(mode="after")
    def consistent_counts(self) -> NativeIceSnapshot:
        if self.checking_pairs + self.failed_pairs + self.succeeded_pairs > self.pairs:
            raise ValueError("inconsistent_pair_counts")
        if self.local_candidates + self.remote_candidates + self.pairs > 256:
            raise ValueError("inconsistent_row_counts")
        return self


class NativePeerSample(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1]
    sequence: Annotated[int, Field(ge=1, le=NATIVE_REPORT_LIMIT)]
    kind: Literal["sample", "final"]
    stage: Stage
    profile: Literal["host", "controlled-stun", "public-stun", "turn"]
    elapsed_ms: Elapsed
    answer_sent: bool
    network: NativeIceSnapshot | None
    network_sample_elapsed_ms: Elapsed | None
    network_sample_age_ms: Elapsed | None

    @model_validator(mode="before")
    @classmethod
    def exact_version(cls, value: Any) -> Any:
        if not isinstance(value, dict) or type(value.get("schema_version")) is not int:
            raise ValueError("invalid_schema_version")
        return value

    @model_validator(mode="after")
    def consistent_observation(self) -> NativePeerSample:
        if (self.kind == "final") != (self.stage in TERMINAL_STAGES):
            raise ValueError("invalid_terminal_stage")
        sampled, age = self.network_sample_elapsed_ms, self.network_sample_age_ms
        if self.network is None:
            if sampled is not None or age is not None:
                raise ValueError("unobserved_network_age")
        elif sampled is None or age is None or sampled + age != self.elapsed_ms:
            raise ValueError("inconsistent_network_age")
        return self


def native_peer_report(data: Any) -> tuple[str, NativePeerSample] | None:
    """Reject arbitrary payloads before they reach a queue or a persistent record."""
    if not isinstance(data, dict) or data.keys() != {"type", "session_id", "sample"}:
        return None
    try:
        if data["type"] != "direct_probe_telemetry" or len(json.dumps(data, allow_nan=False).encode()) > NATIVE_REPORT_BYTES:
            return None
        return session_id(data["session_id"]), NativePeerSample.model_validate(data["sample"])
    except (InvalidDirectProbe, ValidationError, ValueError, TypeError, RecursionError):
        return None
