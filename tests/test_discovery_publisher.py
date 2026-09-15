"""Local signing, actual process locking and failure-injected publication; no WAN writes."""
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from scripts import discovery_publisher as module
from scripts.discovery_manifest import make_manifest, strict_json, verify_manifest
from scripts.discovery_publisher import (
    GitHubDocumentStore,
    PublicationError,
    Publisher,
    QuickTunnelSource,
    RemoteDocument,
    exclusive_lock,
    verify_route,
)

INSTALLATION = "04b8c5d2-c28e-4d12-a687-b3e211a9b6c7"
NOW = 1_800_000_000
PRIMARY = "https://current.trycloudflare.com"
NEW = "https://replacement.trycloudflare.com"


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def payload(version=7, primary=PRIMARY, expires=NOW + 30 * 86400):
    return {"schema_version": 1, "installation_id": INSTALLATION, "config_version": version,
        "issued_at": NOW - 30, "expires_at": expires, "server_url": primary}


class MemoryRemote:
    scope = "owner/config:pilot:discovery.json"

    def __init__(self, raw):
        self.raw = raw
        self.writes = []
        self.fail = None

    def read(self):
        return RemoteDocument(self.raw, hashlib.sha256(self.raw).hexdigest())

    def replace(self, raw, expected_revision, version):
        assert expected_revision == self.read().revision
        self.writes.append(raw)
        if self.fail == "before":
            raise OSError("request lost")
        if self.fail == "conflict":
            raise PublicationError("CAS conflict")
        self.raw = raw
        if self.fail == "after":
            raise OSError("response lost")


@pytest.fixture
def setup(tmp_path, key):
    store = MemoryRemote(make_manifest(payload(), key, "test"))
    def create():
        return Publisher(store, key, "test", INSTALLATION, tmp_path / "private/journal.json",
            tmp_path / "public/discovery.json")
    return store, create


def verified(raw, key):
    return verify_manifest(raw, key.public_key(), "test", INSTALLATION)


def test_unchanged_route_repairs_missing_mirror_without_remote_commit(setup):
    store, create = setup
    subject = create()
    for _ in range(4):
        assert subject.reconcile(PRIMARY, None, NOW)["action"] == "unchanged"
    assert not store.writes
    assert subject.mirror.read_bytes() == store.raw
    subject.mirror.write_text("partial old write")
    create().reconcile(PRIMARY, None, NOW)
    assert subject.mirror.read_bytes() == store.raw


def test_route_change_has_one_version_and_no_secrets_in_public_doc(setup, key):
    store, create = setup
    result = create().reconcile(NEW, PRIMARY, NOW)
    assert result["config_version"] == 8
    assert verified(store.raw, key)["fallback_server_url"] == PRIMARY
    assert set(strict_json(store.raw)) == {"key_id", "payload", "signature"}
    assert create().reconcile(NEW, PRIMARY, NOW + 60)["action"] == "unchanged"
    assert len(store.writes) == 1


def test_renewal_increments_once_then_no_commit_on_every_tick(setup, key):
    store, create = setup
    store.raw = make_manifest(payload(expires=NOW + 86400), key, "test")
    assert create().reconcile(PRIMARY, None, NOW)["config_version"] == 8
    assert verified(store.raw, key)["expires_at"] == NOW + 30 * 86400
    assert create().reconcile(PRIMARY, None, NOW + 60)["action"] == "unchanged"
    assert len(store.writes) == 1


@pytest.mark.parametrize("when", ["before", "after"])
def test_ambiguous_request_survives_process_recreation_with_exact_signed_bytes(setup, key, when):
    store, create = setup
    subject = create()
    store.fail = when
    with pytest.raises(OSError):
        subject.reconcile(NEW, None, NOW)
    saved = strict_json(subject.journal.read_bytes())
    assert saved["phase"] == "pending"
    exact = saved["envelope"].encode()
    assert not subject.mirror.exists()
    store.fail = None
    result = create().reconcile(NEW, None, NOW + 10)
    assert result["config_version"] == 8 and verified(store.raw, key) == verified(exact, key)
    assert all(raw == exact for raw in store.writes)
    assert len(store.writes) == (2 if when == "before" else 1)


