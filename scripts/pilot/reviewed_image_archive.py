"""Bounded Docker-save verification shared by reviewed UI and API artifacts.

Read only: no extraction, Docker calls, shell execution or runtime admission.
"""
from __future__ import annotations

import hashlib
import json
import re
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any


class AdmissionRuleError(ValueError):
    """Only fixed rule text from this verifier, never parser/native input."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise AdmissionRuleError(reason)


def bounded_json(path: Path, limit: int) -> Any:
    require(path.is_file() and not path.is_symlink(), "Expected regular JSON file")
    require(0 < path.stat().st_size <= limit, "JSON byte budget exceeded")
    return json.loads(path.read_text(encoding="utf-8"))


def _bound_config(record: dict, payloads: dict[str, bytes], image_id: str, sizes: dict[str, int]) -> dict:
    """Classic image IDs hash config; containerd IDs hash an OCI target.

    Never accept an arbitrary config found in the archive. An OCI target must
    cryptographically reach the exact Docker manifest config AND layer list.
    """
    path = record.get("Config")
    require(isinstance(path, str) and path in payloads, "Image config digest mismatch")
    config_payload = payloads[path]
    config_digest = "sha256:" + hashlib.sha256(config_payload).hexdigest()
    if config_digest != image_id:
        by_digest = {"sha256:" + hashlib.sha256(value).hexdigest(): value for value in payloads.values()}
        require(image_id in by_digest, "Image config digest mismatch")
        visited: set[str] = set()

        def walk(digest: str, depth: int) -> set[str]:
            if digest in visited:
                return set()
            require(depth <= 3 and len(visited) < 128, "OCI descriptor traversal budget exceeded")
            visited.add(digest)
            require(digest in by_digest, "OCI referenced descriptor missing")
            node = json.loads(by_digest[digest])
            require(isinstance(node, dict) and node.get("schemaVersion") == 2, "Invalid OCI descriptor schema")
            media = node.get("mediaType")
            if media in {"application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json"}:
                children = node.get("manifests")
                require(isinstance(children, list) and 1 <= len(children) <= 16, "Invalid OCI index inventory")
                matches: set[str] = set()
                child_digests = []
                for child in children:
                    require(isinstance(child, dict), "Invalid OCI index descriptor")
                    target = child.get("digest")
                    require(isinstance(target, str) and re.fullmatch(r"sha256:[a-f0-9]{64}", target), "Invalid OCI digest")
                    require(target in by_digest and type(child.get("size")) is int
                            and child["size"] == len(by_digest[target]), "OCI descriptor size/content mismatch")
                    child_digests.append(target)
                    matches.update(walk(target, depth + 1))
                require(len(set(child_digests)) == len(child_digests), "Duplicate OCI index descriptor")
                return matches
            require(media in {"application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"},
                    "Unsupported OCI descriptor type")
            candidate = node.get("config")
            require(isinstance(candidate, dict), "Invalid OCI config descriptor")
            if candidate.get("digest") != config_digest:
                return set()
            require(type(candidate.get("size")) is int and candidate["size"] == len(config_payload), "OCI config size mismatch")
            layers = node.get("layers")
            require(isinstance(layers, list) and 1 <= len(layers) <= 64, "Invalid OCI layers")
            paths = []
            for layer in layers:
                require(isinstance(layer, dict) and isinstance(layer.get("digest"), str)
                        and re.fullmatch(r"sha256:[a-f0-9]{64}", layer["digest"]), "Invalid OCI layer digest")
                layer_path = "blobs/sha256/" + layer["digest"].removeprefix("sha256:")
                require(type(layer.get("size")) is int and layer_path in sizes
                        and layer["size"] == sizes[layer_path], "OCI layer size/content mismatch")
                paths.append(layer_path)
            require(paths == record.get("Layers"), "OCI and Docker layer inventories differ")
            return {digest}

        require(len(walk(image_id, 0)) == 1, "OCI image identity does not uniquely bind config")
    config = json.loads(config_payload)
    require(isinstance(config, dict), "Invalid image config")
    return config


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
    payloads: dict[str, bytes] = {}
    json_bytes = 0
    members: set[str] = set()
    files: dict[str, int] = {}
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
            files[name] = member.size
            total += member.size + 512
            require(member.size >= 0 and total <= expanded_limit, "Expanded image budget exceeded")
            stream = bundle.extractfile(member)
            require(stream is not None, "Unreadable archive member")
            canonical_blob = re.fullmatch(r"blobs/sha256/([a-f0-9]{64})", name)
            if member.size > json_limit:
                if canonical_blob:
                    content_hash = hashlib.sha256()
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        content_hash.update(chunk)
                    require(content_hash.hexdigest() == canonical_blob[1], "OCI blob content digest mismatch")
                continue
            payload = stream.read(json_limit + 1)
            require(len(payload) == member.size, "Incomplete archive member")
            if canonical_blob:
                require(hashlib.sha256(payload).hexdigest() == canonical_blob[1], "OCI blob content digest mismatch")
            if name == "manifest.json":
                manifest = json.loads(payload)
            elif canonical_blob or name.endswith(".json"):
                try:
                    if not isinstance(json.loads(payload), dict):
                        continue
                except (ValueError, UnicodeError):
                    continue
                json_bytes += len(payload)
                require(len(payloads) < 128 and json_bytes <= 8 * json_limit, "OCI metadata inventory budget exceeded")
                payloads[name] = payload
    require(isinstance(manifest, list) and len(manifest) == 1 and isinstance(manifest[0], dict),
            "Expected exactly one Docker image manifest")
    record = manifest[0]
    require(record.get("RepoTags") == [tag], "Archive tag mismatch/additional tags")
    config = _bound_config(record, payloads, image_id, files)
    require(isinstance(config, dict) and config.get("os") == "linux" and config.get("architecture") == "amd64",
            "Image config platform mismatch")
    layers = record.get("Layers")
    require(isinstance(layers, list) and 1 <= len(layers) <= 64
            and all(isinstance(layer, str) and layer in files for layer in layers), "Missing image layers")
    return config, size
