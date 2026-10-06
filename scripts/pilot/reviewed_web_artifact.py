"""Read-only admission of one CI Docker-save archive; never extracts or loads it."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

COMPRESSED_LIMIT = 300 * 1024 * 1024
EXPANDED_LIMIT = 1024 * 1024 * 1024
JSON_LIMIT = 1024 * 1024
REQUIRED_ROUTES = {"/", "/login", "/scripts", "/scripts/builder", "/devices", "/monitoring"}


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def bounded_json(path: Path, limit: int) -> Any:
    require(path.is_file() and not path.is_symlink(), "Expected regular JSON file")
    require(0 < path.stat().st_size <= limit, "JSON byte budget exceeded")
    return json.loads(path.read_text(encoding="utf-8"))


def admit(directory: Path, source: str) -> dict[str, Any]:
    require(bool(re.fullmatch(r"[a-f0-9]{40}", source)), "Expected full source revision")
    directory = directory.resolve(strict=True)
    receipt = bounded_json(directory / "receipt.json", 256 * 1024)
    require(isinstance(receipt, dict) and receipt.get("schemaVersion") == 1, "Invalid receipt schema")
    require(receipt.get("sourceRevision") == source, "Source revision mismatch")
    require(receipt.get("repository") == "RootOne1337/sphere-platform", "Repository mismatch")
    for key in ("runId", "runAttempt"):
        require(type(receipt.get(key)) is int and receipt[key] > 0, "Invalid CI identity")
    require(receipt.get("runtimeInstalled") is False, "Artifact receipt cannot prove runtime admission")
    image = receipt.get("image", {})
    tag = f"sphere-review-frontend:{source}"
    require(isinstance(image, dict) and image.get("tag") == tag, "Unexpected image tag")
    image_id = image.get("id", "")
    require(isinstance(image_id, str) and bool(re.fullmatch(r"sha256:[a-f0-9]{64}", image_id)), "Invalid image digest")
    require(image.get("os") == "linux" and image.get("architecture") == "amd64", "Wrong platform")
    probe = receipt.get("probe", {})
    require(isinstance(probe, dict) and probe.get("loopbackOnly") is True
            and probe.get("readOnlyContainer") is True, "Missing image HTTP admission")
    require(probe.get("browserHydrationVerified") is False and probe.get("backendExecutionVerified") is False,
            "HTTP admission must not imply browser/API acceptance")
    require(type(probe.get("clientAssetsVerified")) is int and 0 < probe["clientAssetsVerified"] <= 512,
            "Invalid client asset admission")
    pages = probe.get("pages")
    require(isinstance(pages, list) and 1 <= len(pages) <= 512, "Invalid page admission")
    routes = set()
    for page in pages:
        require(isinstance(page, dict) and isinstance(page.get("route"), str), "Invalid route receipt")
        route = page["route"]
        require(bool(re.fullmatch(r"/[a-zA-Z0-9/_-]*", route)) and route not in routes, "Invalid/duplicate route")
        routes.add(route)
        if route == "/":
            require((page.get("status") in (307, 308) and page.get("redirect") == "http")
                    or (page.get("status") == 200 and page.get("redirect") in ("next-meta", "next-flight")),
                    "Unverified root redirect")
        else:
            require(page.get("status") == 200, "Page not admitted")
    require(REQUIRED_ROUTES <= routes, "Core pages absent")
    archive = receipt.get("archive", {})
    require(isinstance(archive, dict) and archive.get("file") == "image.tar.gz", "Unexpected archive path")
    require(archive.get("maxExpandedBytes") == EXPANDED_LIMIT, "Unexpected expansion budget")
    path = directory / "image.tar.gz"
    require(path.is_file() and not path.is_symlink(), "Expected regular image archive")
    size = path.stat().st_size
    require(type(archive.get("bytes")) is int and 0 < size <= COMPRESSED_LIMIT and size == archive["bytes"],
            "Compressed image size mismatch/budget exceeded")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    require(digest.hexdigest() == archive.get("sha256"), "Archive SHA256 mismatch")
    manifest = None
    configs: dict[str, tuple[str, Any]] = {}
    members: set[str] = set()
    total = 0
    with tarfile.open(path, mode="r|gz") as bundle:
        for member in bundle:
            name = member.name
            parts = PurePosixPath(name).parts
            require(name and not name.startswith("/") and ".." not in parts and "\\" not in name,
                    "Unsafe archive member")
            require(name not in members and len(members) < 2048, "Duplicate/oversized archive inventory")
            members.add(name)
            require(member.isdir() or member.isfile(), "Archive links/special files rejected")
            if member.isdir():
                continue
            total += member.size + 512  # Include per-file tar header overhead in expansion budget.
            require(member.size >= 0 and total <= EXPANDED_LIMIT, "Expanded image budget exceeded")
            stream = bundle.extractfile(member)
            require(stream is not None, "Unreadable archive member")
            if member.size > JSON_LIMIT:
                continue  # tarfile skips payload; no extraction or layer interpretation.
            payload = stream.read(JSON_LIMIT + 1)
            require(len(payload) == member.size, "Incomplete archive member")
            if name == "manifest.json":
                manifest = json.loads(payload)
            elif hashlib.sha256(payload).hexdigest() == image_id.removeprefix("sha256:"):
                configs[name] = (hashlib.sha256(payload).hexdigest(), json.loads(payload))
    require(isinstance(manifest, list) and len(manifest) == 1 and isinstance(manifest[0], dict),
            "Expected exactly one Docker image manifest")
    record = manifest[0]
    require(record.get("RepoTags") == [tag], "Archive tag mismatch/additional tags")
    require(record.get("Config") in configs, "Image config digest mismatch")
    config = configs[record["Config"]][1]
    require(isinstance(config, dict) and config.get("os") == "linux" and config.get("architecture") == "amd64",
            "Image config platform mismatch")
    runtime = config.get("config", {})
    require(isinstance(runtime, dict) and runtime.get("User") == "1001:1001", "Expected unprivileged runtime")
    require(runtime.get("Cmd") == ["node", "server.js"] and runtime.get("WorkingDir") == "/app"
            and runtime.get("Entrypoint") == ["docker-entrypoint.sh"] and runtime.get("Volumes") in (None, {}),
            "Unexpected runtime entry")
    labels = runtime.get("Labels", {})
    require(isinstance(labels, dict) and labels.get("org.opencontainers.image.revision") == source
            and labels.get("io.sphere.ci.run") == str(receipt["runId"])
            and labels.get("io.sphere.ci.attempt") == str(receipt["runAttempt"]), "Image CI/source binding mismatch")
    layers = record.get("Layers")
    require(isinstance(layers, list) and 1 <= len(layers) <= 64
            and all(isinstance(layer, str) and layer in members for layer in layers), "Missing image layers")
    return {"sourceRevision": source, "imageId": image_id, "imageTag": tag, "archiveBytes": size,
            "runId": receipt["runId"], "runAttempt": receipt["runAttempt"], "pages": len(pages),
            "clientAssets": probe["clientAssetsVerified"], "archiveAdmitted": True, "runtimeInstalled": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(admit(args.directory, args.source)))
    except (ValueError, OSError, tarfile.TarError, TypeError, KeyError):
        print(json.dumps({"archiveAdmitted": False, "runtimeInstalled": False}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
