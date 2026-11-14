from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Palette = Literal["neo-dark", "matrix-green", "deep-space", "light-corporate", "graphite", "sandstone", "dune", "mist"]
Density = Literal["compact", "cozy", "spacious"]
Accent = Literal["theme", "violet", "blue", "emerald", "rose", "amber"]
FontScale = Literal["sm", "base", "lg"]
Sidebar = Literal["auto", "pinned", "rail"]
Inspector = Literal["modal", "drawer"]
Surface = Literal["solid", "glass"]
Glass = Literal["soft", "balanced", "vivid"]
Motion = Literal["system", "reduced"]


class AccountAppearance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    palette: Palette = "neo-dark"
    density: Density = "cozy"
    accent_color: Accent = "theme"
    font_size: FontScale = "base"
    sidebar_mode: Sidebar = "auto"
    inspector_mode: Inspector = "modal"
    surface_style: Surface = "glass"
    glass_strength: Glass = "balanced"
    motion_mode: Motion = "system"


class AccountAppearancePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    palette: Palette | None = None
    density: Density | None = None
    accent_color: Accent | None = None
    font_size: FontScale | None = None
    sidebar_mode: Sidebar | None = None
    inspector_mode: Inspector | None = None
    surface_style: Surface | None = None
    glass_strength: Glass | None = None
    motion_mode: Motion | None = None

    @model_validator(mode="after")
    def contains_changes(self) -> AccountAppearancePatch:
        if not self.model_fields_set or any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("Provide at least one non-null appearance field")
        return self


class UserPreferencesResponse(BaseModel):
    schema_version: Literal[1] = 1
    user_id: UUID
    org_id: UUID
    revision: int = Field(ge=0)
    appearance: AccountAppearance