def test_mirror_disk_failure_recovers_without_second_github_commit(setup, monkeypatch):
    store, create = setup
    subject = create()
    real_write = module.atomic_write
    def fail_mirror(path, raw):
        if path == subject.mirror:
            raise OSError("mirror unavailable")
        real_write(path, raw)
    monkeypatch.setattr(module, "atomic_write", fail_mirror)
    with pytest.raises(OSError):
        subject.reconcile(NEW, None, NOW)
    assert strict_json(subject.journal.read_bytes())["phase"] == "pending"
    monkeypatch.setattr(module, "atomic_write", real_write)
    assert create().reconcile(NEW, None, NOW + 60)["action"] == "unchanged"
    assert len(store.writes) == 1 and subject.mirror.read_bytes() == store.raw


def test_pending_request_does_not_publish_an_old_unverified_route_after_connector_changes(setup, key):
    store, create = setup
    store.fail = "before"
    with pytest.raises(OSError):
        create().reconcile(NEW, None, NOW)
    store.fail = None
    # Only this third route passed the caller's health gate in the new cycle.
    third = "https://third.trycloudflare.com"
    result = create().reconcile(third, None, NOW + 60)
    assert result["server_url"] == third
    assert result["config_version"] == 9  # Do not reuse the journaled v8 for different bytes.
    assert verified(store.raw, key)["server_url"] == third


def test_long_pending_request_does_not_publish_an_expired_manifest(setup, key):
    store, create = setup
    store.fail = "before"
    with pytest.raises(OSError):
        create().reconcile(NEW, None, NOW)
    store.fail = None
    later = NOW + 31 * 86400
    assert create().reconcile(NEW, None, later)["config_version"] == 9
    assert verified(store.raw, key)["expires_at"] > later


def test_journal_failure_prevents_remote_mutation(setup, monkeypatch):
    store, create = setup
    monkeypatch.setattr(module, "atomic_write", lambda *_: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        create().reconcile(NEW, None, NOW)
    assert not store.writes


def test_conflict_never_overwrites_a_different_payload_at_same_version(setup, key):
    store, create = setup
    store.fail = "conflict"
    with pytest.raises(PublicationError):
        create().reconcile(NEW, None, NOW)
    store.raw = make_manifest(payload(version=8, primary="https://operator.invalid"), key, "test")
    store.fail = None
    with pytest.raises(PublicationError, match="Conflicting"):
        create().reconcile(NEW, None, NOW + 10)
    assert len(store.writes) == 1


def test_newer_operator_version_is_preserved_as_floor(setup, key):
    store, create = setup
    create().reconcile(NEW, None, NOW)
    store.raw = make_manifest(payload(version=10, primary=NEW), key, "test")
    assert create().reconcile(PRIMARY, None, NOW + 10)["config_version"] == 11


def test_remote_rollback_and_corrupt_journal_fail_closed(setup, key):
    store, create = setup
    subject = create()
    subject.reconcile(NEW, None, NOW)
    store.raw = make_manifest(payload(), key, "test")
    with pytest.raises(PublicationError, match="behind"):
        create().reconcile(NEW, None, NOW)
    subject.journal.write_text("broken")
    with pytest.raises(ValueError):
        create().reconcile(NEW, None, NOW)
    assert len(store.writes) == 1


def test_journal_is_bound_to_repository_branch_and_installation(setup):
    store, create = setup
    create().reconcile(PRIMARY, None, NOW)
    store.scope += "different-branch"
    with pytest.raises(PublicationError, match="scope"):
        create().reconcile(NEW, None, NOW)
    assert not store.writes


def test_explicitly_retiring_fallback_is_signed_as_complete_route_set(setup, key):
    store, create = setup
    create().reconcile(NEW, PRIMARY, NOW)
    create().reconcile(NEW, None, NOW + 10)
    assert "fallback_server_url" not in verified(store.raw, key)


def test_future_clock_rejected_before_publication(setup, key):
    store, create = setup
    store.raw = make_manifest({**payload(), "issued_at": NOW + 301}, key, "test")
    with pytest.raises(PublicationError, match="clock"):
        create().reconcile(NEW, None, NOW)
    assert not store.writes


def test_actual_os_lock_blocks_other_process_then_releases(tmp_path):
    lock = tmp_path / "publisher.lock"
    code = "from pathlib import Path; from scripts.discovery_publisher import exclusive_lock; " \
        "import sys;\nwith exclusive_lock(Path(sys.argv[1])): print('acquired')"
    with exclusive_lock(lock):
        process = subprocess.run([sys.executable, "-c", code, str(lock)], capture_output=True, timeout=10)
        assert process.returncode != 0 and b"PublisherBusy" in process.stderr
    process = subprocess.run([sys.executable, "-c", code, str(lock)], capture_output=True, timeout=10)
    assert process.returncode == 0 and b"acquired" in process.stdout


def test_32_contending_publishers_create_at_most_one_signed_version(setup):
    store, create = setup
    def attempt(_):
        subject = create()
        try:
            with exclusive_lock(subject.journal.with_suffix(".lock")):
                return subject.reconcile(NEW, None, NOW)
        except module.PublisherBusy:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(32)))
    assert any(results) and len(store.writes) == 1


