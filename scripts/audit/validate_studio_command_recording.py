"""Validate frozen recording evidence without requests or Android commands."""
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
        raise SystemExit("Run without -O: validation uses assertions.")
    manifest = json.loads(within(DIRECTORY, "STUDIO-COMMAND-RECORDING-EVIDENCE.json").read_bytes())
    source = manifest["sourceRevision"]
    assert len(source) == 40 and all(char in "0123456789abcdef" for char in source)
    assert manifest["evidenceSchema"] == 1
    assert manifest["textDigestMode"] == "sha256-after-CRLF-to-LF"
    assert manifest["binaryDigestMode"] == "sha256-raw"
    assert not manifest["secretsRawLogsPrivateConfigurationPublished"]
    assert manifest["backlog"] == {"accepted": 9, "openCriteria": 41, "wholeItemsClosedByThisStage": False}
    receipts = {}
    for row in manifest["evidenceFiles"]:
        blob = within(DIRECTORY, row["file"]).read_bytes().replace(b"\r\n", b"\n")
        assert len(blob) == row["bytesNormalized"] < 100_000
        assert digest(blob) == row["sha256"], row["file"]
        name = Path(row["file"]).stem
        assert name not in receipts
        receipts[name] = json.loads(blob)
        assert receipts[name]["sourceRevision"] == source
    assert len(receipts) == 6
    for row in manifest["sourceHashes"]:
        assert row["source"] == source and row["digestMode"] == "raw-git-blob"
        assert (ROOT / row["file"]).resolve().is_relative_to(ROOT)
        blob = subprocess.check_output(["git", "show", source + ":" + row["file"]], cwd=ROOT, timeout=15)
        assert digest(blob, binary=True) == row["sha256"]
    assert len(manifest["sourceHashes"]) == 8
    build, installed = receipts["ui-build"], receipts["runtime-installation"]
    assert build["exit"] == 0 and build["gitArchiveHeadOnly"]
    assert build["imageId"] == installed["imageId"]
    assert installed["targetOnlyInstalled"] and installed["apiReady"]
    assert installed["preservedContainers"] == 45
    assert installed["apiRevision"] == manifest["apiRevision"]
    assert not installed["apkChanged"] and not installed["tunnelsChanged"]
    tests = receipts["source-tests"]
    assert tests["tests"] == {"total": 1546, "passed": 1546, "failed": 0, "pending": 0}
    assert tests["suites"] == {"total": 128, "passed": 128, "failed": 0}
    assert tests["typeScriptPassed"] and not tests["rawTestLogPublished"]
    canary = receipts["remote-canary"]
    task, version = canary["task"], canary["version"]
    assert task["status"] == "completed" and task["error"] is None
    assert task["script_id"] == version["script_id"] == canary["script"]["id"]
    assert task["script_version_id"] == version["id"] == canary["script"]["current_version_id"]
    assert version["version"] == 1 and len(version["dag_hash"]) == 64
    assert canary["nodeCount"] == len(canary["logs"]) == 10
    assert all(row["success"] and row["error"] is None for row in canary["logs"])
    assert {row["action_type"] for row in canary["logs"]} == {"start", "key_event", "shell", "sleep", "tap", "type_text", "end"}
    assert canary["realTasksCreatedByNativeUi"] == canary["newScriptsCreated"] == canary["newVersionsCreated"] == 1
    assert canary["setupPrerequisiteExplicitlyAdded"] and not canary["frameCorrelatedReplayProven"]
    assert not canary["newTasksCreatedByCollector"]
    native = receipts["native-ui"]
    assert native["capture"] == "native-codex-browser" and native["source"] == source
    assert native["temporaryViewportReset"] and native["mobileVideoAndNavigationVisible"]
    assert all(row["width"] == row["documentWidth"] for row in native["viewportChecks"])
    assert native["errorOrWarningLogCount"] == 0
    assert not native["ackTimingIsInputToFrameLatency"] and not native["allActionsOrFleetSoakProven"]
    ci = receipts["source-ci"]
    assert ci["allFourCompletedSuccess"] and not ci["previewDeploymentPerformed"]
    assert len(ci["workflows"]) == 4
    for workflow in ci["workflows"]:
        assert workflow["headSha"] == source and workflow["status"] == "completed"
        assert workflow["conclusion"] == "success"
    preview = next(row for row in ci["workflows"] if row["workflowName"] == "Preview — Deploy")
    assert {job["name"]: job["conclusion"] for job in preview["jobs"]} == {"guard": "success", "deploy": "skipped"}
    assert len(manifest["screenshots"]) == 5
    for row in manifest["screenshots"]:
        blob = within(DIRECTORY, row["file"]).read_bytes()
        assert len(blob) == row["bytes"] < 1_000_000
        assert row["source"] == source and row["capture"] == "native-codex-browser"
        assert digest(blob, binary=True) == row["sha256"]
        assert list(jpeg_size(blob)) == row["dimensions"]
    print(json.dumps({"artifactIntegrity": "PASS", "scope": "frozen-command-recording-only",
                      "source": source, "receipts": 6, "screenshots": 5,
                      "liveRequestsOrCommandsIssued": False, "wholeBacklogClosed": False}))


if __name__ == "__main__":
    main()
