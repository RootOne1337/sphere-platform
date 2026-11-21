"""Validate frozen Script Studio receipts; no live requests, Android commands or soak."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from xml.etree import ElementTree

from scripts.audit.validate_http_metrics import jpeg_size, within

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "docs/audits/2026-10-06"


def digest(blob: bytes, *, binary: bool = False) -> str:
    return hashlib.sha256(blob if binary else blob.replace(b"\r\n", b"\n")).hexdigest()


def main() -> None:
    if not __debug__:
        raise SystemExit("Run without -O: artifact validation requires assertions.")
    manifest = json.loads(within(DIRECTORY, "SCRIPT-STUDIO-EVIDENCE.json").read_bytes())
    assert manifest["schemaVersion"] == 1 and manifest["status"] == "PARTIAL_STUDIO_FOUNDATION_INSTALLED"
    api, ui = manifest["apiSource"], manifest["uiSource"]
    followup = manifest["testFollowupSource"]
    assert manifest["ledger"] == {"accepted": 9, "open": 41, "immutableBaselineRetained": True}
    assert manifest["openStudioItems"] == [f"EP-{i:03d}" for i in range(14, 21)]
    assert manifest["wireVersion"] == "1.0" and manifest["validationScope"] == "structure-routes-lua-safety"
    assert not any(manifest[key] for key in ["criterionClosed", "recorderReplayImplemented", "apkChanged",
                                            "tunnelsChanged", "liveFleetSlaProven", "storageWriterIdentified",
                                            "fleetLoadOrSoakPerformed"])
    baseline_path = (DIRECTORY / manifest["backlog"]).resolve()
    assert baseline_path.is_relative_to(ROOT / "docs/audits")
    assert digest(baseline_path.read_bytes()) == manifest["backlogSha256"]
    baseline = json.loads(baseline_path.read_bytes())
    assert len(baseline["items"]) == 50 and all(row["state"] == "OPEN" for row in baseline["items"])
    previous = within(DIRECTORY, manifest["previousEvidence"])
    assert digest(previous.read_bytes()) == manifest["previousEvidenceSha256"]
    assert len(manifest["sourceHashes"]) == 20
    for row in manifest["sourceHashes"]:
        assert row["source"] in {api, ui, followup}
        assert (ROOT / row["file"]).resolve().is_relative_to(ROOT)
        blob = subprocess.check_output(["git", "show", row["source"] + ":" + row["file"]], cwd=ROOT, timeout=10)
        assert digest(blob) == row["sha256"], row["file"]
    # Later installs only changed the frontend; don't infer backend compatibility from badges alone.
    assert subprocess.check_output(["git", "rev-parse", api + ":backend"], cwd=ROOT) == subprocess.check_output([
        "git", "rev-parse", ui + ":backend"], cwd=ROOT)
    assert subprocess.check_output(["git", "rev-parse", api + ":backend"], cwd=ROOT) == subprocess.check_output([
        "git", "rev-parse", followup + ":backend"], cwd=ROOT)
    receipts = {}
    assert len({row["file"] for row in manifest["receipts"]}) == len(manifest["receipts"]) == 23
    for row in manifest["receipts"]:
        blob = within(DIRECTORY, row["file"]).read_bytes()
        assert len(blob) < 100_000 and digest(blob) == row["sha256"], row["file"]
        receipts[row["name"]] = json.loads(blob)
    for part, source in [("api", api), ("ui", ui)]:
        build, install = receipts[part + "-build"], receipts[part + "-installed"]
        assert build["source"] == install["source"] == source
        assert build["exit"] == 0 and build["gitArchive"] and install["ready"]
        assert install["changedContainers"] == [install["target"]] and install["otherContainersPreserved"] == 45
        assert install["mountsPreserved"] and install["logRotationPreserved"]
        assert not install["apkChanged"] and not install["tunnelsChanged"]
    assert receipts["api-installed"]["afterFleet"]["statusCounts"]["online"] == 0
    assert receipts["ui-initial-installed"]["beforeFleet"]["statusCounts"]["online"] == 14
    assert receipts["ui-installed"]["afterFleet"]["statusCounts"]["online"] == 14
    assert len(manifest["junit"]) == 2
    for row, expected in zip(manifest["junit"], [596, 35], strict=True):
        blob = within(DIRECTORY, row["file"]).read_bytes()
        assert digest(blob) == row["sha256"]
        tree = ElementTree.fromstring(blob)
        suites = list(tree.iter("testsuite"))
        assert sum(int(s.attrib["tests"]) for s in suites) == expected
        assert len(list(tree.iter("testcase"))) == expected
        assert all(sum(int(s.attrib[k]) for s in suites) == 0 for k in ["failures", "errors", "skipped"])
        receipt = receipts[row["name"] + "-tests"]
        assert receipt["tests"] == expected and receipt["source"] == api
    for name in ["api-tests", "resource-tests", "mypy", "ruff", "schema"]:
        receipt = receipts[name]
        assert receipt["exit"] == 0 and receipt["source"] == api
        assert receipt["imageId"] == receipts["api-build"]["imageId"]
        assert receipt["network"] == "none" and not receipt["applicationSourceMounted"]
    front = receipts["frontend-tests"]
    assert front["source"] == ui and front["success"] and not front["wasInterrupted"]
    assert front["numTotalTests"] == front["numPassedTests"] == 1353
    assert front["numTotalTestSuites"] == front["numPassedTestSuites"] == 122
    assert front["numFailedTests"] == front["numPendingTests"] == front["numRuntimeErrorTestSuites"] == 0
    draft = receipts["draft-api-live"]
    assert draft["source"] == api and draft["anonymousStatus"] == 401 and draft["validStatus"] == 200
    assert draft["scope"] == manifest["validationScope"] and not draft["deviceExecutionVerified"]
    assert draft["before"] == draft["after"] == {"scripts": 17, "versions": 20, "tasks": 435}
    assert draft["scriptVersionTaskCountsUnchanged"] and draft["commonAuthAuditActivityExcluded"]
    assert len(draft["invalidCases"]) == 4
    assert all(row["status"] == 422 and not row["inputReflected"] for row in draft["invalidCases"])
    canary = receipts["canary-live"]
    task, script = canary["task"], canary["script"]
    assert canary["tasksForThisScript"] == 1 and canary["createdAndRunThroughBrowser"]
    assert task["script_version_id"] == script["versionId"] and task["script_id"] == script["id"]
    assert task["device_id"] == canary["device"]["id"] and canary["device"]["name"] == "auto-ph-025"
    assert canary["device"]["agent_version"] == "1.2.45-dev" and script["version"] == 1
    assert task["status"] == "completed" and task["result"]["success"] and task["error_message"] is None
    assert task["result"]["nodes_executed"] == 3
    logs = task["result"]["node_logs"]
    assert [row["action_type"] for row in logs] == ["start", "sleep", "end"]
    assert all(row["success"] for row in logs) and logs[1]["duration_ms"] == 2000
    assert {row["node_id"] for row in logs} == {row["id"] for row in script["dag"]["nodes"]}
    semantic = hashlib.sha256(json.dumps(script["dag"], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    export, browser = receipts["export-file"], receipts["browser-live"]
    assert semantic == script["dagHash"] == export["semanticDagHash"] == browser["serverValidationHash"]
    assert export["bytes"] == 723 and export["equalsSavedVersion"] and export["fileVerifiedIndependently"]
    assert export["downloadEventTimedOut"] == browser["downloadEventTimedOut"]
    assert browser["apiSource"] == api and browser["uiSource"] == ui
    assert browser["dimensions"]["mainHeight"] == browser["dimensions"]["mainScroll"] == 656
    assert browser["mobile"]["width"] == browser["mobile"]["documentWidth"] == 390
    assert browser["mobile"]["canvasHeight"] == 380 and browser["selectedTargets"] == 1
    assert all(browser[key] for key in ["invalidJsonRetained", "invalidJsonSaveBlocked", "undoRestoredValidSource",
                                       "importThroughFileChooser", "roundtripReportedUnchanged", "darkThemeRestored",
                                       "viewportOverrideReset", "browserTaskObservedCompleted"])
    assert browser["finalReopen"]["sourceReportedUnchanged"] and browser["finalReopen"]["serverHashMatched"]
    view = browser["finalReopen"]["fitView"]
    assert view["allNodesInView"] and len(view["nodes"]) == 3
    canvas = view["canvas"]
    assert all(canvas["top"] <= n["top"] < n["bottom"] <= canvas["bottom"] and
               canvas["left"] <= n["left"] < n["right"] <= canvas["right"] for n in view["nodes"])
    assert len(manifest["screenshots"]) == 5
    for row in manifest["screenshots"]:
        blob = within(DIRECTORY, row["file"]).read_bytes()
        assert digest(blob, binary=True) == row["sha256"]
        assert jpeg_size(blob) == (row["width"], row["height"]) and row["nativeBrowser"]
    ci = receipts["source-ci"]
    assert ci["source"] == ui and not ci["laterDocsHeadCiInherited"]
    assert len(ci["runs"]) == 4 and all(run["headSha"] == ui for run in ci["runs"])
    all_green = all(run["status"] == "completed" and run["conclusion"] == "success" for run in ci["runs"])
    assert all_green == ci["allSourceRunsPassed"]
    assert ci["backendTestFailure"]["failed"] == 1 and ci["backendTestFailure"]["passed"] == 2842
    regression = receipts["pipeline-regression"]
    assert regression["tests"] == 47 and regression["exit"] == 0
    assert regression["failures"] == regression["errors"] == regression["skipped"] == 0
    assert not any(regression[key] for key in ["productionDatabaseUsed", "deviceCommandsSent", "containersRestarted",
                                              "databaseReset", "productionHeartbeatChanged"])
    assert regression["applicationSourceCommit"] == api and regression["flakyCiSource"] == ui
    fixed = subprocess.check_output(["git", "show", followup + ":tests/production/test_pipeline_recovery.py"],
                                   cwd=ROOT, timeout=10)
    assert digest(fixed) == regression["testFileSha256"]
    junit = manifest["pipelineRegressionJUnit"]
    blob = within(DIRECTORY, junit["file"]).read_bytes()
    assert digest(blob) == junit["sha256"]
    cases = list(ElementTree.fromstring(blob).iter("testcase"))
    assert len(cases) == 47
    assert len([row for row in cases if row.attrib["name"].startswith(ci["backendTestFailure"]["test"])]) == 2
    next_ci = receipts["followup-ci"]
    assert next_ci["source"] == followup and not next_ci["laterDocsHeadCiInherited"]
    assert all(row["headSha"] == followup for row in next_ci["runs"])
    followup_green = len(next_ci["runs"]) >= 4 and all(row["status"] == "completed" and row["conclusion"] == "success"
                                                     for row in next_ci["runs"])
    assert followup_green == next_ci["allSourceRunsPassed"]
    followup_tests = next_ci["backendTests"]
    assert followup_tests["source"] == followup and followup_tests["conclusion"] == "success"
    assert followup_tests["failed"] == 0 and followup_tests["passed"] == 2844 and followup_tests["skipped"] == 30
    assert not followup_tests["rawLogPublished"]
    contract = receipts["action-contract"]
    assert contract["scope"] == "offline-structural-validation-and-source-inventory"
    assert contract["backendFrontendTypesEqual"] and len(contract["backendTypes"]) == 32
    assert len(contract["androidHandlerTypes"]) == 33 and contract["runtimeOnlyTypes"] == ["loop"]
    assert not contract["publishedTypesWithoutHandler"]
    assert not any(contract[key] for key in ["deviceExecutionVerified", "installedApkCapabilitiesVerified",
                                            "networkRequestsSent", "databaseUsed", "deviceCommandsSent"])
    source_hashes = {row["file"]: row["sha256"] for row in manifest["sourceHashes"]}
    assert all(source_hashes[name] == value for name, value in contract["sourceHashes"].items())
    cases = contract["cases"]
    assert len(cases) == 5 and all(row["structuralValidationAccepted"] for row in cases[:4])
    assert cases[-1]["name"] == "runtime_loop_not_published" and not cases[-1]["structuralValidationAccepted"]
    docs = receipts["document-links"]
    assert docs["documents"] == 8 and docs["valid"] and not docs["errors"]
    assert docs["uniqueOpenPriorityItems"] == 41 and docs["localLinks"] >= 575 and docs["anchors"] == 24
    print(json.dumps({"artifactIntegrity": "PASS", "apiSource": api, "uiSource": ui,
                      "backendTests": 631, "frontendTests": 1353, "remoteCanarySteps": 3,
                      "accepted": 9, "open": 41, "studioCriteriaClosed": False,
                      "sourceCiAllGreen": all_green, "pipelineRegressionTests": 47,
                      "testFollowupCiAllGreen": followup_green, "liveHealthRechecked": False}))


if __name__ == "__main__":
    main()
