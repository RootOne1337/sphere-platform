"""One sequential local CI queue for an explicitly trusted, locally owned branch.

The queue sees only commits already present at the configured LOCAL branch head.
An arbitrary public PR or a remote-only branch update cannot start a host job.
Cloud workflows remain enabled until their separate packaging gates are migrated.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

from scripts.pilot import local_ci as ci
from scripts.pilot.atomic_json import write_json


def volume_exception_authorized(config: dict, now: datetime | None = None) -> bool:
    """An operator's temporary volume warning exception is never a global bypass."""
    exception = config.get("volumeException")
    if exception is None:
        return False
    if not isinstance(exception, dict) or exception.get("authorized") is not True:
        raise ci.Refused("invalid_volume_exception")
    try:
        expiry = datetime.fromisoformat(exception["expiresAtUtc"])
    except (KeyError, TypeError, ValueError):
        raise ci.Refused("invalid_volume_exception_expiry") from None
    current = now or datetime.now(timezone.utc)
    if expiry.tzinfo is None or expiry.utcoffset().total_seconds() != 0:
        raise ci.Refused("utc_volume_exception_expiry_required")
    remaining = (expiry - current).total_seconds()
    if remaining <= 0 or remaining > 24 * 3600:
        raise ci.Refused("volume_exception_expired_or_outside_budget")
    return True


def next_commit(root: Path, trusted_ref: str) -> str | None:
    if not trusted_ref.startswith("refs/heads/"):
        raise ci.Refused("local_trusted_branch_required")
    local_sha = ci.git(root, "rev-parse", "--verify", trusted_ref + "^{commit}")
    if not ci.SHA.fullmatch(local_sha):
        raise ci.Refused("invalid_local_branch_head")
    branch = quote(trusted_ref.removeprefix("refs/heads/"), safe="")
    remote = ci.github(root, f"repos/{ci.REPOSITORY}/branches/{branch}")
    if not isinstance(remote, dict) or remote.get("commit", {}).get("sha") != local_sha:
        return None  # Unpushed local work / remote-only update: do not execute it.
    ci.validate_source(root, local_sha, trusted_ref)
    return local_sha


def tick(config: dict, state: dict) -> dict:
    root = Path(config["root"]).resolve(strict=True)
    sha = next_commit(root, config["trustedRef"])
    if sha is None:
        return state | {"observedAt": ci.utc(), "queueState": "waiting-for-matching-pushed-local-head"}
    # Do not retry a failure every poll, waste resources, or hide its history.
    if state.get("completedSha") == sha:
        return state | {"observedAt": ci.utc(), "queueState": "idle"}
    args = SimpleNamespace(root=str(root), sha=sha, trusted_ref=config["trustedRef"],
                           profiles=config["profiles"], python=config["python"],
                           node=config["node"], java_home=config["javaHome"],
                           android_home=config["androidHome"], publish=True,
                           allow_degraded_volume=volume_exception_authorized(config),
                           report_url=f"https://github.com/{ci.REPOSITORY}/commit/{sha}")
    receipt = ci.run(args)
    return {"schemaVersion": 1, "observedAt": ci.utc(), "queueState": "idle",
            "completedSha": sha, "lastRunId": receipt["runId"], "lastRunState": receipt["state"],
            "trustedRef": config["trustedRef"], "publicForkJobsAccepted": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    root = Path(config["root"]).resolve(strict=True)
    interval = config.get("pollSeconds", 60)
    if type(interval) is not int or not 30 <= interval <= 300:
        raise ci.Refused("poll_interval_outside_budget")
    if not config.get("profiles") or any(profile not in ci.CONTEXTS for profile in config["profiles"]):
        raise ci.Refused("invalid_profile_selection")
    base = root / ".local-pilot/local-ci"
    base.mkdir(parents=True, exist_ok=True)
    state_file = base / "watch.json"
    with ci.execution_lock(base / "watch.lock"):
        state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
        while True:
            try:
                state = tick(config, state)
            except Exception as error:
                state = state | {"observedAt": ci.utc(), "queueState": "blocked",
                                 "reason": str(error) if isinstance(error, ci.Refused) else type(error).__name__}
            write_json(state_file, state)
            if args.once:
                print(json.dumps(state))
                return 0 if state.get("queueState") != "blocked" else 2
            time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
