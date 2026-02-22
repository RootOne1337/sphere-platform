# backend/schemas/vpn/config.py — TZ-06 SPLIT-1
# Pydantic schemas для AWG Config Builder API.
from __future__ import annotations

from pydantic import BaseModel, Field


class AWGObfuscationParamsSchema(BaseModel):
    """Параметры обфускации AmneziaWG (read-only, возвращается в ответе)."""

    jc: int = Field(..., ge=1, le=128, description="Junk packet Count")
    jmin: int = Field(..., ge=0, le=1280, description="Junk packet Min size")
    jmax: int = Field(..., ge=1, le=2280, description="Junk packet Max size")
    s1: int = Field(..., ge=1, le=2048, description="Init packet magic Header")
    s2: int = Field(..., ge=1, le=2048, description="Response packet magic Header")
    h1: int = Field(..., ge=1, description="Init Handshake header")
    h2: int = Field(..., ge=1, description="Response Handshake header")
    h3: int = Field(..., ge=1, description="Under load Handshake header")
    h4: int = Field(..., ge=1, description="Cookie reply Handshake header")


class AWGKeypairResponse(BaseModel):
    """Результат генерации WireGuard keypair. Private key НИКОГДА не возвращается."""

    public_key: str = Field(..., description="WireGuard public key (base64)")


class AWGConfigPreviewRequest(BaseModel):
    """Запрос на предпросмотр конфига (только для разработки/тестирования)."""

    assigned_ip: str = Field(..., description="Tunnel IP для клиента, напр. 10.100.0.1")
    split_tunnel: bool = Field(True, description="True → AllowedIPs=0.0.0.0/0")
    include_psk: bool = Field(True, description="Включить Pre-Shared Key")


class AWGConfigPreviewResponse(BaseModel):
    """Ответ с полным клиентским конфигом и QR-кодом."""

    public_key: str = Field(..., description="Публичный ключ клиента")
    tunnel_ip: str = Field(..., description="Assigned tunnel IP")
    config_text: str = Field(..., description="Клиентский .conf файл AmneziaWG")
    qr_code_b64: str = Field(..., description="Base64 PNG QR-код для сканирования")
    obfuscation: AWGObfuscationParamsSchema
