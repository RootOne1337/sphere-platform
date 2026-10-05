"""Check recorded implementation artifact integrity, not live production health.

Read-only: pinned Git objects, documentation, JSON and reviewed screenshots.
Tests/build/browser receipts are recorded observations; this check does not rerun them.
"""
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
    evidence = json.loads((DIRECTORY / "ENTERPRISE-PRODUCT-IMPLEMENTATION-EVIDENCE.json").read_text(encoding="utf-8"))
    document = (DIRECTORY / "ENTERPRISE-PRODUCT-IMPLEMENTATION.md").read_text(encoding="utf-8")
    original = json.loads((DIRECTORY / "ENTERPRISE-PRODUCT-BACKLOG.json").read_text(encoding="utf-8"))
    assert evidence["schemaVersion"] == 1
    assert evidence["auditSource"] == original["source"]
    source = evidence["implementationSource"]
    assert evidence["installed"]["source"] == source
    assert evidence["installed"]["reviewUiHealthy"] is True
    assert evidence["installed"]["otherContainersPreserved"] == 45
    assert evidence["installed"]["apkRebuiltOrInstalled"] is False
    assert evidence["installed"]["publicUi18080Updated"] is False
    assert evidence["finalUiReceipt"]["uiSource"] == source[:7]
    ledger = evidence["ledger"]
    assert ledger["originalItems"] == len(original["items"]) == 50
    fixed = ledger["defectsFixedInThisBatch"]
    assert fixed == [f"EP-{i:03}" for i in range(1, 6)]
    assert all(next(i for i in original["items"] if i["id"] == identity)["kind"] == "CONFIRMED_DEFECT" for identity in fixed)
    assert ledger["itemsWithOpenCriteria"] == len(original["items"]) - len(fixed)
    assert all(item["state"] == "OPEN" for item in original["items"])
    tests = evidence["tests"]["frontend"]
    assert tests["success"] is True
    assert tests["numTotalTests"] == tests["numPassedTests"] == 1185
    assert tests["numTotalTestSuites"] == tests["numPassedTestSuites"] == 116
    assert tests["numFailedTests"] == tests["numPendingTests"] == 0
    assert evidence["tests"]["typeScriptPassed"] is True
    assert evidence["tests"]["dockerProductionBuildExit"] == 0
    assert all(evidence["tests"]["builderBackendProbe"].values())
    assert evidence["tests"]["backendActionTypes"] == 32
    live = evidence["scriptLiveReceipt"]
    assert live["createdAndSavedViaBrowser"] is True
    assert live["catalogUpdatedWithoutRefresh"] is True
    assert live["serverReadbackCanonical"] is True
    assert live["archivedWithVersionPrecondition"] is True
    assert live["versionsAndDagPreserved"] is True
    assert live["androidCommandsSent"] is False
    assert live["nodeCount"] == 2 and live["versionCountAfterUnchangedGraphSaves"] == 1
    assert re.fullmatch(r"[a-f0-9]{64}", live["dagSha256"])
    final = evidence["finalUiReceipt"]
    headers = final["finalFleetReadback"]["headers"]
    assert all(column in headers for column in ["Доступ", "CPU Android", "RAM Android"])
    assert final["finalFleetReadback"]["sort"] == "ascending"
    assert final["modelSearch"]["matches"] == 1 and final["modelSearch"]["selected"] == 0
    assert final["runFormCancelled"] is True and final["streamsStarted"] == 0
    for name, digest in evidence["frontendGitBlobHashes"].items():
        path = (ROOT / name).resolve()
        assert path.is_relative_to(ROOT)
        blob = subprocess.run(["git", "show", f"{source}:{name}"], cwd=ROOT,
                              capture_output=True, check=True, timeout=10).stdout
        assert hashlib.sha256(blob).hexdigest() == digest, f"Source receipt mismatch {name}"
    screenshots = evidence["screenshots"]
    assert len({image["file"] for image in screenshots}) == len(screenshots) == 9
    for image in screenshots:
        path = (ROOT / image["file"]).resolve()
        assert path.is_relative_to(DIRECTORY)
        blob = path.read_bytes()
        assert image["visuallyReviewed"] is True and blob[:2] == b"\xff\xd8"
        assert len(blob) == image["bytes"]
        assert hashlib.sha256(blob).hexdigest() == image["sha256"]
    checked = 0
    for target in re.findall(r"\]\(([^)]+)\)", document):
        if "://" in target or target.startswith("#"):
            continue
        path = (DIRECTORY / unquote(target.split("#")[0])).resolve()
        assert path.is_relative_to(ROOT) and path.is_file(), f"Missing implementation link {target}"
        checked += 1
    published = document + json.dumps(evidence)
    assert not re.search(r"tt_[a-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|Bearer\s+eyJ", published)
    print(json.dumps({"artifactIntegrity": "PASS", "liveHealthRechecked": False,
                      "frozenSources": len(evidence["frontendGitBlobHashes"]),
                      "reviewedScreenshots": len(screenshots), "localLinks": checked,
                      "recordedTests": tests["numPassedTests"], "remainingItems": 45}))


if __name__ == "__main__":
    main()
