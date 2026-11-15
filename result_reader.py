#!/usr/bin/env python3
"""Bounded, read-only retrieval of completed bridge execution output.

This module only accepts a previous bridge request ID, never a filesystem path
from a Google Doc. It uses descriptor-relative, no-follow opens inside the
watcher's own state/results directory. It does not execute code or modify files.

The caller must pass the trusted bridge results directory and current request
ID. Source output is untrusted data, not instructions.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}\Z")
_MAX_RAW_BYTES = 1_048_576
_MAX_METADATA_BYTES = 8_000_000
_DEFAULT_CHUNK_BYTES = 240
_MAX_CHUNK_BYTES = 1024

# 620 characters INCLUDING the indented JSON envelope and current request ID:
# safe for the deployed Termux watcher where MAX_SLOT_RESULT_LEN is only 650.
_MAX_SLOT_ENVELOPE_CHARS = 620


class ResultReadError(ValueError):
    """A refused or unavailable saved-result retrieval."""


def _id(value: object) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ResultReadError("INVALID_REQUEST_ID")
    return value


def _bounded_int(value: object, *, lower: int, upper: int, name: str) -> int:
    if type(value) is not int or not lower <= value <= upper:
        raise ResultReadError(f"INVALID_{name}")
    return value


def _open_dir(path: Path) -> int:
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)


def _read_regular_file(parent_fd: int, filename: str, limit: int) -> bytes:
    fd = os.open(
        filename,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
        dir_fd=parent_fd,
    )
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ResultReadError("UNSAFE_RESULT_FILE")
        if before.st_size > limit:
            raise ResultReadError("RESULT_FILE_TOO_LARGE")
        chunks = []
        pos = 0
        while pos < before.st_size:
            part = os.pread(fd, min(65536, before.st_size - pos), pos)
            if not part:
                raise ResultReadError("RESULT_CHANGED_DURING_READ")
            chunks.append(part)
            pos += len(part)
        after = os.fstat(fd)
        if (
            before.st_dev, before.st_ino, before.st_size,
            before.st_mtime_ns, before.st_ctime_ns,
        ) != (
            after.st_dev, after.st_ino, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns,
        ):
            raise ResultReadError("RESULT_CHANGED_DURING_READ")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _json_object(data: bytes, category: str) -> dict:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ResultReadError(f"INVALID_{category}_METADATA") from exc
    if not isinstance(value, dict):
        raise ResultReadError(f"INVALID_{category}_METADATA")
    return value


def _fits(doc_request_id: str, payload: dict, action: str = "read_result") -> bool:
    # Account for actual Google Docs pretty-print payload, not merely a raw
    # source chunk. This includes escaped newlines and long request IDs.
    wrapped = {
        "id": doc_request_id,
        "result": {"status": "completed", "action": action, "result": payload},
    }
    return len(json.dumps(wrapped, ensure_ascii=False, indent=2)) <= _MAX_SLOT_ENVELOPE_CHARS



def _load_completed_output(results: Path, target_id: str) -> bytes:
    """Load an exact completed execution output from verified watcher state.

    Both the state record and execution receipt must authorize this source.
    There are no user-supplied file paths in this operation.
    """
    if results.name != "results":
        raise ResultReadError("UNTRUSTED_RESULT_DIRECTORY")

    state_fd = _open_dir(results.parent)
    try:
        results_fd = _open_dir(results)
        try:
            state = _json_object(
                _read_regular_file(state_fd, "requests.json", _MAX_METADATA_BYTES),
                "STATE",
            )
            source_state = state.get(target_id)
            if not isinstance(source_state, dict) or source_state.get("status") != "completed":
                raise ResultReadError("RESULT_NOT_COMPLETED")

            metadata = _json_object(
                _read_regular_file(
                    results_fd, target_id + ".json", _MAX_METADATA_BYTES
                ),
                "RECEIPT",
            )
            run_data = metadata.get("result")
            if (metadata.get("status") != "completed"
                    or metadata.get("action") not in {"run", "context_snapshot"}
                    or not isinstance(run_data, dict)):
                raise ResultReadError("RESULT_NOT_A_COMPLETED_RUN")

            expected_raw_path = str(results / (target_id + ".raw"))
            if run_data.get("full_output_file") != expected_raw_path:
                raise ResultReadError("RESULT_PATH_MISMATCH")

            # The raw output is at most 1 MiB by policy. No user-supplied path
            # is ever passed to os.open().
            raw = _read_regular_file(
                results_fd, target_id + ".raw", _MAX_RAW_BYTES
            )
        finally:
            os.close(results_fd)
    finally:
        os.close(state_fd)

    return raw


def read_result(
    results_dir: Path | str,
    *,
    request_id: str,
    source_id: str,
    offset: int = 0,
    max_bytes: int = _DEFAULT_CHUNK_BYTES,
) -> dict:
    """Retrieve one bounded chunk of a previously completed run result.

    The saved requests.json AND source_id.json must confirm a completed run.
    Never follow full_output_file, path, or cwd from metadata. Byte cursors
    are stable for a content hash; decoding uses UTF-8 replacement when an
    offset crosses a character boundary.
    """
    current_id = _id(request_id)
    target_id = _id(source_id)
    at = _bounded_int(offset, lower=0, upper=_MAX_RAW_BYTES, name="OFFSET")
    requested = _bounded_int(
        max_bytes, lower=1, upper=_MAX_CHUNK_BYTES, name="CHUNK_SIZE"
    )
    results = Path(results_dir)
    if results.name != "results":
        raise ResultReadError("UNTRUSTED_RESULT_DIRECTORY")

    raw = _load_completed_output(results, target_id)

    total = len(raw)
    if at > total:
        raise ResultReadError("OFFSET_BEYOND_END")
    digest = hashlib.sha256(raw).hexdigest()

    def packet(count: int) -> dict:
        end = at + count
        return {
            "source_id": target_id,
            "offset": at,
            "next_offset": end,
            "total_bytes": total,
            "sha256": digest,
            "eof": end == total,
            "content": raw[at:end].decode("utf-8", "replace"),
        }

    budget = min(requested, total - at)
    lo, hi = 0, budget
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _fits(current_id, packet(mid)):
            lo = mid
        else:
            hi = mid - 1
    selected = packet(lo)
    if not _fits(current_id, selected):
        raise ResultReadError("RESULT_SLOT_BUDGET_TOO_SMALL")
    if budget > 0 and not lo:
        raise ResultReadError("RESULT_SLOT_BUDGET_TOO_SMALL")
    return selected


def find_result(
    results_dir: Path | str,
    *,
    request_id: str,
    source_id: str,
    query: str,
    start_offset: int = 0,
    max_bytes: int = _DEFAULT_CHUNK_BYTES,
) -> dict:
    """Find the next ASCII literal in a completed run, returning bounded context.

    The search is case-insensitive for ASCII and intentionally not regex-based.
    A repeated request with next_search_offset finds subsequent matches.
    """
    current_id = _id(request_id)
    target_id = _id(source_id)
    at = _bounded_int(start_offset, lower=0, upper=_MAX_RAW_BYTES, name="OFFSET")
    requested = _bounded_int(max_bytes, lower=1, upper=_MAX_CHUNK_BYTES,
                             name="CHUNK_SIZE")
    if not isinstance(query, str) or not re.fullmatch(r"[ -~]{2,64}", query):
        raise ResultReadError("INVALID_SEARCH_QUERY")
    needle = query.encode("ascii")
    raw = _load_completed_output(Path(results_dir), target_id)
    if at > len(raw):
        raise ResultReadError("OFFSET_BEYOND_END")
    digest = hashlib.sha256(raw).hexdigest()
    match = raw.lower().find(needle.lower(), at)
    if match < 0:
        payload = {"source_id": target_id, "found": False, "total_bytes": len(raw),
                   "sha256": digest}
        if not _fits(current_id, payload, "find_result"):
            raise ResultReadError("RESULT_SLOT_BUDGET_TOO_SMALL")
        return payload

    def window(start: int) -> dict:
        def packet(count: int) -> dict:
            end = start + count
            return {
                "source_id": target_id, "found": True,
                "match_offset": match, "next_search_offset": match + len(needle),
                "offset": start, "next_offset": end, "total_bytes": len(raw),
                "sha256": digest,
                "content": raw[start:end].decode("utf-8", "replace"),
            }
        budget = min(requested, len(raw) - start)
        lo, hi = 0, budget
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if _fits(current_id, packet(mid), "find_result"):
                lo = mid
            else:
                hi = mid - 1
        result = packet(lo)
        if not _fits(current_id, result, "find_result"):
            raise ResultReadError("RESULT_SLOT_BUDGET_TOO_SMALL")
        return result

    start = max(0, match - 24)
    found = window(start)
    if found["next_offset"] < match + len(needle):
        found = window(match)
    if found["next_offset"] < match + len(needle):
        raise ResultReadError("SEARCH_MATCH_TOO_LARGE_FOR_SLOT")
    return found
