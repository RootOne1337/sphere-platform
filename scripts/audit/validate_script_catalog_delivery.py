"""Verify frozen catalog delivery evidence, without network or runtime mutations."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from scripts.audit.validate_http_metrics import jpeg_size, within

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "docs/audits/2026-10-06"


def digest(blob: bytes, *, binary: bool = False) -> str:
    return hashlib.sha256(blob if binary else blob.replace(b"\r\n", b"\n")).hexdigest()


def main() -> None:
    if not __debug__:
        raise SystemExit("Run without -O: evidence validation uses assertions.")
    manifest = json.loads(within(DIRECTORY, "SCRIPT-CATALOG-EVIDENCE.json").read_bytes())
    source = manifest["sourceRevision"]
    assert len(source) == 40 and all(c in "0123456789abcdef" for c in source)
    assert manifest["evidenceSchema"] == 1
    assert manifest["textDigestMode"] == "sha256-after-CRLF-to-LF"
    assert manifest["binaryDigestMode"] == "sha256-raw"
    assert manifest["backlog"] == {"accepted": 9, "openCriteria": 41, "wholeItemsClosedByThisStage": False}
    assert not manifest["uniqueCrossRunTestTotalClaimed"]
    assert not manifest["previewDeploymentPerformed"]
    assert not manifest["secretsSourceSnapshotsRawJunitHostPathsPublished"]
    receipts = {}
    for row in manifest["evidenceFiles"]:
        blob = within(DIRECTORY, row["file"]).read_bytes().replace(b"\r\n", b"\n")
        assert len(blob) == row["bytesNormalized"] < 100_000
        assert digest(blob) == row["sha256"], row["file"]
        name = Path(row["file"]).stem
        assert name not in receipts
        receipts[name] = json.loads(blob)
        assert receipts[name]["sourceRevision"] == source
    assert len(receipts) == 10
    for row in manifest["sourceHashes"]:
        assert row["source"] == source and row["digestMode"] == "raw-git-blob"
        assert (ROOT / row["file"]).resolve().is_relative_to(ROOT)
        blob = subprocess.check_output(["git", "show", source + ":" + row["file"]], cwd=ROOT, timeout=15)
        assert digest(blob, binary=True) == row["sha256"], row["file"]
    assert len(manifest["sourceHashes"]) == 28

    builds, installed = receipts["builds"], receipts["runtime-installation"]
    assert builds["gitArchiveHeadOnly"] and installed["ready"]
    for kind, key in [("api", "apiImageId"), ("ui", "uiImageId")]:
        build = builds["builds"][kind + "-build"]
        assert build["exit"] == 0 and not build["timedOut"] and build["gitArchive"]
        assert build["archiveSha256"] == builds["archiveSha256"]
        assert build["imageId"] == installed[key]
    assert installed["otherContainersPreserved"] == 44
    assert installed["sourceVersionsPointersDatesPreserved"] and installed["taskCountPreserved"]
    assert installed["catalogRows"] == 22 and installed["catalogRawBytes"] == 14037
    for key in ["apkChanged", "tunnelsChanged", "deviceCommandsSent", "schemaDowngradePerformed"]:
        assert installed[key] is False
    assert installed["firstAttempt"]["secondAttemptVerifiedPriorImagesWereRestored"]

    backfill = receipts["migration-backfill"]
    assert backfill["scripts"] == 22 and backfill["versions"] == 25
    assert backfill["alembicHeadAfter"] == "20261006_script_catalog_metadata"
    assert not backfill["rawSourceSnapshotsPublished"]
    for run in backfill["runs"]:
        assert run["sourceDigestBefore"] == run["sourceDigestAfter"]
        assert run["sourceVersionsPointersDatesPreserved"]
        assert run["tasksBefore"] == run["tasksAfter"] == 445
        reconcile = run["stages"]["reconciled"]
        assert reconcile["scanned"] == 25 and reconcile["stopped"] == "complete"
        assert reconcile["failed"] == reconcile["updated"] == reconcile["would_update"] == 0
        assert reconcile["readiness"]["catalog_ready"]
        assert reconcile["readiness"]["source_hashes_reconciled"] is False
    assert backfill["runs"][0]["stages"]["applied"]["updated"] == 25
    assert backfill["runs"][1]["stages"]["applied"]["updated"] == 0

    tests = receipts["source-tests"]
    for name, count in [("catalogLegacyMaintenanceBudget", 171), ("finalMigrationRerun", 1)]:
        result = tests[name]["result"]
        assert result["tests"] == count
        assert result["failures"] == result["errors"] == result["skipped"] == 0
    frontend = receipts["frontend-tests"]
    assert frontend["result"] == "passed" and frontend["exit_code"] == 0
    assert frontend["tests"] == {"total": 1506, "passed": 1506, "failed": 0, "pending": 0}
    assert frontend["suites"] == {"total": 126, "passed": 126, "failed": 0}
    for check in receipts["exact-image-checks"]["checks"].values():
        assert check["source"] == source and check["imageId"] == installed["apiImageId"]
        assert check["exit"] == 0 and not check["timedOut"] and check["network"] == "none"
        assert not check["backendApplicationSourceMounted"]
        if "result" in check:
            assert check["result"]["failures"] == check["result"]["errors"] == check["result"]["skipped"] == 0
    budget = receipts["fixture-budget"]
    properties = budget["properties"]
    assert properties["fixture_rows"] == 100 and properties["nodes_per_version"] == 500
    assert properties["heavy_source_utf8_bytes_per_version"] == 491520
    assert properties["heavy_catalog_raw_utf8_bytes"] == properties["minimal_catalog_raw_utf8_bytes"] == 85176
    assert properties["heavy_legacy_raw_utf8_bytes"] == 48889157
    assert budget["catalogPage256KiBBudgetPassed"] and budget["sqlProjectionCountPerRequest"] == 1
    assert not budget["dagSelectedOrReadTimeHashComputed"]
    assert not budget["deployedLatencyRssBrowserReleaseGatesMeasured"]

    final = receipts["final-readonly"]
    assert final["apiRevision"] == source and final["ready"] == "ready"
    assert final["fleetTotal"] == 19 and final["statusCounts"]["online"] == 14
    assert final["statusCounts"]["offline"] == 5 and final["presenceAvailable"]
    assert final["sourcesExcluded"] and final["cacheControl"] == "no-store"
    ci = receipts["source-ci"]
    assert ci["allFourCompletedSuccess"] and len(ci["workflows"]) == 4
    assert not ci["previewDeploymentPerformed"]
    for workflow in ci["workflows"]:
        assert workflow["headSha"] == source and workflow["status"] == "completed"
        assert workflow["conclusion"] == "success"
    preview = next(row for row in ci["workflows"] if row["databaseId"] == 37429532718)
    assert {j["name"]: j["conclusion"] for j in preview["jobs"]} == {"guard": "success", "deploy": "skipped"}

    native = receipts["native-ui"]
    assert native["capture"] == "native-codex-browser" and native["source"] == source
    assert native["states"] == {"active": 19, "archived": 3, "all": 22, "searchStudio": 2}
    assert all(native["preferences"].values()) and native["temporaryViewportReset"]
    assert all(row["width"] == row["documentWidth"] for row in native["viewportChecks"])
    assert {row["width"] for row in native["viewportChecks"]} == {1280, 724, 390}
    assert native["errorOrWarningLogCount"] == native["realTasksCreated"] == 0
    assert not any(native[key] for key in ["deviceCommandsSent", "networkOrHeapProfilePerformed", "fullRecorderProven", "frameExactReplayProven"])
    assert native["runDialog"]["withoutTargetsDisabled"] and native["runDialog"]["openedOnly"]
    assert len(manifest["screenshots"]) == 9
    for row in manifest["screenshots"]:
        blob = within(DIRECTORY, row["file"]).read_bytes()
        assert row["source"] == source and row["capture"] == "native-codex-browser"
        assert len(blob) == row["bytes"] < 1_000_000
        assert digest(blob, binary=True) == row["sha256"] and list(jpeg_size(blob)) == row["dimensions"]
    print(json.dumps({"artifactIntegrity": "PASS", "scope": "frozen-catalog-delivery-only",
                      "source": source, "receipts": len(receipts), "screenshots": 9,
                      "liveRequestsOrCommandsIssued": False, "wholeBacklogClosed": False}))


if __name__ == "__main__":
    main()
