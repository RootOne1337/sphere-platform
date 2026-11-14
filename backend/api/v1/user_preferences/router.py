from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_current_user, get_tenant_db
from backend.models.user import User
from backend.models.user_preferences import UserPreferences
from backend.schemas.user_preferences import (
    AccountAppearance,
    AccountAppearancePatch,
    UserPreferencesResponse,
)

router = APIRouter(prefix="/user-preferences", tags=["user-preferences"])
_ETAG = re.compile(r'"ui-(0|[1-9][0-9]{0,9})"')


async def current_profile(db: AsyncSession, user: User) -> UserPreferences | None:
    return await db.scalar(select(UserPreferences).where(
        UserPreferences.org_id == user.org_id, UserPreferences.user_id == user.id,
    ))


def serialize(user: User, record: UserPreferences | None, response: Response) -> UserPreferencesResponse:
    revision = record.revision if record else 0
    response.headers["ETag"] = f'"ui-{revision}"'
    response.headers["Cache-Control"] = "private, no-store"
    return UserPreferencesResponse(
        user_id=user.id, org_id=user.org_id, revision=revision,
        appearance=AccountAppearance.model_validate(record.appearance) if record else AccountAppearance(),
    )


@router.get("/me", response_model=UserPreferencesResponse)
async def get_my_preferences(
    response: Response, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_tenant_db),
) -> UserPreferencesResponse:
    return serialize(user, await current_profile(db, user), response)


@router.patch(
    "/me", response_model=UserPreferencesResponse,
    responses={412: {"description": "The preference revision changed"}, 428: {"description": "If-Match is required"}},
)
async def patch_my_preferences(
    body: AccountAppearancePatch,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match", max_length=32)] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> UserPreferencesResponse:
    if if_match is None:
        raise HTTPException(428, "preferences_precondition_required")
    match = _ETAG.fullmatch(if_match)
    if match is None:
        raise HTTPException(400, "preferences_invalid_etag")
    expected = int(match[1])
    current = await current_profile(db, user)
    if expected != (current.revision if current else 0):
        raise HTTPException(412, "preferences_revision_conflict")
    merged = AccountAppearance.model_validate({
        **(current.appearance if current else {}), **body.model_dump(exclude_unset=True),
    })
    record: UserPreferences | None
    if current is None:
        try:
            async with db.begin_nested():
                record = UserPreferences(
                    org_id=user.org_id, user_id=user.id, revision=1, appearance=merged.model_dump(),
                )
                db.add(record)
                await db.flush()
        except IntegrityError:
            if await current_profile(db, user) is None:
                raise
            raise HTTPException(412, "preferences_revision_conflict") from None
    elif merged.model_dump() == current.appearance:
        return serialize(user, current, response)
    else:
        record = await db.scalar(update(UserPreferences).where(
            UserPreferences.org_id == user.org_id, UserPreferences.user_id == user.id,
            UserPreferences.revision == expected,
        ).values(
            revision=UserPreferences.revision + 1, appearance=merged.model_dump(), updated_at=func.now(),
        ).returning(UserPreferences))
        if record is None:
            raise HTTPException(412, "preferences_revision_conflict")
    result = serialize(user, record, response)
    await db.commit()
    return result
