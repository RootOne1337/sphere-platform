"""Source quality preferences and the installed APK's bounded application receipt."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StreamQualitySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    profile: Literal["auto", "detail", "economy"] = "auto"
    max_fps: int | None = Field(default=None, ge=1, le=60)
    max_bitrate_bps: int | None = Field(default=None, ge=100_000, le=32_000_000)


class ActiveStreamQuality(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)
    source_fps: int = Field(ge=1, le=240)
    codec_max_fps: int = Field(ge=1, le=60)
    target_fps: int = Field(ge=1, le=60)
    max_bitrate_bps: int = Field(ge=1, le=32_000_000)
    target_bitrate_bps: int = Field(ge=1, le=32_000_000)
    adaptation: Literal["source", "webrtc", "legacy_queue"]

    @model_validator(mode="after")
    def limits_are_coherent(self) -> "ActiveStreamQuality":
        if self.target_fps > min(self.source_fps, self.codec_max_fps):
            raise ValueError("target cadence exceeds the admitted source capability")
        if self.target_bitrate_bps > self.max_bitrate_bps:
            raise ValueError("target bitrate exceeds the configured ceiling")
        return self


class StreamQualitySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    supported: bool
    protocol: Literal[1] = 1
    settings: StreamQualitySettings
    active: ActiveStreamQuality | None = None
