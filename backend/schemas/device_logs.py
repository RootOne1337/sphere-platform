"""Explicit coverage of a bounded retained-log read, not an archive export."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DeviceLogReadScope(BaseModel):
    schema_version: Literal[1]
    scope: Literal["recent-file-tail"]
    date: str | None
    truncated: bool
    reasons: list[Literal["file_limit", "line_limit", "scan_byte_limit", "response_byte_limit", "oversized_line"]]
    bytes_scanned: int = Field(ge=0, le=2097152)
    scan_byte_limit: Literal[2097152]
    response_lines_bytes: int = Field(ge=2, le=524288)
    response_byte_limit: Literal[524288]
    max_line_bytes: Literal[16384]
    omitted_oversized_lines: int = Field(ge=0)
    files_scanned: int = Field(ge=0, le=3)
    files_available: int = Field(ge=0, le=128)
    max_files: Literal[3]
    concurrent_reads_per_worker: Literal[4]


class DeviceLogsResponse(BaseModel):
    device_id: str
    lines: list[str] = Field(max_length=10000)
    total: int = Field(ge=0, le=10000)
    read: DeviceLogReadScope
