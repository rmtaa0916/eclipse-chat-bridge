#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest

from bridge_queue import BridgeQueue


class TestBridgeQueue(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_queue.db"
        self.queue = BridgeQueue(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _fingerprint(self, payload: dict) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def test_enqueue_and_fifo_order(self):
        # Enqueue 3 requests
        for i in range(1, 4):
            req_id = f"task_req_00{i}"
            payload = {"id": req_id, "action": "run", "script": f"echo {i}"}
            fp = self._fingerprint(payload)
            status, msg = self.queue.enqueue_request(
                request_id=req_id,
                protocol="chatgpt",
                doc_id="doc1",
                fingerprint=fp,
                action="run",
                payload=payload,
            )
            self.assertEqual(status, "ENQUEUED")
            time.sleep(0.01)  # ensure distinct timestamp

        # Dequeue must be strictly FIFO
        item1 = self.queue.fetch_next_fifo()
        self.assertIsNotNone(item1)
        self.assertEqual(item1["id"], "task_req_001")
        self.assertEqual(item1["status"], "RUNNING")

        item2 = self.queue.fetch_next_fifo()
        self.assertIsNotNone(item2)
        self.assertEqual(item2["id"], "task_req_002")

        item3 = self.queue.fetch_next_fifo()
        self.assertIsNotNone(item3)
        self.assertEqual(item3["id"], "task_req_003")

        # Now queue should be empty
        item4 = self.queue.fetch_next_fifo()
        self.assertIsNone(item4)

    def test_duplicate_and_tamper_protection(self):
        req_id = "task_dup_123"
        payload1 = {"id": req_id, "action": "list_files"}
        fp1 = self._fingerprint(payload1)

        # First enqueue
        st, msg = self.queue.enqueue_request(req_id, "chatgpt", "doc1", fp1, "list_files", payload1)
        self.assertEqual(st, "ENQUEUED")

        # Re-enqueue exact same
        st, msg = self.queue.enqueue_request(req_id, "chatgpt", "doc1", fp1, "list_files", payload1)
        self.assertEqual(st, "DUPLICATE")

        # Re-enqueue with modified payload (tampering)
        payload2 = {"id": req_id, "action": "run", "script": "malicious"}
        fp2 = self._fingerprint(payload2)
        st, msg = self.queue.enqueue_request(req_id, "chatgpt", "doc1", fp2, "run", payload2)
        self.assertEqual(st, "REJECTED")

    def test_restart_recovery_flags_running_as_interrupted(self):
        req_id = "task_crash_001"
        payload = {"id": req_id, "action": "run", "script": "sleep 100"}
        fp = self._fingerprint(payload)

        self.queue.enqueue_request(req_id, "chatgpt", "doc1", fp, "run", payload)
        item = self.queue.fetch_next_fifo()
        self.assertEqual(item["id"], req_id)
        self.assertEqual(item["status"], "RUNNING")

        # Simulate crash & restart with new queue instance
        queue2 = BridgeQueue(self.db_path)
        flagged = queue2.recover_interrupted_tasks()
        self.assertIn(req_id, flagged)

        # Interrupted task must NOT be re-executed
        next_item = queue2.fetch_next_fifo()
        self.assertIsNone(next_item)

        rec = queue2.get_request(req_id)
        self.assertEqual(rec["status"], "INTERRUPTED")

    def test_housekeeping_safety_conditions(self):
        req1 = "task_queued"
        p1 = {"id": req1, "action": "run"}
        self.queue.enqueue_request(req1, "chatgpt", "doc1", self._fingerprint(p1), "run", p1)

        req2 = "task_running"
        p2 = {"id": req2, "action": "run"}
        self.queue.enqueue_request(req2, "chatgpt", "doc1", self._fingerprint(p2), "run", p2)
        self.queue.fetch_next_fifo()

        req3 = "task_completed"
        p3 = {"id": req3, "action": "run"}
        self.queue.enqueue_request(req3, "chatgpt", "doc1", self._fingerprint(p3), "run", p3)
        self.queue.fetch_next_fifo()
        self.queue.mark_completed(req3, {"exit_code": 0}, doc_synced=True)

        req4 = "task_failed"
        p4 = {"id": req4, "action": "run"}
        self.queue.enqueue_request(req4, "chatgpt", "doc1", self._fingerprint(p4), "run", p4)
        self.queue.fetch_next_fifo()
        self.queue.mark_failed(req4, "command failed", doc_synced=True)

        # Queued must NOT be pruned
        self.assertFalse(self.queue.is_safe_to_prune(req1))
        # Running must NOT be pruned
        self.assertFalse(self.queue.is_safe_to_prune(req2))
        # Completed with result and doc_synced CAN be pruned
        self.assertTrue(self.queue.is_safe_to_prune(req3))
        # Failed with recorded error CAN be pruned
        self.assertTrue(self.queue.is_safe_to_prune(req4))

    def test_sync_legacy_state_file(self):
        req_id = "task_legacy_001"
        payload = {"id": req_id, "action": "list_files"}
        fp = self._fingerprint(payload)
        self.queue.enqueue_request(req_id, "chatgpt", "doc1", fp, "list_files", payload)
        self.queue.fetch_next_fifo()
        self.queue.mark_completed(req_id, {"status": "completed"})

        state_file = Path(self.temp_dir.name) / "requests.json"
        self.queue.sync_legacy_state_file(state_file)

        self.assertTrue(state_file.is_file())
        legacy = json.loads(state_file.read_text())
        self.assertIn(req_id, legacy)
        self.assertEqual(legacy[req_id]["status"], "completed")
        self.assertEqual(legacy[req_id]["sha256"], fp)


if __name__ == "__main__":
    unittest.main()
