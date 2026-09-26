"""Bounded, transaction-owned-by-caller credential backfill/rotation/verification."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.game_account import GameAccount
from backend.services.account_credentials import (
    get_account_cipher,
    read_account_password,
    set_account_password,
)


@dataclass(frozen=True)
class CredentialBatch:
    cursor: uuid.UUID | None
    scanned: int
    legacy: int
    changed: int


async def process_credential_batch(
    db: AsyncSession, *, after_id: uuid.UUID | None = None, limit: int = 200,
    apply: bool = False, rotate: bool = False, org_id: uuid.UUID | None = None,
) -> CredentialBatch:
    """Verify every token; optionally replace legacy values or rotate all tokens.

    Requires a maintenance window without account/dispatch writers. The caller
    commits a whole successful batch or rolls it back, and advances its cursor
    only after commit. Restart from the beginning after an interruption.
    """
    if not 1 <= limit <= 1000 or (rotate and not apply):
        raise ValueError("Invalid credential migration options")
    get_account_cipher()  # No changes or misleading successful scan without keys.
    query = select(GameAccount).order_by(GameAccount.id).limit(limit)
    if after_id is not None:
        query = query.where(GameAccount.id > after_id)
    if org_id is not None:
        query = query.where(GameAccount.org_id == org_id)
    if apply:
        query = query.with_for_update()
    accounts = list(await db.scalars(query.execution_options(populate_existing=True)))
    legacy = changed = 0
    for account in accounts:
        is_legacy = account.password_ciphertext is None
        if is_legacy:
            legacy += 1
            if not apply:
                continue
            # This is the only permitted legacy plaintext reader.
            password = account.password_encrypted
        else:
            password = read_account_password(account)
        if apply and (is_legacy or rotate):
            set_account_password(account, password)
            # Verify identity and authenticated round trip before committing.
            if read_account_password(account) != password:
                raise RuntimeError("Credential verification failed")
            changed += 1
    if changed:
        await db.flush()
    return CredentialBatch(accounts[-1].id if accounts else after_id,
                           len(accounts), legacy, changed)
