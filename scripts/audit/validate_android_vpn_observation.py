"""Verify frozen Stage B evidence; does not query live services or accept EP-010."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from xml.etree import ElementTree

from scripts.audit.validate_http_metrics import jpeg_size

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "docs/audits/2026-10-05"


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob.replace(b"\r\n", b"\n")).hexdigest()


def main() -> None:
    if not __debug__:
        raise SystemExit("Run without -O: this integrity checker requires assertions.")
    manifest = json.loads((DIRECTORY / "ENTERPRISE-ANDROID-VPN-OBSERVATION-EVIDENCE.json").read_bytes())
    source = manifest["source"]
    assert re.fullmatch(r"[a-f0-9]{40}", source)
    assert manifest["schemaVersion"] == 1
    assert manifest["status"] == "PARTIAL_EP_010_STAGE_B_FOUNDATION_INSTALLED"
    assert manifest["criterionClosed"] is False
    assert manifest["ledger"] == {"accepted": 9, "open": 41, "immutableBaselineRetained": True}
    previous = (DIRECTORY / manifest["previousEvidence"]).resolve()
    assert previous.is_relative_to(DIRECTORY) and digest(previous.read_bytes()) == manifest["previousEvidenceSha256"]
    assert json.loads(previous.read_bytes())["ledger"]["accepted"] == 9
    image = manifest["image"]
    assert image["source"] == source and image["exit"] == 0 and image["gitArchive"]
    assert re.fullmatch(r"sha256:[a-f0-9]{64}", image["imageId"])
    for row in manifest["sourceHashes"]:
        assert (ROOT / row["file"]).resolve().is_relative_to(ROOT)
        blob = subprocess.check_output(["git", "show", source + ":" + row["file"]], cwd=ROOT, timeout=10)
        assert digest(blob) == row["sha256"], row["file"]
    schema = json.loads(subprocess.check_output(["git", "show", source + ":docs/openapi.json"], cwd=ROOT, timeout=10))
    for name in ["DeviceLiveStatus", "DeviceResponse"]:
        props = schema["components"]["schemas"][name]["properties"]
        assert props["vpn_observation_max_age_seconds"]["default"] == 120
        assert props["vpn_observation_state"]["enum"] == ["fresh", "stale", "unknown"]
        assert {part.get("type") for part in props["vpn_active"]["anyOf"]} == {"boolean", "null"}
    receipts = {}
    for row in manifest["receipts"]:
        path = (DIRECTORY / row["file"]).resolve()
        assert path.is_relative_to(DIRECTORY) and path.is_file()
        blob = path.read_bytes()
        assert digest(blob) == row["sha256"], row["file"]
        assert not re.search(rb"tt_[a-z0-9]{20,}|Bearer\s+eyJ|ghp_[A-Za-z0-9]{20,}", blob)
        if path.suffix == ".json":
            receipts[path.stem] = json.loads(blob)
    for name, count in [("agent-status-image-tests", 444), ("resource-image-tests", 35)]:
        receipt = receipts[name]
        assert receipt["source"] == source and receipt["imageId"] == image["imageId"]
        assert receipt["tests"] == count and receipt["exit"] == receipt["failed"] == receipt["errors"] == receipt["skipped"] == 0
        assert not receipt["applicationSourceMounted"] and receipt["network"] == "none"
        suite = ElementTree.parse(DIRECTORY / ("evidence/android-vpn-observation/" + name + ".xml"))
        cases = list(suite.getroot().iter("testcase"))
        assert len(cases) == count
        assert all(not any(case.find(kind) is not None for kind in ["failure", "error", "skipped"]) for case in cases)
    for name in ["mypy", "ruff", "api-schema-check"]:
        receipt = receipts[name]
        assert receipt["source"] == source and receipt["imageId"] == image["imageId"] and receipt["exit"] == 0
        assert not receipt["applicationSourceMounted"] and receipt["network"] == "none"
    assert "five changed test files" in receipts["ruff"]["scope"]
    probe = receipts["redis-probe"]
    assert probe["pass"] and probe["freshFalseReport"]
    assert not probe["productionContacted"] and not probe["persistenceEnabled"]
    assert {row["kind"] for row in probe["races"]} == {"pong", "telemetry"}
    assert all(row["replacementPreserved"] and row["independentClients"] == 2 for row in probe["races"])
    installed = receipts["api-installed"]
    assert installed["source"] == source and installed["ready"] and installed["otherContainersPreserved"] == 45
    assert installed["changedContainers"] == ["sphere-pilot-20260911-backend-1"]
    assert installed["mountsPreserved"] and installed["logRotationPreserved"]
    assert not installed["apkChanged"] and not installed["tunnelsChanged"]
    live = receipts["live-observations"]
    assert live["source"] == source and live["ready"] and live["buildVerified"]
    assert not live["deviceCommandsSent"] and not live["continuousUptimeClaimed"] and not live["vpnTrafficProven"]
    assert live["ownLogout"] == 204 and live["revokedRead"] == 401 and len(live["samples"]) == 6
    for row in live["samples"]:
        assert row["total"] == 19 and row["statusCounts"] == {"online": 14, "busy": 0, "connecting": 0, "offline": 5, "issues": 0}
        assert row["presenceAvailable"] and row["bulkFreshOwnershipVerified"]
        assert row["observationStates"] == {"fresh": 14, "stale": 0, "unknown": 5}
        assert row["reportedVpnValues"] == {"true": 0, "false": 14, "unknown": 5}
        assert 0 <= row["freshAgeMinSeconds"] <= row["freshAgeMaxSeconds"] < 120
    assert live["resourceStates"] == {"cpu": "ready", "cpuQuota": "empty", "memory": "ready", "memoryLimit": "ready"}
    ci = receipts["source-ci"]
    assert ci["source"] == source and ci["laterDocsHeadCiInherited"] is False
    assert ci["unitAndRealService"] == {"passed": 2722, "skipped": 30, "warnings": 1, "coveragePercent": 79.78}
    assert {row["workflowName"] for row in ci["runs"]} >= {"CI — Backend", "CI — Frontend", "CI — Android"}
    assert all(row["headSha"] == source and row["status"] == "completed" and row["conclusion"] == "success" for row in ci["runs"])
    assert all(job["status"] == "completed" and job["conclusion"] == "success" for job in ci["backendJobs"])
    assert len(ci["productionOwnershipCases"]) == 2
    assert all(" PASSED " in line for line in ci["productionOwnershipCases"])
    assert receipts["document-links"] == {"documents": 12, "localLinks": 774, "anchors": 19, "valid": True}
    browser = receipts["browser-observation"]
    assert browser["source"] == source and browser["uiSourcePreserved"] == manifest["uiSourcePreserved"]
    assert browser["apiBadge"] == "W:cb5b3f91 A:d656b579" and browser["warnErrorEntriesReturned"] == 0
    assert not browser["uiCommandsToAndroidSent"] and not browser["newViewportOverrideUsed"]
    assert browser["capturesAreViewportOnly"] and not browser["freshnessMetadataNewUiClaimed"]
    assert browser["documentWidth"] == browser["documentClientWidth"]
    for row in manifest["screenshots"]:
        path = (DIRECTORY / row["file"]).resolve()
        assert path.is_relative_to(DIRECTORY)
        blob = path.read_bytes()
        assert hashlib.sha256(blob).hexdigest() == row["sha256"]
        assert jpeg_size(blob) == (row["width"], row["height"]) == (724, 884)
    print(json.dumps({"artifactIntegrity": "PASS", "source": source, "receiptFiles": len(manifest["receipts"]),
                      "accepted": 9, "open": 41, "EP010Closed": False, "liveHealthRechecked": False}))


if __name__ == "__main__":
    main()
