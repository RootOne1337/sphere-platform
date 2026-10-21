"""Versioned, secret-bearing profile input; preflight never persists or applies it."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

SPHERE_PACKAGE = "com.sphereplatform.agent"


class AppTrafficPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["selected_apps"] = "selected_apps"
    included_packages: list[str] = Field(min_length=1, max_length=64)
    control_plane: Literal["bypass"] = "bypass"
    kill_switch: Literal["selected_apps"] = "selected_apps"
    ipv6: Literal["block", "tunnel"] = "block"

    @field_validator("included_packages")
    @classmethod
    def check_packages(cls, packages: list[str]) -> list[str]:
        import re

        if len(set(packages)) != len(packages):
            raise ValueError("duplicate_package")
        for package in packages:
            if len(package) > 255 or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+", package):
                raise ValueError("invalid_package")
            if package == SPHERE_PACKAGE or package.startswith(SPHERE_PACKAGE + "."):
                raise ValueError("control_application_must_bypass")
        return packages


class VPNProfilePreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    schema_version: Literal[1] = 1
    provider_id: Literal["android-amneziawg", "legacy-root"] = "android-amneziawg"
    protocol: Literal["wireguard", "amneziawg"]
    protocol_version: Literal["1", "1.5", "2", "3.1"]
    config_text: SecretStr = Field(min_length=1, max_length=65536, repr=False)
    traffic_policy: AppTrafficPolicy


class VPNProfileIssue(BaseModel):
    code: str
    line: int | None = None


class VPNProviderCapability(BaseModel):
    provider_id: str
    contract_version: Literal[1] = 1
    execution_available: bool
    app_isolation_available: bool
    supported_protocol_versions: list[str]
    reason: str


class VPNProfilePreflightResponse(BaseModel):
    schema_version: Literal[1] = 1
    config_valid: bool
    apply_allowed: Literal[False] = False
    persisted: Literal[False] = False
    execution_confirmed: Literal[False] = False
    provider: VPNProviderCapability
    protocol: str
    protocol_version: str
    traffic_policy: AppTrafficPolicy
    endpoint: str | None = None
    features: list[str]
    issues: list[VPNProfileIssue]
    blockers: list[str]


def provider_capabilities() -> list[VPNProviderCapability]:
    # No installed, accepted Android app-scoped provider yet. Recognizing a
    # configuration version is deliberately NOT advertised as runtime support.
    return [
        VPNProviderCapability(
            provider_id="android-amneziawg", execution_available=False,
            app_isolation_available=False, supported_protocol_versions=[],
            reason="android_provider_not_integrated",
        ),
        VPNProviderCapability(
            provider_id="legacy-root", execution_available=False,
            app_isolation_available=False, supported_protocol_versions=[],
            reason="legacy_root_has_no_control_plane_isolation",
        ),
    ]
