"""Validate effective documentation status; never probe or alter a live service.

Run: python -m scripts.check_documentation_status
After adding/removing Markdown: python -m scripts.check_documentation_status --write-inventory
Hashes of frozen evidence use repository-normalized LF bytes for Windows/Linux parity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path, PurePosixPath
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


def git_index_paths(root: Path) -> set[str]:
    """Read paths in the Git index, including staged additions and excluding staged deletions."""
    data = subprocess.check_output(["git", "ls-files", "--cached", "--full-name", "-z"], cwd=root)
    return {p for p in data.decode("utf-8", errors="surrogateescape").split("\0") if p}


def markdown_files(root: Path) -> list[str]:
    files = git_index_paths(root)
    return sorted({p for p in files if p.lower().endswith(".md")} | {p for p in SUPPLEMENTAL if (root / p).is_file()})


def document_role(file: str, entrypoints: list[str]) -> str:
    if file in entrypoints or file == "docs/operations/WORK-STATUS.md":
        return "CURRENT_ENTRYPOINT"
    if file.startswith(("docs/audits/", "docs/history/")) or file.endswith("04-EXECUTION-REPORT.md") or "ANALYSIS-FARMING" in file:
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


def markdown_navigation_text(text: str) -> str:
    """Mask fenced blocks and matched inline code spans; not a full GFM parser."""
    visible: list[str] = []
    fence: tuple[str, int] | None = None
    for line in text.splitlines(keepends=True):
        if fence:
            marker, length = fence
            if re.fullmatch(rf"[ \t]*{re.escape(marker)}{{{length},}}[ \t]*", line.rstrip("\r\n")):
                fence = None
            visible.append("\n" if line.endswith("\n") else "")
            continue
        opening = re.match(r"^[ \t]*(`{3,}|~{3,})", line)
        if opening:
            fence = (opening.group(1)[0], len(opening.group(1)))
            visible.append("\n" if line.endswith("\n") else "")
        else:
            visible.append(line)
    text = "".join(visible)
    # Delimiters must have equal run length. A single backtick inside a double
    # span, for example, is content and must not end the span early.
    return re.sub(r"(?<!`)(`+)(?!`)(?s:.*?)(?<!`)\1(?!`)",
                  lambda match: re.sub(r"[^\n]", " ", match.group()), text)


def indexed_parent_directories(indexed_paths: set[str]) -> set[str]:
    return {str(parent) for entry in indexed_paths for parent in PurePosixPath(entry).parents}


def local_link_errors(root: Path, file: str, indexed_paths: set[str] | None = None,
                      indexed_directories: set[str] | None = None) -> list[str]:
    """Check inline local path targets, including encoded spaces and one balanced pair.

    Anchors and reference-style links are outside this bounded scanner's coverage.
    Fenced blocks and matched inline code spans are examples, not navigation;
    this is not a complete Markdown parser. If supplied, indexed_paths also
    requires every target to be represented in the Git index. A directory is
    represented when at least one indexed descendant exists.
    """
    text = (root / file).read_text(encoding="utf-8-sig")
    text = markdown_navigation_text(text)
    errors = []
    if indexed_paths is not None and indexed_directories is None:
        indexed_directories = indexed_parent_directories(indexed_paths)
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
        elif indexed_paths is not None:
            lexical = Path(os.path.abspath((root / file).parent / path))
            try:
                relative = lexical.relative_to(root.resolve()).as_posix()
            except ValueError:
                errors.append(f"{file}: local link escapes repository: {target}")
                continue
            if relative not in indexed_paths and not (resolved.is_dir() and relative in (indexed_directories or set())):
                errors.append(f"{file}: local link target not in Git index: {target}")
    return errors


def validate_installed_receipt(root: Path, installed: dict) -> list[str]:
    """Bind the effective UI/API observation to its own frozen finite receipt.

    Later deliveries need not be members of the historical correction list.
    Matching a source SHA alone does not establish installation or acceptance.
    """
    evidence = installed.get("evidence")
    path = root / evidence if isinstance(evidence, str) and evidence else None
    if path is None or not path.is_file():
        return ["Installed observation receipt is missing"]
    if installed.get("evidenceSha256NormalizedLf") != normalized_hash(path):
        return ["Installed observation receipt fingerprint mismatch"]
    try:
        receipt = read_json(root, evidence)
    except (ValueError, UnicodeError):
        return ["Installed observation receipt is not valid JSON"]
    if not isinstance(receipt, dict):
        return ["Installed observation receipt is not valid JSON"]
    errors = []
    runtime = receipt.get("runtime", {})
    if not isinstance(runtime, dict):
        runtime = {}
    browser = receipt.get("browser", {})
    if not isinstance(browser, dict):
        browser = {}
    if receipt.get("runtimeInstalled") is not True or browser.get("finiteAccepted") is not True:
        errors.append("Installed observation lacks installed finite acceptance")
    if not installed.get("ui") or installed["ui"] != runtime.get("sourceRevision"):
        errors.append("Installed UI does not match referenced observation receipt")
    if not installed.get("api") or installed["api"] != runtime.get("apiSourceRevision"):
        errors.append("Installed API does not match referenced observation receipt")
    return errors


def validate_current_apks(root: Path, installed: dict) -> list[str]:
    """A reported APK version must bind to an actual installed package hash.

    Current mixed-version snapshots have an artifact catalog. Historical
    single-version receipts retain their original schema and fingerprints.
    """
    errors = []
    for binding in [installed.get("pilotApk"), *installed.get("additionalPilotApks", [])]:
        if binding is None:
            continue
        path = root / binding.get("evidence", "__missing__")
        if not path.is_file() or binding.get("evidenceSha256NormalizedLf") != normalized_hash(path):
            errors.append("Pilot APK receipt missing or fingerprint mismatch")
            continue
        apk = read_json(root, binding["evidence"]).get("apk", {})
        artifacts = apk.get("artifacts", [apk])
        rows = apk.get("installedDevices", [])
        if not isinstance(artifacts, list) or not isinstance(rows, list):
            errors.append("Pilot APK artifact catalog or installed packages are malformed")
            continue
        artifact = next((r for r in artifacts if isinstance(r, dict)
                         and r.get("versionCode") == binding.get("versionCode")), {})
        package = next((r for r in rows if isinstance(r, dict)
                        and r.get("deviceId") == binding.get("deviceId")), {})
        if (type(binding.get("versionCode")) is not int
                or binding.get("versionCode") != package.get("versionCode")
                or binding.get("version") != artifact.get("version")
                or binding.get("sourceRevision") != artifact.get("sourceRevision")
                or not re.fullmatch(r"[a-f0-9]{64}", str(binding.get("apkSha256", "")))
                or binding.get("apkSha256") != artifact.get("sha256")
                or binding.get("apkSha256") != package.get("installedPackageSha256")):
            errors.append("Pilot APK version/source/hash does not match installed package evidence")
    fleet = installed.get("fleetApkEvidence")
    if fleet:
        path = root / fleet.get("evidence", "__missing__")
        if not path.is_file() or fleet.get("evidenceSha256NormalizedLf") != normalized_hash(path):
            errors.append("Current APK fleet receipt missing or fingerprint mismatch")
        else:
            apk = read_json(root, fleet["evidence"]).get("apk", {})
            rows = apk.get("installedDevices", [])
            artifacts = apk.get("artifacts", [apk])
            if not isinstance(rows, list) or not isinstance(artifacts, list):
                return errors + ["Current APK fleet artifact catalog or installed packages are malformed"]
            ids = [r.get("deviceId") for r in rows if isinstance(r, dict)]
            valid_ids = all(isinstance(d, str)
                            and re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", d)
                            for d in ids)
            if (not valid_ids or len(ids) != len(rows)
                    or valid_ids and len(set(ids)) != len(rows)
                    or type(fleet.get("installedCount")) is not int or fleet["installedCount"] != len(rows)):
                errors.append("Current APK fleet count does not match unique installed packages")
            for row in rows:
                artifact = next((r for r in artifacts if isinstance(r, dict) and isinstance(row, dict)
                                 and type(r.get("versionCode")) is int
                                 and r.get("versionCode") == row.get("versionCode")), {})
                if (not isinstance(row, dict) or type(row.get("versionCode")) is not int
                        or not re.fullmatch(r"[a-f0-9]{64}", str(artifact.get("sha256", "")))
                        or row.get("installedPackageSha256") != artifact.get("sha256")):
                    errors.append("Current APK fleet includes an unverified installed package")
                    break
            if "verifiedVersionCounts" in fleet:
                counts = dict(Counter(str(r.get("versionCode")) for r in rows if isinstance(r, dict)))
                if fleet["verifiedVersionCounts"] != counts:
                    errors.append("Current APK version counts do not match installed package evidence")
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
    delivered = registry.get("installedCorrections", [])
    if len({item["id"] for item in delivered}) != len(delivered):
        errors.append("Duplicate installed correction")
    for correction in delivered:
        path = root / correction.get("deliveryEvidence", "__missing__")
        if not path.is_file() or correction.get("deliveryEvidenceSha256NormalizedLf") != normalized_hash(path):
            errors.append("Installed correction delivery receipt missing or fingerprint mismatch")
            continue
        receipt = read_json(root, correction["deliveryEvidence"])
        if (correction.get("installed") is not True or correction.get("runtimeAccepted") is not False
                or receipt.get("runtimeInstalled") is not True
                or receipt.get("runtime", {}).get("sourceRevision") != correction.get("installedRevision")
                or correction["id"] not in receipt.get("deliveredCorrectionIds", [])):
            errors.append("Installed correction lacks a matching delivery or invents runtime acceptance")
    errors.extend(validate_installed_receipt(root, registry["installed"]))
    errors.extend(validate_current_apks(root, registry["installed"]))
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
    direct = registry["directMedia"]
    if direct["state"] == "DEFERRED_DESIGN":
        if direct["implementationAuthorizedNow"]:
            errors.append("Deferred direct-media design cannot claim implementation authorization")
    elif direct["state"] in {"PROTOTYPE_SOURCE", "DIAGNOSTIC_PILOT_INSTALLED"}:
        if (direct["implementationAuthorizedNow"] is not True or not direct.get("implementationAuthorization")
                or direct.get("prototypeScope") != "diagnostic_echo_only" or direct.get("mediaControlInstalled") is not False
                or direct["state"] == "PROTOTYPE_SOURCE" and direct.get("runtimeInstalled") is not False):
            errors.append("Direct probe source must retain authorization, diagnostic scope and uninstalled gates")
        if not (root / direct.get("implementationEvidence", "__missing__")).is_file():
            errors.append("Direct probe implementation evidence is missing")
        if direct["state"] == "DIAGNOSTIC_PILOT_INSTALLED":
            errors.extend(validate_diagnostic_pilot(root, direct))
    elif direct["state"] == "READONLY_VIDEO_PILOT_INSTALLED":
        if (direct["implementationAuthorizedNow"] is not True or not direct.get("implementationAuthorization")
                or direct.get("prototypeScope") != "readonly_video_v1"
                or direct.get("readOnlyVideoInstalled") is not True or direct.get("directInputInstalled") is not False
                or direct.get("mediaControlInstalled") is not False or direct.get("runtimeInstalled") is not True):
            errors.append("Read-only video pilot cannot imply direct Android input or production media acceptance")
        if not (root / direct.get("implementationEvidence", "__missing__")).is_file():
            errors.append("Direct probe implementation evidence is missing")
        errors.extend(validate_readonly_video_pilot(root, direct))
    elif direct["state"] in {"PRIMARY_VIDEO_PILOT_INSTALLED", "DIRECT_MEDIA_PILOT_INSTALLED"}:
        with_input = direct["state"] == "DIRECT_MEDIA_PILOT_INSTALLED"
        if (direct["implementationAuthorizedNow"] is not True or not direct.get("implementationAuthorization")
                or direct.get("prototypeScope") != ("primary_video_and_input_v1" if with_input else "primary_video_v1")
                or direct.get("primaryVideoInstalled") is not True or direct.get("readOnlyVideoInstalled") is not True
                or direct.get("directInputInstalled") is not with_input or direct.get("mediaControlInstalled") is not with_input
                or direct.get("runtimeInstalled") is not True or direct.get("productionAccepted") is not False
                or type(direct.get("primaryVideoObserved")) is not bool
                or with_input and direct.get("directInputAccepted") is not False):
            errors.append("Direct media installation cannot imply direct input or production acceptance" if with_input
                          else "Primary video pilot cannot imply direct input or production acceptance")
        if not (root / direct.get("implementationEvidence", "__missing__")).is_file():
            errors.append("Direct probe implementation evidence is missing")
        errors.extend(validate_primary_video_pilot(root, direct, with_direct_input=with_input))
        current_evidence = direct.get("currentObservationEvidence")
        if current_evidence:
            if (current_evidence != registry["installed"].get("evidence")
                    or direct.get("currentObservationEvidenceSha256NormalizedLf")
                    != registry["installed"].get("evidenceSha256NormalizedLf")):
                errors.append("Current primary-video observation must match the installed observation receipt")
            path = root / current_evidence
            if path.is_file():
                sample = read_json(root, current_evidence).get("browser", {})
                if direct.get("primaryVideoObserved") is True and (
                        type(sample.get("directFramesPresented")) is not int
                        or sample["directFramesPresented"] <= 0):
                    errors.append("Historical primary frames cannot prove the current direct-video route")
    else:
        errors.append("Direct-media state requires a reviewed implementation/installation gate")
    for file in registry["authoritativeEntrypoints"]:
        if "WORK-STATUS" not in (root / file).read_text(encoding="utf-8-sig"):
            errors.append(f"{file}: missing authoritative work-status pointer")
    for key in ("previousCrosscheck",):
        if not (root / registry[key]).is_file():
            errors.append(f"Missing {key}")
    return errors


def validate_diagnostic_pilot(root: Path, direct: dict) -> list[str]:
    """An installed echo experiment cannot imply media, input or channel acceptance."""
    errors = []
    if (direct.get("runtimeInstalled") is not True or direct.get("pilotCurrentlyEnabled") is not True
            or direct.get("prototypeScope") != "diagnostic_echo_only" or direct.get("mediaControlInstalled") is not False):
        errors.append("Installed diagnostic pilot has inconsistent runtime/scope gates")
    path = root / direct.get("pilotEvidence", "__missing__")
    if not path.is_file() or direct.get("pilotEvidenceSha256NormalizedLf") != normalized_hash(path):
        return errors + ["Installed diagnostic pilot receipt missing or fingerprint mismatch"]
    receipt = read_json(root, str(path.relative_to(root)))
    pilot = receipt.get("diagnosticPilot", {})
    if (receipt.get("runtimeInstalled") is not True or pilot.get("scope") != "diagnostic_echo_only"
            or pilot.get("deviceIds") != direct.get("pilotDeviceIds")
            or not isinstance(pilot.get("deviceIds"), list) or len(pilot["deviceIds"]) != 1
            or not isinstance(pilot["deviceIds"][0], str)
            or not re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", pilot["deviceIds"][0])
            or pilot.get("enabled") is not True or pilot.get("mediaControlInstalled") is not False
            or pilot.get("channelAccepted") is not False):
        errors.append("Installed diagnostic receipt must bind one device and retain unaccepted channel/media gates")
    return errors


def validate_readonly_video_pilot(root: Path, direct: dict) -> list[str]:
    """Separate signed/runtime delivery from the later observation of real RTP frames."""
    path = root / direct.get("pilotEvidence", "__missing__")
    if not path.is_file() or direct.get("pilotEvidenceSha256NormalizedLf") != normalized_hash(path):
        return ["Read-only video installation receipt missing or fingerprint mismatch"]
    receipt = read_json(root, str(path.relative_to(root)))
    pilot, apk = receipt.get("diagnosticPilot", {}), receipt.get("apk", {})
    devices = pilot.get("deviceIds")
    if (receipt.get("runtimeInstalled") is not True or direct.get("pilotCurrentlyEnabled") is not True
            or pilot.get("enabled") is not True or pilot.get("scope") != "readonly_video_v1"
            or pilot.get("readOnlyVideoInstalled") is not True or pilot.get("directInputInstalled") is not False
            or pilot.get("mediaControlInstalled") is not False or pilot.get("videoAccepted") is not False
            or devices != direct.get("pilotDeviceIds") or not isinstance(devices, list) or len(devices) != 1
            or not isinstance(devices[0], str)
            or not re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", devices[0])
            or type(apk.get("versionCode")) is not int or apk["versionCode"] < 10251
            or not isinstance(apk.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", apk["sha256"])
            or apk.get("installedPackageSha256") != apk.get("sha256")):
        return ["Read-only video receipt must bind one updated APK and retain unaccepted video/input gates"]
    return []


def validate_primary_video_pilot(root: Path, direct: dict, *, with_direct_input: bool = False) -> list[str]:
    """Bind the enabled fleet to installed APK hashes, separately from one observed path."""
    path = root / direct.get("pilotEvidence", "__missing__")
    if not path.is_file() or direct.get("pilotEvidenceSha256NormalizedLf") != normalized_hash(path):
        return ["Primary video installation receipt missing or fingerprint mismatch"]
    receipt = read_json(root, str(path.relative_to(root)))
    pilot, apk = receipt.get("diagnosticPilot", {}), receipt.get("apk", {})
    devices, installed = pilot.get("deviceIds"), apk.get("installedDevices")
    uuid_pattern = r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}"
    if (receipt.get("runtimeInstalled") is not True or direct.get("pilotCurrentlyEnabled") is not True
            or pilot.get("enabled") is not True
            or pilot.get("scope") != ("primary_video_and_input_v1" if with_direct_input else "primary_video_v1")
            or pilot.get("primaryVideoInstalled") is not True or pilot.get("directInputInstalled") is not with_direct_input
            or pilot.get("mediaControlInstalled") is not with_direct_input or pilot.get("productionAccepted") is not False
            or with_direct_input and pilot.get("directInputAccepted") is not False
            or not isinstance(devices, list) or not 1 <= len(devices) <= 64
            or any(not isinstance(d, str) or not re.fullmatch(uuid_pattern, d) for d in devices)
            or len(set(devices)) != len(devices) or devices != direct.get("pilotDeviceIds")
            or type(apk.get("versionCode")) is not int or apk["versionCode"] < (10255 if with_direct_input else 10252)
            or not isinstance(apk.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", apk["sha256"])
            or not isinstance(installed, list) or len(installed) != len(devices)):
        return ["Primary video receipt must bind an explicit updated fleet and retain input/production gates"]
    ids = []
    for row in installed:
        if (not isinstance(row, dict) or not isinstance(row.get("deviceId"), str)
                or row.get("installedPackageSha256") != apk["sha256"]
                or type(row.get("versionCode")) is not int or row["versionCode"] != apk["versionCode"]):
            return ["Primary video fleet includes an unverified APK installation"]
        ids.append(row["deviceId"])
    if len(set(ids)) != len(ids) or set(ids) != set(devices):
        return ["Primary video fleet does not match installed APK evidence"]
    observation = receipt.get("browser", {}).get("primaryObservation", {})
    if direct.get("primaryVideoObserved") is True and (
            type(observation.get("framesPresented")) is not int or observation["framesPresented"] <= 0
            or observation.get("deviceId") not in devices or observation.get("transport") != "direct_webrtc"
            or observation.get("controlTransport") not in ({"server_websocket", "direct_webrtc"}
                                                           if with_direct_input else {"server_websocket"})
            or observation.get("localhostRouteProven") is not False
            or observation.get("latencySlaAccepted") is not False):
        return ["Primary video observation cannot invent frames, localhost locality or a latency SLA"]
    if direct.get("primaryVideoObserved") is True and observation.get("controlTransport") == "direct_webrtc":
        gestures = receipt.get("browser", {}).get("nativeGestureObservations")
        if not isinstance(gestures, list) or not any(
                isinstance(row, dict) and row.get("deviceId") == observation.get("deviceId")
                and type(row.get("sentEvents")) is int and row["sentEvents"] >= 3
                and type(row.get("nativeInputReceipts")) is int and 3 <= row["nativeInputReceipts"] <= row["sentEvents"]
                and row.get("nativeDownConfirmed") is True and row.get("nativeUpConfirmed") is True
                and type(row.get("nativeMoveReceipts")) is int and 1 <= row["nativeMoveReceipts"] <= row["nativeInputReceipts"] - 2
                and type(row.get("serverTouchEvents")) is int
                and row["serverTouchEvents"] == 0 for row in gestures):
            return ["Observed direct input requires matching native gesture and UP receipts without server touch events"]
    return []


def validate_inventory(root: Path, registry: dict, inventory: dict) -> list[str]:
    records = inventory["documents"]
    files = [r["file"] for r in records]
    errors = []
    indexed_paths = git_index_paths(root)
    indexed_directories = indexed_parent_directories(indexed_paths)
    if len(files) != len(set(files)) or set(files) != set(markdown_files(root)):
        errors.append("Markdown inventory is incomplete, stale or duplicated; regenerate it")
    if inventory["countsByRole"] != dict(Counter(r["role"] for r in records)):
        errors.append("Inventory role counts disagree")
    for record in records:
        if record["role"] not in ROLES or record["role"] != document_role(record["file"], registry["authoritativeEntrypoints"]):
            errors.append(f"{record['file']}: incorrect documentation role")
        if record["role"] in {"CURRENT_ENTRYPOINT", "OPERATING_GUIDE", "PROJECT_POLICY"}:
            errors.extend(local_link_errors(root, record["file"], indexed_paths, indexed_directories))
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
