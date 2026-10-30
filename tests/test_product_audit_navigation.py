import unittest

from scripts.audit.validate_product_audit import _DATED_NAVIGATION_NOTE, frozen_audit_body


class ProductAuditNavigationTests(unittest.TestCase):
    def test_original_audit_without_note_is_unchanged(self):
        original = "# Frozen audit\n\nEvidence line\n> Original quoted evidence\n"
        self.assertEqual(frozen_audit_body(original), original)

    def test_exact_dated_navigation_preserves_all_evidence_lines(self):
        original = "# Frozen audit\n\nEvidence line\n> Original quoted evidence\n"
        annotated = "# Frozen audit\n\n" + "\n".join(_DATED_NAVIGATION_NOTE) + "\n" + original.split("\n\n", 1)[1]
        self.assertEqual(frozen_audit_body(annotated), original)
        changed = annotated.replace("Evidence line", "Changed evidence line\nExtra evidence")
        self.assertIn("Changed evidence line\nExtra evidence", frozen_audit_body(changed))

    def test_unknown_or_displaced_note_cannot_hide_added_lines(self):
        note = "\n".join(_DATED_NAVIGATION_NOTE)
        for document in ("# Frozen audit\n\n" + note.replace("baseline5", "baseline6") + "\nEvidence\n",
                         "# Frozen audit\n\nEvidence\n" + note + "\n"):
            with self.subTest(document=document):
                self.assertEqual(frozen_audit_body(document), document)
