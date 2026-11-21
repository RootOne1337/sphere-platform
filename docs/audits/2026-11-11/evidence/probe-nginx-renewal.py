"""Observe certificate reload in a disposable nginx using two synthetic certificates."""

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import time
import uuid

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[4]
HOST = "audit.example.test"
IMAGE = "nginx:alpine"


def docker(*args, check=True):
    return subprocess.run(["docker", *args], check=check, capture_output=True,
                          text=True, encoding="utf-8", timeout=20)


def cert_files(folder, serial):
    now = datetime.now(UTC)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOST)])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(serial).not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(HOST)]), critical=False)
            .sign(key, hashes.SHA256()))
    (folder / "fullchain.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (folder / "privkey.pem").write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return cert.fingerprint(hashes.SHA256()).hex()


def tls_fingerprint(port):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # The two certificates are intentionally self-signed fixture identities.
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection(("127.0.0.1", port), timeout=1) as peer:
        with ctx.wrap_socket(peer, server_hostname=HOST) as tls:
            return hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()


def wait_for_fingerprint(port, expected):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            if tls_fingerprint(port) == expected:
                return
        except OSError:
            pass
        time.sleep(0.1)
    raise RuntimeError("The disposable gateway did not present the expected certificate")


def run(folder):
    certs = folder / "certs"
    certs.mkdir()
    previous = cert_files(certs, 1)
    config = folder / "nginx.conf"
    source = (ROOT / "infrastructure/nginx/nginx.conf").read_text(encoding="utf-8")
    config.write_text(source.replace("${SERVER_HOSTNAME}", HOST), encoding="utf-8")
    name = "sphere-audit-nginx-renewal-" + uuid.uuid4().hex[:10]
    docker("image", "inspect", IMAGE)
    try:
        docker("run", "-d", "--pull", "never", "--name", name, "--read-only",
               "--tmpfs", "/var/cache/nginx", "--tmpfs", "/run",
               "-p", "127.0.0.1::443", "--entrypoint", "nginx",
               "--mount", f"type=bind,src={config},dst=/tmp/nginx.generated.conf,readonly",
               "--mount", f"type=bind,src={certs},dst=/etc/letsencrypt/live/{HOST},readonly",
               IMAGE, "-c", "/tmp/nginx.generated.conf", "-g", "daemon off;")
        port = int(docker("port", name, "443/tcp").stdout.strip().rsplit(":", 1)[1])
        wait_for_fingerprint(port, previous)
        replacement = cert_files(certs, 2)
        before_reload = tls_fingerprint(port)
        docker("kill", "--signal=HUP", name)
        wait_for_fingerprint(port, replacement)
        return {
            "nginx": docker("exec", name, "nginx", "-v").stderr.strip(),
            "initial_certificate_observed": True,
            "after_replacing_files": "initial" if before_reload == previous else "other",
            "after_reload": "replacement",
        }
    finally:
        docker("rm", "-f", name, check=False)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="sphere-audit-nginx-") as directory:
        print(json.dumps(run(Path(directory)), indent=2))
