# backend/services/mfa_service.py
# ВЛАДЕЛЕЦ: TZ-01 SPLIT-2. TOTP MFA через Google Authenticator.
from __future__ import annotations

import base64
import io

import pyotp
import qrcode


class MFAService:
    """TOTP-MFA сервис (RFC 6238 / Google Authenticator совместимый)."""

    ISSUER = "Sphere Platform"

    def generate_totp_secret(self) -> str:
        """Сгенерировать случайный Base32 секрет для TOTP."""
        return pyotp.random_base32()

    def get_totp_uri(self, secret: str, email: str) -> str:
        """Получить otpauth:// URI для QR-кода / аутентификатора."""
        return pyotp.totp.TOTP(secret).provisioning_uri(
            name=email,
            issuer_name=self.ISSUER,
        )

    def generate_qr_code(self, totp_uri: str) -> str:
        """Сгенерировать base64-encoded PNG QR-код для otpauth URI."""
        img = qrcode.make(totp_uri)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    def verify_totp(self, secret: str, code: str) -> bool:
        """
        Проверить TOTP-код. Допуск ±30 секунд (valid_window=1).
        Возвращает False если secret is None (MFA не настроен).
        """
        if not secret or not code:
            return False
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)
