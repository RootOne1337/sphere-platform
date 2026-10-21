"""Internal preparation only. No HTTP plaintext, queueing or physical retries.

The operation journal must bind the authenticated device recipient to the exact
operation before calling this module. A sealed command is not an apply receipt.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa, x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.models.vpn_profile import VPNProfileRevision
from backend.schemas.vpn.profile import VPNProfilePreflightRequest
from backend.services.vpn.profile_preflight import preflight_profile
from backend.services.vpn.profile_secrets import decrypt_revision

ALGORITHM = "RSA-OAEP-SHA256-MGF1-SHA1+A256GCM"


class ProfileDeliveryRejected(Exception):
    """Stable code only; crypto/parser exceptions must never cross this boundary."""


@dataclass(frozen=True)
class DeviceRecipient:
    operation_id: uuid.UUID
    expires_at_epoch_ms: int
    key: rsa.RSAPublicKey = field(repr=False)

    @classmethod
    def parse(cls, payload: object, operation_id: uuid.UUID, now_epoch_ms: int) -> DeviceRecipient:
        try:
            if not isinstance(payload, dict) or payload.keys() != {"operation_id", "public_key_der", "algorithm", "expires_at_epoch_ms"}:
                raise ValueError()
            expiry = payload["expires_at_epoch_ms"]
            encoded = payload["public_key_der"]
            if (payload["operation_id"] != str(operation_id) or payload["algorithm"] != ALGORITHM
                    or type(expiry) is not int or not 0 < expiry - now_epoch_ms <= 305000
                    or not isinstance(encoded, str) or not 1 <= len(encoded) <= 1400):
                raise ValueError()
            key = serialization.load_der_public_key(base64.b64decode(encoded, validate=True))
            if not isinstance(key, rsa.RSAPublicKey) or key.key_size != 2048 or key.public_numbers().e != 65537:
                raise ValueError()
            return cls(operation_id, expiry, key)
        except Exception:
            raise ProfileDeliveryRejected("vpn_device_recipient_rejected") from None


def client_identity(config: str, org_id: uuid.UUID) -> str:
    """Organization-scoped public-key identity for future active-lease uniqueness.

    Base64 spelling and X25519 private-key clamping cannot create two identities
    for one WireGuard public key. The private key or its hash is never returned.
    """
    try:
        section = ""
        values = []
        for raw in config.splitlines():
            line = raw.split("#", 1)[0].strip()
            if line.startswith("["):
                section = line.lower()
            elif section == "[interface]" and "=" in line and line.split("=", 1)[0].strip().lower() == "privatekey":
                values.append(line.split("=", 1)[1].strip())
        if len(values) != 1:
            raise ValueError()
        key = base64.b64decode(values[0], validate=True)
        if len(key) != 32:
            raise ValueError()
        public = x25519.X25519PrivateKey.from_private_bytes(key).public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )
        return hashlib.sha256(b"sphere-vpn-client-v1\x00" + org_id.bytes + public).hexdigest()
    except Exception:
        raise ProfileDeliveryRejected("vpn_client_identity_unavailable") from None


def seal_revision(
    revision: VPNProfileRevision, *, org_id: uuid.UUID, operation_id: uuid.UUID,
    session_id: uuid.UUID, action: str, recipient: DeviceRecipient, now_epoch_ms: int,
) -> dict:
    """Only ciphertext leaves this function. Ownership is checked before decrypt."""
    if revision.org_id != org_id:
        raise ProfileDeliveryRejected("vpn_profile_not_found")
    if action not in {"apply", "rotate"} or recipient.operation_id != operation_id:
        raise ProfileDeliveryRejected("vpn_delivery_identity_invalid")
    if not 0 < recipient.expires_at_epoch_ms - now_epoch_ms <= 305000:
        raise ProfileDeliveryRejected("vpn_device_recipient_expired")
    config, _ = decrypt_revision(revision)
    # Revalidate the current bounded provider contract before creating a wire
    # payload; an old stored profile is not perpetual execution authorization.
    try:
        profile = VPNProfilePreflightRequest.model_validate({
            "schema_version": revision.schema_version, "provider_id": revision.provider_id,
            "protocol": revision.protocol, "protocol_version": revision.protocol_version,
            "traffic_policy": revision.traffic_policy, "config_text": config,
        })
        if revision.provider_id != "android-amneziawg" or not preflight_profile(profile).config_valid:
            raise ValueError()
        body = {"schema_version": 1, "request_id": str(operation_id), "session_id": str(session_id),
                "action": action, "profile_revision_id": str(revision.id), "profile": {
                    "protocol": revision.protocol, "protocol_version": revision.protocol_version,
                    "traffic_policy": profile.traffic_policy.model_dump(), "config_text": config,
                }}
        plaintext = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        if len(plaintext) > 98304:
            raise ValueError()
        key, nonce = AESGCM.generate_key(bit_length=256), os.urandom(12)
        encrypted = AESGCM(key).encrypt(nonce, plaintext, str(operation_id).encode())
        # AndroidKeyStore OAEP historically uses SHA-1 for MGF1 even when OAEP
        # digest is SHA-256. Match the explicit Android recipient contract.
        # developer.android.com/privacy-and-security/cryptography#oaep-mgf1-message-digest
        wrapped = recipient.key.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA256(), label=None))  # nosec B303
        encode = lambda value: base64.b64encode(value).decode("ascii")  # noqa: E731
        return {"envelope": {"operationId": str(operation_id), "wrappedKey": encode(wrapped),
                             "nonce": encode(nonce), "ciphertext": encode(encrypted)}}
    except Exception:
        raise ProfileDeliveryRejected("vpn_profile_delivery_rejected") from None
