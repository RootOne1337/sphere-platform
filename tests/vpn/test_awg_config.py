# tests/vpn/test_awg_config.py — TZ-06 SPLIT-1
# Unit-тесты для AWGConfigBuilder и AWGObfuscationParams.
from __future__ import annotations

import base64

from backend.services.vpn.awg_config import AWGConfigBuilder, AWGObfuscationParams
from backend.services.vpn.dependencies import decrypt_private_key, encrypt_private_key

# ---------------------------------------------------------------------------
# AWGObfuscationParams
# ---------------------------------------------------------------------------

def test_generate_random_obfuscation_params():
    params = AWGObfuscationParams.generate_random()
    assert 1 <= params.jc <= 128
    assert 0 <= params.jmin <= 1279
    assert params.jmax > params.jmin
    assert 1 <= params.s1 <= 2048
    assert 1 <= params.s2 <= 2048
    assert 1 <= params.h1 <= 2147483647
    assert 1 <= params.h2 <= 2147483647
    assert 1 <= params.h3 <= 2147483647
    assert 1 <= params.h4 <= 2147483647


def test_generate_random_obfuscation_params_are_unique():
    """Два вызова должны давать разные параметры (с высокой вероятностью)."""
    p1 = AWGObfuscationParams.generate_random()
    p2 = AWGObfuscationParams.generate_random()
    # Вероятность коллизии всех полей пренебрежимо мала
    assert p1.model_dump() != p2.model_dump()


# ---------------------------------------------------------------------------
# generate_keypair — через wg binary или fallback
# ---------------------------------------------------------------------------

def test_generate_keypair_returns_base64_strings(awg_builder: AWGConfigBuilder):
    private, public = awg_builder.generate_keypair()
    # должны быть непустыми base64-совместимыми строками
    assert len(private) > 0
    assert len(public) > 0
    # base64 decode не должен бросать
    base64.b64decode(private + "==")
    base64.b64decode(public + "==")


def test_generate_keypair_fallback(awg_builder: AWGConfigBuilder, monkeypatch):
    """Fallback через cryptography при отсутствии wg binary."""
    import subprocess
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError))

    private, public = awg_builder.generate_keypair()

    assert len(base64.b64decode(private)) == 32
    assert len(base64.b64decode(public)) == 32


def test_generate_keypair_fallback_keys_differ(awg_builder: AWGConfigBuilder, monkeypatch):
    """Два вызова fallback должны давать разные ключи."""
    import subprocess
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError))

    priv1, pub1 = awg_builder.generate_keypair()
    priv2, pub2 = awg_builder.generate_keypair()
    assert priv1 != priv2
    assert pub1 != pub2


# ---------------------------------------------------------------------------
# generate_psk
# ---------------------------------------------------------------------------

def test_generate_psk_is_32_bytes(awg_builder: AWGConfigBuilder):
    psk = awg_builder.generate_psk()
    decoded = base64.b64decode(psk)
    assert len(decoded) == 32


def test_generate_psk_are_unique(awg_builder: AWGConfigBuilder):
    psk1 = awg_builder.generate_psk()
    psk2 = awg_builder.generate_psk()
    assert psk1 != psk2


# ---------------------------------------------------------------------------
# build_client_config
# ---------------------------------------------------------------------------

def test_build_client_config_contains_all_awg_fields(awg_builder: AWGConfigBuilder):
    obfuscation = AWGObfuscationParams.generate_random()
    config = awg_builder.build_client_config(
        private_key="test_private_key",
        assigned_ip="10.100.0.1",
        obfuscation=obfuscation,
    )

    assert "[Interface]" in config
    assert "PrivateKey = test_private_key" in config
    assert "Address = 10.100.0.1/32" in config
    assert f"Jc = {obfuscation.jc}" in config
    assert f"Jmin = {obfuscation.jmin}" in config
    assert f"Jmax = {obfuscation.jmax}" in config
    assert f"S1 = {obfuscation.s1}" in config
    assert f"S2 = {obfuscation.s2}" in config
    assert f"H1 = {obfuscation.h1}" in config
    assert f"H2 = {obfuscation.h2}" in config
    assert f"H3 = {obfuscation.h3}" in config
    assert f"H4 = {obfuscation.h4}" in config
    assert "[Peer]" in config
    assert f"PublicKey = {awg_builder.server_public_key}" in config
    assert f"Endpoint = {awg_builder.server_endpoint}" in config
    assert "PersistentKeepalive = 25" in config


def test_build_client_config_split_tunnel_true(awg_builder: AWGConfigBuilder):
    obfuscation = AWGObfuscationParams.generate_random()
    config = awg_builder.build_client_config(
        private_key="pk", assigned_ip="10.100.0.1", obfuscation=obfuscation,
        split_tunnel=True,
    )
    assert "AllowedIPs = 0.0.0.0/0" in config


def test_build_client_config_split_tunnel_false(awg_builder: AWGConfigBuilder):
    obfuscation = AWGObfuscationParams.generate_random()
    config = awg_builder.build_client_config(
        private_key="pk", assigned_ip="10.100.0.1", obfuscation=obfuscation,
        split_tunnel=False,
    )
    assert "AllowedIPs = 10.100.0.0/16" in config


def test_build_client_config_with_psk(awg_builder: AWGConfigBuilder):
    obfuscation = AWGObfuscationParams.generate_random()
    psk = awg_builder.generate_psk()
    config = awg_builder.build_client_config(
        private_key="pk", assigned_ip="10.100.0.1", obfuscation=obfuscation, psk=psk,
    )
    assert f"PresharedKey = {psk}" in config


def test_build_client_config_without_psk(awg_builder: AWGConfigBuilder):
    obfuscation = AWGObfuscationParams.generate_random()
    config = awg_builder.build_client_config(
        private_key="pk", assigned_ip="10.100.0.1", obfuscation=obfuscation, psk=None,
    )
    assert "PresharedKey" not in config


# ---------------------------------------------------------------------------
# to_qr_code
# ---------------------------------------------------------------------------

def test_to_qr_code_returns_valid_base64_png(awg_builder: AWGConfigBuilder):
    obfuscation = AWGObfuscationParams.generate_random()
    config = awg_builder.build_client_config(
        private_key="pk", assigned_ip="10.100.0.1", obfuscation=obfuscation,
    )
    qr_b64 = awg_builder.to_qr_code(config)
    png_bytes = base64.b64decode(qr_b64)
    # PNG magic bytes: \x89PNG\r\n\x1a\n
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_to_qr_code_is_non_empty(awg_builder: AWGConfigBuilder):
    qr_b64 = awg_builder.to_qr_code("test config data")
    assert len(qr_b64) > 0


# ---------------------------------------------------------------------------
# Fernet encryption/decryption of private key
# ---------------------------------------------------------------------------

def test_encrypt_decrypt_private_key_roundtrip(fernet_cipher):

    original = "dGVzdF9wcml2YXRlX2tleV9iYXNlNjRfcGFkZGluZz0="
    encrypted = encrypt_private_key(original, fernet_cipher)
    assert isinstance(encrypted, bytes)
    assert encrypted != original.encode()

    decrypted = decrypt_private_key(encrypted, fernet_cipher)
    assert decrypted == original


def test_encrypted_private_key_is_different_each_time(fernet_cipher):
    """Fernet использует случайный nonce → каждое шифрование уникально."""
    key = "dGVzdF9wcml2YXRlX2tleV9iYXNlNjRfcGFkZGluZz0="
    enc1 = encrypt_private_key(key, fernet_cipher)
    enc2 = encrypt_private_key(key, fernet_cipher)
    assert enc1 != enc2
