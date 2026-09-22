"""Аварийный OTA не должен превращать старый JWT в доступ к управлению."""

import time
import uuid
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi import WebSocketDisconnect
from starlette.datastructures import URL

from backend.core.config import settings
from backend.models import Device, Organization
from backend.services.device_ota_recovery import OtaRecoveryGrant, get_ota_recovery


@pytest.mark.parametrize(("error", "expected"), [
    (None, None), ({"token": "private"}, None),
    ("OTA download failed: 401", "download_http_401"),
    ("SHA-256 mismatch: private payload", "checksum_mismatch"),
    ("SSRF protection: secret host", "download_origin_rejected"),
    ("unexpected end of stream on private URL", "download_unexpected_eof"),
    ("stream was reset: PROTOCOL_ERROR", "http2_reset_protocol_error"),
    ("stream was reset: private", "download_stream_interrupted"),
    ("Permission denied /private/path", "permission_denied"),
    ("create install session failed", "package_install_failure"),
    ("arbitrary credential never copied", "unclassified"),
])
def test_recovery_diagnostics_never_emit_agent_error_text(error, expected):
    from backend.services.device_ota_recovery import recovery_failure_code
    assert recovery_failure_code(error) == expected


@pytest.fixture
async def recovery_case(db_session, monkeypatch):
    now = int(time.time())
    org = Organization(name="isolated recovery", slug=uuid.uuid4().hex)
    db_session.add(org)
    await db_session.flush()
    grant = OtaRecoveryGrant(command_id=uuid.uuid4(), sha256="a" * 64, version_name="isolated",
                             created_at=now, expires_at=now + 1800, issued_before=now - 1)
    device = Device(org_id=org.id, name="isolated-copy", meta={"ota_recovery": grant.model_dump(mode="json")})
    db_session.add(device)
    await db_session.flush()
    grant = grant.signed(device)
    device.meta = {"ota_recovery": grant.model_dump(mode="json")}
    monkeypatch.setattr("backend.services.cache_service.CacheService.is_token_blacklisted", AsyncMock(return_value=False))
    claims = {"sub": str(device.id), "org_id": str(org.id), "role": "device", "type": "access",
              "jti": str(uuid.uuid4()), "iat": now - 3600, "exp": now - 1}
    return device, grant, claims


def encode(claims):
    return jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


async def test_expired_device_token_only_gets_exact_recovery_grant(db_session, recovery_case):
    device, grant, claims = recovery_case
    result = await get_ota_recovery(encode(claims), db_session, device_id=str(device.id), sha256=grant.sha256)
    assert result and result[0].id == device.id and result[1] == grant
    from backend.core.security import decode_access_token
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(encode(claims))
    assert await get_ota_recovery(encode(claims), db_session, sha256="b" * 64) is None
    assert await get_ota_recovery(encode(claims), db_session, device_id=str(uuid.uuid4())) is None


@pytest.mark.parametrize("change", ["user", "foreign_org", "fresh", "too_old", "missing_exp", "bad_signature",
                                    "inactive", "expired_grant", "long_grant", "revoked", "no_grant", "tampered_grant"])
async def test_recovery_boundaries(db_session, recovery_case, monkeypatch, change):
    device, grant, claims = recovery_case
    now = int(time.time())
    if change == "user":
        claims["role"] = "super_admin"
    if change == "foreign_org":
        claims["org_id"] = str(uuid.uuid4())
    if change == "fresh":
        claims.update(iat=now, exp=now + 3600)
    if change == "too_old":
        claims["iat"] = now - 72 * 3600 - 1
    if change == "missing_exp":
        claims.pop("exp")
    if change == "inactive":
        device.is_active = False
    if change == "expired_grant":
        grant.expires_at = now
    if change == "long_grant":
        grant.expires_at = now + 3601
    if change == "tampered_grant":
        grant.sha256 = "b" * 64
    if change == "revoked":
        monkeypatch.setattr("backend.services.cache_service.CacheService.is_token_blacklisted", AsyncMock(return_value=True))
    device.meta = {} if change == "no_grant" else {"ota_recovery": grant.model_dump(mode="json")}
    token = encode(claims)
    if change == "bad_signature":
        token = jwt.encode(claims, "isolated-wrong-secret-for-signature-regression", algorithm=settings.JWT_ALGORITHM)
    assert await get_ota_recovery(token, db_session) is None


async def test_ota_channel_sends_only_granted_update_and_ignores_copied_task_receipts(recovery_case):
    from backend.api.ws.android.router import serve_ota_recovery
    device, grant, _ = recovery_case
    ws = AsyncMock()
    ws.base_url = URL("wss://isolated.invalid/")
    ws.receive_json.side_effect = [{"type": "command_result", "command_id": "foreign-task", "status": "completed"},
                                   WebSocketDisconnect(1000)]
    await serve_ota_recovery(ws, str(device.id), grant)
    messages = [c.args[0] for c in ws.send_json.await_args_list]
    assert [m["type"] for m in messages] == ["auth_ok", "OTA_UPDATE"]
    assert messages[1]["payload"]["sha256"] == grant.sha256
    assert messages[1]["payload"]["download_url"] == "https://isolated.invalid/api/v1/updates/artifacts/" + grant.sha256
