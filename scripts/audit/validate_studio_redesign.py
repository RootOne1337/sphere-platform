"""Validate frozen redesign evidence; never issue live requests or Android input."""
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


def git_blob(source: str, path: str) -> bytes:
    assert len(source) == 40 and all(c in "0123456789abcdef" for c in source)
    assert (ROOT / path).resolve().is_relative_to(ROOT)
    return subprocess.check_output(["git", "show", source + ":" + path], cwd=ROOT, timeout=15)


def main() -> None:
    if not __debug__:
        raise SystemExit("Run without -O: validation requires assertions.")
    manifest = json.loads(within(DIRECTORY, "STUDIO-REDESIGN-EVIDENCE.json").read_bytes())
    assert manifest["schemaVersion"] == 1
    assert manifest["status"] == "PARTIAL_REDESIGN_INSTALLED"
    api, ui = manifest["apiSource"], manifest["uiSource"]
    assert manifest["ledger"] == {"accepted": 9, "open": 41, "immutableBaselineRetained": True}
    assert manifest["openStudioItems"] == [f"EP-{i:03d}" for i in range(14, 21)]
    for name in ["criterionClosed", "frameExactReplayProven", "fullRecorderImplemented",
                 "uia2InstrumentationAdded", "apkChanged", "tunnelsChanged", "fleetSlaProven",
                 "storageWriterIdentified", "fleetLoadOrSoakPerformed", "backendChanged"]:
        assert manifest[name] is False, name
    assert manifest["captureScope"] == "submitted-click-swipe-wheel-memory-only"
    assert manifest["xpathScope"] == "owned-root-hierarchy-explicit-insertion-30s-lease"
    assert manifest["catalogMetadataOnly"] is False
    previous = within(DIRECTORY, manifest["previousEvidence"])
    assert digest(previous.read_bytes()) == manifest["previousEvidenceSha256"]
    baseline = (DIRECTORY / manifest["backlog"]).resolve()
    assert baseline.is_relative_to(ROOT / "docs/audits")
    assert digest(baseline.read_bytes()) == manifest["backlogSha256"]
    assert len(json.loads(baseline.read_bytes())["items"]) == 50
    assert subprocess.check_output(["git", "rev-parse", api + ":backend"], cwd=ROOT) == subprocess.check_output(
        ["git", "rev-parse", ui + ":backend"], cwd=ROOT)

    required = {"frontend/app/(dashboard)/scripts/page.tsx", "frontend/app/(dashboard)/scripts/builder/page.tsx",
                "frontend/app/(dashboard)/tasks/[id]/page.tsx", "frontend/src/features/scripts/studio/DeviceWorkbench.tsx",
                "frontend/src/features/scripts/studio/layout.ts", "frontend/lib/dag/studio.ts",
                "frontend/scripts/prepare-elk-worker.mjs", "frontend/package-lock.json"}
    hashed = set()
    for row in manifest["sourceHashes"]:
        assert row["source"] == ui and row["file"] not in hashed
        hashed.add(row["file"])
        assert digest(git_blob(ui, row["file"]), binary=row.get("binary", False)) == row["sha256"], row["file"]
    assert required <= hashed
    assert manifest["libraries"]["elkjs"] == {"version": "0.12.0", "licenseChosen": "EPL-2.0", "localWorker": True}
    assert manifest["libraries"]["reactFlow"]["license"] == "MIT"
    package = json.loads(git_blob(ui, "frontend/package.json"))
    assert package["dependencies"]["elkjs"] == "0.12.0"

    receipts = {}
    for row in manifest["receipts"]:
        assert row["name"] not in receipts
        blob = within(DIRECTORY, row["file"]).read_bytes()
        assert len(blob) < 100_000 and digest(blob) == row["sha256"], row["file"]
        receipts[row["name"]] = json.loads(blob)
    build, installed = receipts["ui-build"], receipts["ui-installed"]
    assert build["source"] == installed["source"] == ui
    assert build["exit"] == 0 and build["gitArchive"] and installed["ready"]
    assert build["imageId"] == manifest["uiImageId"]
    assert installed["changedContainers"] == ["sphere-review-20261002-review-ui-1"]
    assert installed["otherContainersPreserved"] == 45 and installed["mountsPreserved"] and installed["logRotationPreserved"]
    assert not installed["apkChanged"] and not installed["tunnelsChanged"]
    for sample in [installed["beforeFleet"], installed["afterFleet"]]:
        assert sample["total"] == 19 and sample["presenceAvailable"]
        assert sum(sample["statusCounts"].values()) == sample["total"]
    tests = receipts["frontend-tests"]
    assert tests["source"] == ui and tests["success"] and tests["failed"] == tests["pending"] == 0
    assert tests["tests"] >= 1443 and tests["suites"] >= 125
    assert tests["tests"] == manifest["tests"] and tests["suites"] == manifest["suites"]
    assert tests["typeCheckExit"] == 0 and tests["execution"] == "local-jest-in-band-no-cache"
    assets = receipts["packaged-elk-assets"]
    assert assets["source"] == ui and assets["imageId"] == manifest["uiImageId"]
    assert assets["worker"]["url"] == "/vendor/elk/worker-0.12.0.js"
    assert assets["license"]["url"] == "/vendor/elk/LICENSE.md"
    assert all(assets[key]["httpStatus"] == 200 and len(assets[key]["sha256"]) == 64 for key in ["worker", "license"])
    assert assets["license"]["epl2TextPresent"]
    native = receipts["native-ui"]
    assert native["source"] == ui and native["capture"] == "native-codex-browser"
    assert native["workbenchDesktop"]["viewportWidth"] == native["workbenchDesktop"]["documentWidth"] == 1440
    assert native["workbenchDesktop"]["nodeDimensions"] == [[256, 133]] * 3
    assert native["taskMobile"]["viewportWidth"] == native["taskMobile"]["documentWidth"] == 390
    assert native["editorMobileAfterReload"]["canvasHeight"] == 440
    assert native["editorMobileAfterReload"]["documentWidth"] == 390
    assert all(native["pendingNodeForm"][key] for key in ["undoDisabled", "saveDisabled", "cancelRestoredUndo", "undoRestoredOriginalTitle"])
    assert native["pendingNodeForm"]["publishedOrExecuted"] is False
    integrity = receipts["git-integrity"]
    assert integrity["source"] == ui and integrity["exit"] == 0
    assert not any(integrity[key] for key in ["historyRewritten", "workingTreeReset", "storageWriterIdentified"])
    for name in ["git-tree-repair", "git-operations-tree-repair"]:
        repair = receipts[name]
        assert repair["type"] == "tree" and repair["canonicalGitSha1Verified"] and repair["originalQuarantined"]
        assert repair["historyAndWorkingTreeChanged"] is False

    ci = receipts["source-ci"]
    assert ci["source"] == ci["installedUiSource"] == ui and ci["installedApiSource"] == api
    assert ci["allFourCompletedSuccess"] and ci["documentationHeadChecksSeparate"]
    assert {row["workflow"] for row in ci["workflows"]} == {"backend", "frontend", "preview", "android"}
    for row in ci["workflows"]:
        assert row["source"] == ui and row["status"] == "completed" and row["conclusion"] == "success"
        assert row["url"] == f"https://github.com/RootOne1337/sphere-platform/actions/runs/{row['runId']}"
        expected_jobs = {"guard": "success", "deploy": "skipped"} if row["workflow"] == "preview" else None
        if expected_jobs is not None:
            assert {job["name"]: job["conclusion"] for job in row["jobs"]} == expected_jobs
        else:
            assert row["jobs"] and all(job["conclusion"] == "success" for job in row["jobs"])
    assert ci["previewDeploymentPerformed"] is False
    assert ci["backendTestSummary"] == {"passed": 2844, "skipped": 30, "warnings": 1}
    assert not any(ci[key] for key in ["fleetSlaProven", "allActionsProven", "storageWriterIdentified"])
    sample = receipts["catalog-payload-sample"]
    assert sample["apiSource"] == api and sample["uiSource"] == ui and sample["httpStatus"] == 200
    assert sample["request"] == {"path": "/api/v1/scripts", "state": "active", "page": 1, "per_page": 25}
    assert sample["scope"] == "one-real-current-page-read-no-load-or-heap-profile"
    assert sample["rowsReturned"] == sample["rowsContainingFullCurrentDag"] == sample["total"] == 19
    assert sample["decodedResponseBytes"] == sample["downloadedBodyBytes"] == 31368
    assert sample["contentEncoding"] == "identity" and sample["aggregateNodesInReturnedDags"] == 106
    assert 0 < sample["dagJsonContributionBytes"] < sample["decodedResponseBytes"]

    canaries = [receipts["remote-canary"], receipts["remote-canary-final"]]
    ids = set()
    for canary in canaries:
        task = canary["task"]
        assert task["id"] not in ids
        ids.add(task["id"])
        assert task["status"] == "completed" and canary["scriptVersionId"] == manifest["canaryVersionId"]
        assert canary["deviceId"] == manifest["canaryDeviceId"]
        assert canary["dagHash"] == manifest["canaryDagHash"]
        assert hashlib.sha256(json.dumps(canary["dag"], sort_keys=True, ensure_ascii=False).encode()).hexdigest() == canary["dagHash"]
        assert len(canary["dag"]["nodes"]) == 3
        assert sorted(node["action"]["type"] for node in canary["dag"]["nodes"]) == ["end", "sleep", "start"]
        assert next(node["action"]["ms"] for node in canary["dag"]["nodes"] if node["action"]["type"] == "sleep") == 4000
        reports = canary["logs"]
        assert len(reports) == 3 and all(row["success"] for row in reports)
        assert [row["action_type"] for row in reports] == ["start", "sleep", "end"]
        assert reports[1]["duration_ms"] >= 4000
        assert canary["uiRevision"] in manifest["canaryUiSources"]
    assert len(ids) == 2 and manifest["realTasksCreated"] == 2

    native_names = set()
    for row in manifest["screenshots"]:
        assert row["capture"] == "native-codex-browser" and row["name"] not in native_names
        native_names.add(row["name"])
        blob = within(DIRECTORY, row["file"]).read_bytes()
        assert digest(blob, binary=True) == row["sha256"], row["file"]
        assert list(jpeg_size(blob)) == row["dimensions"], row["file"]
        assert len(blob) < 1_000_000
    assert {"catalog-final", "editor-final", "workbench-final", "task-final", "task-mobile"} <= native_names
    assert all(row["source"] == ui for row in manifest["screenshots"] if row["name"] in {
        "workbench-final", "task-final", "task-mobile"})
    print(json.dumps({"artifactIntegrity": "PASS", "scope": "frozen-redesign-receipts-only",
                      "uiSource": ui, "apiSource": api, "tests": tests["tests"], "suites": tests["suites"],
                      "remoteTasks": len(ids), "screenshots": len(native_names), "ledger": manifest["ledger"]}))


if __name__ == "__main__":
    main()
