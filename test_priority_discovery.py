"""Offline tests for bounded metadata-first source discovery."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

import priority_discovery as priority
from test_context_snapshot import FakeReader


class PriorityDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="priority-discovery-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.addCleanup(lambda: os.close(self.fd))

    def scan(self, goal, reader=FakeReader):
        return priority.discover_screened(self.fd, goal, reader)

    def test_late_named_relevant_source_beats_overview_prefix(self):
        for idx in range(350):
            (self.root / f"module_{idx:03d}.py").write_text(
                f"def helper_{idx}(): return {idx}\n", encoding="utf-8"
            )
        (self.root / "zz_critical_bridge_reader.py").write_text(
            "def critical_bridge_reader(): return 'found'\n", encoding="utf-8"
        )
        result = self.scan("critical bridge reader")
        paths = [x["path"] for x in result["files"]]
        self.assertIn("zz_critical_bridge_reader.py", paths)
        self.assertLessEqual(len(paths), priority.MAX_SELECTED_FILES)
        self.assertEqual(result["selection"]["eligible_candidates"], 351)
        self.assertTrue(result["selection"]["incomplete"])
        self.assertLessEqual(result["selection"]["source_attempts"], priority.MAX_ATTEMPTED_FILES)
        self.assertEqual(result["selection"]["selection_mode"],
                         "PRIORITY_BEFORE_SOURCE_READ")

    def test_research_request_prefers_documents(self):
        for idx in range(35):
            (self.root / f"engine_{idx:03d}.py").write_text("def engine(): return 1\n")
        docs = self.root / "notes"
        docs.mkdir()
        for idx in range(22):
            (docs / f"research_protocol_{idx:03d}.md").write_text(
                "# Research protocol\nStudy design and clinical notes\n", encoding="utf-8"
            )
        result = self.scan("research protocol notes study design")
        selected = result["files"]
        documents = [x for x in selected if x["kind"] == "DOC"]
        self.assertTrue(result["selection"]["research_intent"])
        self.assertGreaterEqual(len(documents), 15)
        self.assertTrue(all(x["sha256"] and x["text"] for x in documents))

    def test_excludes_backup_symlink_hardlink_and_screened_secrets(self):
        (self.root / "normal.py").write_text("def safe(): return 1\n")
        backups = self.root / "backups"
        backups.mkdir()
        (backups / "critical_reader.py").write_text("def old(): return 0\n")
        (self.root / "critical_link.py").symlink_to(self.root / "normal.py")
        (self.root / "critical_hardlink.py").hardlink_to(self.root / "normal.py")
        (self.root / "critical_secret.py").write_text("FAKE_UNSCREENED_SECRET\n")
        result = self.scan("critical reader")
        paths = [x["path"] for x in result["files"]]
        self.assertNotIn("backups/critical_reader.py", paths)
        self.assertNotIn("critical_link.py", paths)
        self.assertNotIn("critical_hardlink.py", paths)
        self.assertNotIn("critical_secret.py", paths)

    def test_root_directory_ceiling_fails_closed(self):
        class TightReader(FakeReader):
            MAX_DIR_ENUMERATION_ENTRIES = 8
            MAX_ENTRIES_PER_DIR = 4
        for idx in range(25):
            (self.root / f"target_{idx:03d}.py").write_text("def sample(): pass\n")
        result = self.scan("target", reader=TightReader)
        self.assertEqual(result["files"], [])
        self.assertTrue(result["selection"]["entries_truncated"])
        self.assertTrue(result["selection"]["incomplete"])
        self.assertLessEqual(result["selection"]["raw_entries_enumerated"], 8)

    def test_relevant_nested_directory_is_prioritized(self):
        for idx in range(48):
            subdir = self.root / f"misc_{idx:03d}"
            subdir.mkdir()
            (subdir / "unrelated.py").write_text("def unrelated(): pass\n")
        relevant = self.root / "critical_engine"
        relevant.mkdir()
        (relevant / "handler.py").write_text("def critical_handler(): return 5\n")
        result = self.scan("critical engine handler")
        self.assertIn("critical_engine/handler.py",
                      [x["path"] for x in result["files"]])

    def test_no_source_file_modification(self):
        file = self.root / "notes.md"
        file.write_text("Research notes\n")
        before = file.read_bytes()
        self.scan("research notes")
        self.assertEqual(file.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
