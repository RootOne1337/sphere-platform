"""Validate frozen upload-intake evidence; no live requests, cleanup or load test."""
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


def git_blob(source: str, name: str) -> bytes:
    assert re.fullmatch(r"[0-9a-f]{40}", source)
    assert (ROOT / name).resolve().is_relative_to(ROOT)
    return subprocess.check_output(["git", "show", source + ":" + name], cwd=ROOT, timeout=10)


def main() -> None:
    if not __debug__:
        raise SystemExit("Run without -O: evidence validation requires assertions.")
    manifest = json.loads((DIRECTORY / "DEVICE-LOG-UPLOAD-EVIDENCE.json").read_bytes())
    source, ui, baseline = (manifest[key] for key in ["source", "uiSource", "baselineSource"])
    assert manifest["schemaVersion"] == 1 and manifest["status"] == "PARTIAL_EP_033_UPLOAD_INTAKE_INSTALLED"
    assert not manifest["criterionClosed"]
    assert manifest["ledger"] == {"accepted": 9, "open": 41, "immutableBaselineRetained": True}
    assert manifest["budgets"] == {"bodyBytes": 524288, "intakeSeconds": 60, "uploadsPerWorker": 4,
                                  "workers": 4, "globalSemaphore": False}
    assert manifest["frontendTreeUnchanged"]
    assert subprocess.check_output(["git", "rev-parse", source + ":frontend"], cwd=ROOT) == subprocess.check_output([
        "git", "rev-parse", ui + ":frontend"], cwd=ROOT)
    for row in manifest["sourceHashes"]:
        assert row["source"] == source and digest(git_blob(source, row["file"])) == row["sha256"], row["file"]
    for key in ["beforeEvidence", "previousEvidence"]:
        path = (DIRECTORY / manifest[key]).resolve()
        assert path.is_relative_to(DIRECTORY) and path.is_file()
        assert digest(path.read_bytes()) == manifest[key + "Sha256"]
    before = json.loads((DIRECTORY / manifest["beforeEvidence"]).read_bytes())
    assert before["source"] == baseline and not before["workingTreeModified"]
    receipts = {}
    assert len({row["file"] for row in manifest["receipts"]}) == len(manifest["receipts"])
    for row in manifest["receipts"]:
        path = (DIRECTORY / row["file"]).resolve()
        assert path.is_relative_to(DIRECTORY) and path.is_file()
        blob = path.read_bytes()
        assert digest(blob) == row["sha256"], row["file"]
        assert not re.search(rb"tt_[a-z0-9]{20,}|Bearer\s+eyJ|ghp_[A-Za-z0-9]{20,}", blob)
        if path.suffix == ".json":
            receipts[path.stem] = json.loads(blob)
    after = receipts["after"]
    assert after["source"] == source and not after["workingTreeModified"]
    for index, (old, new) in enumerate(zip(before["cases"], after["cases"], strict=True)):
        assert old["contentLengthDeclared"] == new["contentLengthDeclared"] == (index == 0)
        assert old["generatedBodyBytes"] == new["generatedBodyBytes"] == 8388608
        assert old["chunkBytes"] == new["chunkBytes"] == 65536
        assert old["receiveCalls"] == 128 and old["asgiBodyBytesConsumed"] == 8388608 and old["requestBodyCached"]
        assert new["receiveCalls"] == (0 if index == 0 else 9)
        assert new["asgiBodyBytesConsumed"] == (0 if index == 0 else 589824)
        assert old["pythonTracedPeakBytes"] > 8 * 1024 * 1024 and new["pythonTracedPeakBytes"] < 1024 * 1024
        assert old["status"] == new["status"] == 413
        assert not new["requestBodyCached"] and new["storedFiles"] == 0 and new["temporaryFilesRemoved"]
    assert not any(after[key] for key in ["liveServicesContacted", "authorizationProven", "hostDiskWriterIdentified",
                                         "aggregateProcessRssBoundProven"])
    image = receipts["api-build"]
    assert image == manifest["apiImage"] and image["source"] == source and image["exit"] == 0
    assert image["gitArchive"] and not image["applicationSourceMounted"]
    assert re.fullmatch(r"sha256:[a-f0-9]{64}", image["imageId"])
    for name in ["image-tests", "resource-tests", "mypy", "ruff", "api-schema-check"]:
        receipt = receipts[name]
        assert receipt["source"] == source and receipt["imageId"] == image["imageId"] and receipt["exit"] == 0
        assert receipt["network"] == "none" and not receipt["applicationSourceMounted"]
    for name, count in [("image-tests", 537), ("resource-tests", 35)]:
        receipt = receipts[name]
        assert receipt["tests"] == count and receipt["failed"] == receipt["errors"] == receipt["skipped"] == 0
        cases = list(ElementTree.parse(DIRECTORY / ("evidence/log-upload-budget/" + name + ".xml")).getroot().iter("testcase"))
        assert len(cases) == count and all(all(case.find(kind) is None for kind in ["failure", "error", "skipped"]) for case in cases)
        if name == "image-tests":
            assert sum("test_log_upload_budget" in case.attrib["classname"] for case in cases) == 35
    old_schema, new_schema = (json.loads(git_blob(sha, "docs/openapi.json")) for sha in [baseline, source])
    responses = old_schema["paths"]["/api/v1/logs/upload"]["post"]["responses"]
    for key in ["400", "408", "413", "503"]:
        assert key not in responses
        responses[key] = new_schema["paths"]["/api/v1/logs/upload"]["post"]["responses"][key]
    assert old_schema == new_schema and manifest["schemaChangesOnlyFourUploadResponses"]
    installed = receipts["installed"]
    assert installed["source"] == source and installed["imageId"] == image["imageId"] and installed["ready"]
    assert installed["onlyBackendChanged"] and installed["otherContainersPreserved"] == 45
    assert installed["mountsPreserved"] and installed["logRotationPreserved"]
    prefixes = installed["existingPrefixes"]
    assert prefixes == {"files": 14, "bytes": 3614902, "prefixHashesVerified": True, "uid": 1001}
    assert not any(installed[key] for key in ["uiChanged", "apkChanged", "tunnelsChanged", "diskWriterIdentified"])
    live = receipts["live"]
    assert live["source"] == source and live["ready"] and live["ownLogout"] == 204 and live["revokedRead"] == 401
    assert not any(live[key] for key in ["deviceCommandsSent", "logsDeleted", "syntheticSuccessfulUploadsSent",
                                       "diskWriterIdentified", "continuousUptimeClaimed"])
    assert live["rejectedFixtureAbsentFromTail"] and live["checks"][0]["status"] == 200
    assert live["checks"][0]["returnedLines"] == 1000
    for row in live["checks"][1:]:
        assert row["status"] == 413 and row["sentBytes"] == 524289
        assert row["identity"] == "operator-jwt-in-X-API-Key" and not row["agentAuthenticationProven"]
    for row in live["receivedUploads"].values():
        assert row["files"] == row["originalPrefixesVerified"] == 14 and row["originalPrefixBytes"] == 3614902
        assert row["filesReceivingAfterInstallation"] == 5 and row["appendedBytes"] == 324393
        assert row["bytes"] == 3939295 and not row["rawLogsPublished"]
    browser = receipts["browser-observation"]
    assert browser["source"] == source and browser["uiSource"] == ui
    assert browser["layout"]["width"] == browser["layout"]["scrollWidth"] == 1280
    assert all(browser[key] for key in ["nonemptyLogsVisibleBeforeSearch", "noMatchSearchVerified",
                                       "manualRefreshSucceeded", "boundedReadMetadataVisible", "componentMismatchVisible"])
    assert browser["warnErrorEntriesReturned"] == 0
    assert not any(browser[key] for key in ["deviceCommandsSent", "logsDeleted", "themeChanged", "rawLogsPublished"])
    for row in manifest["screenshots"]:
        path = (DIRECTORY / row["file"]).resolve()
        assert path.is_relative_to(DIRECTORY)
        blob = path.read_bytes()
        assert hashlib.sha256(blob).hexdigest() == row["sha256"] and jpeg_size(blob) == (row["width"], row["height"])
    ci = receipts["source-ci"]
    assert ci["source"] == source and not ci["laterDocsHeadCiInherited"]
    assert len(ci["runs"]) >= 4 and all(row["headSha"] == source for row in ci["runs"])
    all_green = all(row["status"] == "completed" and row["conclusion"] == "success" for row in ci["runs"])
    assert all_green == ci["allSourceRunsPassed"]
    assert receipts["document-links"]["valid"] and receipts["document-links"]["uniqueOpenPriorityItems"] == 41
    print(json.dumps({"artifactIntegrity": "PASS", "source": source, "uiSource": ui,
                      "receipts": len(manifest["receipts"]), "imageTestsPassed": 572,
                      "accepted": 9, "open": 41, "EP033Closed": False,
                      "sourceCiAllGreen": all_green, "liveHealthRechecked": False}))


if __name__ == "__main__":
    main()
