"""Authenticated binding prevents moving ciphertext between tenants/revisions."""
from __future__ import annotations

import json

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from fastapi import HTTPException

from backend.core.config import settings
from backend.models.vpn_profile import VPNProfileRevision


def unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="vpn_profile_secrets_unavailable")


def get_profile_cipher() -> MultiFernet:
    keys = settings.VPN_PROFILE_ENCRYPTION_KEYS.get_secret_value().split(",")
    if not 1 <= len(keys) <= 8 or any(not key.strip() for key in keys):
        raise unavailable()
    try:
        return MultiFernet([Fernet(key.strip().encode("ascii")) for key in keys])
    except (ValueError, UnicodeError):
        raise unavailable() from None


def _identity(row: VPNProfileRevision) -> dict:
    return {
        "version": 1, "purpose": "sphere-vpn-profile",
        "org_id": str(row.org_id), "profile_id": str(row.profile_id), "revision_id": str(row.id),
        "revision": row.revision, "request_id": str(row.request_id),
        "created_by_id": str(row.created_by_id),
        "provider_id": row.provider_id, "protocol": row.protocol, "protocol_version": row.protocol_version,
        "schema_version": row.schema_version, "traffic_policy": row.traffic_policy,
        "name": row.name, "description": row.description, "endpoint": row.endpoint, "features": row.features,
    }


def encrypt_revision(row: VPNProfileRevision, config: str, request_fingerprint: str) -> bytes:
    payload = {"identity": _identity(row), "config": config, "request_fingerprint": request_fingerprint}
    return get_profile_cipher().encrypt(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def decrypt_revision(row: VPNProfileRevision) -> tuple[str, str]:
    # Internal only. No HTTP endpoint returns this payload or a QR equivalent.
    try:
        payload = json.loads(get_profile_cipher().decrypt(row.config_ciphertext))
        if (not isinstance(payload, dict) or payload.get("identity") != _identity(row)
                or not isinstance(payload.get("config"), str)
                or not isinstance(payload.get("request_fingerprint"), str)):
            raise unavailable()
        return payload["config"], payload["request_fingerprint"]
    except (InvalidToken, ValueError, TypeError, UnicodeError):
        raise unavailable() from None
