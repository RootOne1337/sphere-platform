"""Recoverable game credentials; no legacy plaintext fallback at runtime."""

from __future__ import annotations

import json
import uuid

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from fastapi import HTTPException

from backend.core.config import settings
from backend.models.game_account import GameAccount


class AccountCredentialUnavailable(HTTPException):
    def __init__(self) -> None:
        # Never include a token, key, password or crypto exception in API/log text.
        super().__init__(status_code=503, detail="Account credentials unavailable")


def get_account_cipher() -> MultiFernet:
    keys = settings.ACCOUNT_CREDENTIAL_KEYS.get_secret_value().split(",")
    if not 1 <= len(keys) <= 8 or any(not key.strip() for key in keys):
        raise AccountCredentialUnavailable()
    try:
        return MultiFernet([Fernet(key.strip().encode("ascii")) for key in keys])
    except (ValueError, UnicodeError):
        raise AccountCredentialUnavailable() from None


def set_account_password(account: GameAccount, password: str) -> None:
    """Encrypt before any flush, and clear the legacy plaintext in the same write."""
    cipher = get_account_cipher()
    account_id = account.id or uuid.uuid4()
    payload = json.dumps({
        "version": 1, "org_id": str(account.org_id), "account_id": str(account_id),
        "password": password,
    }, ensure_ascii=False).encode("utf-8")
    token = cipher.encrypt(payload).decode("ascii")
    account.id = account_id
    account.password_ciphertext = token
    account.password_encrypted = ""


def read_account_password(account: GameAccount) -> str:
    """Authenticate the encrypted identity as well as the password itself."""
    if account.password_ciphertext is None:
        # Only the offline migration may interpret the old column as plaintext.
        raise AccountCredentialUnavailable()
    try:
        payload = json.loads(get_account_cipher().decrypt(account.password_ciphertext.encode("ascii")))
        if (not isinstance(payload, dict) or type(payload.get("version")) is not int
                or payload["version"] != 1
                or payload.get("org_id") != str(account.org_id)
                or payload.get("account_id") != str(account.id)
                or not isinstance(payload.get("password"), str)):
            raise AccountCredentialUnavailable()
        return payload["password"]
    except (InvalidToken, ValueError, UnicodeError):
        raise AccountCredentialUnavailable() from None
