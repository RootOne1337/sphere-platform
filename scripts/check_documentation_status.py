"""Validate effective documentation status; never probe or alter a live service.

Run: python -m scripts.check_documentation_status
After adding/removing Markdown: python -m scripts.check_documentation_status --write-inventory
Hashes of frozen evidence use repository-normalized LF bytes for Windows/Linux parity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = "docs/operations/STATUS-REGISTRY.json"
INVENTORY = "docs/operations/DOCUMENT-INVENTORY.json"
SUPPLEMENTAL = {"docs/operations/WORK-STATUS.md", "docs/audits/2026-10-09/DOCUMENTATION-RECONCILIATION.md"}
ROLES = {"CURRENT_ENTRYPOINT", "OPERATING_GUIDE", "DATED_EVIDENCE", "DESIGN_SPECIFICATION", "ADR", "PROJECT_POLICY", "SUPPORTING_DOCUMENT"}
LINK = re.compile(r"(?<!!)\[[^\]\n]+\]\((<[^>]+>|(?:[^\s()]|\([^)]*\))+)\)")


def read_json(root: Path, file: str) -> dict:
    return json.loads((root / file).read_text(encoding="utf-8-sig"))


def normalized_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def markdown_files(root: Path) -> list[str]:
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode("utf-8").split("\0")
    return sorted({p for p in files if p.lower().endswith(".md")} | {p for p in SUPPLEMENTAL if (root / p).is_file()})


def document_role(file: str, entrypoints: list[str]) -> str:
    if file in entrypoints or file == "docs/operations/WORK-STATUS.md":
        return "CURRENT_ENTRYPOINT"
    if file.startswith("docs/audits/") or file.endswith("04-EXECUTION-REPORT.md") or "ANALYSIS-FARMING" in file:
        return "DATED_EVIDENCE"
    if file.startswith(("specs/", "docs/specs/", "docs/design/", "docs/load-test/")) or file.endswith("AI-READINESS.md"):
        return "DESIGN_SPECIFICATION"
    if file.startswith("docs/adr/"):
        return "ADR"
    if file in {"CONTRIBUTING.md", "SECURITY.md", "SUPPORT.md"} or file.startswith(".github/"):
        return "PROJECT_POLICY"
    if file.startswith("docs/"):
        return "OPERATING_GUIDE"
    return "SUPPORTING_DOCUMENT"


def make_inventory(root: Path, registry: dict) -> dict:
    records = [{"file": p, "role": document_role(p, registry["authoritativeEntrypoints"])} for p in markdown_files(root)]
    return {
        "schemaVersion": 1,
        "reviewedAtUtc": registry["reviewedAtUtc"],
        "scope": "All tracked Markdown classified; active local-link paths scanned. Not semantic attestation of every sentence, command execution, external-link or live acceptance.",
        "countsByRole": dict(sorted(Counter(r["role"] for r in records).items())),
        "documents": records,
    }


def local_link_errors(root: Path, file: str) -> list[str]:
    """Check inline local path targets, including encoded spaces and one balanced pair.

    Anchors and reference-style links are outside this bounded scanner's coverage.
    Code fences are examples, not navigation.
    """
    text = (root / file).read_text(encoding="utf-8-sig")
    text = re.sub(r"(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?^\s*\1\s*$", "", text)
    errors = []
    for match in LINK.finditer(text):
        target = match[1].strip("<>")
        parts = urlsplit(target)
        if parts.scheme or parts.netloc or not parts.path:
            continue
        path = unquote(parts.path)
        if path.startswith("/"):
            # Web route, not a repo-relative document target.
            continue
        resolved = ((root / file).parent / path).resolve()
        if not resolved.is_relative_to(root.resolve()):
            errors.append(f"{file}: local link escapes repository: {target}")
        elif not resolved.exists():
            errors.append(f"{file}: missing local link: {target}")
    return errors


def validate_registry(root: Path, registry: dict) -> list[str]:
    errors: list[str] = []
    baseline = read_json(root, registry["baseline"])
    originals = {item["id"]: item for item in baseline["items"]}
    items = registry["items"]
    ids = [item["id"] for item in items]
    if len(ids) != len(set(ids)) or set(ids) != set(originals):
        errors.append("Product IDs must match all unique baseline IDs")
    counts = Counter(item["state"] for item in items)
    if set(counts) - {"OPEN", "ACCEPTED_RECORDED_SCOPE"}:
        errors.append("Unsupported product state")
    expected = {"items": len(items), "acceptedRecordedScope": counts["ACCEPTED_RECORDED_SCOPE"], "open": counts["OPEN"]}
    if registry["counts"] != expected:
        errors.append("Declared product counts disagree with item states")
    for item in items:
        id = item["id"]
        original = originals.get(id)
        if original is not None:
            for field, baseline_field in (("acceptanceCriteria", "acceptance"), ("dependencies", "dependencies"), ("kind", "kind"), ("priority", "priority")):
                if item[field] != original[baseline_field]:
                    errors.append(f"{id}: changed baseline {field}")
        if item["fleetAccepted"]:
            errors.append(f"{id}: fleet acceptance is not supported by this ledger")
        if item["estimatedScope"] not in {"S", "M", "L", "XL"}:
            errors.append(f"{id}: invalid estimated scope")
        if item["state"] == "ACCEPTED_RECORDED_SCOPE":
            evidence = item.get("acceptanceEvidence")
            if not evidence or not (root / evidence).is_file():
                errors.append(f"{id}: accepted without an existing receipt")
            elif item.get("acceptanceEvidenceSha256NormalizedLf") != normalized_hash(root / evidence):
                errors.append(f"{id}: frozen closure receipt fingerprint mismatch")
            else:
                receipt = read_json(root, evidence)
                ledger = receipt.get("ledger", {})
                admitted = ledger.get("closedInThisBatch", ledger.get("defectsFixedInThisBatch", []))
                if id not in admitted:
                    errors.append(f"{id}: receipt does not admit this item in its recorded batch")
            if item["progress"] != "ACCEPTED_FINITE" or not item["currentScope"]:
                errors.append(f"{id}: accepted scope/progress missing")
        elif not item["remaining"]:
            errors.append(f"{id}: OPEN without remaining criteria")
        for source in item["sourceRefs"]:
            if not (root / source["file"]).is_file():
                errors.append(f"{id}: missing source {source['file']}")
    legacy = registry["legacy"]
    unclosed = legacy["partial"] + legacy["open"]
    if len(set(unclosed)) != len(unclosed) or legacy["unclosed"] != len(unclosed) or legacy["total"] != legacy["sourceFixed"] + len(unclosed):
        errors.append("Legacy counts/membership disagree")
    if set(legacy["productCrosswalk"]) != set(unclosed):
        errors.append("Legacy crosswalk does not cover remaining findings")
    for related in legacy["productCrosswalk"].values():
        if not set(related) <= set(ids):
            errors.append("Legacy crosswalk references an unknown product item")
    chats = registry["chatRequirements"]
    if len({r["id"] for r in chats}) != len(chats):
        errors.append("Duplicate chat requirement")
    for req in chats:
        if not set(req["productItems"]) <= set(ids) or not req["remaining"]:
            errors.append(f"{req['id']}: invalid mapping or missing residual scope")
        if req["state"] not in {"ACCEPTED_FINITE", "PARTIAL", "OPEN", "SOURCE_FIXED_NOT_INSTALLED", "DEFERRED_DESIGN"}:
            errors.append(f"{req['id']}: unsupported state")
        if req["state"] == "ACCEPTED_FINITE" and not req["evidence"]:
            errors.append(f"{req['id']}: finite acceptance without receipt")
        for file in req["evidence"] + req["sourcePaths"]:
            if not (root / file).is_file():
                errors.append(f"{req['id']}: missing reference {file}")
    for correction in registry["pendingCorrections"]:
        if correction["installed"] or not (root / correction["evidence"]).is_file():
            errors.append("Pending source correction incorrectly marked installed or missing receipt")
    completed = registry.get("completedCorrections", [])
    if len({item["id"] for item in completed}) != len(completed):
        errors.append("Duplicate completed correction")
    for correction in completed:
        path = root / correction["evidence"]
        if not path.is_file() or correction.get("evidenceSha256NormalizedLf") != normalized_hash(path):
            errors.append("Completed correction receipt missing or fingerprint mismatch")
            continue
        receipt = read_json(root, correction["evidence"])
        if (receipt.get("correction") != {"id": correction["id"], "sourceRevision": correction["sourceRevision"]}
                or receipt.get("runtimeInstalled") is not True
                or receipt.get("runtime", {}).get("sourceRevision") != correction["installedRevision"]
                or receipt.get("browser", {}).get("finiteAccepted") is not True):
            errors.append("Completed correction does not match its installed finite receipt")
        if (registry["installed"]["evidence"] == correction["evidence"]
                and registry["installed"]["ui"] != correction["installedRevision"]):
            errors.append("Installed UI does not match referenced correction receipt")
    if registry["directMedia"]["implementationAuthorizedNow"] or registry["directMedia"]["state"] != "DEFERRED_DESIGN":
        errors.append("Direct-media implementation is outside this reconciliation scope")
    for file in registry["authoritativeEntrypoints"]:
        if "WORK-STATUS" not in (root / file).read_text(encoding="utf-8-sig"):
            errors.append(f"{file}: missing authoritative work-status pointer")
    for key in ("previousCrosscheck",):
        if not (root / registry[key]).is_file():
            errors.append(f"Missing {key}")
    return errors


def validate_inventory(root: Path, registry: dict, inventory: dict) -> list[str]:
    records = inventory["documents"]
    files = [r["file"] for r in records]
    errors = []
    if len(files) != len(set(files)) or set(files) != set(markdown_files(root)):
        errors.append("Markdown inventory is incomplete, stale or duplicated; regenerate it")
    if inventory["countsByRole"] != dict(Counter(r["role"] for r in records)):
        errors.append("Inventory role counts disagree")
    for record in records:
        if record["role"] not in ROLES or record["role"] != document_role(record["file"], registry["authoritativeEntrypoints"]):
            errors.append(f"{record['file']}: incorrect documentation role")
        if record["role"] in {"CURRENT_ENTRYPOINT", "OPERATING_GUIDE"}:
            errors.extend(local_link_errors(root, record["file"]))
    return errors


def validate_status_report(registry: dict, text: str) -> list[str]:
    """Require the human-facing table to agree with the machine ledger."""
    rows = re.findall(r"^\| (EP-\d{3}) \| (P\d) \| ([SMLX]+) \| ([A-Z_]+) / ([A-Z_]+) \|", text, re.MULTILINE)
    expected = [(i["id"], i["priority"], i["estimatedScope"], i["state"], i["progress"]) for i in registry["items"]]
    errors = []
    if rows != expected:
        errors.append("WORK-STATUS product table disagrees with machine registry")
    counts = registry["counts"]
    if f"**{counts['acceptedRecordedScope']} принято / {counts['open']} открыто из {counts['items']}**" not in text:
        errors.append("WORK-STATUS product totals disagree")
    for req in registry["chatRequirements"]:
        pattern = rf"### {re.escape(req['id'])} · [^\n]+\n\n\*\*{re.escape(req['state'])}\*\*"
        if not re.search(pattern, text):
            errors.append(f"{req['id']}: WORK-STATUS requirement state missing or stale")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-inventory", action="store_true", help="Write documentation inventory only; no service actions")
    args = parser.parse_args()
    registry = read_json(ROOT, REGISTRY)
    if args.write_inventory:
        (ROOT / INVENTORY).write_text(json.dumps(make_inventory(ROOT, registry), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    inventory = read_json(ROOT, INVENTORY)
    errors = (validate_registry(ROOT, registry) + validate_inventory(ROOT, registry, inventory)
              + validate_status_report(registry, (ROOT / "docs/operations/WORK-STATUS.md").read_text(encoding="utf-8-sig")))
    print(json.dumps({"valid": not errors, "product": registry["counts"], "legacyUnclosed": registry["legacy"]["unclosed"],
                      "chatRequirements": len(registry["chatRequirements"]), "markdownDocuments": len(inventory["documents"]),
                      "roles": inventory["countsByRole"], "errors": errors}, ensure_ascii=False, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
