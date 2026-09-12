"""Prepare/verify a routes-only signed manifest offline; never publishes or embeds a secret.

RSA PKCS#1 v1.5 with SHA-256 matches Android SHA256withRSA (API 1+).
The signature covers exact UTF-8 payload bytes carried as standard Base64.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

MAX_ENVELOPE = 64 * 1024
MAX_PAYLOAD = 32 * 1024


def strict_json(data: bytes) -> dict:
    def pairs(items):
        output = {}
        for key, value in items:
            if key in output:
                raise ValueError("Duplicate JSON key")
            output[key] = value
        return output

    document = json.loads(data.decode("utf-8"), object_pairs_hook=pairs)
    if not isinstance(document, dict):
        raise ValueError("Expected JSON object")
    return document


def validate_payload(payload: dict) -> None:
    required = {"schema_version", "installation_id", "config_version", "issued_at", "expires_at", "server_url"}
    if not required <= payload.keys() or payload.keys() - required - {"fallback_server_url"}:
        raise ValueError("Invalid route manifest fields; credentials are not permitted")
    for name in ("schema_version", "config_version", "issued_at", "expires_at"):
        if not isinstance(payload[name], int) or isinstance(payload[name], bool):
            raise ValueError("Manifest numbers must be integers")
    if payload["schema_version"] != 1 or not 1 <= payload["config_version"] <= 2**53 - 1:
        raise ValueError("Unsupported schema or version")
    if str(uuid.UUID(payload["installation_id"])) != payload["installation_id"]:
        raise ValueError("Expected canonical installation UUID")
    if not 1 <= payload["issued_at"] < payload["expires_at"] <= 253_402_300_799:
        raise ValueError("Invalid manifest time interval")
    for name in ("server_url", "fallback_server_url"):
        value = payload.get(name)
        if value is None and name == "fallback_server_url":
            continue
        if not isinstance(value, str) or any(c.isspace() for c in value) or "\\" in value:
            raise ValueError("Invalid route URL")
        url = urlsplit(value)
        if (url.scheme != "https" or not url.hostname or url.username is not None
                or url.password is not None or "?" in value or "#" in value
                or url.path not in ("", "/")):
            raise ValueError("Routes must be HTTPS origins without credentials, path or query")
        if url.port is not None and not 1 <= url.port <= 65535:
            raise ValueError("Invalid route port")


def make_manifest(payload: dict, key: rsa.RSAPrivateKey, key_id: str) -> bytes:
    validate_payload(payload)
    if not key_id or not isinstance(key, rsa.RSAPrivateKey) or not 2048 <= key.key_size <= 4096:
        raise ValueError("Expected named RSA key of 2048–4096 bits")
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(raw) > MAX_PAYLOAD:
        raise ValueError("Payload too large")
    signature = key.sign(raw, padding.PKCS1v15(), hashes.SHA256())
    return json.dumps({"key_id": key_id, "payload": base64.b64encode(raw).decode("ascii"),
        "signature": base64.b64encode(signature).decode("ascii")}, indent=2).encode("utf-8") + b"\n"


def verify_manifest(raw: bytes, public_key: rsa.RSAPublicKey, key_id: str, installation_id: str) -> dict:
    if len(raw) > MAX_ENVELOPE:
        raise ValueError("Envelope too large")
    envelope = strict_json(raw)
    if envelope.keys() != {"key_id", "payload", "signature"} or envelope["key_id"] != key_id:
        raise ValueError("Invalid envelope or unknown key")
    payload_bytes = base64.b64decode(envelope["payload"], validate=True)
    signature = base64.b64decode(envelope["signature"], validate=True)
    if len(payload_bytes) > MAX_PAYLOAD:
        raise ValueError("Payload too large")
    if not isinstance(public_key, rsa.RSAPublicKey) or not 2048 <= public_key.key_size <= 4096:
        raise ValueError("Invalid public key")
    public_key.verify(signature, payload_bytes, padding.PKCS1v15(), hashes.SHA256())
    payload = strict_json(payload_bytes)
    validate_payload(payload)
    if payload["installation_id"] != installation_id:
        raise ValueError("Different installation")
    return payload


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as source:
        value = source.read(limit + 1)
    if len(value) > limit:
        raise ValueError("Input file too large")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sign = sub.add_parser("sign", help="Sign a routes-only payload using an existing PEM private key")
    sign.add_argument("--payload", type=Path, required=True)
    sign.add_argument("--private-key", type=Path, required=True)
    sign.add_argument("--key-id", required=True)
    sign.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify", help="Verify signature/schema/installation; does not contact routes")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--public-key", type=Path, required=True)
    verify.add_argument("--key-id", required=True)
    verify.add_argument("--installation-id", required=True)
    args = parser.parse_args()
    if args.command == "sign":
        payload = strict_json(read_bounded(args.payload, MAX_PAYLOAD))
        key = serialization.load_pem_private_key(read_bounded(args.private_key, 16 * 1024), password=None)
        document = make_manifest(payload, key, args.key_id)
        verify_manifest(document, key.public_key(), args.key_id, payload["installation_id"])
        if args.output.resolve() in {args.private_key.resolve(), args.payload.resolve()}:
            raise ValueError("Output must not overwrite an input file")
        atomic_write(args.output, document)
    else:
        key = serialization.load_pem_public_key(read_bounded(args.public_key, 16 * 1024))
        payload = verify_manifest(read_bounded(args.manifest, MAX_ENVELOPE), key, args.key_id, args.installation_id)
    print(json.dumps({"signature_and_schema": "verified", "installation_id": payload["installation_id"],
        "config_version": payload["config_version"], "route_reachability_tested": False,
        "freshness_checked": False}))


if __name__ == "__main__":
    main()
