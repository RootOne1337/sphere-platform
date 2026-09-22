"""Временный канал установки одного APK для потерявших refresh-токены копий.

Разрешение выдаёт super_admin на конкретную карточку и опубликованный digest.
Оно не выдаёт токены, не подключает командный канал и не разрешает обычный API.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import uuid

import jwt
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.database.tenant import bind_tenant_context
from backend.models.device import Device
from backend.services.cache_service import CacheService


def recovery_failure_code(error: object) -> str | None:
    """Классифицировать ответ старого APK, не записывая произвольный текст/секреты."""
    if not isinstance(error, str) or not error:
        return None
    value = error[:2048].lower()
    match = re.search(r"ota download failed: (\d{3})\b", value)
    if match:
        return "download_http_" + match.group(1)
    for fragments, code in (
        (("sha-256 mismatch",), "checksum_mismatch"),
        (("ssrf protection", "download must use https"), "download_origin_rejected"),
        (("timeout", "timed out"), "timeout"),
        (("unexpected end of stream", "stream was reset", "stream closed"), "download_stream_interrupted"),
        (("permission", "eacces", "not allowed"), "permission_denied"),
        (("space", "enospc"), "storage_full"),
        (("certificate", "ssl", "trust anchor"), "tls_failure"),
        (("resolve host", "unknownhost"), "dns_failure"),
        (("connect", "unreachable", "network"), "connection_failure"),
        (("install", "session"), "package_install_failure"),
        (("execution_interrupted", "cancel"), "execution_interrupted"),
        (("expired",), "command_expired"),
    ):
        if any(fragment in value for fragment in fragments):
            return code
    return "unclassified"


class OtaRecoveryGrant(BaseModel):
    """Ограничение по APK, сроку и моменту выдачи старого токена."""

    model_config = ConfigDict(extra="forbid")
    command_id: uuid.UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    version_name: str = Field(min_length=1, max_length=100)
    created_at: int
    expires_at: int
    issued_before: int
    authorization_tag: str = ""

    def signed(self, device: Device) -> OtaRecoveryGrant:
        """Подпись связывает grant с организацией/устройством и не доверяет обычному meta update."""
        return self.model_copy(update={"authorization_tag": self._tag(device)})

    def _tag(self, device: Device) -> str:
        body = self.model_dump(mode="json", exclude={"authorization_tag"})
        message = "sphere/ota-recovery/v1\0" + str(device.org_id) + "\0" + str(device.id) + "\0" + json.dumps(body, sort_keys=True)
        return hmac.new(settings.JWT_SECRET_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()

    def is_authorized(self, device: Device) -> bool:
        return hmac.compare_digest(self.authorization_tag, self._tag(device))


async def get_ota_recovery(
    token: str, db: AsyncSession, *, device_id: str | None = None, sha256: str | None = None,
) -> tuple[Device, OtaRecoveryGrant] | None:
    """Проверяет подпись старого device JWT и отдельное краткосрочное разрешение.

    Истечение access допускается только здесь: не более 72 часов с выдачи,
    grant живёт максимум час. Новые JWT, пользователи и отозванные токены
    не попадают в recovery. Отсутствие Redis/SQL не разрешает доступ.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM],
                             options={"verify_exp": False,
                                      "require": ["sub", "org_id", "role", "jti", "type", "iat", "exp"]})
        if payload["type"] != "access" or payload["role"] != "device":
            return None
        subject, org = uuid.UUID(payload["sub"]), uuid.UUID(payload["org_id"])
        issued, expiry = payload["iat"], payload["exp"]
        if any(not isinstance(value, int) or isinstance(value, bool) for value in (issued, expiry)):
            return None
        now = int(time.time())
        if not now - 72 * 3600 <= issued <= now or expiry <= issued:
            return None
        if device_id is not None and str(subject) != device_id:
            return None
        if await CacheService().is_token_blacklisted(payload["jti"]):
            return None
        await bind_tenant_context(db, str(org))
        device = await db.get(Device, subject)
        if not device or not device.is_active or device.org_id != org:
            return None
        raw = (device.meta or {}).get("ota_recovery")
        if not isinstance(raw, dict):
            return None
        grant = OtaRecoveryGrant.model_validate(raw)
        if not grant.is_authorized(device):
            return None
        if not (grant.created_at <= now < grant.expires_at <= grant.created_at + 3600):
            return None
        if not issued <= grant.issued_before <= grant.created_at:
            return None
        if sha256 is not None and grant.sha256 != sha256:
            return None
        return device, grant
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError, ValidationError):
        return None
