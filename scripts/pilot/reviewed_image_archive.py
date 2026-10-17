"""Bounded Docker-save verification shared by reviewed UI and API artifacts.

Read only: no extraction, Docker calls, shell execution or runtime admission.
"""
from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def bounded_json(path: Path, limit: int) -> Any:
    require(path.is_file() and not path.is_symlink(), "Expected regular JSON file")
    require(0 < path.stat().st_size <= limit, "JSON byte budget exceeded")
    return json.loads(path.read_text(encoding="utf-8"))


def admit_archive(directory: Path, archive: Any, image_id: str, tag: str, *,
                  compressed_limit: int, expanded_limit: int, json_limit: int) -> tuple[dict[str, Any], int]:
    require(isinstance(archive, dict) and archive.get("file") == "image.tar.gz", "Unexpected archive path")
    require(archive.get("maxExpandedBytes") == expanded_limit, "Unexpected expansion budget")
    path = directory / "image.tar.gz"
    require(path.is_file() and not path.is_symlink(), "Expected regular image archive")
    size = path.stat().st_size
    require(type(archive.get("bytes")) is int and 0 < size <= compressed_limit and size == archive["bytes"],
            "Compressed image size mismatch/budget exceeded")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    require(digest.hexdigest() == archive.get("sha256"), "Archive SHA256 mismatch")
    manifest = None
    configs: dict[str, Any] = {}
    members: set[str] = set()
    files: set[str] = set()
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
            files.add(name)
            total += member.size + 512
            require(member.size >= 0 and total <= expanded_limit, "Expanded image budget exceeded")
            stream = bundle.extractfile(member)
            require(stream is not None, "Unreadable archive member")
            if member.size > json_limit:
                continue
            payload = stream.read(json_limit + 1)
            require(len(payload) == member.size, "Incomplete archive member")
            if name == "manifest.json":
                manifest = json.loads(payload)
            elif hashlib.sha256(payload).hexdigest() == image_id.removeprefix("sha256:"):
                configs[name] = json.loads(payload)
    require(isinstance(manifest, list) and len(manifest) == 1 and isinstance(manifest[0], dict),
            "Expected exactly one Docker image manifest")
    record = manifest[0]
    require(record.get("RepoTags") == [tag], "Archive tag mismatch/additional tags")
    require(record.get("Config") in configs, "Image config digest mismatch")
    config = configs[record["Config"]]
    require(isinstance(config, dict) and config.get("os") == "linux" and config.get("architecture") == "amd64",
            "Image config platform mismatch")
    layers = record.get("Layers")
    require(isinstance(layers, list) and 1 <= len(layers) <= 64
            and all(isinstance(layer, str) and layer in files for layer in layers), "Missing image layers")
    return config, size
