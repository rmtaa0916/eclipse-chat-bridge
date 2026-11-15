"""Offline regression tests for bridge saved-result pagination.

Run with: python3 -B -m unittest -v test_result_reader.py
No Termux, network, Google Docs, or provider sessions are required.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

import result_reader as reader
from latest_response_slot import _bound_slot_result


class ReadResultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)
        self.results = self.state / "results"
        self.results.mkdir()
        self.target_id = "first_script_20261115"
        self.current_id = "context_read_20261115"
        self.marker = b"ROOT_CAUSE_AT_MIDDLE"

    def store(self, output: bytes, *, status="completed", action="run",
              raw_path=None, filename=None):
        target = filename or self.target_id
        (self.results / (target + ".raw")).write_bytes(output)
        (self.results / (target + ".json")).write_text(
            json.dumps({
                "status": status, "action": action,
                "result": {
                    "exit_code": 1,
                    "full_output_file": raw_path or str(self.results / (target + ".raw")),
                },
            }), encoding="utf-8",
        )
        (self.state / "requests.json").write_text(
            json.dumps({target: {"status": status, "sha256": "a"*64}}),
            encoding="utf-8",
        )

    def retrieve(self, **kwargs):
        return reader.read_result(
            self.results,
            request_id=self.current_id, source_id=self.target_id,
            **kwargs,
        )

    def test_recovers_middle_from_twenty_thousand_byte_log(self):
        raw = b"A"*10000 + self.marker + b"B"*10000
        self.store(raw)
        found = self.retrieve(offset=9990, max_bytes=150)
        self.assertIn("ROOT_CAUSE_AT_MIDDLE", found["content"])
        self.assertEqual(found["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(found["total_bytes"], len(raw))
        self.assertGreater(found["next_offset"], found["offset"])
        self.assertFalse(found["eof"])

    def test_gdocs_slot_650_preserves_mid_log_evidence(self):
        raw = b"start\n" + b"X"*9000 + self.marker + b"Y"*9000
        self.store(raw)
        found = self.retrieve(offset=9000, max_bytes=180)
        self.assertIn("ROOT_CAUSE_AT_MIDDLE", found["content"])
        response = {"status": "completed", "action": "read_result", "result": found}
        bounded = _bound_slot_result(response, max_len=650)
        self.assertIn("ROOT_CAUSE_AT_MIDDLE", json.dumps(bounded))
        wrapped = {"id": self.current_id, "result": response}
        self.assertLessEqual(len(json.dumps(wrapped, ensure_ascii=False, indent=2)), 620)

    def test_cursor_paginates_without_missing_bytes(self):
        raw = b"ABCDEF"*90
        self.store(raw)
        pos, collected, digest = 0, bytearray(), None
        for _ in range(40):
            packet = self.retrieve(offset=pos, max_bytes=70)
            self.assertEqual(packet["offset"], pos)
            self.assertLessEqual(packet["next_offset"] - pos, 70)
            self.assertGreaterEqual(packet["next_offset"], pos)
            digest = packet["sha256"]
            collected.extend(packet["content"].encode("utf-8"))
            pos = packet["next_offset"]
            if packet["eof"]:
                break
        self.assertEqual(bytes(collected), raw)
        self.assertEqual(digest, hashlib.sha256(raw).hexdigest())

    def test_empty_result_is_valid(self):
        self.store(b"")
        packet = self.retrieve()
        self.assertEqual(packet["content"], "")
        self.assertEqual(packet["total_bytes"], 0)
        self.assertEqual(packet["next_offset"], 0)
        self.assertTrue(packet["eof"])

    def test_escaped_newlines_fit_local_slot(self):
        self.store((b"line\n"*1000))
        packet = self.retrieve(offset=0, max_bytes=1024)
        wrapper = {
            "id": self.current_id,
            "result": {"status": "completed", "action": "read_result", "result": packet},
        }
        self.assertLessEqual(
            len(json.dumps(wrapper, ensure_ascii=False, indent=2)), 620
        )
        self.assertTrue(packet["content"])
        self.assertLessEqual(packet["next_offset"], 1024)

    def test_invalid_ids_and_offsets_rejected(self):
        self.store(b"data")
        for source in ("../secrets", "/etc/passwd", "", "tiny", "a/"*15):
            with self.subTest(source=source), self.assertRaises(reader.ResultReadError):
                reader.read_result(
                    self.results, request_id=self.current_id, source_id=source
                )
        for val in (-1, 4.0, True, "4", 1_048_577):
            with self.subTest(offset=val), self.assertRaises(reader.ResultReadError):
                self.retrieve(offset=val)
        with self.assertRaises(reader.ResultReadError):
            self.retrieve(offset=5)
        for value in (0, 1025, True, 1.2):
            with self.subTest(max_bytes=value), self.assertRaises(reader.ResultReadError):
                self.retrieve(max_bytes=value)

    def test_refuses_pending_or_error_runs(self):
        self.store(b"data", status="running")
        with self.assertRaisesRegex(reader.ResultReadError, "RESULT_NOT_COMPLETED"):
            self.retrieve()
        self.store(b"data", status="error")
        with self.assertRaisesRegex(reader.ResultReadError, "RESULT_NOT_COMPLETED"):
            self.retrieve()
        self.store(b"data", action="read_file")
        with self.assertRaisesRegex(reader.ResultReadError, "RESULT_NOT_A_COMPLETED_RUN"):
            self.retrieve()

    def test_refuses_mismatched_raw_path(self):
        self.store(b"data", raw_path="/tmp/other-run-output.raw")
        with self.assertRaisesRegex(reader.ResultReadError, "RESULT_PATH_MISMATCH"):
            self.retrieve()

    def test_refuses_symlinks_and_multiple_hardlinks(self):
        self.store(b"data")
        raw = self.results / (self.target_id + ".raw")
        raw.unlink()
        raw.symlink_to(self.results / "other.raw")
        with self.assertRaises(OSError):
            self.retrieve()
        raw.unlink()
        raw.write_bytes(b"data")
        os.link(raw, self.results / "duplicate.raw")
        with self.assertRaisesRegex(reader.ResultReadError, "UNSAFE_RESULT_FILE"):
            self.retrieve()

    def test_refuses_symlink_receipt_and_symlink_state(self):
        self.store(b"data")
        receipt = self.results / (self.target_id + ".json")
        backup = self.results / "other.json"
        receipt.replace(backup)
        receipt.symlink_to(backup)
        with self.assertRaises(OSError):
            self.retrieve()
        receipt.unlink()
        backup.replace(receipt)
        statefile = self.state / "requests.json"
        moved = self.state / "other-state.json"
        statefile.replace(moved)
        statefile.symlink_to(moved)
        with self.assertRaises(OSError):
            self.retrieve()

    def test_limits_oversize_raw_and_metadata(self):
        self.store(b"A" * 1_048_577)
        with self.assertRaisesRegex(reader.ResultReadError, "RESULT_FILE_TOO_LARGE"):
            self.retrieve()
        self.store(b"data")
        (self.results / (self.target_id + ".json")).write_bytes(b"Z" * 8_000_001)
        with self.assertRaisesRegex(reader.ResultReadError, "RESULT_FILE_TOO_LARGE"):
            self.retrieve()

    def test_find_result_recovers_middle_without_known_offset(self):
        raw = b"A"*12000 + self.marker + b"B"*12000
        self.store(raw)
        found = reader.find_result(
            self.results, request_id=self.current_id, source_id=self.target_id,
            query="root_cause_at_middle",
        )
        self.assertTrue(found["found"])
        self.assertEqual(found["match_offset"], 12000)
        self.assertIn("ROOT_CAUSE_AT_MIDDLE", found["content"])
        self.assertEqual(found["sha256"], hashlib.sha256(raw).hexdigest())
        result = {"status": "completed", "action": "find_result", "result": found}
        self.assertIn("ROOT_CAUSE_AT_MIDDLE",
                      json.dumps(_bound_slot_result(result, max_len=650)))
        self.assertLessEqual(
            len(json.dumps({"id": self.current_id, "result": result},
                           ensure_ascii=False, indent=2)), 620
        )

    def test_find_result_repeated_matches_and_no_match(self):
        self.store(b"ERROR one\nnormal\nERROR two\nnormal")
        first = reader.find_result(
            self.results, request_id=self.current_id, source_id=self.target_id,
            query="error",
        )
        self.assertEqual(first["match_offset"], 0)
        second = reader.find_result(
            self.results, request_id=self.current_id, source_id=self.target_id,
            query="ERROR", start_offset=first["next_search_offset"],
        )
        self.assertEqual(second["match_offset"], 17)
        absent = reader.find_result(
            self.results, request_id=self.current_id, source_id=self.target_id,
            query="ERROR", start_offset=second["next_search_offset"],
        )
        self.assertFalse(absent["found"])
        self.assertEqual(absent["total_bytes"], len(b"ERROR one\nnormal\nERROR two\nnormal"))

    def test_find_result_treats_query_as_literal_not_regex(self):
        self.store(b"error=123\nmore logs")
        absent = reader.find_result(
            self.results, request_id=self.current_id, source_id=self.target_id,
            query=".*",
        )
        self.assertFalse(absent["found"])
        for query in ("", "x", "\nerror", "a"*65, "🦊", None):
            with self.subTest(query=query), self.assertRaises(reader.ResultReadError):
                reader.find_result(
                    self.results, request_id=self.current_id,
                    source_id=self.target_id, query=query,
                )

    def test_find_result_enforces_source_receipt_rules(self):
        self.store(b"SECRET_CODE")
        metadata = self.results / (self.target_id + ".json")
        meta = json.loads(metadata.read_text())
        meta["action"] = "read_file"
        metadata.write_text(json.dumps(meta))
        with self.assertRaisesRegex(reader.ResultReadError, "RESULT_NOT_A_COMPLETED_RUN"):
            reader.find_result(
                self.results, request_id=self.current_id,
                source_id=self.target_id, query="SECRET",
            )

    def test_no_writes_to_source_tree(self):
        self.store(b"a"*2000)
        before = sorted((str(p), p.read_bytes()) for p in self.state.rglob("*") if p.is_file())
        for i in range(3):
            self.retrieve(offset=i*50, max_bytes=130)
        after = sorted((str(p), p.read_bytes()) for p in self.state.rglob("*") if p.is_file())
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
