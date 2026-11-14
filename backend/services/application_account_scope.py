"""Resolve the exact account pool of an explicitly bound device."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.application_profile import ApplicationProfile
from backend.models.device import Device
from backend.models.game_account import GameAccount


async def resolve_application_account_scope(db: AsyncSession, device: Device) -> tuple[str, str] | None:
    """Legacy devices have no explicit pool. An invalid binding fails closed."""
    if device.application_profile_id is None and device.application_server_key is None:
        return None
    profile = await db.scalar(select(ApplicationProfile).where(
        ApplicationProfile.id == device.application_profile_id,
        ApplicationProfile.org_id == device.org_id,
    ))
    if profile is not None:
        for server in profile.servers:
            if server["key"] == device.application_server_key:
                return profile.key, server["name"]
    raise HTTPException(409, "Device application binding is unavailable")


def require_account_scope(account: GameAccount, scope: tuple[str, str] | None) -> None:
    if scope is not None and (account.game, account.server_name) != scope:
        raise HTTPException(409, "Account does not match the device application and server")