@pytest.mark.parametrize("status,body", [(503, {}), (200, {"installation_id": "someone-else"}), (302, {})])
def test_route_health_rejects_outage_foreign_installation_and_redirects(status, body):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body))) as client:
        with pytest.raises(PublicationError):
            verify_route(client, NEW, INSTALLATION)


def test_health_probe_sends_no_credentials_and_checks_both_paths():
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"installation_id": INSTALLATION, "status": "ready"})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        verify_route(client, NEW, INSTALLATION)
    assert [r.url.path for r in requests] == ["/api/v1/config/agent", "/api/v1/health/readyz"]
    assert all("authorization" not in r.headers and "x-api-key" not in r.headers for r in requests)


def test_github_transport_uses_exact_branch_cas_and_stdin_body(monkeypatch):
    commands = []
    def run(args, **kwargs):
        commands.append((args, kwargs))
        return json.dumps({"type": "file", "encoding": "base64", "content": "e30=", "sha": "a" * 40}).encode()
    monkeypatch.setattr(module, "run_command", run)
    store = GitHubDocumentStore("owner/repo", "codex/pilot", "pilots/agent.json")
    document = store.read()
    store.replace(b"signed-public-only", document.revision, 9)
    assert commands[0][0][6].endswith("?ref=codex%2Fpilot")
    body = json.loads(commands[1][1]["body"])
    assert body["sha"] == "a" * 40 and body["branch"] == "codex/pilot"
    assert commands[1][0][-2:] == ["--input", "-"]
    assert not any("signed-public-only" in item for item in commands[1][0])


def test_source_uses_exact_scope_and_only_current_process_logs(monkeypatch):
    container = {"Id": "a" * 64, "Config": {"Labels": {"com.docker.compose.project": "isolated-pilot",
        "com.docker.compose.service": "cloudflare-quick"}},
        "State": {"Running": True, "Paused": False, "Health": {"Status": "healthy"}, "StartedAt": "fresh-start"}}
    commands = []
    def run(args, **_):
        commands.append(args)
        return b"abc\n" if args[1] == "ps" else json.dumps([container]).encode()
    monkeypatch.setattr(module, "run_command", run)
    def logs(args, **kwargs):
        assert args[1:4] == ["logs", "--since", "fresh-start"]
        return subprocess.CompletedProcess(args, 0, b"", NEW.encode())
    monkeypatch.setattr(module.subprocess, "run", logs)
    source = QuickTunnelSource("isolated-pilot", "cloudflare-quick")
    assert source.observe() == NEW
    assert "label=com.docker.compose.project=isolated-pilot" in commands[0]
    container["State"]["Paused"] = True
    with pytest.raises(PublicationError, match="healthy"):
        source.observe()


