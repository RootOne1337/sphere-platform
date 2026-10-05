"""Check pinned log-reader/storage evidence without contacting live services."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from xml.etree import ElementTree

from scripts.audit.validate_http_metrics import jpeg_size

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "docs/audits/2026-10-06"


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob.replace(b"\r\n", b"\n")).hexdigest()


def main() -> None:
    if not __debug__:
        raise SystemExit("Run without -O: artifact checks require assertions.")
    manifest = json.loads((DIRECTORY / "DEVICE-LOG-READ-EVIDENCE.json").read_bytes())
    source, reader = manifest["source"], manifest["readerSource"]
    assert all(re.fullmatch(r"[a-f0-9]{40}", sha) for sha in [source, reader])
    assert manifest["schemaVersion"] == 1
    assert manifest["status"] == "PARTIAL_EP_033_READ_AND_STORAGE_INSTALLED"
    assert not manifest["criterionClosed"]
    assert manifest["ledger"] == {"accepted": 9, "open": 41, "immutableBaselineRetained": True}
    assert manifest["applicationTreeUnchangedInStorageCommit"] and manifest["uiSource"] == reader
    assert not subprocess.check_output(["git", "diff", reader, source, "--", "backend", ":!backend/Dockerfile"], cwd=ROOT).strip()
    assert subprocess.check_output(["git", "rev-parse", source + ":frontend"], cwd=ROOT) == subprocess.check_output(["git", "rev-parse", reader + ":frontend"], cwd=ROOT)
    for row in manifest["sourceHashes"]:
        assert (ROOT / row["file"]).resolve().is_relative_to(ROOT)
        blob = subprocess.check_output(["git", "show", row["source"] + ":" + row["file"]], cwd=ROOT, timeout=10)
        assert digest(blob) == row["sha256"], row["file"]
    receipts = {}
    for row in manifest["receipts"]:
        path = (DIRECTORY / row["file"]).resolve()
        assert path.is_relative_to(DIRECTORY) and path.is_file()
        blob = path.read_bytes()
        assert digest(blob) == row["sha256"], row["file"]
        assert not re.search(rb"tt_[a-z0-9]{20,}|Bearer\s+eyJ|ghp_[A-Za-z0-9]{20,}", blob)
        if path.suffix == ".json":
            receipts[path.stem] = json.loads(blob)
    before_path = (DIRECTORY / manifest["beforeEvidence"]).resolve()
    assert before_path.is_relative_to(DIRECTORY)
    assert digest(before_path.read_bytes()) == manifest["beforeEvidenceSha256"]
    before = json.loads(before_path.read_bytes())
    after = receipts["after"]
    assert after["source"] == reader and not after["workingTreeModified"]
    assert before["fixtureBytes"] == after["fixtureBytes"] == 25165824
    assert before["returnedLines"] == after["returnedLines"] == 1000
    assert before["linesSha256"] == after["linesSha256"]
    assert before["pythonTracedPeakBytes"] == 48271208 and after["pythonTracedPeakBytes"] < 1024 * 1024
    assert after["wholeFileReadBytes"] == 0 and after["temporaryFilesRemoved"]
    assert not after["hostDiskWriterIdentified"] and not after["liveServicesContacted"]
    assert after["readMetadata"]["bytes_scanned"] <= 2097152
    assert after["readMetadata"]["response_lines_bytes"] <= 524288
    for name, revision in [("storage-api-build", source), ("ui-build", reader)]:
        build = receipts[name]
        assert build["source"] == revision and build["exit"] == 0 and build["gitArchive"]
        assert re.fullmatch(r"sha256:[a-f0-9]{64}", build["imageId"])
    assert manifest["apiImage"] == receipts["storage-api-build"] and manifest["uiImage"] == receipts["ui-build"]
    for name, count, revision, image in [
        ("agent-status-image-tests", 502, reader, receipts["api-build"]["imageId"]),
        ("resource-image-tests", 35, reader, receipts["api-build"]["imageId"]),
        ("storage-reader-image-tests", 26, source, receipts["storage-api-build"]["imageId"]),
    ]:
        receipt = receipts[name]
        assert receipt["source"] == revision and receipt["imageId"] == image
        assert receipt["tests"] == count and receipt["exit"] == receipt["failed"] == receipt["errors"] == receipt["skipped"] == 0
        assert receipt["network"] == "none" and not receipt["applicationSourceMounted"]
        cases = list(ElementTree.parse(DIRECTORY / ("evidence/log-read-budget/" + name + ".xml")).getroot().iter("testcase"))
        assert len(cases) == count and all(all(case.find(kind) is None for kind in ["failure", "error", "skipped"]) for case in cases)
    suite = ElementTree.parse(DIRECTORY / "evidence/log-read-budget/storage-compose-tests.xml").getroot().find("testsuite")
    assert suite is not None and int(suite.attrib["tests"]) == 23
    assert all(int(suite.attrib[key]) == 0 for key in ["failures", "errors", "skipped"])
    frontend = receipts["frontend-validation"]
    assert frontend["source"] == reader and frontend["passed"] == 1307 and frontend["suites"] == 121
    assert frontend["success"] and frontend["failed"] == frontend["skipped"] == 0
    assert frontend["productionNodeMajor"] == 24 and frontend["productionBuildIncludesTypes"]
    installed = receipts["storage-installed"]
    assert installed["source"] == source and installed["readerSource"] == reader and installed["ready"]
    assert installed["otherContainersPreserved"] == 45 and installed["existingMountsPreserved"] and installed["logRotationPreserved"]
    assert installed["stoppedWriterCopy"] and installed["stagingRetained"] and len(installed["failedAttempts"]) == 2
    assert installed["migrated"]["files"] == installed["verified"]["files"] == 14
    assert installed["migrated"]["bytes"] == installed["verified"]["bytes"] == 902996
    assert installed["migrated"]["hashesVerified"] and installed["verified"]["prefixHashesVerified"]
    assert installed["verified"]["uid"] == 1001 and installed["verified"]["writeCanaryRemoved"]
    assert installed["freshVolumeNonRootRecreation"] and installed["postRollbackRecreationPreservedAllPrefixes"]
    assert not any(installed[key] for key in ["apkChanged", "tunnelsChanged", "diskWriterIdentified"])
    live = receipts["storage-live"]
    assert live["source"] == source and live["ready"] and live["ownLogout"] == 204 and live["revokedRead"] == 401
    assert not any(live[key] for key in ["deviceCommandsSent", "logFilesCreatedDeleted", "diskWriterIdentified", "continuousUptimeClaimed"])
    assert live["reads"][0]["returnedLines"] > 0
    assert all(row["status"] == 422 for row in live["reads"] if row["query"] in ["invalid-date", "oversized-search"])
    browser = receipts["browser-observation"]
    assert browser["source"] == source and browser["uiSource"] == reader
    assert browser["desktop"]["width"] == browser["desktop"]["scrollWidth"] == 1440
    assert browser["mobile"]["width"] == browser["mobile"]["scrollWidth"] == 390
    assert browser["mobile"]["regionWidth"] == browser["mobile"]["regionScrollWidth"] == 352
    assert browser["finalDefault"]["width"] == browser["finalDefault"]["scrollWidth"]
    assert browser["viewportOverrideReset"] and browser["originalDarkThemeRestored"] and browser["manualRefreshSucceeded"]
    assert browser["searchNoMatchVerified"] and browser["nonemptyDeviceLogsPreviouslyVisible"]
    assert browser["warnErrorEntriesReturned"] == 0 and not browser["deviceCommandsSent"] and not browser["logsDeleted"]
    for row in manifest["screenshots"]:
        path = (DIRECTORY / row["file"]).resolve()
        assert path.is_relative_to(DIRECTORY)
        blob = path.read_bytes()
        assert hashlib.sha256(blob).hexdigest() == row["sha256"]
        assert jpeg_size(blob) == (row["width"], row["height"])
    ci = receipts["source-ci"]
    assert not ci["laterDocsHeadCiInherited"] and set(ci["sources"]) == {source, reader}
    for sha, rows in ci["sources"].items():
        assert len(rows) >= 4 and all(row["headSha"] == sha for row in rows)
    all_green = all(row["conclusion"] == "success" and row["status"] == "completed" for rows in ci["sources"].values() for row in rows)
    assert all_green == ci["allSourceRunsPassed"]
    annotations = receipts["source-ci-runner-annotations"]
    assert annotations["source"] == source and annotations["workflowId"] == 37365950863
    assert not annotations["testsExecutedByTheseJobs"] and not annotations["fullBackendCiPassed"]
    assert {row["name"] for row in annotations["jobs"]} == {"Tests", "Security (bandit + pip-audit)"}
    assert all(not row["runnerAssigned"] and row["conclusion"] == "cancelled" and row["failureAnnotations"] for row in annotations["jobs"])
    assert receipts["document-links"]["valid"] and receipts["document-links"]["uniqueOpenPriorityItems"] == 41
    print(json.dumps({"artifactIntegrity": "PASS", "source": source, "readerSource": reader,
                      "receipts": len(manifest["receipts"]), "accepted": 9, "open": 41,
                      "EP033Closed": False, "sourceCiAllGreen": all_green, "liveHealthRechecked": False}))


if __name__ == "__main__":
    main()
