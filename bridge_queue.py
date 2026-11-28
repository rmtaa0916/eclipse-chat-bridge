#!/usr/bin/env python3
"""Persistent SQLite FIFO Queue for ECLIPSE Bridge.

Guarantees:
- ACID transactional persistence via SQLite (WAL mode).
- Strict FIFO ordering for the single execution worker.
- Duplicate ID protection and SHA-256 fingerprint verification.
- Tamper detection (rejects modified payloads reusing the same request ID).
- Safe crash recovery: pending QUEUED items survive and execute in order;
  interrupted RUNNING items are flagged for inspection and NEVER automatically re-run.
- Dual-protocol tagging ('chatgpt' and 'gemini') with zero Mode 7 references.
- Bi-directional sync with legacy requests.json for backwards-compatibility.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple


def _json_dumps_canonical(val: Any) -> str:
    return json.dumps(val, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class BridgeQueue:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            isolation_level=None,  # autocommit / manual control
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS queue (
                    id TEXT PRIMARY KEY,
                    protocol TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT,
                    error_msg TEXT,
                    enqueued_at REAL NOT NULL,
                    started_at REAL,
                    completed_at REAL,
                    doc_synced INTEGER NOT NULL DEFAULT 0,
                    delivery_channel TEXT
                );
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_queue_status_enqueued
                ON queue(status, enqueued_at);
            """)

    def enqueue_request(
        self,
        request_id: str,
        protocol: str,
        doc_id: str,
        fingerprint: str,
        action: str,
        payload: Dict[str, Any],
    ) -> Tuple[str, str]:
        """Enqueue incoming request.

        Returns (status_code, message):
        - ('ENQUEUED', 'Successfully enqueued')
        - ('DUPLICATE', 'Request already enqueued or completed')
        - ('REJECTED', 'Refused changed request with reused ID')
        """
        raw_payload = _json_dumps_canonical(payload)
        now = time.time()
        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            cur = conn.cursor()
            cur.execute("SELECT sha256, status FROM queue WHERE id = ?", (request_id,))
            row = cur.fetchone()
            if row is not None:
                existing_sha = row["sha256"]
                existing_status = row["status"]
                conn.execute("COMMIT;")
                if existing_sha != fingerprint:
                    return "REJECTED", f"Refused changed request with reused ID: {request_id}"
                return "DUPLICATE", f"Request {request_id} already exists with status {existing_status}"

            cur.execute(
                """
                INSERT INTO queue (
                    id, protocol, doc_id, sha256, action, payload, status, enqueued_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'QUEUED', ?)
                """,
                (request_id, protocol, doc_id, fingerprint, action, raw_payload, now),
            )
            conn.execute("COMMIT;")
            return "ENQUEUED", f"Request {request_id} enqueued"
        except Exception as exc:
            try:
                conn.execute("ROLLBACK;")
            except Exception:
                pass
            raise exc
        finally:
            conn.close()

    def fetch_next_fifo(self) -> Optional[Dict[str, Any]]:
        """Atomically fetch and mark the next QUEUED request as RUNNING."""
        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, protocol, doc_id, sha256, action, payload, status, enqueued_at
                FROM queue
                WHERE status = 'QUEUED'
                ORDER BY enqueued_at ASC
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if row is None:
                conn.execute("COMMIT;")
                return None

            req_id = row["id"]
            now = time.time()
            cur.execute(
                "UPDATE queue SET status = 'RUNNING', started_at = ? WHERE id = ?",
                (now, req_id),
            )
            conn.execute("COMMIT;")

            item = dict(row)
            item["status"] = "RUNNING"
            item["started_at"] = now
            try:
                item["payload"] = json.loads(row["payload"])
            except Exception:
                pass
            return item
        except Exception as exc:
            try:
                conn.execute("ROLLBACK;")
            except Exception:
                pass
            raise exc
        finally:
            conn.close()

    def mark_completed(
        self,
        request_id: str,
        result: Dict[str, Any],
        doc_synced: bool = False,
        delivery_channel: str = "",
    ) -> None:
        now = time.time()
        raw_result = _json_dumps_canonical(result)
        conn = self._get_connection()
        try:
            conn.execute(
                """
                UPDATE queue
                SET status = 'COMPLETED',
                    result = ?,
                    completed_at = ?,
                    doc_synced = ?,
                    delivery_channel = ?
                WHERE id = ?
                """,
                (raw_result, now, 1 if doc_synced else 0, delivery_channel, request_id),
            )
        finally:
            conn.close()

    def mark_failed(
        self,
        request_id: str,
        error_msg: str,
        result: Optional[Dict[str, Any]] = None,
        doc_synced: bool = False,
        delivery_channel: str = "",
    ) -> None:
        now = time.time()
        raw_result = _json_dumps_canonical(result) if result is not None else None
        conn = self._get_connection()
        try:
            conn.execute(
                """
                UPDATE queue
                SET status = 'FAILED',
                    error_msg = ?,
                    result = ?,
                    completed_at = ?,
                    doc_synced = ?,
                    delivery_channel = ?
                WHERE id = ?
                """,
                (error_msg, raw_result, now, 1 if doc_synced else 0, delivery_channel, request_id),
            )
        finally:
            conn.close()

    def mark_declined(self, request_id: str) -> None:
        now = time.time()
        conn = self._get_connection()
        try:
            conn.execute(
                "UPDATE queue SET status = 'DECLINED', completed_at = ? WHERE id = ?",
                (now, request_id),
            )
        finally:
            conn.close()

    def recover_interrupted_tasks(self) -> List[str]:
        """Flag any RUNNING tasks from a previous run as INTERRUPTED.

        Returns list of request IDs flagged.
        Per specification: NEVER re-run commands with uncertain outcomes automatically!
        """
        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            cur = conn.cursor()
            cur.execute("SELECT id FROM queue WHERE status = 'RUNNING'")
            interrupted = [row["id"] for row in cur.fetchall()]
            if interrupted:
                cur.execute("UPDATE queue SET status = 'INTERRUPTED' WHERE status = 'RUNNING'")
            conn.execute("COMMIT;")
            return interrupted
        except Exception as exc:
            try:
                conn.execute("ROLLBACK;")
            except Exception:
                pass
            raise exc
        finally:
            conn.close()

    def count_pending(self) -> int:
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM queue WHERE status = 'QUEUED'")
            row = cur.fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()

    def get_stats(self) -> Dict[str, int]:
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT status, count(*) FROM queue GROUP BY status")
            counts = {row[0]: int(row[1]) for row in cur.fetchall()}
            return {
                "total": sum(counts.values()),
                "queued": counts.get("QUEUED", 0),
                "running": counts.get("RUNNING", 0),
                "completed": counts.get("COMPLETED", 0),
                "failed": counts.get("FAILED", 0),
                "declined": counts.get("DECLINED", 0),
                "interrupted": counts.get("INTERRUPTED", 0),
            }
        finally:
            conn.close()

    def get_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM queue WHERE id = ?", (request_id,))
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def is_safe_to_prune(self, request_id: str) -> bool:
        """Keeper condition: only delete entries safely completed & recorded."""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT status, completed_at, doc_synced
                FROM queue
                WHERE id = ?
                """,
                (request_id,),
            )
            row = cur.fetchone()
            if row is None:
                return False
            status = row["status"]
            # Active or interrupted requests are protected indefinitely
            if status in ("QUEUED", "RUNNING", "INTERRUPTED"):
                return False
            # Completed or failed requests with recorded results are eligible
            if status in ("COMPLETED", "FAILED", "DECLINED") and row["completed_at"] is not None:
                return True
            return False
        finally:
            conn.close()

    def migrate_legacy_state(self, state_path: Path | str) -> int:
        """Migrate existing historical requests from requests.json if not present."""
        path = Path(state_path)
        if not path.is_file():
            return 0
        try:
            legacy = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(legacy, dict):
                return 0
        except Exception:
            return 0

        migrated = 0
        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            cur = conn.cursor()
            for req_id, rec in legacy.items():
                if not isinstance(rec, dict):
                    continue
                sha = rec.get("sha256", "")
                st = rec.get("status", "completed").upper()
                cur.execute("SELECT id FROM queue WHERE id = ?", (req_id,))
                if cur.fetchone() is None:
                    cur.execute(
                        """
                        INSERT INTO queue (
                            id, protocol, doc_id, sha256, action, payload, status,
                            enqueued_at, completed_at, doc_synced
                        ) VALUES (?, 'chatgpt', 'legacy', ?, 'legacy', '{}', ?, 0.0, 0.0, 1)
                        """,
                        (req_id, sha, st),
                    )
                    migrated += 1
            conn.execute("COMMIT;")
        except Exception:
            try:
                conn.execute("ROLLBACK;")
            except Exception:
                pass
            return 0
        finally:
            conn.close()
        return migrated

    def sync_legacy_state_file(self, state_path: Path | str) -> None:
        """Atomically synchronize queue state to requests.json for backwards-compatibility."""
        target = Path(state_path)
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, sha256, status FROM queue")
            legacy_dict: Dict[str, Dict[str, str]] = {}
            for row in cur.fetchall():
                st = row["status"].lower()
                legacy_dict[row["id"]] = {
                    "sha256": row["sha256"],
                    "status": st,
                }
        finally:
            conn.close()

        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = target.with_suffix(f".tmp.{os.getpid()}")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(legacy_dict, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, target)
