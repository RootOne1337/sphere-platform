"""Verify immutable installed-agent canary evidence without contacting devices."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.audit.validate_android_focused_text_clear import png_size
from scripts.audit.validate_http_metrics import within

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "docs/audits/2026-10-06"


def main() -> None:
    if not __debug__:
        raise SystemExit("Run without -O: evidence validation uses assertions.")
    manifest = json.loads(within(DIRECTORY, "ANDROID-CLEAR-INSTALLED-EVIDENCE.json").read_bytes())
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
    assert set(receipts) == {"installation", "task", "native-png-recovery", "dag-and-reports", "native-browser"}
    install, task = receipts["installation"], receipts["task"]
    assert install["sourceRevision"] == task["sourceRevision"] == manifest["sourceRevision"]
    assert install["status"] == "completed-and-new-heartbeat" and install["installAttempts"] == 1
    assert install["uidBefore"] == install["uidAfter"]
    assert install["signerMatches"] and install["packageHashVerified"] and install["backupOfStoppedPackage"]
    assert install["stoppedPreferencesByteIdenticalBeforeExplicitStart"]
    assert install["deviceIdentityPreserved"] and install["catalogCountPreserved"] and install["otherDeviceVersionsPreserved"]
    assert not any(install[k] for k in ("dataCleared", "otherDevicesUpdated", "backendUiTunnelsChanged", "otaCatalogChanged"))
    assert install["installedVersionCode"] == task["expectedVersionCode"] == 10246
    assert task["status"] == "terminal-completed" and task["tasksCreated"] == task["scriptsCreated"] == 1
    assert not task["automaticRetry"] and task["deviceActionsRetries"] == 0
    assert task["screenshots"] == {"task_id": task["taskId"], "screenshots": []}
    report = receipts["dag-and-reports"]
    encoded = json.dumps(report["dag"], sort_keys=True, ensure_ascii=False).encode()
    assert hashlib.sha256(encoded).hexdigest() == task["dagHash"] == report["dagHash"]
    nodes = report["dag"]["nodes"]
    assert len(nodes) == len(report["logs"]) == task["nodeCount"] == report["result"]["nodes_executed"] == 25
    assert all(n["retry"] == 0 for n in nodes)
    assert [n["id"] for n in nodes] == [n["node_id"] for n in report["logs"]]
    assert all(n["success"] and n["error"] is None for n in report["logs"])
    logs = {n["node_id"]: n for n in report["logs"]}
    assert logs["read_final_text"]["output"] == "replacement-native"
    for name in ("assert_initial_empty", "assert_seed", "assert_whole_empty", "assert_empty_repeat", "assert_replace_seed", "assert_replacement"):
        assert logs[name]["output"] == "true"
    for name in ("clear_focused", "clear_empty"):
        assert logs[name]["output"] == "{adapter=root-key-chord, field_verified=false}"
    assert not logs["final_screenshot"]["screenshot_key"]
    recovery = receipts["native-png-recovery"]
    assert recovery["taskId"] == task["taskId"] and recovery["manualAdbRecovery"]
    assert not recovery["pixelReencoding"] and not recovery["taskArtifactUploaded"]
    assert recovery["ownedLocalFileCleanupConfirmed"]
    assert len(manifest["assets"]) == 4
    for row in manifest["assets"]:
        blob = within(DIRECTORY, row["file"]).read_bytes()
        assert len(blob) == row["bytes"] and hashlib.sha256(blob).hexdigest() == row["sha256"]
        if row["file"].endswith(".png"):
            assert png_size(blob) == (960, 540) and recovery["sha256"] == row["sha256"]
        else:
            assert blob.startswith(b"\xff\xd8\xff")
    browser = receipts["native-browser"]
    assert not browser["desktopDocumentOverflow"] and browser["viewportOverrideReset"]
    assert browser["taskRepeatButtonNotClicked"] and browser["capturedConsoleWarningsOrErrors"] == 0
    print(json.dumps({"receipts": 5, "assets": 4, "installedVersionCode": 10246, "canary": "25/25", "taskArtifactDelivery": "not-connected"}))


if __name__ == "__main__":
    main()
