"""Regression guards against false closure and stale documentation navigation."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_documentation_status import (
    INVENTORY,
    REGISTRY,
    ROOT,
    RUNTIME_GUIDES,
    installed_runtime_banner,
    local_link_errors,
    normalized_hash,
    read_json,
    validate_current_apks,
    validate_diagnostic_pilot,
    validate_installed_receipt,
    validate_inventory,
    validate_primary_video_pilot,
    validate_readonly_video_pilot,
    validate_registry,
    validate_runtime_banners,
    validate_status_report,
)


class DocumentationStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = copy.deepcopy(read_json(ROOT, REGISTRY))

    def test_recorded_status_is_consistent(self) -> None:
        self.assertEqual(validate_registry(ROOT, self.registry), [])

    def test_probe_source_cannot_claim_installed_media_or_omit_authorization(self) -> None:
        for key, value in (("runtimeInstalled", True), ("mediaControlInstalled", True),
                           ("implementationAuthorizedNow", False), ("prototypeScope", "full_control")):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.registry)
                changed["directMedia"].update(state="PROTOTYPE_SOURCE", runtimeInstalled=False,
                                              mediaControlInstalled=False, implementationAuthorizedNow=True,
                                              prototypeScope="diagnostic_echo_only")
                changed["directMedia"][key] = value
                self.assertTrue(any("Direct probe source" in error for error in validate_registry(ROOT, changed)))

    def test_probe_evidence_cannot_be_omitted(self) -> None:
        self.registry["directMedia"]["implementationEvidence"] = "docs/absent-probe.md"
        self.assertIn("Direct probe implementation evidence is missing", validate_registry(ROOT, self.registry))

    def test_installed_echo_pilot_requires_exact_finite_receipt_and_scope(self) -> None:
        device = "753fd530-2f19-4e5e-98ba-769863678141"
        pilot = {"enabled": True, "scope": "diagnostic_echo_only", "deviceIds": [device],
                 "mediaControlInstalled": False, "channelAccepted": False}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "pilot.json"
            path.write_text(json.dumps({"runtimeInstalled": True, "diagnosticPilot": pilot}), encoding="utf-8")
            direct = {"runtimeInstalled": True, "pilotCurrentlyEnabled": True,
                      "prototypeScope": "diagnostic_echo_only", "mediaControlInstalled": False,
                      "pilotEvidence": path.name, "pilotDeviceIds": [device],
                      "pilotEvidenceSha256NormalizedLf": normalized_hash(path)}
            self.assertEqual(validate_diagnostic_pilot(root, direct), [])
            for key, value in (("deviceIds", []), ("deviceIds", [device, device]),
                               ("deviceIds", ["arbitrary"]), ("channelAccepted", True),
                               ("mediaControlInstalled", True), ("enabled", False),
                               ("scope", "full_control")):
                with self.subTest(key=key, value=value):
                    changed = pilot | {key: value}
                    path.write_text(json.dumps({"runtimeInstalled": True, "diagnosticPilot": changed}), encoding="utf-8")
                    bound = direct | {"pilotEvidenceSha256NormalizedLf": normalized_hash(path)}
                    self.assertTrue(validate_diagnostic_pilot(root, bound))
            self.assertTrue(validate_diagnostic_pilot(root, direct))

    def test_current_runtime_banners_agree_with_frozen_installation(self) -> None:
        self.assertEqual(validate_runtime_banners(ROOT, self.registry), [])

    def test_readonly_video_receipt_requires_exact_updated_apk_and_keeps_input_unaccepted(self) -> None:
        device = "753fd530-2f19-4e5e-98ba-769863678141"
        pilot = dict(enabled=True, scope="readonly_video_v1", deviceIds=[device],
                     readOnlyVideoInstalled=True, directInputInstalled=False,
                     mediaControlInstalled=False, videoAccepted=False)
        apk = dict(versionCode=10251, sha256="a" * 64, installedPackageSha256="a" * 64)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "pilot.json"

            def bound(picture=pilot, package=apk):
                path.write_text(json.dumps(dict(runtimeInstalled=True, diagnosticPilot=picture, apk=package)), encoding="utf-8")
                return dict(pilotEvidence=path.name, pilotEvidenceSha256NormalizedLf=normalized_hash(path),
                            pilotCurrentlyEnabled=True, pilotDeviceIds=[device])

            self.assertEqual(validate_readonly_video_pilot(root, bound()), [])
            for key, value in (("deviceIds", [device, device]), ("scope", "diagnostic_echo_only"),
                               ("directInputInstalled", True), ("mediaControlInstalled", True),
                               ("readOnlyVideoInstalled", False), ("videoAccepted", True)):
                with self.subTest(key=key):
                    self.assertTrue(validate_readonly_video_pilot(root, bound(pilot | {key: value})))
            for key, value in (("versionCode", 10250), ("versionCode", True), ("sha256", "wrong"),
                               ("installedPackageSha256", "b" * 64)):
                with self.subTest(key=key):
                    self.assertTrue(validate_readonly_video_pilot(root, bound(package=apk | {key: value})))
            direct = bound()
            path.write_text("{}", encoding="utf-8")
            self.assertTrue(validate_readonly_video_pilot(root, direct))

    def test_primary_video_requires_every_installed_hash_and_keeps_locality_and_latency_unaccepted(self) -> None:
        devices = ["414ce0e9-4b93-4f96-b9ca-ee675f53835e", "753fd530-2f19-4e5e-98ba-769863678141"]
        pilot = dict(enabled=True, scope="primary_video_v1", deviceIds=devices, primaryVideoInstalled=True,
                     directInputInstalled=False, mediaControlInstalled=False, productionAccepted=False)
        apk = dict(versionCode=10252, sha256="a" * 64, installedDevices=[
            dict(deviceId=d, versionCode=10252, installedPackageSha256="a" * 64) for d in devices])
        observation = dict(deviceId=devices[0], framesPresented=1804, transport="direct_webrtc",
                           controlTransport="server_websocket", localhostRouteProven=False, latencySlaAccepted=False)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "primary.json"

            def bound(picture=pilot, package=apk, sample=observation):
                path.write_text(json.dumps(dict(runtimeInstalled=True, diagnosticPilot=picture, apk=package,
                                               browser=dict(primaryObservation=sample))), encoding="utf-8")
                return dict(pilotEvidence=path.name, pilotEvidenceSha256NormalizedLf=normalized_hash(path),
                            pilotCurrentlyEnabled=True, pilotDeviceIds=devices, primaryVideoObserved=True)

            self.assertEqual(validate_primary_video_pilot(root, bound()), [])
            for key, value in (("deviceIds", []), ("deviceIds", devices * 2), ("deviceIds", [1]),
                               ("scope", "full_control"), ("directInputInstalled", True),
                               ("mediaControlInstalled", True), ("productionAccepted", True)):
                with self.subTest(key=key):
                    self.assertTrue(validate_primary_video_pilot(root, bound(pilot | {key: value})))
            for package in [apk | {"versionCode": True}, apk | {"versionCode": 10251},
                            apk | {"sha256": "wrong"}, apk | {"installedDevices": apk["installedDevices"][:1]},
                            apk | {"installedDevices": [apk["installedDevices"][0]] * 2},
                            apk | {"installedDevices": [None, None]},
                            apk | {"installedDevices": [apk["installedDevices"][0] | {"installedPackageSha256": "b" * 64},
                                                       apk["installedDevices"][1]]}]:
                with self.subTest(package=package):
                    self.assertTrue(validate_primary_video_pilot(root, bound(package=package)))
            for key, value in (("framesPresented", 0), ("framesPresented", True), ("deviceId", "ungranted"),
                               ("transport", "server_websocket"), ("controlTransport", "direct_webrtc"),
                               ("localhostRouteProven", True), ("latencySlaAccepted", True)):
                with self.subTest(key=key):
                    self.assertTrue(validate_primary_video_pilot(root, bound(sample=observation | {key: value})))
            direct = bound()
            path.write_text("{}", encoding="utf-8")
            self.assertTrue(validate_primary_video_pilot(root, direct))

    def test_direct_media_installation_requires_updated_hashes_without_accepting_input_execution(self) -> None:
        device = "414ce0e9-4b93-4f96-b9ca-ee675f53835e"
        pilot = dict(enabled=True, scope="primary_video_and_input_v1", deviceIds=[device],
                     primaryVideoInstalled=True, directInputInstalled=True, mediaControlInstalled=True,
                     directInputAccepted=False, productionAccepted=False)
        apk = dict(versionCode=10255, sha256="a" * 64, installedDevices=[
            dict(deviceId=device, versionCode=10255, installedPackageSha256="a" * 64)])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "direct.json"

            def bound(picture=pilot, package=apk):
                path.write_text(json.dumps(dict(runtimeInstalled=True, diagnosticPilot=picture, apk=package)), encoding="utf-8")
                return dict(pilotEvidence=path.name, pilotEvidenceSha256NormalizedLf=normalized_hash(path),
                            pilotCurrentlyEnabled=True, pilotDeviceIds=[device], primaryVideoObserved=False)

            self.assertEqual(validate_primary_video_pilot(root, bound(), with_direct_input=True), [])
            for key, value in (("directInputAccepted", True), ("productionAccepted", True),
                               ("directInputInstalled", False), ("mediaControlInstalled", False),
                               ("scope", "primary_video_v1")):
                with self.subTest(key=key):
                    self.assertTrue(validate_primary_video_pilot(root, bound(picture=pilot | {key: value}), with_direct_input=True))
            for package in (apk | {"versionCode": 10254}, apk | {"installedDevices": []},
                            apk | {"installedDevices": [apk["installedDevices"][0] | {"installedPackageSha256": "b" * 64}]}):
                with self.subTest(package=package):
                    self.assertTrue(validate_primary_video_pilot(root, bound(package=package), with_direct_input=True))

    def test_direct_media_registry_keeps_execution_and_production_unaccepted(self) -> None:
        base = dict(state="DIRECT_MEDIA_PILOT_INSTALLED", implementationAuthorizedNow=True,
                    prototypeScope="primary_video_and_input_v1", runtimeInstalled=True, primaryVideoInstalled=True,
                    readOnlyVideoInstalled=True, primaryVideoObserved=False, directInputInstalled=True,
                    mediaControlInstalled=True, directInputAccepted=False, productionAccepted=False)
        for key, value in (("directInputAccepted", True), ("mediaControlInstalled", False),
                           ("productionAccepted", True), ("implementationAuthorizedNow", False)):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.registry)
                changed["directMedia"].update(base | {key: value})
                self.assertIn("Direct media installation cannot imply direct input or production acceptance",
                              validate_registry(ROOT, changed))

    def test_primary_registry_cannot_claim_direct_input_or_production_from_video_installation(self) -> None:
        base = dict(state="PRIMARY_VIDEO_PILOT_INSTALLED", implementationAuthorizedNow=True,
                    prototypeScope="primary_video_v1", runtimeInstalled=True, primaryVideoInstalled=True,
                    readOnlyVideoInstalled=True, primaryVideoObserved=True, directInputInstalled=False,
                    mediaControlInstalled=False, productionAccepted=False)
        for key, value in (("directInputInstalled", True), ("mediaControlInstalled", True),
                           ("productionAccepted", True), ("primaryVideoObserved", 1),
                           ("primaryVideoInstalled", False), ("implementationAuthorizedNow", False)):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.registry)
                changed["directMedia"].update(base | {key: value})
                self.assertIn("Primary video pilot cannot imply direct input or production acceptance",
                              validate_registry(ROOT, changed))

    def test_old_api_banner_fails_while_historical_revisions_remain_valid(self) -> None:
        banner = installed_runtime_banner(self.registry["installed"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = [*self.registry["authoritativeEntrypoints"], "docs/operations/WORK-STATUS.md", *RUNTIME_GUIDES]
            for file in files:
                path = root / file
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"# Guide\n\n{banner}\n\nHistorical API be803773 / UI 0b321d49.\n", encoding="utf-8")
            self.assertEqual(validate_runtime_banners(root, self.registry), [])
            path = root / "docs/operations/SCRIPT-STUDIO.md"
            path.write_text(path.read_text(encoding="utf-8").replace(
                self.registry["installed"]["api"][:8], "be803773"), encoding="utf-8")
            self.assertEqual(validate_runtime_banners(root, self.registry),
                             ["docs/operations/SCRIPT-STUDIO.md: current runtime banner is stale, malformed or buried"])

    def test_banner_cannot_be_missing_duplicated_or_hidden_after_history(self) -> None:
        registry = {"authoritativeEntrypoints": [], "installed": self.registry["installed"]}
        banner = installed_runtime_banner(registry["installed"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = ["docs/operations/WORK-STATUS.md", *RUNTIME_GUIDES]
            for file in files:
                path = root / file
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(banner + "\r\n", encoding="utf-8")
            self.assertEqual(validate_runtime_banners(root, registry), [])
            target = root / files[0]
            for text, expected in (("# Without banner\n", "requires one"),
                                   (banner + "\n" + banner, "requires one"),
                                   ("\n" * 40 + banner, "stale, malformed or buried")):
                with self.subTest(text=text):
                    target.write_text(text, encoding="utf-8")
                    errors = validate_runtime_banners(root, registry)
                    self.assertEqual(len(errors), 1)
                    self.assertIn(expected, errors[0])

    def test_cannot_close_an_item_by_changing_only_its_state(self) -> None:
        self.registry["items"][17]["state"] = "ACCEPTED_RECORDED_SCOPE"
        errors = validate_registry(ROOT, self.registry)
        self.assertTrue(any("EP-018: accepted without" in error for error in errors))
        self.assertTrue(any("counts disagree" in error for error in errors))

    def test_duplicate_product_id_is_rejected(self) -> None:
        self.registry["items"][-1]["id"] = "EP-001"
        self.assertTrue(any("unique baseline IDs" in e for e in validate_registry(ROOT, self.registry)))

    def test_unrelated_valid_receipt_cannot_close_a_new_item(self) -> None:
        item = self.registry["items"][17]
        accepted = self.registry["items"][0]
        item["state"], item["progress"] = "ACCEPTED_RECORDED_SCOPE", "ACCEPTED_FINITE"
        item["acceptanceEvidence"] = accepted["acceptanceEvidence"]
        item["acceptanceEvidenceSha256NormalizedLf"] = accepted["acceptanceEvidenceSha256NormalizedLf"]
        self.registry["counts"]["acceptedRecordedScope"] += 1
        self.registry["counts"]["open"] -= 1
        self.assertIn("EP-018: receipt does not admit this item in its recorded batch", validate_registry(ROOT, self.registry))

    def test_cannot_silently_remove_acceptance_criteria(self) -> None:
        self.registry["items"][0]["acceptanceCriteria"].pop()
        self.assertIn("EP-001: changed baseline acceptanceCriteria", validate_registry(ROOT, self.registry))

    def test_frozen_receipt_fingerprint_change_is_rejected(self) -> None:
        self.registry["items"][0]["acceptanceEvidenceSha256NormalizedLf"] = "0" * 64
        self.assertIn("EP-001: frozen closure receipt fingerprint mismatch", validate_registry(ROOT, self.registry))

    def test_partial_canary_does_not_authorize_fleet_closure(self) -> None:
        self.registry["items"][17]["fleetAccepted"] = True
        self.assertIn("EP-018: fleet acceptance is not supported by this ledger", validate_registry(ROOT, self.registry))

    def test_source_fix_cannot_be_reported_installed(self) -> None:
        self.registry["pendingCorrections"].append({
            "id": "UNDELIVERED", "installed": True,
            "evidence": "docs/audits/2026-10-09/STUDIO-RECORDER-CLOCK-FIX.md",
        })
        self.assertTrue(any("incorrectly marked installed" in e for e in validate_registry(ROOT, self.registry)))

    def test_installed_correction_cannot_invent_delivery_or_runtime_acceptance(self) -> None:
        for key, value in (("deliveryEvidenceSha256NormalizedLf", "0" * 64),
                           ("id", "UNDELIVERED_CORRECTION"), ("runtimeAccepted", True),
                           ("installedRevision", "0" * 40)):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.registry)
                changed["installedCorrections"][0][key] = value
                self.assertTrue(any("Installed correction" in error for error in validate_registry(ROOT, changed)))

    def test_completed_correction_fingerprint_is_required(self) -> None:
        self.registry["completedCorrections"][0]["evidenceSha256NormalizedLf"] = "0" * 64
        self.assertIn("Completed correction receipt missing or fingerprint mismatch", validate_registry(ROOT, self.registry))

    def test_unrelated_receipt_cannot_admit_a_completed_correction(self) -> None:
        correction = self.registry["completedCorrections"][0]
        correction["evidence"] = self.registry["items"][0]["acceptanceEvidence"]
        correction["evidenceSha256NormalizedLf"] = normalized_hash(ROOT / correction["evidence"])
        self.assertIn("Completed correction does not match its installed finite receipt", validate_registry(ROOT, self.registry))

    def test_current_installed_ui_cannot_drift_from_referenced_receipt(self) -> None:
        self.registry["installed"]["ui"] = "0" * 40
        self.assertIn("Installed UI does not match referenced observation receipt", validate_registry(ROOT, self.registry))

    def test_current_installed_api_cannot_drift_from_referenced_receipt(self) -> None:
        self.registry["installed"]["api"] = "0" * 40
        self.assertIn("Installed API does not match referenced observation receipt", validate_registry(ROOT, self.registry))

    def test_current_installed_receipt_fingerprint_is_required(self) -> None:
        self.registry["installed"]["evidenceSha256NormalizedLf"] = "0" * 64
        self.assertIn("Installed observation receipt fingerprint mismatch", validate_registry(ROOT, self.registry))

    def test_pilot_apk_cannot_be_promoted_from_a_built_file_or_reported_version_alone(self) -> None:
        for key, value in (("versionCode", 10300), ("versionCode", True), ("apkSha256", "0" * 64),
                           ("sourceRevision", "0" * 40), ("version", "1.3.0")):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.registry["installed"])
                changed["pilotApk"][key] = value
                self.assertIn("Pilot APK version/source/hash does not match installed package evidence",
                              validate_current_apks(ROOT, changed))

    def test_current_fleet_cannot_reuse_a_larger_historical_delivery_count(self) -> None:
        changed = copy.deepcopy(self.registry["installed"])
        changed["fleetApkEvidence"]["installedCount"] += 1
        self.assertIn("Current APK fleet count does not match unique installed packages",
                      validate_current_apks(ROOT, changed))

    def test_current_apk_evidence_is_frozen_separately_from_runtime_identity(self) -> None:
        changed = copy.deepcopy(self.registry["installed"])
        changed["pilotApk"]["evidenceSha256NormalizedLf"] = "0" * 64
        self.assertIn("Pilot APK receipt missing or fingerprint mismatch", validate_current_apks(ROOT, changed))

    def test_every_current_fleet_row_requires_the_exact_catalog_package(self) -> None:
        fleet = self.registry["installed"]["fleetApkEvidence"]
        original = read_json(ROOT, fleet["evidence"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "fleet.json"
            for field, value in (("installedPackageSha256", "0" * 64), ("versionCode", True),
                                  ("versionCode", 10300)):
                with self.subTest(field=field):
                    receipt = copy.deepcopy(original)
                    receipt["apk"]["installedDevices"][-1][field] = value
                    path.write_text(json.dumps(receipt), encoding="utf-8")
                    binding = fleet | {"evidence": path.name,
                                       "evidenceSha256NormalizedLf": normalized_hash(path)}
                    self.assertIn("Current APK fleet includes an unverified installed package",
                                  validate_current_apks(root, {"fleetApkEvidence": binding}))

    def test_historical_primary_frames_cannot_be_promoted_to_a_current_direct_route(self) -> None:
        self.registry["directMedia"]["primaryVideoObserved"] = True
        self.assertIn("Historical primary frames cannot prove the current direct-video route",
                      validate_registry(ROOT, self.registry))

    def test_current_installed_receipt_must_exist(self) -> None:
        self.registry["installed"]["evidence"] = "missing-install-receipt.json"
        self.assertIn("Installed observation receipt is missing", validate_registry(ROOT, self.registry))

    def test_current_source_identity_does_not_prove_installation_or_acceptance(self) -> None:
        installed = copy.deepcopy(self.registry["installed"])
        original = read_json(ROOT, installed["evidence"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installed["evidence"] = "receipt.json"
            for field in ("runtimeInstalled", "finiteAccepted"):
                with self.subTest(field=field):
                    receipt = copy.deepcopy(original)
                    target = receipt if field == "runtimeInstalled" else receipt["browser"]
                    target[field] = False
                    path = root / installed["evidence"]
                    path.write_text(json.dumps(receipt), encoding="utf-8")
                    installed["evidenceSha256NormalizedLf"] = normalized_hash(path)
                    self.assertIn("Installed observation lacks installed finite acceptance",
                                  validate_installed_receipt(root, installed))

    def test_malformed_current_installed_receipt_reports_an_error(self) -> None:
        installed = copy.deepcopy(self.registry["installed"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installed["evidence"] = "receipt.json"
            path = root / installed["evidence"]
            for text in ("{", "[]"):
                with self.subTest(text=text):
                    path.write_text(text, encoding="utf-8")
                    installed["evidenceSha256NormalizedLf"] = normalized_hash(path)
                    self.assertEqual(validate_installed_receipt(root, installed),
                                     ["Installed observation receipt is not valid JSON"])

    def test_legacy_duplicate_does_not_inflate_count(self) -> None:
        self.registry["legacy"]["open"].append("F32")
        self.assertIn("Legacy counts/membership disagree", validate_registry(ROOT, self.registry))

    def test_unmapped_chat_requirement_is_rejected(self) -> None:
        self.registry["chatRequirements"][0]["productItems"] = ["EP-999"]
        self.assertTrue(any("CHAT-01: invalid mapping" in e for e in validate_registry(ROOT, self.registry)))

    def test_omitted_document_is_detected(self) -> None:
        inventory = copy.deepcopy(read_json(ROOT, INVENTORY))
        inventory["documents"].pop()
        self.assertTrue(any("inventory is incomplete" in e for e in validate_inventory(ROOT, self.registry, inventory)))

    def test_link_paths_skip_examples_and_check_encoded_balanced_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "docs" / "has space.md").write_text("ok", encoding="utf-8")
            (root / "docs" / "(contract).md").write_text("ok", encoding="utf-8")
            (root / "docs" / "guide.md").write_text(
                "[space](has%20space.md) [brackets]((contract).md)\n"
                "```md\n[example](absent.md)\n```\n[bad](missing.md)\n",
                encoding="utf-8",
            )
            self.assertEqual(local_link_errors(root, "docs/guide.md"), ["docs/guide.md: missing local link: missing.md"])

    def test_receipt_hash_is_portable_between_windows_and_linux(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "lf.json", root / "crlf.json"
            first.write_bytes(b'{\n  "accepted": true\n}\n')
            second.write_bytes(first.read_bytes().replace(b"\n", b"\r\n"))
            self.assertEqual(normalized_hash(first), normalized_hash(second))

    def test_human_status_table_cannot_drift_from_registry(self) -> None:
        text = (ROOT / "docs/operations/WORK-STATUS.md").read_text(encoding="utf-8")
        self.assertEqual(validate_status_report(self.registry, text), [])
        wrong = text.replace("| EP-018 | P1 | L | OPEN / PARTIAL |", "| EP-018 | P1 | L | ACCEPTED_RECORDED_SCOPE / ACCEPTED_FINITE |")
        self.assertIn("WORK-STATUS product table disagrees with machine registry", validate_status_report(self.registry, wrong))

    def test_human_chat_scope_cannot_report_trajectory_accepted(self) -> None:
        text = (ROOT / "docs/operations/WORK-STATUS.md").read_text(encoding="utf-8")
        wrong = text.replace("### CHAT-06 · Запись непрерывной траектории жеста\n\n**OPEN**", "### CHAT-06 · Запись непрерывной траектории жеста\n\n**ACCEPTED_FINITE**")
        self.assertIn("CHAT-06: WORK-STATUS requirement state missing or stale", validate_status_report(self.registry, wrong))


if __name__ == "__main__":
    unittest.main()
