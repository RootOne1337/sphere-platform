"""Validate frozen EP-009 artifacts; never claim fresh live health or rerun tests."""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

from scripts.audit.validate_http_metrics import jpeg_size

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "docs/audits/2026-10-05"


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def main() -> None:
    if not __debug__:
        raise SystemExit("Run without -O: this integrity checker requires assertions.")
    evidence = json.loads((DIRECTORY / "ENTERPRISE-CONTAINER-RESOURCE-EVIDENCE.json").read_bytes())
    assert evidence["schemaVersion"] == 1 and evidence["status"] == "ACCEPTED_FOR_EP_009"
    source = evidence["source"]
    assert re.fullmatch(r"[a-f0-9]{40}", source)
    baseline_bytes = (DIRECTORY / evidence["auditBaseline"]).read_bytes().replace(b"\r\n", b"\n")
    original = json.loads(baseline_bytes)
    assert digest(baseline_bytes) == evidence["auditBaselineSha256"]
    assert len(original["items"]) == 50 and all(item["state"] == "OPEN" for item in original["items"])
    previous_bytes = (DIRECTORY / evidence["previousEvidence"]).read_bytes().replace(b"\r\n", b"\n")
    previous = json.loads(previous_bytes)
    assert digest(previous_bytes) == evidence["previousEvidenceSha256"]
    ledger = evidence["ledger"]
    assert ledger["closedInPreviousBatch"] == previous["ledger"]["closedInPreviousBatch"] + previous["ledger"]["closedInThisBatch"]
    assert ledger["closedInThisBatch"] == ["EP-009"] and ledger["baselineNotRewritten"]
    closed = ledger["closedInPreviousBatch"] + ledger["closedInThisBatch"]
    assert len(set(closed)) == ledger["totalClosed"] == 9
    assert ledger["itemsWithOpenCriteria"] == 50 - len(closed) == 41
    assert set(closed) <= {item["id"] for item in original["items"]}
    assert len(evidence["gitBlobHashes"]) == 19
    for item in evidence["gitBlobHashes"]:
        assert item["revision"] == source and (ROOT / item["file"]).resolve().is_relative_to(ROOT)
        blob = subprocess.check_output(["git", "show", source + ":" + item["file"]], cwd=ROOT, timeout=10)
        assert digest(blob) == item["sha256"], item["file"]
    for receipt in evidence["publicReceipts"]:
        path = (DIRECTORY / receipt["file"]).resolve()
        assert path.is_relative_to(DIRECTORY) and path.is_file()
        assert digest(path.read_bytes().replace(b"\r\n", b"\n")) == receipt["sha256"], receipt["file"]
    tests = evidence["tests"]
    assert tests["frontend"]["source"] == source and tests["frontend"]["success"]
    assert tests["frontend"]["numTotalTests"] == tests["frontend"]["numPassedTests"] == 1275
    assert tests["frontend"]["numPassedTestSuites"] == tests["frontend"]["numTotalTestSuites"] == 120
    assert tests["frontend"]["numFailedTests"] == tests["frontend"]["numPendingTests"] == 0
    assert tests["api"]["tests"] == 27 and tests["api"]["failed"] == tests["api"]["skipped"] == 0
    assert tests["api"]["exactProductionImage"] and not tests["api"]["applicationSourceMounted"]
    assert tests["mypy"]["files"] == 231 and tests["mypy"]["exit"] == tests["ruff"]["exit"] == 0
    assert tests["frontendTypeScriptPassed"] and tests["promtoolPassed"]
    ci = evidence["sourceCi"]
    assert {row["workflow"] for row in ci} == {"backend", "frontend", "android"}
    for row in ci:
        assert row["headSha"] == source and row["status"] == "completed"
        assert row["conclusion"] == "success"
        assert re.fullmatch(r"https://github.com/RootOne1337/sphere-platform/actions/runs/\d+", row["url"])
    for kind in ["api", "ui"]:
        build, installed = evidence["builds"][kind], evidence["installed"][kind]
        assert build["source"] == installed["source"] == source and build["gitArchive"] and build["exit"] == 0
        assert re.fullmatch(r"sha256:[a-f0-9]{64}", build["imageId"])
        assert installed["ready"] and installed["otherContainersPreserved"] == 45
        assert installed["mountsPreserved"] and installed["logRotationPreserved"]
        assert not installed["apkChanged"] and not installed["tunnelsChanged"]
    assert evidence["installed"]["prometheus"]["changedContainers"] == []
    assert evidence["installed"]["prometheus"]["otherContainersPreserved"] == 46
    runtime = evidence["runtime"]
    kernel = runtime["kernel"]
    assert kernel["kernelComparisonPassed"] and kernel["cgroupVersion"] == "v1"
    assert kernel["boundedSamples"] == 10 and not kernel["duplicateResourceSamples"] and not kernel["pidLabels"]
    assert kernel["metricMemoryLimitBytes"] == 2147483648 and kernel["metricCpuQuotaCores"] is None
    assert kernel["resourcesAvailable"] == {"cpu": 1, "cpuQuota": 0, "memory": 1, "memoryLimit": 1}
    assert runtime["unauthorized"] == 401 and runtime["browserQueryRejected"] == 400
    assert runtime["httpMetricsPreserved"] and not runtime["backfillPerformed"] and not runtime["longSoakAccepted"]
    assert [row["window"] for row in runtime["windows"]] == ["1h", "6h", "24h"]
    for row, step in zip(runtime["windows"], [15, 30, 60]):
        assert row["stepSeconds"] == step
        assert row["states"] == {"cpu": "ready", "cpuQuota": "empty", "memory": "ready", "memoryLimit": "ready"}
        assert row["latest"]["memoryLimit"] == 2 and row["points"]["cpuQuota"] == 0
        assert all(math.isfinite(value) and value >= 0 for value in row["latest"].values())
        assert all(count <= 1441 for count in row["points"].values())
    final = evidence["final"]
    assert final["ownSessionLogout"] == 204 and final["ownSessionRevokedResourceRequest"] == 401
    assert len(final["samples"]) == 6 and all(row["statusCounts"]["online"] == row["onlineDeviceCount"] == 14 for row in final["samples"])
    assert not final["continuousUptimeClaimed"] and not final["deviceCommandsSent"]
    browser = evidence["browser"]
    assert browser["viewports"] == [1600, 390] and browser["pageWidthEqualsViewport"]
    assert browser["mobileRefreshButtonPixels"] == 40 and browser["automaticRefreshObserved"]
    assert browser["viewportReset"] and browser["originalDarkThemeRestored"]
    assert len(browser["screenshots"]) == 5
    for screenshot in browser["screenshots"]:
        path = (DIRECTORY / screenshot["file"]).resolve()
        assert path.is_relative_to(DIRECTORY) and path.is_file()
        blob = path.read_bytes()
        assert digest(blob) == screenshot["sha256"]
        assert jpeg_size(blob) == (screenshot["width"], screenshot["height"])
    document = (DIRECTORY / "ENTERPRISE-CONTAINER-RESOURCE-HISTORY.md").read_text(encoding="utf-8")
    links = 0
    for target in re.findall(r"\]\(([^)]+)\)", document):
        if "://" in target or target.startswith("#"):
            continue
        path = (DIRECTORY / unquote(target.split("#")[0])).resolve()
        assert path.is_relative_to(ROOT) and path.is_file(), target
        links += 1
    assert not re.search(r"tt_[a-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|Bearer\s+eyJ", document + json.dumps(evidence))
    print(json.dumps({"frozenSource": source, "files": 19, "screenshots": 5,
                      "accepted": 9, "openCriteria": 41, "localLinks": links,
                      "freshLiveHealthChecked": False}))


if __name__ == "__main__":
    main()
