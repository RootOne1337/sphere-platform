# tests/test_services/test_mfa_service.py
# TZ-01 SPLIT-2: Unit-тесты для MFAService (TOTP генерация и верификация).
from __future__ import annotations

import base64

import pyotp

from backend.services.mfa_service import MFAService


class TestMFAService:
    def test_generate_totp_secret_valid_base32(self):
        svc = MFAService()
        secret = svc.generate_totp_secret()
        # pyotp Base32 secret — должен успешно создавать TOTP объект
        totp = pyotp.TOTP(secret)
        assert len(totp.now()) == 6

    def test_get_totp_uri_format(self):
        svc = MFAService()
        secret = svc.generate_totp_secret()
        uri = svc.get_totp_uri(secret, "user@sphere.io")
        assert uri.startswith("otpauth://totp/")
        assert "Sphere%20Platform" in uri or "Sphere+Platform" in uri or "Sphere" in uri
        assert "user%40sphere.io" in uri or "user@sphere.io" in uri

    def test_generate_qr_code_returns_base64_png(self):
        svc = MFAService()
        secret = svc.generate_totp_secret()
        uri = svc.get_totp_uri(secret, "test@example.com")
        b64 = svc.generate_qr_code(uri)
        data = base64.b64decode(b64)
        # PNG magic bytes: \x89PNG
        assert data[:4] == b"\x89PNG"

    def test_verify_totp_valid_code(self):
        svc = MFAService()
        secret = svc.generate_totp_secret()
        valid_code = pyotp.TOTP(secret).now()
        assert svc.verify_totp(secret, valid_code) is True

    def test_verify_totp_invalid_code(self):
        svc = MFAService()
        secret = svc.generate_totp_secret()
        assert svc.verify_totp(secret, "000000") is False

    def test_verify_totp_empty_secret_returns_false(self):
        svc = MFAService()
        assert svc.verify_totp("", "123456") is False

    def test_verify_totp_empty_code_returns_false(self):
        svc = MFAService()
        secret = svc.generate_totp_secret()
        assert svc.verify_totp(secret, "") is False

    def test_verify_totp_none_secret_returns_false(self):
        svc = MFAService()
        assert svc.verify_totp(None, "123456") is False  # type: ignore[arg-type]
