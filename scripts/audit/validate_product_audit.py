"""Validate frozen product audit evidence, references, counts and dependency graph.

This is an artifact-integrity check, not a claim that audited defects are fixed.
Reads files and Git objects only. Source references are checked at the frozen SHA;
later fixes do not rewrite the historical audit. Screenshots stay immutable.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "docs/audits/2026-10-05"


def main() -> None:
    document = (DIRECTORY / "ENTERPRISE-PRODUCT-AUDIT.md").read_text(encoding="utf-8")
    evidence = json.loads((DIRECTORY / "ENTERPRISE-PRODUCT-AUDIT-EVIDENCE.json").read_text(encoding="utf-8"))
    backlog = json.loads((DIRECTORY / "ENTERPRISE-PRODUCT-BACKLOG.json").read_text(encoding="utf-8"))
    manifest = json.loads((DIRECTORY / "ENTERPRISE-PRODUCT-SOURCE-MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["source"] == evidence["source"]
    assert manifest["frontendGitBlobHashes"].keys() == evidence["frontendSourceHashes"].keys()
    assert len(document.splitlines()) >= 3000, "Required detailed audit is incomplete"
    assert len(document.splitlines()) == evidence["validation"]["documentLineCount"]
    assert evidence["openApiRuntimeMatchesCommitted"] is True
    assert backlog["source"] == evidence["source"]
    items = {item["id"]: item for item in backlog["items"]}
    assert len(items) == len(backlog["items"]) == evidence["counts"]["backlogItems"]
    assert dict(Counter(i["kind"] for i in items.values())) == evidence["counts"]["byKind"]
    assert evidence["counts"]["byKind"]["CONFIRMED_DEFECT"] == 6
    assert len({v["route"] for v in evidence["browser"]}) == 22
    assert len(evidence["httpOperations"]) == 178
    assert all(item["state"] == "OPEN" for item in items.values())
    assert all(len(item["acceptance"]) >= 3 for item in items.values())
    visited, active = set(), set()

    def walk(identity: str) -> None:
        assert identity in items, f"Missing dependency {identity}"
        assert identity not in active, f"Dependency cycle at {identity}"
        if identity in visited:
            return
        active.add(identity)
        for dependency in items[identity]["dependencies"]:
            walk(dependency)
        active.remove(identity)
        visited.add(identity)

    for identity in items:
        walk(identity)
        assert f"### {identity}." in document
    source_lines, source_bytes = {}, {}

    def frozen_source(name: str) -> bytes:
        if name not in source_bytes:
            source_bytes[name] = subprocess.run(
                ["git", "show", f"{evidence['source']}:{name}"], cwd=ROOT,
                check=True, capture_output=True, timeout=10,
            ).stdout
        return source_bytes[name]

    for ref in evidence["sourceReferences"]:
        path = (ROOT / ref["file"]).resolve()
        assert path.is_relative_to(ROOT), "Reference outside repository"
        source_lines.setdefault(ref["file"], frozen_source(ref["file"]).decode("utf-8-sig").splitlines())
        assert 1 <= ref["line"] <= len(source_lines[ref["file"]]), f"Invalid line {ref}"
    assert hashlib.sha256(frozen_source("docs/openapi.json")).hexdigest() == evidence["openApiSha256"]
    for file, digest in manifest["frontendGitBlobHashes"].items():
        # The original inventory recorded mixed LF/CRLF checkout bytes, which
        # cannot be reconstructed after edits. Keep those historical receipts;
        # independently verify the pinned Git blobs with a separate manifest.
        assert hashlib.sha256(frozen_source(file)).hexdigest() == digest, f"Frozen Git receipt mismatch {file}"
    code_links = re.findall(r"https://github\.com/RootOne1337/sphere-platform/blob/([0-9a-f]+)/([^\s)]+)#L(\d+)", document)
    for sha, encoded, line in code_links:
        assert sha == evidence["source"]
        name = unquote(encoded)
        assert name in source_lines and 1 <= int(line) <= len(source_lines[name])
    relative_links = re.findall(r"\]\(([^)]+)\)", document)
    checked_local = 0
    for target in relative_links:
        if "://" in target or target.startswith("#"):
            continue
        path = (DIRECTORY / target.split("#")[0]).resolve()
        assert path.is_relative_to(ROOT) and path.is_file(), f"Missing local link {target}"
        checked_local += 1
    for image in evidence["screenshots"]:
        path = ROOT / image["file"]
        payload = path.read_bytes()
        assert payload[:2] == b"\xff\xd8", f"Screenshot format {path.name}"
        assert len(payload) == image["bytes"]
        assert hashlib.sha256(payload).hexdigest() == image["sha256"]
    published = document + json.dumps(evidence) + json.dumps(backlog)
    assert not re.search(r"tt_[a-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|Bearer\s+eyJ", published)
    print(json.dumps({
        "result": "PASS", "documentLines": len(document.splitlines()),
        "backlogItems": len(items), "sourceReferences": len(evidence["sourceReferences"]),
        "codeLinks": len(code_links), "localLinks": checked_local,
        "reviewedScreenshots": len(evidence["screenshots"]),
        "frozenGitSourcesVerified": len(manifest["frontendGitBlobHashes"]),
        "originalCheckoutByteHashesReplayed": False,
        "productDefectsRemainOpen": True,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
