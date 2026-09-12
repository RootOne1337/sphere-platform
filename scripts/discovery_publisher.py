"""Publish signed routes for one explicitly scoped outbound Quick Tunnel.

Run on the Docker host with its existing GitHub CLI credential. No Docker mutations,
backend restarts, enrollment secrets or global tunnel names. Journal before remote
CAS; recover ambiguous publication without signing two payloads at the same version.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from scripts.discovery_manifest import (
    MAX_ENVELOPE,
    atomic_write,
    make_manifest,
    read_bounded,
    strict_json,
    validate_payload,
    verify_manifest,
)


class PublicationError(RuntimeError):
    """Safe diagnostic; never includes subprocess output or credentials."""


class PublisherBusy(PublicationError):
    pass


_thread_locks_guard = threading.Lock()
_thread_locks: dict[str, threading.Lock] = {}


@contextmanager
def exclusive_lock(path: Path):
    with _thread_locks_guard:
        thread_lock = _thread_locks.setdefault(os.path.normcase(str(path.resolve())), threading.Lock())
    if not thread_lock.acquire(blocking=False):
        raise PublisherBusy("Publisher already running in this process")
    try:
        with _process_lock(path):
            yield
    finally:
        thread_lock.release()


@contextmanager
def _process_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise PublisherBusy("Publisher already running for this journal") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@dataclass(frozen=True)
class RemoteDocument:
    raw: bytes
    revision: str


class DocumentStore(Protocol):
    scope: str

    def read(self) -> RemoteDocument: ...

    def replace(self, raw: bytes, expected_revision: str, version: int) -> None: ...


def run_command(args: list[str], *, body: bytes | None = None, timeout: int = 30) -> bytes:
    result = subprocess.run(args, input=body, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        status = re.search(rb"HTTP (\d{3})", result.stderr)
        suffix = f", HTTP {status[1].decode()}" if status else ""
        raise PublicationError(f"{Path(args[0]).stem} failed (exit {result.returncode}{suffix})")
    if len(result.stdout) > 512 * 1024:
        raise PublicationError("Command output exceeds budget")
    return result.stdout


class GitHubDocumentStore:
    def __init__(self, repository: str, branch: str, path: str, gh: str = "gh"):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
            raise ValueError("Expected owner/repository")
        if not branch or branch.startswith("-") or any(c.isspace() for c in branch):
            raise ValueError("Expected an explicit branch")
        if not path or path.startswith("/") or ".." in path.split("/") or "\\" in path:
            raise ValueError("Expected repository-relative document path")
        self.gh, self.branch = gh, branch
        self.endpoint = f"repos/{repository}/contents/{quote(path, safe='/')}"
        self.scope = f"{repository}:{branch}:{path}"

    def api(self, method: str, endpoint: str, body: dict | None = None) -> dict:
        args = [self.gh, "api", "--hostname", "github.com", "--method", method, endpoint,
            "-H", "Accept: application/vnd.github+json", "-H", "Cache-Control: no-cache",
            "-H", "X-GitHub-Api-Version: 2026-03-10"]
        payload = None
        if body is not None:
            args.extend(["--input", "-"])
            payload = json.dumps(body).encode()
        return strict_json(run_command(args, body=payload))

    def read(self) -> RemoteDocument:
        document = self.api("GET", self.endpoint + "?ref=" + quote(self.branch, safe=""))
        if document.get("type") != "file" or document.get("encoding") != "base64":
            raise PublicationError("Expected existing GitHub file; bootstrap it explicitly")
        raw = base64.b64decode("".join(document["content"].split()), validate=True)
        if len(raw) > MAX_ENVELOPE or not re.fullmatch(r"[0-9a-f]{40,64}", document["sha"]):
            raise PublicationError("Invalid GitHub document")
        return RemoteDocument(raw, document["sha"])

    def replace(self, raw: bytes, expected_revision: str, version: int) -> None:
        self.api("PUT", self.endpoint, {"branch": self.branch, "sha": expected_revision,
            "content": base64.b64encode(raw).decode(),
            "message": f"ops(discovery): publish verified route configuration v{version}\n\n"
                "Advance signed installation version after scoped route health verification or "
                "scheduled renewal. Preserve device identity and unrelated environment files."})


class Publisher:
    def __init__(self, store: DocumentStore, key: rsa.RSAPrivateKey, key_id: str,
                 installation_id: str, journal: Path, mirror: Path,
                 ttl_seconds: int = 30 * 86400, renew_before_seconds: int = 7 * 86400):
        if not isinstance(key, rsa.RSAPrivateKey) or not 2048 <= key.key_size <= 4096:
            raise ValueError("Expected RSA signing key")
        if not 60 <= renew_before_seconds < ttl_seconds <= 90 * 86400:
            raise ValueError("Invalid renewal window")
        # Do not open the live journal via Path.resolve during construction:
        # Windows readers without delete sharing can interrupt its atomic rename.
        if os.path.normcase(os.path.abspath(journal)) == os.path.normcase(os.path.abspath(mirror)):
            raise ValueError("Journal and public mirror must be different files")
        self.store, self.key, self.key_id = store, key, key_id
        self.installation_id, self.journal, self.mirror = installation_id, journal, mirror
        self.ttl, self.renew_before = ttl_seconds, renew_before_seconds
        self.scope = store.scope + ":" + installation_id + ":" + key_id

    def verify(self, raw: bytes) -> dict:
        return verify_manifest(raw, self.key.public_key(), self.key_id, self.installation_id)

    def save(self, phase: str, raw: bytes, revision: str) -> None:
        data = json.dumps({"scope": self.scope, "phase": phase,
            "envelope": raw.decode(), "base_revision": revision}).encode()
        if not self.journal.exists() or read_bounded(self.journal, MAX_ENVELOPE * 2) != data:
            atomic_write(self.journal, data)

    def reconcile(self, primary: str, fallback: str | None, now: int) -> dict:
        """Caller holds the process lock and has verified route reachability/installation."""
        desired = {"schema_version": 1, "installation_id": self.installation_id,
            "config_version": 1, "issued_at": now, "expires_at": now + self.ttl,
            "server_url": primary}
        if fallback and fallback != primary:
            desired["fallback_server_url"] = fallback
        validate_payload(desired)
        remote = self.store.read()
        current = self.verify(remote.raw)
        if current["issued_at"] > now + 300:
            raise PublicationError("Publisher clock is behind the signed document")
        pending_raw = None
        if self.journal.exists():
            saved = strict_json(read_bounded(self.journal, MAX_ENVELOPE * 2))
            if saved.get("scope") != self.scope or saved.get("phase") not in {"pending", "committed"}:
                raise PublicationError("Journal belongs to a different publication scope")
            saved_raw = saved["envelope"].encode()
            previous = self.verify(saved_raw)
            if previous["issued_at"] > now + 300:
                raise PublicationError("Publisher clock is behind its journal")
            if current["config_version"] == previous["config_version"] and current != previous:
                raise PublicationError("Conflicting signed payloads at the same version")
            if current["config_version"] < previous["config_version"]:
                if saved["phase"] != "pending" or saved["base_revision"] != remote.revision:
                    raise PublicationError("Remote version is behind the publication journal")
                # Retry the exact signed bytes after a lost request/response; never reuse
                # this version for a new route, timestamp or expiry.
                pending_raw = saved_raw
        raw = pending_raw or remote.raw
        payload = self.verify(raw)
        same_routes = all(payload.get(k) == desired.get(k) for k in ("server_url", "fallback_server_url"))
        if not same_routes or payload["expires_at"] <= now + self.renew_before:
            # A pending route may no longer be the currently verified connector.
            # Supersede it at a greater version instead of publishing stale routes
            # or giving the same reserved version different signed bytes.
            desired["config_version"] = payload["config_version"] + 1
            raw = make_manifest(desired, self.key, self.key_id)
            payload = self.verify(raw)
        publish = raw != remote.raw
        if publish:
            self.save("pending", raw, remote.revision)
            self.store.replace(raw, remote.revision, payload["config_version"])
            # Read back API state rather than claiming success from an ambiguous PUT.
            observed = self.store.read()
            if self.verify(observed.raw) != payload:
                raise PublicationError("Concurrent document change after publication")
            remote = observed
        # Repair a lost mirror write even when GitHub needs no new commit.
        if not self.mirror.exists() or read_bounded(self.mirror, MAX_ENVELOPE) != raw:
            atomic_write(self.mirror, raw)
        self.save("committed", raw, remote.revision)
        return {"action": "published" if publish else "unchanged",
            "config_version": payload["config_version"], "server_url": payload["server_url"],
            "expires_at": payload["expires_at"], "mirror_verified": True,
            "desired_route_pending": any(payload.get(k) != desired.get(k) for k in ("server_url", "fallback_server_url"))}


class QuickTunnelSource:
    def __init__(self, project: str, service: str, docker: str = "docker", cache_path: Path | None = None):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]+", project) or not re.fullmatch(r"[a-z0-9-]+", service):
            raise ValueError("Explicit Compose project and service required")
        self.project, self.service, self.docker = project, service, docker
        self.last_identity: tuple[str, str] | None = None
        self.last_url: str | None = None
        self.cache_path = cache_path

    def observe(self) -> str:
        ids = run_command([self.docker, "ps", "-q", "--filter", "label=com.docker.compose.project=" + self.project,
            "--filter", "label=com.docker.compose.service=" + self.service]).decode().split()
        if len(ids) != 1:
            raise PublicationError("Expected exactly one running connector for configured scope")
        container = json.loads(run_command([self.docker, "inspect", ids[0]]))[0]
        labels, state = container["Config"]["Labels"], container["State"]
        if (labels.get("com.docker.compose.project") != self.project
                or labels.get("com.docker.compose.service") != self.service
                or not state["Running"] or state["Paused"]
                or state.get("Health", {}).get("Status") != "healthy"):
            raise PublicationError("Scoped connector is not healthy")
        identity = (container["Id"], state["StartedAt"])
        if self.last_identity is None and self.cache_path and self.cache_path.exists():
            try:
                cached = strict_json(read_bounded(self.cache_path, 4096))
                if (cached.get("project") == self.project and cached.get("service") == self.service
                        and cached.get("identity") == list(identity)
                        and re.fullmatch(r"https://[a-z0-9-]+\.trycloudflare\.com", cached.get("url", ""))):
                    self.last_identity, self.last_url = identity, cached["url"]
            except (ValueError, TypeError):
                pass  # Observation cache is not the signed version floor; re-observe logs.
        if identity != self.last_identity:
            # cloudflared writes the new URL to stderr. Bound log size and filter
            # by this process start so retained logs cannot advertise a prior URL.
            result = subprocess.run([self.docker, "logs", "--since", state["StartedAt"], "--tail", "500",
                container["Id"]], capture_output=True, timeout=15, check=False)
            if result.returncode or len(result.stdout) + len(result.stderr) > 512 * 1024:
                raise PublicationError("Cannot read bounded connector startup logs")
            urls = re.findall(rb"https://[a-z0-9-]+\.trycloudflare\.com\b", result.stdout + result.stderr)
            if not urls:
                raise PublicationError("Current connector URL absent from startup logs")
            self.last_url, self.last_identity = urls[-1].decode(), identity
            if self.cache_path:
                atomic_write(self.cache_path, json.dumps({"project": self.project, "service": self.service,
                    "identity": identity, "url": self.last_url}).encode())
        if self.last_url is None:
            raise PublicationError("Missing observed route")
        return self.last_url


def verify_route(client: httpx.Client, url: str, installation_id: str) -> None:
    for path in ("/api/v1/config/agent", "/api/v1/health/readyz"):
        with client.stream("GET", url + path, headers={"Cache-Control": "no-cache"}) as response:
            if response.status_code != 200:
                raise PublicationError("Candidate route is not ready")
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > MAX_ENVELOPE:
                    raise PublicationError("Candidate probe exceeds budget")
            body = strict_json(bytes(data))
            if path.endswith("/agent") and body.get("installation_id") != installation_id:
                raise PublicationError("Candidate route belongs to a different installation")


def run(config: dict, *, once: bool) -> None:
    private = Path(config["private_key"])
    state_dir, mirror = Path(config["state_dir"]), Path(config["mirror"])
    if not all(p.is_absolute() for p in (private, state_dir, mirror)):
        raise ValueError("Use absolute paths for supervised runs")
    if (private.resolve().is_relative_to(mirror.parent.resolve())
            or private.resolve().is_relative_to(state_dir.resolve())
            or state_dir.resolve().is_relative_to(mirror.parent.resolve())
            or mirror.resolve().is_relative_to(state_dir.resolve())):
        raise ValueError("Private signing state must be outside the public directory")
    interval = config.get("interval_seconds", 60)
    if not 30 <= interval <= 3600:
        raise ValueError("Invalid polling interval")
    key = serialization.load_pem_private_key(read_bounded(private, 16 * 1024), password=None)
    store = GitHubDocumentStore(config["repository"], config["branch"], config["document_path"], config.get("gh", "gh"))
    source = QuickTunnelSource(config["compose_project"], config["compose_service"], config.get("docker", "docker"),
        state_dir / "source.json")
    publisher = Publisher(store, key, config["key_id"], config["installation_id"],
        state_dir / "journal.json", mirror)
    with exclusive_lock(state_dir / "publisher.lock"), httpx.Client(timeout=8, follow_redirects=False) as client:
        last_success = None
        if (state_dir / "status.json").exists():
            try:
                prior_status = strict_json(read_bounded(state_dir / "status.json", 16 * 1024))
                if prior_status.get("scope") == publisher.scope:
                    last_success = prior_status.get("last_success_at")
            except (ValueError, OSError):
                pass
        while True:
            started = time.monotonic()
            try:
                route = source.observe()
                verify_route(client, route, config["installation_id"])
                fallback = config.get("fallback_url")
                if fallback and fallback != route:
                    verify_route(client, fallback, config["installation_id"])
                # A restarted/replaced connector must not publish a just-observed stale URL.
                if source.observe() != route:
                    raise PublicationError("Connector changed during readiness verification")
                result = publisher.reconcile(route, fallback, int(time.time()))
                last_success = int(time.time())
                status = {"status": "ok", **result}
            except Exception as exc:
                status = {"status": "error", "error_type": type(exc).__name__,
                    "reason": str(exc) if isinstance(exc, PublicationError) else type(exc).__name__}
            status.update(checked_at=int(time.time()), last_success_at=last_success,
                duration_seconds=round(time.monotonic() - started, 3), scope=publisher.scope,
                compose_project=source.project, compose_service=source.service)
            atomic_write(state_dir / "status.json", json.dumps(status, indent=2).encode())
            if once:
                print(json.dumps(status))
                if status["status"] != "ok":
                    raise PublicationError("Publication cycle failed; inspect status and scoped services")
                return
            time.sleep(max(1, interval - (time.monotonic() - started)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    run(strict_json(read_bounded(args.config, 16 * 1024)), once=args.once)


if __name__ == "__main__":
    main()
