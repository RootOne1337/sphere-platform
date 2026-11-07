"""Offline signer and Android wire-format compatibility; never contact declared routes."""

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from scripts.discovery_manifest import make_manifest, strict_json, validate_payload, verify_manifest

ROOT = Path(__file__).resolve().parents[1]
INSTALLATION = "04b8c5d2-c28e-4d12-a687-b3e211a9b6c7"


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def payload():
    return {"schema_version": 1, "installation_id": INSTALLATION, "config_version": 7,
        "issued_at": 1_799_999_940, "expires_at": 1_800_003_600, "server_url": "https://primary.invalid",
        "fallback_server_url": "https://backup.invalid"}


def test_exact_signed_payload_round_trip(key, payload):
    document = make_manifest(payload, key, "test-key")
    assert verify_manifest(document, key.public_key(), "test-key", INSTALLATION) == payload
    envelope = strict_json(document)
    envelope["payload"] = base64.b64encode(json.dumps({**payload, "config_version": 8}).encode()).decode()
    with pytest.raises(InvalidSignature):
        verify_manifest(json.dumps(envelope).encode(), key.public_key(), "test-key", INSTALLATION)


@pytest.mark.parametrize("field,value", [
    ("config_version", True), ("config_version", "1"), ("config_version", 1.5), ("config_version", 0),
    ("config_version", 2**53), ("schema_version", 2), ("expires_at", 1),
    ("server_url", "http://cleartext.invalid"), ("server_url", "https://user:password@host.invalid"),
    ("server_url", "https://host.invalid?key=secret"), ("server_url", "https://host.invalid#fragment"),
    ("server_url", "https://host.invalid/path"), ("server_url", "https://host.invalid:99999"),
    ("fallback_server_url", "file:///tmp/config"), ("enrollment_api_key", "never-public"),
])
def test_invalid_payload_is_rejected_before_signing(payload, field, value):
    with pytest.raises((ValueError, TypeError)):
        validate_payload({**payload, field: value})


def test_duplicate_keys_are_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        strict_json(b'{"config_version":1,"config_version":2}')


def test_other_installation_and_unknown_key_are_rejected(key, payload):
    document = make_manifest(payload, key, "test-key")
    for key_id, installation in [("other-key", INSTALLATION), ("test-key", "different-installation")]:
        with pytest.raises(ValueError):
            verify_manifest(document, key.public_key(), key_id, installation)


def test_published_cross_language_vector_is_valid():
    folder = ROOT / "android/app/src/test/resources/discovery"
    public = serialization.load_der_public_key(base64.b64decode((folder / "public-key.txt").read_text()))
    verified = verify_manifest((folder / "signed-v1.json").read_bytes(), public, "test-key", INSTALLATION)
    assert verified["config_version"] == 7


def test_real_cli_signs_and_verifies_without_private_material_in_output(tmp_path, key, payload):
    private = tmp_path / "key.pem"
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    public = tmp_path / "public.pem"
    public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo))
    source = tmp_path / "payload.json"
    source.write_text(json.dumps(payload))
    output = tmp_path / "public.json"
    command = [sys.executable, str(ROOT / "scripts/discovery_manifest.py")]
    signed = subprocess.run([*command, "sign", "--payload", str(source), "--private-key", str(private),
        "--key-id", "test-key", "--output", str(output)], capture_output=True, text=True, timeout=15)
    assert signed.returncode == 0, signed.stderr
    verified = subprocess.run([*command, "verify", "--manifest", str(output), "--public-key", str(public),
        "--key-id", "test-key", "--installation-id", INSTALLATION], capture_output=True, text=True, timeout=15)
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["signature_and_schema"] == "verified"
    assert "PRIVATE KEY" not in output.read_text() + signed.stdout + verified.stdout


def test_cli_failure_preserves_existing_public_document(tmp_path, payload):
    source = tmp_path / "payload.json"
    source.write_text(json.dumps(payload))
    private = tmp_path / "invalid.pem"
    private.write_text("invalid")
    output = tmp_path / "public.json"
    output.write_text("last good document")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/discovery_manifest.py"), "sign",
        "--payload", str(source), "--private-key", str(private), "--key-id", "test-key", "--output", str(output)],
        capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert output.read_text() == "last good document"
