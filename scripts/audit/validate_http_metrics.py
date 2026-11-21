"""Check frozen EP-008 artifacts; do not rerun tests or claim current live health."""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "docs/audits/2026-10-05"


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def within(base: Path, name: str) -> Path:
    path = (base / name).resolve()
    assert path.is_relative_to(base) and path.is_file(), name
    return path


def jpeg_size(blob: bytes) -> tuple[int, int]:
    """Read dimensions from a bounded JPEG header without third-party dependencies."""
    assert blob[:2] == b"\xff\xd8" and len(blob) < 2_000_000
    offset = 2
    while offset < len(blob):
        assert blob[offset] == 0xFF
        while offset < len(blob) and blob[offset] == 0xFF:
            offset += 1
        marker = blob[offset]
        offset += 1
        if marker in {0xD9, 0xDA}:
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            continue
        size = int.from_bytes(blob[offset:offset + 2], "big")
        assert size >= 2 and offset + size <= len(blob)
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            assert size >= 8
            return (int.from_bytes(blob[offset + 5:offset + 7], "big"),
                    int.from_bytes(blob[offset + 3:offset + 5], "big"))
        offset += size
    raise AssertionError("JPEG dimensions missing")


def main() -> None:
    if not __debug__:
        raise SystemExit("Run without -O: this integrity checker requires assertions.")
    document = (DIRECTORY / "ENTERPRISE-HTTP-METRICS.md").read_text(encoding="utf-8")
    blob = (DIRECTORY / "ENTERPRISE-HTTP-METRICS-EVIDENCE.json").read_bytes()
    assert len(blob) < 500_000
    evidence = json.loads(blob)
    original = json.loads((DIRECTORY / "ENTERPRISE-PRODUCT-BACKLOG.json").read_bytes())
    previous_bytes = within(DIRECTORY, evidence["previousEvidence"]).read_bytes()
    previous = json.loads(previous_bytes)
    assert digest(previous_bytes.replace(b"\r\n", b"\n")) == evidence["previousEvidenceSha256"]
    assert digest((DIRECTORY / "ENTERPRISE-PRODUCT-BACKLOG.json").read_bytes().replace(
        b"\r\n", b"\n")) == evidence["auditBaselineSha256"]
    assert evidence["textHashFormat"] == "UTF-8 bytes with CRLF normalized to LF; matches Git text blobs"
    assert evidence["schemaVersion"] == 1 and evidence["auditSource"] == original["source"]
    sources = evidence["sources"]
    assert all(re.fullmatch(r"[a-f0-9]{40}", revision) for revision in sources.values())
    files = evidence["gitBlobHashes"]
    assert len({entry["file"] for entry in files}) == len(files) == 19
    for entry in files:
        assert entry["revision"] in sources.values()
        assert (ROOT / entry["file"]).resolve().is_relative_to(ROOT)
        actual = subprocess.run(["git", "show", f"{entry['revision']}:{entry['file']}"],
                                cwd=ROOT, capture_output=True, check=True, timeout=10).stdout
        assert digest(actual) == entry["sha256"], entry["file"]
    ledger = evidence["ledger"]
    assert all(item["state"] == "OPEN" for item in original["items"])
    assert ledger["originalItems"] == len(original["items"]) == 50
    assert ledger["closedInPreviousBatch"] == (
        previous["ledger"]["closedInPreviousBatch"] + previous["ledger"]["closedInThisBatch"])
    assert ledger["closedInThisBatch"] == ["EP-008"] and ledger["baselineNotRewritten"]
    closed = ledger["closedInPreviousBatch"] + ledger["closedInThisBatch"]
    assert ledger["totalClosed"] == len(set(closed)) == 8
    assert ledger["itemsWithOpenCriteria"] == len(original["items"]) - len(closed) == 42
    assert set(closed) <= {item["id"] for item in original["items"]}
    tests = evidence["tests"]
    for key, source, count, suites in [("frontendFull", "feature", 1235, 118),
                                      ("frontendTargeted", "ui", 99, 4)]:
        result = tests[key]
        assert result["source"] == sources[source] and result["success"]
        assert result["numTotalTests"] == result["numPassedTests"] == count
        assert result["numTotalTestSuites"] == result["numPassedTestSuites"] == suites
        assert result["numFailedTests"] == result["numPendingTests"] == 0
    assert tests["frontendHttpAndAndroidMocked"] and tests["frontendTypeScriptPassed"]
    assert tests["changedFileLintPassed"] and tests["eslintCompatibilityMode"]
    assert tests["apiRegressionsRerunInThisBatch"] is False
    gateway_tests = tests["gatewayPreflight"]
    assert gateway_tests["source"] == sources["gatewayPreflight"]
    assert gateway_tests["tests"] == 14 and gateway_tests["exit"] == gateway_tests["failed"] == 0
    assert all(gateway_tests[key] for key in ["ruffPassed", "realRenderedComposeValidated",
               "gatewayImageNginxTestPassed", "nginxTestExternalNetworkDisabled"])
    build = evidence["build"]
    assert build["source"] == sources["ui"] and build["exit"] == 0 and build["gitArchive"]
    assert re.fullmatch(r"sha256:[a-f0-9]{64}", build["imageId"])
    install = evidence["installation"]
    assert install["uiSource"] == sources["ui"] and install["gatewaySource"] == sources["gateway"]
    assert install["uiImageId"] == build["imageId"] and install["otherContainersPreserved"] == 44
    assert install["nginxRenderedAndHealthy"] and install["apiApkTunnelsUnchanged"]
    assert install["staticUiIp"] == "172.30.0.3" and install["toolsProxyIp"] == "172.29.0.3"
    assert install["dynamicPool"] == "172.30.0.128/25" and install["zeroDowntimeClaimed"] is False
    rollback = evidence["firstGuardRollback"]
    assert rollback["errorStatus"] == 504 and rollback["rollbackLoginStatus"] == 200
    assert rollback["rolledBackTo"] == sources["feature"]
    assert rollback["subsequentLogEvidence"]["observedWrongUiUpstream"] == "192.168.0.1:3000"
    canary = evidence["replacementCanary"]
    assert canary["uiSource"] == sources["ui"] and canary["gatewaySource"] == sources["gateway"]
    assert canary["observedStatuses"] == ["200", "502"] and canary["probeCount"] == 23
    assert canary["staticUiIp"] == install["staticUiIp"] and canary["gatewayNotRestarted"]
    assert canary["allObservedUiErrorUpstreamsReservedAddress"] and canary["finalUiHealthy"]
    assert canary["finalLoginStatus"] == 200 and canary["androidCommandsSent"] is False
    assert canary["zeroDowntimeClaimed"] is False
    live = evidence["liveHttp"]
    assert live["uiSource"] == sources["ui"] and live["backendSource"] == sources["api"]
    assert live["gatewaySource"] == sources["gateway"] and live["anonymousStatus"] == 401
    assert live["duplicateWindowStatus"] == live["arbitraryQueryStatus"] == 400
    assert live["logoutStatus"] == 204 and live["revokedProbeStatus"] == 401
    assert live["remoteCommandsSent"] is False
    assert [entry["window"] for entry in live["windows"]] == ["1h", "6h", "24h"]
    observed = datetime.fromisoformat(live["observedAt"])
    for entry, step in zip(live["windows"], [15, 30, 60], strict=True):
        assert entry["stepSeconds"] == step and 0 < entry["bytes"] < 2_000_000
        assert 0 <= entry["durationSeconds"] < 5 and 0 < entry["routeCount"] <= 30
        age = (observed - datetime.fromisoformat(entry["lastScrape"])).total_seconds()
        assert -5 <= age <= 45
        assert set(entry["metrics"]) == {"rps", "p95", "serverErrors", "clientErrors"}
        for signal in entry["metrics"].values():
            assert signal["state"] == "ready" and 0 < signal["points"] <= 1441
            assert math.isfinite(signal["latest"]) and signal["latest"] >= 0
    grafana = evidence["liveGrafana"]
    assert grafana["uiSource"] == sources["ui"] and grafana["apiSource"] == sources["api"]
    for key in ["grafanaProfileStatus", "dashboardHtmlStatus", "grafanaQueryStatus", "featureReadStatus"]:
        assert grafana[key] == 200
    for key in ["anonymousStatus", "tamperedStatus", "directSpoofedHeaderStatus",
                "revokedTicketStatus", "revokedRenewalStatus"]:
        assert grafana[key] == 401
    assert grafana["grafanaRole"] == "Viewer" and grafana["grafanaAdmin"] is False
    assert grafana["dashboardUid"] == "sphere-collection" and grafana["dashboardCanEdit"] is False
    assert grafana["dashboardPanels"] == 5 and grafana["grafanaQueryFrames"] > 0
    assert grafana["mutationStatus"] == 405 and grafana["sphereLogoutStatus"] == 204
    assert grafana["secondsAfterMintAtRevocation"] < 90 and grafana["logoutOnlyOwnedCanarySession"]
    assert grafana["deviceCommandsSent"] is False
    browser = evidence["browser"]
    assert browser["observedUiRevision"] == sources["ui"][:8]
    assert browser["observedApiRevision"] == sources["api"][:8]
    assert browser["realDataGraphsVisuallyReviewed"] and browser["routeFilterAndSelectionVerified"]
    for size in ["wideViewport", "mobileViewport"]:
        assert browser[size]["clientWidth"] == browser[size]["documentScrollWidth"] == browser[size]["width"]
    assert browser["mobileViewport"]["refreshButtonWidth"] == browser["mobileViewport"]["refreshButtonHeight"] == 40
    assert browser["nativeGrafanaVisuallyReviewed"] and browser["nativeGrafanaWelcomeInsteadOfDashboard"] is False
    assert browser["temporaryViewportReset"] and len(browser["screenshots"]) == 5
    for screenshot in browser["screenshots"]:
        path = within(ROOT, screenshot["file"])
        assert path.is_relative_to(DIRECTORY) and path.suffix == ".jpg"
        image = path.read_bytes()
        assert screenshot["visuallyReviewed"] and screenshot["source"] == sources["ui"]
        assert digest(image) == screenshot["sha256"] and len(image) == screenshot["bytes"]
        assert jpeg_size(image) == (screenshot["width"], screenshot["height"])
    resource_ref = evidence["resourceFinal"]
    resource_bytes = within(DIRECTORY, resource_ref["file"]).read_bytes()
    assert digest(resource_bytes.replace(b"\r\n", b"\n")) == resource_ref["sha256"]
    resource = json.loads(resource_bytes)
    assert resource["collectorState"] == "complete" and resource["samplesRead"] == 241
    assert resource["writerAttribution"] == "UNDETERMINED"
    assert resource["diskOrRamLeakDeclaredFixed"] is False and resource_ref["diskOrRamLeakDeclaredFixed"] is False
    links = 0
    for target in re.findall(r"\]\(([^)]+)\)", document):
        if "://" in target or target.startswith("#"):
            continue
        within(ROOT, (DIRECTORY / unquote(target.split("#")[0])).relative_to(ROOT).as_posix())
        links += 1
    assert not re.search(r"tt_[a-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|Bearer\s+eyJ", document + blob.decode())
    print(json.dumps({"artifactIntegrity": "PASS", "liveHealthRechecked": False,
                      "testsRerun": False, "frozenFiles": len(files),
                      "reviewedScreenshots": 5, "localLinks": links,
                      "recordedFrontendFullTests": 1235, "recordedGatewayTests": 14,
                      "closedItems": 8, "remainingItems": 42}))


if __name__ == "__main__":
    main()
