"""Validate pinned follow-up evidence; this does not recheck live health or rerun tests."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "docs/audits/2026-10-05"


def main() -> None:
    evidence = json.loads((DIRECTORY / "ENTERPRISE-PRODUCT-FOLLOWUP-EVIDENCE.json").read_text(encoding="utf-8"))
    document = (DIRECTORY / "ENTERPRISE-PRODUCT-FOLLOWUP.md").read_text(encoding="utf-8")
    original = json.loads((DIRECTORY / "ENTERPRISE-PRODUCT-BACKLOG.json").read_text(encoding="utf-8"))
    previous_path = (DIRECTORY / evidence["previousEvidence"]).resolve()
    assert previous_path.is_relative_to(DIRECTORY)
    previous_bytes = previous_path.read_bytes()
    previous = json.loads(previous_bytes)
    assert hashlib.sha256(previous_bytes).hexdigest() == evidence["previousEvidenceSha256"]
    assert evidence["schemaVersion"] == 1 and evidence["auditSource"] == original["source"]
    sources = evidence["sources"]
    assert all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in sources.values())
    for entry in evidence["gitBlobHashes"]:
        assert entry["revision"] in sources.values()
        assert (ROOT / entry["file"]).resolve().is_relative_to(ROOT)
        blob = subprocess.run(["git", "show", f"{entry['revision']}:{entry['file']}"],
                              cwd=ROOT, capture_output=True, check=True, timeout=10).stdout
        assert hashlib.sha256(blob).hexdigest() == entry["sha256"], entry["file"]
    ledger = evidence["ledger"]
    assert ledger["originalItems"] == len(original["items"]) == 50
    assert ledger["closedInPreviousBatch"] == previous["ledger"]["defectsFixedInThisBatch"]
    assert ledger["closedInThisBatch"] == ["EP-006", "EP-007"]
    closed = ledger["closedInPreviousBatch"] + ledger["closedInThisBatch"]
    assert ledger["totalClosed"] == len(set(closed)) == 7
    assert ledger["itemsWithOpenCriteria"] == len(original["items"]) - len(closed) == 43
    assert all(item["state"] == "OPEN" for item in original["items"])
    tests = evidence["tests"]
    front = tests["frontend"]
    assert front["numTotalTests"] == front["numPassedTests"] == 1196
    assert front["numTotalTestSuites"] == front["numPassedTestSuites"] == 116
    assert front["numFailedTests"] == front["numPendingTests"] == 0 and front["success"] is True
    assert tests["frontendTypeScriptPassed"] is True
    back = tests["backendImage"]
    assert back["counts"] == {"tests": 70, "failures": 0, "errors": 0, "skipped": 0}
    assert back["exit"] == 0 and back["source"] == sources["api"]
    assert back["applicationSourceMounted"] is False and back["network"] == "none"
    for name in ["backendMypy", "backendRuff", "openApiCatalog"]:
        assert tests[name]["exit"] == 0 and tests[name]["source"] == sources["api"]
    assert tests["backendMypy"]["sourceFiles"] == 229
    for name in ["api", "ui"]:
        assert evidence["builds"][name]["exit"] == 0
        assert evidence["builds"][name]["source"] == sources[name]
        assert evidence["builds"][name]["gitArchive"] is True
    installation = evidence["installation"]
    assert installation["api"]["source"] == sources["api"] and installation["api"]["ready"] is True
    assert installation["api"]["otherContainersPreserved"] == 45
    obs = installation["observability"]
    assert obs["uiSource"] == sources["ui"] and obs["topologySource"] == sources["topology"]
    assert obs["staticProxyVerified"] and obs["grafanaWhitelistMatches"] and obs["newContainersHealthy"]
    assert obs["grafanaPrometheusVolumesPreserved"] and obs["otherContainersPreserved"] == 43
    assert installation["guardRollbacks"]["zeroDowntimeClaimed"] is False
    assert installation["apkRebuiltOrInstalled"] is False and installation["publicUi18080Updated"] is False
    live = evidence["liveHttp"]
    assert live["uiSource"] == sources["ui"] and live["apiSource"] == sources["api"]
    for key in ["grafanaProfileStatus", "dashboardHtmlStatus", "grafanaQueryStatus", "featureReadStatus"]:
        assert live[key] == 200
    for key in ["anonymousStatus", "tamperedStatus", "directSpoofedHeaderStatus",
                "revokedTicketStatus", "revokedRenewalStatus"]:
        assert live[key] == 401
    assert live["mutationStatus"] == 405 and live["sphereLogoutStatus"] == 204
    assert live["secondsAfterMintAtRevocation"] < 90 and live["logoutOnlyOwnedCanarySession"]
    assert live["grafanaRole"] == "Viewer" and live["grafanaAdmin"] is False
    assert live["dashboardUid"] == "sphere-collection" and live["dashboardCanEdit"] is False
    assert live["grafanaQueryFrames"] > 0 and live["deviceCommandsSent"] is False
    recheck = evidence["liveHttpRecheck"]
    for key in ["apiSource", "uiSource", "grafanaProfileStatus", "dashboardHtmlStatus",
                "grafanaQueryStatus", "grafanaRole", "dashboardUid", "anonymousStatus",
                "tamperedStatus", "mutationStatus", "directSpoofedHeaderStatus",
                "sphereLogoutStatus", "revokedTicketStatus", "revokedRenewalStatus"]:
        assert recheck[key] == live[key], f"Recheck differs: {key}"
    assert recheck["secondsAfterMintAtRevocation"] < 90
    assert recheck["grafanaQueryFrames"] > 0 and recheck["deviceCommandsSent"] is False
    canary = evidence["webhookCanary"]
    assert canary["transport"] == "real loopback HTTP" and canary["receiverClosed"]
    assert canary["externalRequests"] is False and canary["sphereTasksCreated"] is False
    expected = [([204], []), ([403], []), ([429, 204], [7]), ([503, 204], [5]), ([503] * 4, [5, 30, 120])]
    assert len(canary["cases"]) == len(expected)
    for receipt, (statuses, delays) in zip(canary["cases"], expected, strict=True):
        assert receipt["httpStatuses"] == statuses and receipt["attempts"] == len(statuses)
        assert receipt["retryDelaysSeconds"] == delays and receipt["signatureValid"] and receipt["stableDeliveryId"]
        assert receipt["transportZeroYields"] >= 0
    browser = evidence["browser"]
    assert browser["observedUiRevision"] == sources["ui"][:8]
    assert browser["observedApiRevision"] == sources["api"][:8]
    assert browser["welcomeInsteadOfDashboard"] is False and browser["realDataGraphsVisuallyReviewed"]
    screenshot = browser["screenshot"]
    path = (ROOT / screenshot["file"]).resolve()
    assert path.is_relative_to(DIRECTORY)
    blob = path.read_bytes()
    assert blob[:2] == b"\xff\xd8" and screenshot["visuallyReviewed"]
    assert len(blob) == screenshot["bytes"] and hashlib.sha256(blob).hexdigest() == screenshot["sha256"]
    links = 0
    for target in re.findall(r"\]\(([^)]+)\)", document):
        if "://" in target or target.startswith("#"):
            continue
        path = (DIRECTORY / unquote(target.split("#")[0])).resolve()
        assert path.is_relative_to(ROOT) and path.is_file(), target
        links += 1
    assert not re.search(r"tt_[a-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|Bearer\s+eyJ", document + json.dumps(evidence))
    print(json.dumps({"artifactIntegrity": "PASS", "liveHealthRechecked": False,
                      "frozenSources": len(evidence["gitBlobHashes"]), "reviewedScreenshots": 1,
                      "localLinks": links, "recordedFrontendTests": 1196,
                      "recordedBackendImageTests": 70, "remainingItems": 43}))


if __name__ == "__main__":
    main()
