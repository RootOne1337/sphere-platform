"""Check frozen partial EP-010 receipts; never recheck live health or close EP-010."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from xml.etree import ElementTree

from scripts.audit.validate_http_metrics import jpeg_size

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "docs/audits/2026-10-05"


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob.replace(b"\r\n", b"\n")).hexdigest()


def main() -> None:
    if not __debug__:
        raise SystemExit("Run without -O: this integrity checker requires assertions.")
    manifest = json.loads((DIRECTORY / "ENTERPRISE-LIVE-COVERAGE-EVIDENCE.json").read_bytes())
    source = manifest["source"]
    assert re.fullmatch(r"[a-f0-9]{40}", source)
    assert manifest["schemaVersion"] == 1 and manifest["status"] == "PARTIAL_EP_010_STAGE_A_INSTALLED"
    assert manifest["criterionClosed"] is False
    assert manifest["ledger"] == {"accepted": 9, "open": 41, "immutableBaselineRetained": True}
    previous = (DIRECTORY / manifest["previousEvidence"]).read_bytes()
    assert digest(previous) == manifest["previousEvidenceSha256"]
    ledger = json.loads(previous)["ledger"]
    assert ledger["totalClosed"] == 9 and ledger["itemsWithOpenCriteria"] == 41
    for row in manifest["sourceHashes"]:
        assert (ROOT / row["file"]).resolve().is_relative_to(ROOT)
        blob = subprocess.check_output(["git", "show", source + ":" + row["file"]], timeout=10, cwd=ROOT)
        assert digest(blob) == row["sha256"], row["file"]
        if row["file"].startswith("backend/monitoring/"):
            prior = subprocess.check_output(["git", "show", manifest["uiSourcePreserved"] + ":" + row["file"]], timeout=10, cwd=ROOT)
            assert blob == prior, "Resource producers must match the accepted EP-009 source."
    receipts = {}
    for row in manifest["receipts"]:
        path = (DIRECTORY / row["file"]).resolve()
        assert path.is_relative_to(DIRECTORY) and path.is_file()
        blob = path.read_bytes()
        assert digest(blob) == row["sha256"]
        assert not re.search(rb"tt_[a-z0-9]{20,}|Bearer\s+eyJ|ghp_[A-Za-z0-9]{20,}", blob)
        if path.suffix == ".json":
            receipts[path.stem] = json.loads(blob)
    exported = receipts["api-schema-export"]
    assert exported["source"] == source and exported["imageId"] == manifest["image"]["imageId"]
    assert exported["exporterCheckExit"] == 0 and exported["documentsMatch"]
    assert exported["network"] == "none" and not exported["lifespanStarted"]
    assert not exported["applicationSourceMounted"]
    repair = manifest["documentationRepairCommit"]
    assert re.fullmatch(r"[a-f0-9]{40}", repair)
    schema = json.loads(subprocess.check_output(["git", "show", repair + ":docs/openapi.json"], timeout=10, cwd=ROOT))
    properties = schema["components"]["schemas"]["VPNPoolStats"]["properties"]
    assert properties["handshake_max_age_seconds"]["default"] == 180
    assert {item.get("format") for item in properties["observed_at"]["anyOf"]} == {"date-time", None}
    for name, count in [("vpn-image-tests", 99), ("resource-image-tests", 27)]:
        row = receipts[name]
        assert row["source"] == source and row["tests"] == count
        assert row["exit"] == row["failed"] == row["errors"] == row["skipped"] == 0
        assert not row["applicationSourceMounted"] and row["network"] == "none"
        assert row["imageId"] == manifest["image"]["imageId"]
        suite = ElementTree.parse(DIRECTORY / ("evidence/live-coverage/" + name + ".xml"))
        cases = list(suite.getroot().iter("testcase"))
        assert len(cases) == count and all(not any(case.find(kind) is not None for kind in ["failure", "error", "skipped"]) for case in cases)
    installed = receipts["api-installed"]
    assert installed["source"] == source and installed["ready"]
    assert installed["otherContainersPreserved"] == 45
    assert installed["mountsPreserved"] and installed["logRotationPreserved"]
    assert installed["changedContainers"] == ["sphere-pilot-20260911-backend-1"]
    assert not installed["apkChanged"] and not installed["tunnelsChanged"]
    live = receipts["vpn-live"]
    assert live["peerCount"] == live["activeCount"] == live["staleCount"] == live["assignedCount"] == 0
    assert live["handshakeMaxAgeSeconds"] == 180 and live["peerFlagsAgree"]
    assert not live["routerReadPerformed"] and not live["androidCommandsSent"]
    final = receipts["final-check"]
    assert final["ownLogout"] == 204 and final["revokedRead"] == 401
    assert len(final["samples"]) == 6 and all(row["statusCounts"]["online"] == 14 for row in final["samples"])
    assert not final["continuousUptimeClaimed"] and not final["deviceCommandsSent"]
    assert final["resourceStates"] == {"cpu": "ready", "cpuQuota": "empty", "memory": "ready", "memoryLimit": "ready"}
    for row in manifest["screenshots"]:
        path = (DIRECTORY / row["file"]).resolve()
        assert path.is_relative_to(DIRECTORY)
        blob = path.read_bytes()
        assert hashlib.sha256(blob).hexdigest() == row["sha256"]
        assert jpeg_size(blob) == (row["width"], row["height"])
    assert not re.search(r"tt_[a-z0-9]{20,}|Bearer\s+eyJ|ghp_[A-Za-z0-9]{20,}", json.dumps(manifest))
    print(json.dumps({"artifactIntegrity": "PASS", "source": source, "accepted": 9,
                      "open": 41, "EP010Closed": False, "liveHealthRechecked": False}))


if __name__ == "__main__":
    main()
