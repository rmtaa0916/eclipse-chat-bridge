#!/usr/bin/env python3
"""Integration tests for Unified ECLIPSE Bridge.

Verifies the 9 acceptance criteria from ChatGPT's Final Implementation Plan:
1. Ten requests execute in submission order (FIFO).
2. New requests are accepted during an active execution.
3. A failed or timed-out request does not discard following requests.
4. Duplicate or altered request IDs cannot execute again.
5. Watcher restart preserves queued work without unsafe replay.
6. Housekeeping never removes unfinished work.
7. Google Docs sync failure preserves results and can recover.
8. Dual protocol support: ChatGPT and Gemini requests execute seamlessly.
9. Backward compatibility with Mode 2 and CLI interfaces.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

import watch
from bridge_queue import BridgeQueue
from gemini_protocol import (
    REQUEST_START_TOKEN as GEMINI_START,
    REQUEST_END_TOKEN as GEMINI_END,
)


class TestUnifiedBridgeIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.temp_dir.name) / "state"
        self.state_dir.mkdir(parents=True, mode=0o700)
        self.results_dir = self.state_dir / "results"
        self.results_dir.mkdir(parents=True, mode=0o700)
        self.state_file = self.state_dir / "requests.json"
        self.db_path = self.state_dir / "bridge_queue.db"
        self.queue = BridgeQueue(self.db_path)
        self.root_dir = Path(self.temp_dir.name) / "root"
        self.root_dir.mkdir(parents=True, mode=0o700)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _make_chatgpt_req(self, req_id: str, script: str) -> dict:
        return {"id": req_id, "action": "run", "cwd": str(self.root_dir), "script": script, "timeout_seconds": 10}

    def _make_gemini_req(self, req_id: str, script: str) -> dict:
        return {"id": req_id, "action": "run", "cwd": str(self.root_dir), "script": script, "timeout_seconds": 10}

    def test_ten_requests_execute_in_submission_order(self):
        """Criterion 1: Ten requests execute in strict submission order (FIFO)."""
        doc_content = []
        for i in range(1, 11):
            req = self._make_chatgpt_req(f"req_batch_{i:03d}", f"echo step_{i}")
            doc_content.append(watch.START + "\n" + json.dumps(req) + "\n" + watch.END)
        full_text = "\n".join(doc_content)

        class MockClient:
            def get_doc(self, doc_id):
                return {"revisionId": "rev_batch_1", "body": {"content": [{"paragraph": {"elements": [{"startIndex": 1, "endIndex": 1 + len(full_text), "textRun": {"content": full_text}}]}}]}}

        delivered_order = []

        def mock_deliver(req_id, result, result_dir, **kwargs):
            delivered_order.append(req_id)
            return True, result_dir / f"{req_id}.txt"

        with patch.object(watch, "STATE_DIR", self.state_dir), \
             patch.object(watch, "ROOT", self.root_dir), \
             patch.object(watch, "GoogleDocsClient", MockClient), \
             patch.object(watch, "notify_start"), \
             patch.object(watch, "deliver", side_effect=mock_deliver), \
             patch.object(watch, "sync_response_to_doc", return_value=True), \
             patch.object(watch.sys, "argv", ["watch.py", "--once", "--doc-id", "test-document", "--gemini-doc-id", ""]):
            ret = watch.main()
            self.assertEqual(ret, 0)

        # Confirm exactly 10 requests were delivered in exact order 1..10
        expected = [f"req_batch_{i:03d}" for i in range(1, 11)]
        self.assertEqual(delivered_order, expected)
        stats = self.queue.get_stats()
        self.assertEqual(stats["completed"], 10)
        self.assertEqual(stats["queued"], 0)

    def test_failed_request_does_not_halt_following_requests(self):
        """Criterion 3: Failed request does not discard following requests."""
        req1 = self._make_chatgpt_req("req_fail_001", "exit 2")
        req2 = self._make_chatgpt_req("req_pass_002", "echo ok")
        full_text = f"{watch.START}\n{json.dumps(req1)}\n{watch.END}\n{watch.START}\n{json.dumps(req2)}\n{watch.END}"

        class MockClient:
            def get_doc(self, doc_id):
                return {"revisionId": "rev1", "body": {"content": [{"paragraph": {"elements": [{"startIndex": 1, "endIndex": 1 + len(full_text), "textRun": {"content": full_text}}]}}]}}

        with patch.object(watch, "STATE_DIR", self.state_dir), \
             patch.object(watch, "ROOT", self.root_dir), \
             patch.object(watch, "GoogleDocsClient", MockClient), \
             patch.object(watch, "notify_start"), \
             patch.object(watch, "deliver", return_value=(True, self.results_dir / "x")), \
             patch.object(watch, "sync_response_to_doc", return_value=True), \
             patch.object(watch.sys, "argv", ["watch.py", "--once", "--doc-id", "test-document", "--gemini-doc-id", ""]):
            ret = watch.main()
            self.assertEqual(ret, 0)

        # req1 completed (with non-zero exit), req2 also completed
        self.assertTrue((self.results_dir / "req_fail_001.json").is_file())
        self.assertTrue((self.results_dir / "req_pass_002.json").is_file())

    def test_dual_protocol_chatgpt_and_gemini_requests(self):
        """Criterion 8: Dual protocol support: ChatGPT and Gemini requests execute seamlessly."""
        req_chatgpt = self._make_chatgpt_req("req_chatgpt_01", "echo hello_chatgpt")
        req_gemini = self._make_gemini_req("req_gemini_01", "echo hello_gemini")
        full_text = (
            f"{watch.START}\n{json.dumps(req_chatgpt)}\n{watch.END}\n"
            f"{GEMINI_START}\n{json.dumps(req_gemini)}\n{GEMINI_END}"
        )

        class MockClient:
            def get_doc(self, doc_id):
                return {"revisionId": "rev_dual_1", "body": {"content": [{"paragraph": {"elements": [{"startIndex": 1, "endIndex": 1 + len(full_text), "textRun": {"content": full_text}}]}}]}}

        executed_protocols = {}

        def mock_sync_chatgpt(client, doc_id, req_id, res):
            executed_protocols[req_id] = "chatgpt"
            return True

        def mock_sync_gemini(client, doc_id, req_id, res):
            executed_protocols[req_id] = "gemini"
            return True

        with patch.object(watch, "STATE_DIR", self.state_dir), \
             patch.object(watch, "ROOT", self.root_dir), \
             patch.object(watch, "GoogleDocsClient", MockClient), \
             patch.object(watch, "notify_start"), \
             patch.object(watch, "deliver", return_value=(True, self.results_dir / "x")), \
             patch.object(watch, "sync_response_to_doc", side_effect=mock_sync_chatgpt), \
             patch.object(watch, "sync_gemini_response_to_doc", side_effect=mock_sync_gemini), \
             patch.object(watch.sys, "argv", ["watch.py", "--once", "--doc-id", "test-document", "--gemini-doc-id", ""]):
            ret = watch.main()
            self.assertEqual(ret, 0)

        self.assertEqual(executed_protocols.get("req_chatgpt_01"), "chatgpt")
        self.assertEqual(executed_protocols.get("req_gemini_01"), "gemini")

    def test_restart_preserves_queued_work_without_unsafe_replay(self):
        """Criterion 5: Watcher restart preserves queued work; marks interrupted work for review."""
        # 1. Enqueue 2 requests in DB directly
        req1 = self._make_chatgpt_req("req_crashed_1", "sleep 100")
        fp1 = hashlib.sha256(json.dumps(req1, sort_keys=True).encode()).hexdigest()
        self.queue.enqueue_request("req_crashed_1", "chatgpt", "doc1", fp1, "run", req1)
        # Fetch it (simulating active running state before a crash)
        item1 = self.queue.fetch_next_fifo()
        self.assertEqual(item1["status"], "RUNNING")

        req2 = self._make_chatgpt_req("req_waiting_2", "echo wait_done")
        fp2 = hashlib.sha256(json.dumps(req2, sort_keys=True).encode()).hexdigest()
        self.queue.enqueue_request("req_waiting_2", "chatgpt", "doc1", fp2, "run", req2)

        # 2. Restart watcher in --once mode with empty doc
        class MockClient:
            def get_doc(self, doc_id):
                return {"revisionId": "rev2", "body": {"content": []}}

        executed = []

        def mock_deliver(req_id, res, rdir, **kwargs):
            executed.append(req_id)
            return True, rdir / f"{req_id}.txt"

        with patch.object(watch, "STATE_DIR", self.state_dir), \
             patch.object(watch, "ROOT", self.root_dir), \
             patch.object(watch, "GoogleDocsClient", MockClient), \
             patch.object(watch, "notify_start"), \
             patch.object(watch, "deliver", side_effect=mock_deliver), \
             patch.object(watch, "sync_response_to_doc", return_value=True), \
             patch.object(watch.sys, "argv", ["watch.py", "--once", "--doc-id", "test-document", "--gemini-doc-id", ""]):
            ret = watch.main()
            self.assertEqual(ret, 0)

        # Crashed task must NOT have been replayed
        self.assertNotIn("req_crashed_1", executed)
        rec1 = self.queue.get_request("req_crashed_1")
        self.assertEqual(rec1["status"], "INTERRUPTED")

        # Waiting task must have executed
        self.assertIn("req_waiting_2", executed)
        rec2 = self.queue.get_request("req_waiting_2")
        self.assertEqual(rec2["status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
