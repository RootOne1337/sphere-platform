"""Read-only, explicit ownership plan for local Sphere build images.

No deletion, global prune, service restart or scheduled job. An empty/unknown
ownership proof excludes an image. Plans do not authorize later deletion without
a fresh container/tag/identity check, as containers can change after collection.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

OWNED_REPOSITORIES = frozenset({
    "sphere-review-frontend",
    "sphere-pilot-20260911-backend",
    "sphere-pilot-20260911-frontend",
    "sphere-ui-inspection-recovery-web-tests",
})
ROOT = Path(__file__).resolve().parents[2]
COMMIT_TAG = re.compile(r"[0-9a-f]{7,40}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")


def plan_retention(
    images: list[dict[str, Any]],
    containers: list[dict[str, Any]],
    resolve_commit: Callable[[str], str | None],
    current_commit: str,
    keep_latest: int = 2,
) -> dict[str, Any]:
    if not 2 <= keep_latest <= 10:
        raise ValueError("Retain at least two versions, at most ten.")
    if not re.fullmatch(r"[0-9a-f]{40}", current_commit):
        raise ValueError("Current reviewed commit must be a full verified SHA.")
    if len({image["Id"] for image in images}) != len(images):
        raise ValueError("Duplicate image identities.")
    protected = {container["Image"] for container in containers}
    eligible = []
    excluded: dict[str, int] = {}
    for image in images:
        identity = image["Id"]
        if not IMAGE_ID.fullmatch(identity):
            raise ValueError("Unknown Docker image identity.")
        tags = image.get("RepoTags") or []
        reason = "untagged" if not tags else None
        commits = []
        repositories = set()
        for tag in tags:
            repository, separator, revision = tag.rpartition(":")
            if not separator or repository not in OWNED_REPOSITORIES:
                reason = "foreign-or-unattested-tag"
                break
            if not COMMIT_TAG.fullmatch(revision):
                reason = "noncommit-tag"
                break
            commit = resolve_commit(revision)
            if commit is None or not re.fullmatch(r"[0-9a-f]{40}", commit):
                reason = "unresolved-source"
                break
            commits.append(commit)
            repositories.add(repository)
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        created = datetime.fromisoformat(image["Created"].replace("Z", "+00:00"))
        if created.tzinfo is None:
            raise ValueError("Image creation time must have a timezone.")
        if current_commit in commits:
            protected.add(identity)
        eligible.append({"imageId": identity, "tags": sorted(tags),
                         "created": image["Created"], "logicalBytes": image["Size"],
                         "sourceCommits": commits, "repositories": sorted(repositories),
                         "sortTime": created})
    for repository in OWNED_REPOSITORIES:
        versions = sorted((x for x in eligible if repository in x["repositories"]),
                          key=lambda x: (x["sortTime"], x["imageId"]), reverse=True)
        protected.update(x["imageId"] for x in versions[:keep_latest])
    candidates = [{key: value for key, value in x.items() if key != "sortTime"}
                  for x in eligible if x["imageId"] not in protected]
    return {"schemaVersion": 1, "observedAt": datetime.now(timezone.utc).isoformat(),
            "mode": "read-only-plan", "currentCommit": current_commit,
            "ownedRepositories": sorted(OWNED_REPOSITORIES), "keepLatest": keep_latest,
            "candidateImages": sorted(candidates, key=lambda x: (x["created"], x["imageId"])),
            "protectedImageIds": sorted(protected), "excludedCounts": excluded,
            "containerIdentities": [{"id": x["Id"], "image": x["Image"],
                                      "startedAt": x["State"]["StartedAt"],
                                      "status": x["State"]["Status"]} for x in containers],
            "deletionPerformed": False, "physicalBytesReclaimed": None,
            "requiresFreshIdentityCheckBeforeApply": True}


def command(*arguments: str) -> str:
    result = subprocess.run(arguments, cwd=ROOT, check=True, capture_output=True,
                            text=True, encoding="utf-8", timeout=30)
    if len(result.stdout.encode("utf-8")) > 4 * 1024 * 1024:
        raise ValueError("Native response exceeds report input budget.")
    return result.stdout


def inspect_batches(kind: str, identities: list[str]) -> list[dict[str, Any]]:
    if len(identities) > 4096:
        raise ValueError("Inventory exceeds bounded batch count; no plan written.")
    output = []
    for index in range(0, len(identities), 32):
        output.extend(json.loads(command("docker", kind, "inspect", *identities[index:index + 32])))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-commit", required=True, help="Reviewed installed source commit")
    parser.add_argument("--keep-latest", type=int, default=2, choices=range(2, 11))
    args = parser.parse_args()
    if not COMMIT_TAG.fullmatch(args.current_commit):
        parser.error("Current commit must be a hexadecimal Git revision.")
    cache: dict[str, str | None] = {}

    def resolve(revision: str) -> str | None:
        if revision not in cache:
            try:
                cache[revision] = command("git", "rev-parse", "--verify", revision + "^{commit}").strip()
            except subprocess.CalledProcessError:
                cache[revision] = None
        return cache[revision]

    current = resolve(args.current_commit)
    if current is None:
        parser.error("Reviewed commit does not exist in this checkout.")
    image_ids = list(dict.fromkeys(command("docker", "image", "ls", "-q", "--no-trunc").splitlines()))
    container_ids = command("docker", "ps", "-aq", "--no-trunc").splitlines()
    report = plan_retention(inspect_batches("image", image_ids),
                            inspect_batches("container", container_ids), resolve, current,
                            args.keep_latest)
    # Confirm all-container dependencies stayed constant during native inventory.
    check_ids = command("docker", "ps", "-aq", "--no-trunc").splitlines()
    check = inspect_batches("container", check_ids)
    check_identity = sorted((x["Id"], x["Image"], x["State"]["StartedAt"], x["State"]["Status"]) for x in check)
    planned_identity = sorted((x["id"], x["image"], x["startedAt"], x["status"]) for x in report["containerIdentities"])
    if check_identity != planned_identity:
        raise ValueError("Container baseline changed during inventory; discard plan.")
    destination = ROOT / ".local-pilot" / ("image-retention-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + ".json")
    destination.resolve().relative_to(ROOT.resolve())
    body = json.dumps(report, ensure_ascii=False, indent=2)
    if len(body.encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("Plan exceeds report budget; nothing written.")
    with destination.open("x", encoding="utf-8") as output:
        output.write(body + "\n")
    print(json.dumps({"plan": str(destination), "candidates": len(report["candidateImages"]),
                      "containers": len(report["containerIdentities"]), "deletionPerformed": False}))


if __name__ == "__main__":
    main()
