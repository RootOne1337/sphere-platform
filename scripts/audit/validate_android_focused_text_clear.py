"""Validate pinned APK candidate evidence offline; never install or run commands."""
from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import zlib
from pathlib import Path

from scripts.audit.validate_http_metrics import within

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "docs/audits/2026-10-06"


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def png_size(blob: bytes) -> tuple[int, int]:
    """Check all PNG chunk CRCs and dimensions without decoding image pixels."""
    assert blob[:8] == b"\x89PNG\r\n\x1a\n" and len(blob) < 1_000_000
    offset = 8
    first = True
    dimensions = (0, 0)
    while offset + 12 <= len(blob):
        size = struct.unpack(">I", blob[offset:offset + 4])[0]
        end = offset + 12 + size
        assert end <= len(blob)
        kind = blob[offset + 4:offset + 8]
        payload = blob[offset + 8:end - 4]
        assert struct.unpack(">I", blob[end - 4:end])[0] == zlib.crc32(kind + payload) & 0xFFFFFFFF
        if first:
            assert kind == b"IHDR" and size == 13
            dimensions = struct.unpack(">II", payload[:8])
            first = False
        offset = end
        if kind == b"IEND":
            assert size == 0 and offset == len(blob)
            return dimensions
    raise AssertionError("Incomplete PNG")


def main() -> None:
    if not __debug__:
        raise SystemExit("Run without -O: evidence validation uses assertions.")
    manifest = json.loads(within(DIRECTORY, "ANDROID-FOCUSED-TEXT-CLEAR-EVIDENCE.json").read_bytes())
    source = manifest["sourceRevision"]
    assert len(source) == 40 and all(c in "0123456789abcdef" for c in source)
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
    assert set(receipts) == {"candidate-build", "source-tests", "native-helper", "generated-class-corruption", "source-ci"}
    assert len(manifest["sourceHashes"]) == 12
    paths = set()
    for row in manifest["sourceHashes"]:
        assert row["source"] == source and row["digestMode"] == "raw-git-blob"
        assert row["file"].startswith("android/") and (ROOT / row["file"]).resolve().is_relative_to(ROOT)
        assert row["file"] not in paths
        paths.add(row["file"])
        blob = subprocess.check_output(["git", "show", source + ":" + row["file"]], cwd=ROOT, timeout=15)
        assert digest(blob) == row["sha256"]
    build = receipts["candidate-build"]
    candidate = build["candidate"]
    assert candidate["source_commit"] == candidate["android_tree_matches_reviewed_version_commit"] == source
    assert candidate["version_name"] == "1.2.46-dev" and candidate["version_code"] == 10246
    assert candidate["package"] == "com.sphereplatform.agent.pilot.debug"
    assert candidate["signer_matches_local_pilot_baseline"] and len(candidate["certificate_sha256"]) == 64
    assert not candidate["installed"] and not candidate["published_to_ota"]
    assert not build["apkBinaryPublishedInRepository"] and not build["productionSignedReleaseOrFleetRolloutAccepted"]
    assert build["zipCrcPassed"] and all(d["headerChecksumsValid"] for d in build["dex"])
    assert build["dex"] and all(len(d["sha256"]) == 64 for d in build["dex"])
    tests = receipts["source-tests"]
    assert tests["uniqueTestsCannotBeSummedAcrossFlavors"] and not tests["rawLogsOrBuildConfigPublished"]
    for name, flavor in tests["flavors"].items():
        assert flavor["counts"] == candidate["tests"][name] == {"tests": 856, "failures": 0, "errors": 0, "skipped": 1}
        assert flavor["passed"] == 855 and flavor["suites"] == 71
        assert sum(int(s["tests"]) for s in flavor["focusedSuites"]) == 45
        assert all(int(s[k]) == 0 for s in flavor["focusedSuites"] for k in ["failures", "errors", "skipped"])
        assert len(flavor["assumptionSkipped"]) == 1
    assert set(tests["flavors"]) == {"dev", "enterprise"}
    native = receipts["native-helper"]
    assert native["scope"] == "root-helper-only-on-local-Android" and native["sdk"] == 28
    assert native["screen"] == [960, 540] and native["apkSha256"] == candidate["sha256"]
    assert native["initialText"] == "sphere-clear-original" and native["cursorMovedFromEnd"]
    assert native["afterClearText"] == "" and native["emptyClearIdempotent"]
    assert native["followUpText"] == "after-clear" and native["fixtureTempFilesAbsentAfterTest"]
    assert native["restoredToAndroidHome"] and not native["installed"] and not native["publishedToOta"]
    assert not native["rootQueueIntegrationVerifiedByNativeTest"] and not native["clipboardContentVerifiedByNativeTest"]
    assert not native["helperTimingIsVideoLatencyOrFleetP95"]
    incident = receipts["generated-class-corruption"]
    assert len(incident["classes"]) == 4 and not incident["rootCauseEstablished"]
    assert incident["classes"][-1]["magic"] == "ffffffff"
    assert incident["onlyOneGeneratedFileRemovedAndRegenerated"] and incident["removedBytes"] == 1753
    assert incident["regeneratedClass"]["magic"] == "cafebabe"
    assert incident["regeneratedClass"]["sha256"] == incident["classes"][2]["sha256"]
    assert not incident["sourceFilesChanged"] and not incident["filesystemRepairOrDiskGrowthWriterEstablished"]
    ci = receipts["source-ci"]
    assert ci["allFourCompletedSuccess"] and not ci["previewDeploymentPerformed"]
    assert len(ci["workflows"]) == 4
    assert all(w["headSha"] == source and w["status"] == "completed" and w["conclusion"] == "success" for w in ci["workflows"])
    preview = next(w for w in ci["workflows"] if w["name"] == "Preview — Deploy")
    assert {j["name"]: j["conclusion"] for j in preview["jobs"]} == {"guard": "success", "deploy": "skipped"}
    assert len(manifest["screenshots"]) == 2
    hashes = set()
    for row in manifest["screenshots"]:
        blob = within(DIRECTORY, row["file"]).read_bytes()
        assert len(blob) == row["bytes"] and digest(blob) == row["sha256"]
        assert row["source"] == source and row["capture"] == "native-Android-adb-screencap-original-PNG"
        assert list(png_size(blob)) == row["dimensions"] == [960, 540]
        hashes.add(row["sha256"])
    assert len(hashes) == 2
    print(json.dumps({"artifactIntegrity": "PASS", "scope": "candidate-and-local-Android-helper-only",
                      "source": source, "receipts": 5, "screenshots": 2,
                      "apkInstalledOrOtaPublished": False, "wholeBacklogClosed": False}))


if __name__ == "__main__":
    main()
