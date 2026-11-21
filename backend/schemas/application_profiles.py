"""Validated application metadata; server entries are never probed here."""

import re
import uuid
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

MAX_PROFILES = 100
MAX_SERVERS = 100
ProfileKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
ProfileName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
AndroidPackage = Annotated[str, StringConstraints(
    pattern=r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$", max_length=255,
)]
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class ApplicationServer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: ProfileKey
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
    domain: Annotated[str, StringConstraints(min_length=1, max_length=254)]
    port: int = Field(ge=1, le=65535, strict=True)

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        domain = value.removesuffix(".").lower()
        if len(domain) > 253 or not all(_DNS_LABEL.fullmatch(label) for label in domain.split(".")):
            raise ValueError("expected a hostname without scheme, path or port")
        return domain


def _unique_servers(servers: list[ApplicationServer]) -> list[ApplicationServer]:
    if len(servers) != len({server.key for server in servers}):
        raise ValueError("server keys must be unique within an application")
    if len(servers) != len({server.name.casefold() for server in servers}):
        raise ValueError("server names must be unique within an application")
    return servers


class CreateApplicationProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: ProfileKey
    name: ProfileName
    android_package: AndroidPackage | None = None
    servers: list[ApplicationServer] = Field(default_factory=list, max_length=MAX_SERVERS)

    @field_validator("servers")
    @classmethod
    def validate_servers(cls, value: list[ApplicationServer]) -> list[ApplicationServer]:
        return _unique_servers(value)


class UpdateApplicationProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_updated_at: AwareDatetime
    name: ProfileName | None = None
    android_package: AndroidPackage | None = None
    servers: list[ApplicationServer] | None = Field(None, max_length=MAX_SERVERS)

    @model_validator(mode="after")
    def validate_patch(self) -> "UpdateApplicationProfile":
        if self.model_fields_set == {"expected_updated_at"}:
            raise ValueError("expected at least one profile field to update")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name must not be null")
        if "servers" in self.model_fields_set:
            if self.servers is None:
                raise ValueError("servers must not be null")
            _unique_servers(self.servers)
        return self


class ApplicationProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: ProfileKey
    name: ProfileName
    android_package: AndroidPackage | None = None
    servers: list[ApplicationServer] = Field(max_length=MAX_SERVERS)
    source: Literal["builtin", "tenant"] = "tenant"
    aliases: list[str] = Field(default_factory=list)
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class ApplicationProfileList(BaseModel):
    items: list[ApplicationProfileResponse] = Field(max_length=MAX_PROFILES)
    total: int
