from __future__ import annotations

import base64
import json
import uuid
from types import SimpleNamespace

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.services.vpn.profile_delivery import (
    ALGORITHM,
    DeviceRecipient,
    ProfileDeliveryRejected,
    client_identity,
    seal_revision,
)
from tests.vpn.test_profile_preflight import CONFIG, KEY

NOW = 1800000000000


def test_wide_scope_cannot_be_delivered_as_a_v1_selected_app_command(monkeypatch, recipient):
    private, operation, payload = recipient
    org = uuid.uuid4()
    policy = {"mode": "all_apps_except_control", "kill_switch": "all_apps_except_control", "control_plane": "bypass", "ipv6": "block"}
    revision = SimpleNamespace(org_id=org, id=uuid.uuid4(), schema_version=2, provider_id="android-amneziawg",
                               protocol="wireguard", protocol_version="1", traffic_policy=policy)
    monkeypatch.setattr("backend.services.vpn.profile_delivery.decrypt_revision", lambda _: (CONFIG, "private-fingerprint"))
    command = seal_revision(revision, org_id=org, operation_id=operation, session_id=uuid.uuid4(), action="apply",
                            recipient=DeviceRecipient.parse(payload, operation, NOW), now_epoch_ms=NOW)
    envelope = command["envelope"]
    key = private.decrypt(base64.b64decode(envelope["wrappedKey"]), padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA256(), label=None))
    body = json.loads(AESGCM(key).decrypt(base64.b64decode(envelope["nonce"]), base64.b64decode(envelope["ciphertext"]), str(operation).encode()))
    assert body["schema_version"] == 2 and body["profile"]["traffic_policy"] == policy
    assert KEY not in json.dumps(command)
    revision.schema_version = 1
    with pytest.raises(ProfileDeliveryRejected):
        seal_revision(revision, org_id=org, operation_id=operation, session_id=uuid.uuid4(), action="apply",
                      recipient=DeviceRecipient.parse(payload, operation, NOW), now_epoch_ms=NOW)


@pytest.fixture
def recipient():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    operation = uuid.uuid4()
    payload = {"operation_id": str(operation), "public_key_der": base64.b64encode(private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode(),
        "algorithm": ALGORITHM, "expires_at_epoch_ms": NOW + 300000}
    return private, operation, payload


def test_sealed_wire_contains_no_plaintext_and_binds_to_one_operation(monkeypatch, recipient):
    private, operation, payload = recipient
    org = uuid.uuid4()
    revision = SimpleNamespace(org_id=org, id=uuid.uuid4(), schema_version=1, provider_id="android-amneziawg",
                               protocol="wireguard", protocol_version="1", traffic_policy={"included_packages": ["org.example.game"]})
    monkeypatch.setattr("backend.services.vpn.profile_delivery.decrypt_revision", lambda _: (CONFIG, "private-fingerprint"))
    command = seal_revision(revision, org_id=org, operation_id=operation, session_id=uuid.uuid4(), action="apply",
                            recipient=DeviceRecipient.parse(payload, operation, NOW), now_epoch_ms=NOW)
    assert KEY not in json.dumps(command) and "config_text" not in json.dumps(command)
    envelope = command["envelope"]
    key = private.decrypt(base64.b64decode(envelope["wrappedKey"]), padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA256(), label=None))
    raw = AESGCM(key).decrypt(base64.b64decode(envelope["nonce"]), base64.b64decode(envelope["ciphertext"]), str(operation).encode())
    body = json.loads(raw)
    assert body["profile"]["config_text"] == CONFIG
    assert body["request_id"] == str(operation)
    assert body["profile"]["traffic_policy"]["control_plane"] == "bypass"
    with pytest.raises(InvalidTag):
        AESGCM(key).decrypt(base64.b64decode(envelope["nonce"]), base64.b64decode(envelope["ciphertext"]), str(uuid.uuid4()).encode())
    with pytest.raises(ProfileDeliveryRejected, match="expired"):
        seal_revision(revision, org_id=org, operation_id=operation, session_id=uuid.uuid4(), action="apply",
                      recipient=DeviceRecipient.parse(payload, operation, NOW), now_epoch_ms=NOW + 300001)


@pytest.mark.parametrize("change", [
    {"algorithm": "RSA"}, {"expires_at_epoch_ms": True}, {"expires_at_epoch_ms": NOW},
    {"expires_at_epoch_ms": NOW + 305001}, {"public_key_der": "private-sentinel"}, {"operation_id": str(uuid.uuid4())},
])
def test_bad_recipient_never_exposes_parser_details(recipient, change):
    _, operation, payload = recipient
    with pytest.raises(ProfileDeliveryRejected) as failure:
        DeviceRecipient.parse(payload | change, operation, NOW)
    assert str(failure.value) == "vpn_device_recipient_rejected" and failure.value.__suppress_context__


def test_foreign_revision_is_rejected_before_decrypt(monkeypatch, recipient):
    _, operation, payload = recipient
    monkeypatch.setattr("backend.services.vpn.profile_delivery.decrypt_revision", lambda _: pytest.fail("Foreign revision decrypted"))
    with pytest.raises(ProfileDeliveryRejected, match="not_found"):
        seal_revision(SimpleNamespace(org_id=uuid.uuid4()), org_id=uuid.uuid4(), operation_id=operation,
                      session_id=uuid.uuid4(), action="apply", recipient=DeviceRecipient.parse(payload, operation, NOW), now_epoch_ms=NOW)


def test_client_key_aliases_have_one_public_identity_and_separate_tenant_namespace():
    org = uuid.uuid4()
    identity = client_identity(CONFIG, org)
    key = bytearray(base64.b64decode(KEY))
    key[0] ^= 7  # X25519 clears the low three bits; same public key.
    alternate = CONFIG.replace(KEY, base64.b64encode(key).decode())
    assert client_identity(alternate, org) == identity
    assert client_identity(CONFIG, uuid.uuid4()) != identity
    assert KEY not in identity and len(identity) == 64
    for malformed in ["private-sentinel", CONFIG.replace(KEY, "private-sentinel"), CONFIG.replace("[Peer]", "PrivateKey=" + KEY + "\n[Peer]")]:
        with pytest.raises(ProfileDeliveryRejected, match="vpn_client_identity_unavailable"):
            client_identity(malformed, org)