def test_source_cache_survives_publisher_restart_but_not_connector_restart(tmp_path, monkeypatch):
    container = {"Id": "a" * 64, "Config": {"Labels": {"com.docker.compose.project": "isolated-pilot",
        "com.docker.compose.service": "cloudflare-quick"}},
        "State": {"Running": True, "Paused": False, "Health": {"Status": "healthy"}, "StartedAt": "first-start"}}
    monkeypatch.setattr(module, "run_command", lambda args, **_: b"abc" if args[1] == "ps" else json.dumps([container]).encode())
    calls = []
    def logs(args, **_):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, b"", (PRIMARY if args[3] == "first-start" else NEW).encode())
    monkeypatch.setattr(module.subprocess, "run", logs)
    observation = tmp_path / "source.json"
    assert QuickTunnelSource("isolated-pilot", "cloudflare-quick", cache_path=observation).observe() == PRIMARY
    # A new one-shot process can recover its URL even if startup log lines rotated out.
    assert QuickTunnelSource("isolated-pilot", "cloudflare-quick", cache_path=observation).observe() == PRIMARY
    assert len(calls) == 1
    container["State"]["StartedAt"] = "second-start"
    assert QuickTunnelSource("isolated-pilot", "cloudflare-quick", cache_path=observation).observe() == NEW
    assert len(calls) == 2 and calls[-1][3] == "second-start"


def test_source_refuses_similarly_named_foreign_container(monkeypatch):
    container = {"Config": {"Labels": {"com.docker.compose.project": "old-installation",
        "com.docker.compose.service": "cloudflare-quick"}}, "State": {}}
    monkeypatch.setattr(module, "run_command", lambda args, **_: b"abc" if args[1] == "ps" else json.dumps([container]).encode())
    with pytest.raises(PublicationError, match="healthy"):
        QuickTunnelSource("isolated-pilot", "cloudflare-quick").observe()


@pytest.mark.parametrize("raw", [b"", b"one\ntwo\n"])
def test_source_refuses_missing_or_ambiguous_connector(monkeypatch, raw):
    monkeypatch.setattr(module, "run_command", lambda *_: raw)
    with pytest.raises(PublicationError, match="exactly one"):
        QuickTunnelSource("isolated-pilot", "cloudflare-quick").observe()


def test_unhealthy_or_overlarge_probe_does_not_contact_second_route():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, content=b"x" * (module.MAX_ENVELOPE + 1))
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(PublicationError, match="budget"):
            verify_route(client, NEW, INSTALLATION)
    assert len(calls) == 1


def test_run_does_not_publish_or_rewrite_mirror_when_connector_is_down(tmp_path, key, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    private = tmp_path / "private/key.pem"
    private.parent.mkdir()
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    mirror = tmp_path / "public/discovery.json"
    mirror.parent.mkdir()
    original = make_manifest(payload(), key, "test")
    mirror.write_bytes(original)
    config = {"repository": "owner/repo", "branch": "pilot", "document_path": "discovery.json",
        "private_key": str(private), "state_dir": str(tmp_path / "private/state"), "mirror": str(mirror),
        "installation_id": INSTALLATION, "key_id": "test", "compose_project": "isolated-pilot",
        "compose_service": "cloudflare-quick"}
    monkeypatch.setattr(QuickTunnelSource, "observe", lambda _: (_ for _ in ()).throw(PublicationError("down")))
    monkeypatch.setattr(GitHubDocumentStore, "read", lambda _: pytest.fail("No GitHub call for an unverified route"))
    with pytest.raises(PublicationError, match="cycle failed"):
        module.run(config, once=True)
    assert mirror.read_bytes() == original
    state = strict_json((tmp_path / "private/state/status.json").read_bytes())
    assert state["status"] == "error" and state["error_type"] == "PublicationError"
    assert not (tmp_path / "private/state/journal.json").exists()
