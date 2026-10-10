"""Read-only admission of one CI Docker-save archive; never extracts or loads it."""
from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.pilot.reviewed_image_archive import admit_archive, bounded_json, require  # noqa: E402

COMPRESSED_LIMIT = 300 * 1024 * 1024
EXPANDED_LIMIT = 1024 * 1024 * 1024
JSON_LIMIT = 1024 * 1024
REQUIRED_ROUTES = {"/", "/login", "/scripts", "/scripts/builder", "/devices", "/monitoring"}


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
    config, size = admit_archive(directory, receipt.get("archive"), image_id, tag,
        compressed_limit=COMPRESSED_LIMIT, expanded_limit=EXPANDED_LIMIT, json_limit=JSON_LIMIT)
    runtime = config.get("config", {})
    require(isinstance(runtime, dict) and runtime.get("User") == "1001:1001", "Expected unprivileged runtime")
    require(runtime.get("Cmd") == ["node", "server.js"] and runtime.get("WorkingDir") == "/app"
            and runtime.get("Entrypoint") == ["docker-entrypoint.sh"] and runtime.get("Volumes") in (None, {}),
            "Unexpected runtime entry")
    labels = runtime.get("Labels", {})
    require(isinstance(labels, dict) and labels.get("org.opencontainers.image.revision") == source
            and labels.get("io.sphere.ci.run") == str(receipt["runId"])
            and labels.get("io.sphere.ci.attempt") == str(receipt["runAttempt"]), "Image CI/source binding mismatch")
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
