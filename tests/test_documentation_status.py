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
    validate_installed_receipt,
    validate_inventory,
    validate_registry,
    validate_runtime_banners,
    validate_status_report,
)


class DocumentationStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = copy.deepcopy(read_json(ROOT, REGISTRY))

    def test_recorded_status_is_consistent(self) -> None:
        self.assertEqual(validate_registry(ROOT, self.registry), [])

    def test_current_runtime_banners_agree_with_frozen_installation(self) -> None:
        self.assertEqual(validate_runtime_banners(ROOT, self.registry), [])

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
