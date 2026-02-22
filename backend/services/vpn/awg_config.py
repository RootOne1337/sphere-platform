# backend/services/vpn/awg_config.py — TZ-06 SPLIT-1
# AWG (AmneziaWG) конфигуратор: ключи, обфускация, клиентский .conf, QR-код.
from __future__ import annotations

import base64
import io
import secrets
import subprocess

import qrcode
import qrcode.constants
from pydantic import BaseModel


class AWGObfuscationParams(BaseModel):
    """
    Параметры обфускации AmneziaWG — рандомизируются для каждого peer.
    Документация: https://docs.amnezia.org/documentation/amnezia-wg/
    """

    jc: int     # Junk packet Count (1-128)
    jmin: int   # Junk packet Min size (0-1280)
    jmax: int   # Junk packet Max size (jmin-1280)
    s1: int     # Init packet magic Header (1-2048)
    s2: int     # Response packet magic Header (1-2048)
    h1: int     # Init Handshake header (1-2147483647)
    h2: int     # Response Handshake header (1-2147483647)
    h3: int     # Under load Handshake header (1-2147483647)
    h4: int     # Cookie reply Handshake header (1-2147483647)

    @classmethod
    def generate_random(cls) -> "AWGObfuscationParams":
        """Генерировать случайные параметры обфускации."""
        jmin = secrets.randbelow(200)
        return cls(
            jc=secrets.randbelow(128) + 1,
            jmin=jmin,
            jmax=jmin + secrets.randbelow(1000) + 1,
            s1=secrets.randbelow(2048) + 1,
            s2=secrets.randbelow(2048) + 1,
            h1=secrets.randbelow(2147483647) + 1,
            h2=secrets.randbelow(2147483647) + 1,
            h3=secrets.randbelow(2147483647) + 1,
            h4=secrets.randbelow(2147483647) + 1,
        )


class AWGConfigBuilder:
    """
    Сборщик клиентских конфигураций AmneziaWG.
    Один экземпляр на приложение (DI через FastAPI Depends).
    """

    def __init__(
        self,
        server_public_key: str,
        server_endpoint: str,           # "vpn.example.com:51820"
        dns: str = "1.1.1.1, 8.8.8.8",
        server_psk_enabled: bool = True,
    ):
        self.server_public_key = server_public_key
        self.server_endpoint = server_endpoint
        self.dns = dns
        self.server_psk_enabled = server_psk_enabled

    def generate_keypair(self) -> tuple[str, str]:
        """
        Генерировать WireGuard keypair (private_key, public_key).
        Использует subprocess + wg genkey / wg pubkey.
        Fallback: X25519 через cryptography если wg binary недоступен.
        """
        try:
            private = subprocess.check_output(
                ["wg", "genkey"], text=True, timeout=5
            ).strip()
            public = subprocess.check_output(
                ["wg", "pubkey"], input=private, text=True, timeout=5
            ).strip()
            return private, public
        except FileNotFoundError:
            return self._generate_keypair_fallback()

    @staticmethod
    def _generate_keypair_fallback() -> tuple[str, str]:
        """Fallback: X25519 keypair через cryptography (без wg binary)."""
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

        privkey = X25519PrivateKey.generate()
        private_bytes = privkey.private_bytes_raw()
        public_bytes = privkey.public_key().public_bytes_raw()
        return (
            base64.b64encode(private_bytes).decode(),
            base64.b64encode(public_bytes).decode(),
        )

    @staticmethod
    def generate_psk() -> str:
        """Генерировать Pre-Shared Key (32 байта base64)."""
        return base64.b64encode(secrets.token_bytes(32)).decode()

    def build_client_config(
        self,
        private_key: str,
        assigned_ip: str,
        obfuscation: AWGObfuscationParams,
        psk: str | None = None,
        split_tunnel: bool = True,
    ) -> str:
        """
        Собрать AmneziaWG клиентский конфиг (формат .conf).

        split_tunnel=True  → AllowedIPs = 0.0.0.0/0 (весь трафик через VPN)
        split_tunnel=False → AllowedIPs = 10.100.0.0/16 (только внутренний трафик)
        """
        allowed_ips = "0.0.0.0/0" if split_tunnel else "10.100.0.0/16"

        config = f"""[Interface]
PrivateKey = {private_key}
Address = {assigned_ip}/32
DNS = {self.dns}
Jc = {obfuscation.jc}
Jmin = {obfuscation.jmin}
Jmax = {obfuscation.jmax}
S1 = {obfuscation.s1}
S2 = {obfuscation.s2}
H1 = {obfuscation.h1}
H2 = {obfuscation.h2}
H3 = {obfuscation.h3}
H4 = {obfuscation.h4}

[Peer]
PublicKey = {self.server_public_key}
AllowedIPs = {allowed_ips}
Endpoint = {self.server_endpoint}
PersistentKeepalive = 25"""

        if psk:
            config += f"\nPresharedKey = {psk}"

        return config.strip()

    def to_qr_code(self, config_text: str) -> str:
        """Конвертировать конфиг в base64 PNG QR-код для Android клиента."""
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(config_text)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer)  # qrcode PilImage.save: default kind=PNG
        return base64.b64encode(buffer.getvalue()).decode()
