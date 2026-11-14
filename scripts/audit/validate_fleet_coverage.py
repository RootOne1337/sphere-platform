"""Verify immutable tenant-coverage evidence; no live query or EP-010 acceptance."""
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
        raise SystemExit("Run without -O: evidence checks require assertions.")
    manifest = json.loads((DIRECTORY / "ENTERPRISE-FLEET-COVERAGE-EVIDENCE.json").read_bytes())
    source, ui_source = manifest["source"], manifest["uiSource"]
    assert all(re.fullmatch(r"[a-f0-9]{40}", sha) for sha in [source, ui_source])
    assert manifest["schemaVersion"] == 1 and manifest["status"] == "PARTIAL_EP_010_TENANT_COVERAGE_INSTALLED"
    assert not manifest["criterionClosed"]
    assert manifest["ledger"] == {"accepted": 9, "open": 41, "immutableBaselineRetained": True}
    previous = (DIRECTORY / manifest["previousEvidence"]).resolve()
    assert previous.is_relative_to(DIRECTORY) and digest(previous.read_bytes()) == manifest["previousEvidenceSha256"]
    assert json.loads(previous.read_bytes())["ledger"]["accepted"] == 9
    for row in manifest["sourceHashes"]:
        assert (ROOT / row["file"]).resolve().is_relative_to(ROOT)
        blob = subprocess.check_output(["git", "show", source + ":" + row["file"]], cwd=ROOT, timeout=10)
        assert digest(blob) == row["sha256"], row["file"]
    trees = [subprocess.check_output(["git", "rev-parse", sha + ":frontend"], cwd=ROOT, timeout=10) for sha in [source, ui_source]]
    assert trees[0] == trees[1]
    schema = json.loads(subprocess.check_output(["git", "show", source + ":docs/openapi.json"], cwd=ROOT, timeout=10))
    assert schema["paths"]["/api/v1/monitoring/fleet-coverage"]["get"]["responses"]["200"]
    assert schema["components"]["schemas"]["FleetCoverageResponse"]["properties"]["schema_version"]["const"] == 1
    receipts = {}
    for row in manifest["receipts"]:
        path = (DIRECTORY / row["file"]).resolve()
        assert path.is_relative_to(DIRECTORY) and path.is_file()
        blob = path.read_bytes()
        assert digest(blob) == row["sha256"], row["file"]
        assert not re.search(rb"tt_[a-z0-9]{20,}|Bearer\s+eyJ|ghp_[A-Za-z0-9]{20,}", blob)
        if path.suffix == ".json":
            receipts[path.stem] = json.loads(blob)
    for kind, revision in [("api", source), ("ui", ui_source)]:
        image = manifest[kind + "Image"]
        assert image == receipts[kind + "-build"] and image["source"] == revision
        assert image["exit"] == 0 and image["gitArchive"] and re.fullmatch(r"sha256:[a-f0-9]{64}", image["imageId"])
        installed = receipts[kind + "-installed"]
        assert installed["source"] == revision and installed["ready"] and installed["otherContainersPreserved"] == 45
        assert installed["mountsPreserved"] and installed["logRotationPreserved"]
        assert not installed["apkChanged"] and not installed["tunnelsChanged"]
    for name, count in [("agent-status-image-tests", 476), ("resource-image-tests", 35)]:
        receipt = receipts[name]
        assert receipt["source"] == source and receipt["imageId"] == manifest["apiImage"]["imageId"]
        assert receipt["tests"] == count and receipt["exit"] == receipt["failed"] == receipt["errors"] == receipt["skipped"] == 0
        assert not receipt["applicationSourceMounted"] and receipt["network"] == "none"
        cases = list(ElementTree.parse(DIRECTORY / ("evidence/fleet-coverage/" + name + ".xml")).getroot().iter("testcase"))
        assert len(cases) == count and all(all(case.find(kind) is None for kind in ["failure", "error", "skipped"]) for case in cases)
    for name in ["mypy", "ruff", "api-schema-check"]:
        receipt = receipts[name]
        assert receipt["source"] == source and receipt["imageId"] == manifest["apiImage"]["imageId"] and receipt["exit"] == 0
        assert not receipt["applicationSourceMounted"] and receipt["network"] == "none"
    frontend = receipts["frontend-validation"]
    assert frontend["source"] == ui_source and frontend["passed"] == 1298 and frontend["suites"] == 121
    assert frontend["failed"] == frontend["skipped"] == 0 and frontend["productionNodeMajor"] == 24
    assert frontend["productionBuildIncludesTypes"] and frontend["uiTreeUnchangedInCorrection"]
    failed = receipts["initial-live-failure"]
    assert failed["source"] == ui_source and not failed["coverageReadSuccessful"] and failed["partialCountsHidden"]
    assert "UnicodeDecodeError" in failed["cause"] and not failed["correctedSourceProven"]
    live = receipts["live-observations"]
    assert live["source"] == source and live["ready"] and live["buildVerified"] and len(live["samples"]) == 6
    assert live["ownLogout"] == 204 and live["revokedRead"] == 401
    assert not any(live[key] for key in ["deviceCommandsSent", "continuousUptimeClaimed", "vpnTrafficProven", "independentProducerProven", "transportProbesConnected"])
    for row in live["samples"]:
        data = row["coverage"]
        assert "org_id" not in data and row["registryAgreement"] and row["tenantScopeVerified"]
        assert data["inventory"]["counts"] == {"total": 19}
        assert data["presence"]["counts"] == {"online": 14, "busy": 0, "connecting": 0, "offline": 0, "error": 0, "unknown": 5}
        assert data["android_vpn"]["counts"] == {"active": 0, "inactive": 14, "stale": 0, "unknown": 5}
        assert sum(data["vpn_assignment"]["counts"].values()) == sum(data["handshakes"]["counts"].values()) == 0
        assert data["transport_tunnels"]["state"] == "unmeasured" and data["transport_tunnels"]["counts"] is None
    browser = receipts["browser-observation"]
    assert browser["source"] == source and browser["uiSource"] == ui_source
    assert browser["viewportOverrideReset"] and browser["originalDarkThemeRestored"] and browser["manualRefreshSucceeded"]
    assert browser["desktop"]["gridColumns"] == 3 and browser["desktop"]["documentScrollWidth"] == 1440
    assert browser["mobile"]["width"] == browser["mobile"]["scrollWidth"] == 390
    assert browser["finalDefault"]["documentWidth"] == browser["finalDefault"]["documentScrollWidth"] == 724
    for group in [browser["mobile"]["cards"], browser["finalDefault"]["cards"]]:
        assert len(group) == 6 and all(card["scrollWidth"] == card["clientWidth"] for card in group)
    assert browser["warnErrorEntriesReturned"] == 0 and not browser["uiCommandsToAndroidSent"]
    for row in manifest["screenshots"]:
        path = (DIRECTORY / row["file"]).resolve()
        assert path.is_relative_to(DIRECTORY)
        blob = path.read_bytes()
        assert hashlib.sha256(blob).hexdigest() == row["sha256"]
        assert jpeg_size(blob) == (row["width"], row["height"])
    ci = receipts["source-ci"]
    assert ci["source"] == source and not ci["laterDocsHeadCiInherited"] and len(ci["coverageEndpointCases"]) == 32
    assert all(row["headSha"] == source and row["status"] == "completed" and row["conclusion"] == "success" for row in ci["runs"])
    assert all(row["status"] == "completed" and row["conclusion"] == "success" for row in ci["backendJobs"])
    assert receipts["document-links"]["valid"]
    print(json.dumps({"artifactIntegrity": "PASS", "source": source, "uiSource": ui_source,
                      "receipts": len(manifest["receipts"]), "accepted": 9, "open": 41,
                      "EP010Closed": False, "liveHealthRechecked": False}))


if __name__ == "__main__":
    main()
