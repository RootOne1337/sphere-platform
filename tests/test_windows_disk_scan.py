import json
import tempfile
import unittest
from pathlib import Path

from scripts.pilot import windows_disk_scan as scan


class WindowsDiskReportTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def test_truncated_ready_tool_export_cannot_be_reported_as_complete(self):
        file = self.base / "scan.csv"
        file.write_text(
            "Name,Logical Size,Physical Size,WinDirStat Attributes\n"
            'C:\\,100,120,0x30000002\n"unfinished',
            encoding="utf-8",
        )
        result = scan.summarize(file, producer_complete=True)
        self.assertFalse(result["completeExport"])
        self.assertEqual(result["malformedRows"], 1)
        self.assertEqual(result["rowsRead"], 1)

    def test_russian_export_is_parsed_but_inaccessible_space_is_unknown(self):
        file = self.base / "scan.csv"
        file.write_text(
            "Имя,Логический размер,Физический размер,WinDirStat Атрибуты\n"
            "C:\\,100,120,0x30000002\nC:\\file,10,16,0x20000008\n",
            encoding="utf-8",
        )
        result = scan.summarize(file, producer_complete=False)
        self.assertFalse(result["completeExport"])
        self.assertEqual(result["largestAccessibleFiles"][0]["physicalBytes"], 16)
        self.assertEqual(result["protectedInaccessibleSpace"], "UNKNOWN")
        self.assertTrue(result["hardlinksMayShareAllocation"])

    def test_retention_never_deletes_an_unmarked_foreign_directory(self):
        foreign = self.base / "personal"
        foreign.mkdir()
        file = foreign / "preserve.txt"
        file.write_text("data")
        with self.assertRaises(ValueError):
            scan.retain(self.base)
        self.assertTrue(file.exists())

    def test_retention_preserves_active_reports_and_bounds_completed_snapshots(self):
        for i in range(4):
            directory = self.base / str(i)
            directory.mkdir()
            (directory / "status.json").write_text(
                json.dumps({"producer": "sphere-windirstat-wrapper", "state": "exported"})
            )
            (directory / "summary.json").write_text("{}")
        scan.retain(self.base)
        self.assertEqual(len(list(self.base.iterdir())), 3)
        active = self.base / "active"
        active.mkdir()
        (active / "status.json").write_text(
            json.dumps({"producer": "sphere-windirstat-wrapper", "state": "running"})
        )
        with self.assertRaises(ValueError):
            scan.retain(self.base)
        self.assertTrue(active.exists())
