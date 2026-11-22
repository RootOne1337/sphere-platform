"""Validate pinned screenshot-cache delivery receipts without contacting Android."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from scripts.audit.validate_android_focused_text_clear import png_size
from scripts.audit.validate_http_metrics import within

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "docs/audits/2026-10-06"


def main() -> None:
    if not __debug__:
        raise SystemExit("Run without -O: evidence validation uses assertions.")
    manifest = json.loads(within(DIRECTORY, "ANDROID-SCREENSHOT-CACHE-EVIDENCE.json").read_bytes())
    source = manifest["sourceRevision"]
    assert re.fullmatch(r"[0-9a-f]{40}", source)
    assert manifest["evidenceSchema"] == 1
    assert manifest["textDigestMode"] == "sha256-after-CRLF-to-LF"
    assert manifest["binaryDigestMode"] == "sha256-raw"
    assert not manifest["secretsOrPrivatePackageBackupPublished"]
    assert manifest["backlog"] == {"accepted": 9, "openCriteria": 41, "wholeItemsClosedByThisStage": False}

    receipts = {}
    for row in manifest["evidenceFiles"]:
        blob = within(DIRECTORY, row["file"]).read_bytes().replace(b"\r\n", b"\n")
        assert len(blob) == row["bytesNormalized"] < 100_000
        assert hashlib.sha256(blob).hexdigest() == row["sha256"]
        name = Path(row["file"]).stem
        assert name not in receipts
        receipts[name] = json.loads(blob)
    assert set(receipts) == {
        "candidate-build", "installation", "focused-tests", "resources", "build-resources",
        "task-canary", "native-browser", "source-ci", "linux-junit",
    }

    expected_sources = {"android/version.properties"}
    expected_sources.update(
        f"android/app/src/main/kotlin/com/sphereplatform/agent/commands/{name}.kt"
        for name in ("ScreenshotFileStore", "AdbActionExecutor", "DagRunner", "CommandDispatcher")
    )
    expected_sources.update(
        f"android/app/src/test/kotlin/com/sphereplatform/agent/commands/{name}.kt"
        for name in ("ScreenshotFileStoreTest", "AdbScreenshotTest", "DagRunnerTest")
    )
    assert len(manifest["sourceHashes"]) == len(expected_sources) == 8
    assert {r["file"] for r in manifest["sourceHashes"]} == expected_sources
    for row in manifest["sourceHashes"]:
        assert row["source"] == source and row["digestMode"] == "raw-git-blob"
        blob = subprocess.check_output(["git", "show", f"{source}:{row['file']}"], cwd=ROOT, timeout=30)
        assert hashlib.sha256(blob).hexdigest() == row["sha256"]

    build = receipts["candidate-build"]
    candidate = build["candidate"]
    install, task = receipts["installation"], receipts["task-canary"]
    assert build["sourceRevision"] == candidate["source_commit"] == install["sourceRevision"] == task["sourceRevision"] == source
    assert candidate["version_code"] == install["installedVersionCode"] == task["agentVersionCode"] == 10247
    assert candidate["sha256"] == install["candidateSha256"] == task["candidateSha256"]
    assert build["zipCrcPassed"] and build["trackedAndroidFilesMatchedGitSource"] == 186
    assert len(build["dex"]) == 15 and all(d["headerChecksumsValid"] for d in build["dex"])
    assert not build["apkBinaryPublishedInRepository"] and not build["remoteFleetOrProductionAccepted"]
    # Build-time installation flag is historical; the subsequent installation receipt is authoritative.
    assert not candidate["installed"] and not candidate["published_to_ota"]
    assert candidate["signer_matches_local_pilot_baseline"]
    assert all(t == {"tests": 872, "failures": 0, "errors": 0, "skipped": 3} for t in candidate["tests"].values())
    assert receipts["focused-tests"]["total"] == {"tests": 110, "failures": 0, "errors": 0, "skipped": 2}
    for name in ("resources", "build-resources"):
        assert receipts[name]["buildAllowed"] and not receipts[name]["findings"]

    assert install["status"] == "completed-and-new-heartbeat" and install["installAttempts"] == 1
    assert install["deviceId"] == task["deviceId"] == install["lastReadback"]["id"]
    assert install["beforeVersionCode"] == 10246 and install["targetVersionCode"] == 10247
    assert install["uidBefore"] == install["uidAfter"] == 10082
    for name in (
        "signerMatches", "packageHashVerified", "backupOfStoppedPackage",
        "stoppedPreferencesByteIdenticalBeforeExplicitStart", "deviceIdentityPreserved",
        "catalogCountPreserved", "otherDeviceVersionsPreserved",
    ):
        assert install[name]
    assert not any(install[n] for n in ("dataCleared", "otherDevicesUpdated", "backendUiTunnelsChanged", "otaCatalogChanged"))

    assert task["status"] == "terminal-completed" and task["tasksCreated"] == task["scriptsCreated"] == 1
    assert not task["automaticRetry"] and task["deviceActionRetries"] == 0
    encoded = json.dumps(task["dag"], sort_keys=True, ensure_ascii=False).encode()
    assert hashlib.sha256(encoded).hexdigest() == task["dagHash"]
    nodes, logs = task["dag"]["nodes"], task["logs"]
    assert len(nodes) == len(logs) == task["nodeCount"] == task["task"]["result"]["nodes_executed"] == 14
    assert task["task"]["id"] == task["taskId"]
    assert task["task"]["status"] == "completed" and task["task"]["script_version_id"] == task["versionId"]
    assert [n["id"] for n in nodes] == [n["node_id"] for n in logs]
    assert all(n["retry"] == 0 for n in nodes) and all(n["success"] and not n["error"] for n in logs)
    captures = [n for n in logs if n["action_type"] == "screenshot"]
    assert len(captures) == task["captureRequests"] == 10
    paths = []
    for capture in captures:
        match = re.fullmatch(
            r"\{path=(.+/capture-[0-9a-f-]{36}\.png), format=png, storage=android-local-cache, server_artifact_available=false\}",
            capture["output"],
        )
        assert match and not capture["screenshot_key"]
        paths.append(match[1])
    assert len(set(paths)) == 10 and all(p.startswith(task["cacheDirectory"] + "/") for p in paths)
    assert task["cacheAbsentBefore"] and task["oldestTwoEvicted"] and task["noStagingFileReported"]
    assert len(task["cacheFiles"]) == task["cacheFileCount"] == 8
    assert {p["path"] for p in task["cacheFiles"]} == set(paths[2:])
    assert sum(p["bytes"] for p in task["cacheFiles"]) == task["cacheBytes"] == 1_880_304
    assert all(57 <= p["bytes"] <= 5 * 1024 * 1024 for p in task["cacheFiles"])
    assert task["serverManifest"] == {"task_id": task["taskId"], "screenshots": []}
    assert not task["originalPng"]["pixelReencoded"] and task["ownedRecoveryTemporaryCleanupConfirmed"]
    assert task["localCachePreservedForRetentionObservation"]
    assert task["captureDurationsMs"] == [c["duration_ms"] for c in captures]

    assert len(manifest["assets"]) == 4
    png_count = 0
    for row in manifest["assets"]:
        blob = within(DIRECTORY, row["file"]).read_bytes()
        assert len(blob) == row["bytes"] and hashlib.sha256(blob).hexdigest() == row["sha256"]
        if row["file"].endswith(".png"):
            png_count += 1
            assert png_size(blob) == tuple(task["originalPng"]["dimensions"]) == (960, 540)
            assert len(blob) == task["originalPng"]["bytes"] == 235_038
            assert row["sha256"] == task["originalPng"]["sha256"]
        else:
            assert blob.startswith(b"\xff\xd8\xff")
    assert png_count == 1

    browser = receipts["native-browser"]
    assert browser["url"].endswith(task["taskId"]) and browser["visibleTaskReports"] == "14/14"
    assert not browser["desktopDocumentOverflow"] and browser["capturedWarningsOrErrors"] == 0
    assert browser["viewportOverrideReset"] and browser["taskRepeatNotClicked"]
    assert browser["localOnlyReceiptExpanded"] and browser["missingServerArtifactMessageVisible"]
    ci, junit = receipts["source-ci"], receipts["linux-junit"]
    assert ci["sourceRevision"] == junit["sourceRevision"] == source
    assert len(ci["runs"]) == 4 and ci["linuxJUnitArtifactInspected"]
    assert all(r["headSha"] == source and r["status"] == "completed" and r["conclusion"] == "success" for r in ci["runs"])
    assert junit["runId"] == 37478519344 and junit["artifactId"] == 11421017980
    assert junit["windowsSkippedSymlinkFixturesPassedOnLinux"] and junit["allScreenshotCasesPassed"]
    assert len(junit["variants"]) == 4
    for variant in junit["variants"]:
        assert variant["totals"] == {"tests": 872, "failures": 0, "errors": 0, "skipped": 1}
        suites = variant["screenshotSuites"]
        assert len(suites) == 2 and sum(s["tests"] for s in suites) == 16
        cases = [c for s in suites for c in s["cases"]]
        assert len(cases) == 16 and all(c["outcome"] == "passed" for c in cases)
        assert sum("symlink" in c["name"] for c in cases) == 2
    print(json.dumps({"receipts": 9, "assets": 4, "sourceFiles": 8, "installedVersionCode": 10247,
                      "canary": "14/14; 10 captures; 8 retained", "linuxScreenshotCases": "16 passed per variant",
                      "serverArtifactDelivery": "not-connected"}))


if __name__ == "__main__":
    main()
