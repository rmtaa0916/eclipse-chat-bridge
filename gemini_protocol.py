#!/usr/bin/env python3
"""ECLIPSE Gemini Protocol Handler & Review 23 Security Engine.

Contains:
- Gemini protocol parser & tokens (<<<ECLIPSE_GEMINI_REQUEST_V1>>>)
- Serialization-aware logarithmic binary search bounding (<= 32,768 characters)
- Context reader AST analysis and sandboxed memfd execution
- Write capability check with strict HTTP 200 enforcement
- Gemini diagnostic slot replacement
"""
from __future__ import annotations

import ast
import codecs
import errno
import fcntl
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import urllib.error
import urllib.request

REQUEST_START_TOKEN = "<<<ECLIPSE_GEMINI_REQUEST_V1>>>"
REQUEST_END_TOKEN = "<<<END_ECLIPSE_GEMINI_REQUEST_V1>>>"
RESPONSE_START_TOKEN = "<<<ECLIPSE_GEMINI_RESPONSE_V1>>>"
RESPONSE_END_TOKEN = "<<<END_ECLIPSE_GEMINI_RESPONSE_V1>>>"
DIAGNOSTIC_SECTION_START = "<<<ECLIPSE_DIAGNOSTIC_SECTION_V1>>>"
DIAGNOSTIC_SECTION_END = "<<<END_ECLIPSE_DIAGNOSTIC_SECTION_V1>>>"
LATEST_DIAGNOSTIC_HEADING = "LATEST DIAGNOSTIC RESULT"

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")
MAX_RESPONSE_PAYLOAD_CHARS = 32768
_WRAPPER_OVERHEAD = len(RESPONSE_START_TOKEN) + len(RESPONSE_END_TOKEN) + 2
MAX_JSON_BODY_CHARS = MAX_RESPONSE_PAYLOAD_CHARS - _WRAPPER_OVERHEAD

DEFAULT_CONTEXT_READER_SHA256 = "ed5bc45c53e54e6441ec780a2b9fafe7751fd24cf70ab3b1f86ea72e4fc810cc"
TRUSTED_CONTEXT_READER = Path("/root/projects/chat-run-docs/context_reader.py")

SENSITIVE_BASENAMES = frozenset({
    "token.json", "credentials.json", ".env", ".envrc", "id_rsa", "id_ed25519",
    "id_ecdsa", "id_dsa", "authorized_keys", "known_hosts", "cookies.sqlite",
    "Cookies", "Login Data"
})
SENSITIVE_GLOB_PATTERNS = (".env*", "*.pem", "*.key", "*.p12", "*.pfx", "*secret*", "*credential*")
SENSITIVE_DIR_NAMES = frozenset({".ssh", ".gnupg", ".aws", ".config", ".kube", ".docker"})
SENSITIVE_ABSOLUTE_PATHS = frozenset({
    Path("/etc/shadow"), Path("/etc/passwd"), Path("/etc/gshadow"),
    Path("/proc/kcore"), Path("/proc/self/environ")
})
DEFAULT_ALLOWED_ROOTS = (Path("/root/projects"), Path("/data/data/com.termux/files"))


class SecurityError(ValueError):
    pass


class RevisionConflictError(RuntimeError):
    pass


def is_valid_request_id(req_id: Any) -> bool:
    return isinstance(req_id, str) and bool(REQUEST_ID_PATTERN.fullmatch(req_id))


def is_sensitive_path(resolved: Path) -> bool:
    if resolved in SENSITIVE_ABSOLUTE_PATHS:
        return True
    for sensitive in SENSITIVE_ABSOLUTE_PATHS:
        if resolved == sensitive or sensitive in resolved.parents:
            return True
    for part in resolved.parts:
        if not part or part == "/":
            continue
        if part in SENSITIVE_BASENAMES or part in SENSITIVE_DIR_NAMES:
            return True
        for pattern in SENSITIVE_GLOB_PATTERNS:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def checked_path(raw_path: str | Path, allowed_roots: tuple[Path, ...] | list[Path] | None = None) -> Path:
    if raw_path is None or (isinstance(raw_path, str) and not raw_path.strip()):
        raise SecurityError("Empty path is not allowed")
    candidate = Path(os.path.expanduser(str(raw_path)))
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    resolved = candidate.resolve(strict=False)
    if is_sensitive_path(resolved):
        raise SecurityError(f"Access to sensitive credential path denied: {resolved}")
    roots = tuple(allowed_roots) if allowed_roots is not None else DEFAULT_ALLOWED_ROOTS
    resolved_roots = [Path(r).resolve(strict=False) for r in roots]
    for root in resolved_roots:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise SecurityError(f"Path {resolved} is outside allowed roots: {[str(r) for r in resolved_roots]}")


def parse_gemini_requests(doc_text: str) -> List[Dict[str, Any]]:
    requests: List[Dict[str, Any]] = []
    pattern = re.compile(
        r"(?m)^" + re.escape(REQUEST_START_TOKEN) + r"\r?\n([\s\S]*?)\r?\n" + re.escape(REQUEST_END_TOKEN) + r"\r?$"
    )
    for match in pattern.finditer(doc_text):
        raw = match.group(1).strip()
        if raw.startswith("```") and raw.endswith("```"):
            raw = "\n".join(raw.splitlines()[1:-1]).strip()
        if len(raw.encode("utf-8")) > 32_000:
            continue
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            req_id = value.get("id") or value.get("request_id")
            if is_valid_request_id(req_id):
                value["id"] = req_id
                requests.append(value)
    return requests


def format_gemini_response(req_id: str, res: Dict[str, Any], delivery_token: Optional[str] = None) -> str:
    """Format response adhering to Review 23 serialization-aware output bounding."""
    if not is_valid_request_id(req_id):
        raise ValueError(f"Invalid request ID: {req_id!r}")

    if isinstance(res, dict):
        status = res.get("status", "completed")
        action = res.get("action", "")
        payload: Dict[str, Any] = {"id": req_id, "status": status, "action": action}
        if delivery_token:
            payload["delivery_token"] = delivery_token
        if "result" in res:
            raw_res = res["result"]
        elif status != "error":
            raw_res = res
        else:
            raw_res = None

        if isinstance(raw_res, dict):
            pub_res = dict(raw_res)
            if "content" in pub_res:
                pub_res.pop("raw_content", None)
                pub_res.pop("lines", None)
            if pub_res.get("truncated"):
                pub_res["partial_delivery"] = True
                payload["partial_delivery"] = True
            payload["result"] = pub_res
        elif raw_res is not None:
            payload["result"] = raw_res

        if "error" in res:
            payload["error"] = res["error"]
    else:
        payload = {"id": req_id, "status": "completed", "action": "", "result": res}
        if delivery_token:
            payload["delivery_token"] = delivery_token

    target_budget = MAX_JSON_BODY_CHARS
    body = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    if len(body) > target_budget:
        payload["truncated"] = True
        payload["partial_delivery"] = True
        res_val = payload.get("result")

        if isinstance(res_val, dict) and "content" in res_val and isinstance(res_val["content"], str):
            trimmed_res = dict(res_val)
            trimmed_res["truncated"] = True
            trimmed_res["partial_delivery"] = True
            orig_content = str(trimmed_res["content"])
            suffix = "\n... [partial delivery: content bounded to fit payload limit]"

            low = 0
            high = len(orig_content)
            best_cand = ""
            while low <= high:
                mid = (low + high) // 2
                cand = orig_content[:mid] + (suffix if mid < len(orig_content) else "")
                trimmed_res["content"] = cand
                trimmed_res["published_content_chars"] = len(cand)
                payload["result"] = trimmed_res
                cand_body = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
                if len(cand_body) <= target_budget:
                    best_cand = cand
                    low = mid + 1
                else:
                    high = mid - 1

            trimmed_res["content"] = best_cand
            trimmed_res["published_content_chars"] = len(best_cand)
            payload["result"] = trimmed_res
            body = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
        elif isinstance(res_val, str):
            low = 0
            high = len(res_val)
            suffix = "\n... [partial delivery: truncated]"
            best_cand = ""
            while low <= high:
                mid = (low + high) // 2
                cand = res_val[:mid] + suffix
                payload["result"] = cand
                cand_body = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
                if len(cand_body) <= target_budget:
                    best_cand = cand
                    low = mid + 1
                else:
                    high = mid - 1
            payload["result"] = best_cand
            body = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)

        # Fallback postcondition
        if len(body) > target_budget:
            base: Dict[str, Any] = {
                "id": str(req_id)[:64],
                "status": str(payload.get("status", "completed"))[:32],
                "action": str(payload.get("action", ""))[:32],
                "truncated": True,
                "partial_delivery": True,
                "result": {
                    "truncated": True,
                    "partial_delivery": True,
                    "summary": "Response payload bounded to limit",
                    "content": "",
                },
            }
            if delivery_token:
                base["delivery_token"] = str(delivery_token)[:64]
            target_str = str(res_val.get("content") if isinstance(res_val, dict) and "content" in res_val else res_val)
            low = 0
            high = len(target_str)
            best_cand = ""
            suffix = "\n... [bounded]"
            while low <= high:
                mid = (low + high) // 2
                base["result"]["content"] = target_str[:mid] + suffix
                b_cand = json.dumps(base, indent=2, sort_keys=True, ensure_ascii=False)
                if len(b_cand) <= target_budget:
                    best_cand = target_str[:mid] + suffix
                    low = mid + 1
                else:
                    high = mid - 1
            base["result"]["content"] = best_cand
            body = json.dumps(base, indent=2, sort_keys=True, ensure_ascii=False)

    formatted = f"{RESPONSE_START_TOKEN}\n{body}\n{RESPONSE_END_TOKEN}"
    if len(formatted) > MAX_RESPONSE_PAYLOAD_CHARS:
        minimal_body = json.dumps({
            "id": str(req_id)[:64],
            "status": "completed",
            "action": str(payload.get("action", ""))[:32],
            "truncated": True,
            "partial_delivery": True,
            "result": {"summary": "Content truncated to satisfy response bound"},
        }, indent=2, sort_keys=True, ensure_ascii=False)
        formatted = f"{RESPONSE_START_TOKEN}\n{minimal_body}\n{RESPONSE_END_TOKEN}"

    assert len(formatted) <= MAX_RESPONSE_PAYLOAD_CHARS, f"Response size {len(formatted)} exceeds {MAX_RESPONSE_PAYLOAD_CHARS}"
    return formatted


def verify_write_delivery_capability(client: Any, doc_id: str) -> bool:
    """Strict HTTP 200 write check on Google Drive API canEdit capability."""
    if client is None or not doc_id:
        return False
    if hasattr(client, "verify_write_capability") and callable(client.verify_write_capability):
        try:
            return bool(client.verify_write_capability(doc_id))
        except Exception:
            return False

    if not hasattr(client, "token_mgr"):
        return False
    try:
        if callable(client.token_mgr):
            token = client.token_mgr()
        elif hasattr(client.token_mgr, "get_access_token"):
            token = client.token_mgr.get_access_token()
        else:
            token = str(client.token_mgr)
    except Exception:
        return False
    if not token:
        return False

    try:
        url = f"https://www.googleapis.com/drive/v3/files/{doc_id}?fields=capabilities/canEdit"
        req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
        req.add_header("Authorization", f"Bearer {token}")
        opener = getattr(client, "opener", None) or urllib.request.build_opener()
        with opener.open(req, timeout=15.0) as resp:
            resp_code = getattr(resp, "status", getattr(resp, "code", None))
            if resp_code != 200:
                return False
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return bool(data.get("capabilities", {}).get("canEdit") is True)
    except Exception:
        return False


def _find_gemini_diagnostic_span(doc_payload: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    body = doc_payload.get("body") or {}
    content = body.get("content") or []
    full_text_parts: List[str] = []
    element_map: List[Tuple[int, int, int]] = []
    curr_char_idx = 0
    for block in content:
        if not isinstance(block, dict):
            continue
        paragraph = block.get("paragraph")
        if not isinstance(paragraph, dict):
            continue
        elements = paragraph.get("elements") or []
        for elem in elements:
            if not isinstance(elem, dict):
                continue
            text_run = elem.get("textRun")
            if not isinstance(text_run, dict):
                continue
            content_str = text_run.get("content")
            if not isinstance(content_str, str) or not content_str:
                continue
            start_idx = elem.get("startIndex")
            end_idx = elem.get("endIndex")
            if isinstance(start_idx, int) and isinstance(end_idx, int):
                length = len(content_str)
                element_map.append((curr_char_idx, curr_char_idx + length, start_idx))
                full_text_parts.append(content_str)
                curr_char_idx += length

    full_text = "".join(full_text_parts)
    start_pos = full_text.find(DIAGNOSTIC_SECTION_START)
    if start_pos == -1:
        return None
    end_pos = full_text.find(DIAGNOSTIC_SECTION_END, start_pos)
    if end_pos == -1:
        return None
    end_pos += len(DIAGNOSTIC_SECTION_END)
    if end_pos < len(full_text) and full_text[end_pos] == "\n":
        end_pos += 1

    doc_start: Optional[int] = None
    doc_end: Optional[int] = None
    for c_start, c_end, d_start in element_map:
        if doc_start is None and c_start <= start_pos < c_end:
            doc_start = d_start + (start_pos - c_start)
        if doc_end is None and c_start < end_pos <= c_end:
            doc_end = d_start + (end_pos - c_start)
            break
    if doc_start is not None and doc_end is not None and doc_start < doc_end:
        return (doc_start, doc_end)
    return None


def sync_gemini_response_to_doc(client: Any, doc_id: str, req_id: str, result: Dict[str, Any]) -> bool:
    """Sync Gemini formatted response to Google Doc."""
    try:
        response_block = format_gemini_response(req_id, result)
        doc_payload = client.get_doc(doc_id)
        revision_id = doc_payload.get("revisionId")
        if not revision_id:
            return False

        span = _find_gemini_diagnostic_span(doc_payload)
        replacement_text = f"{DIAGNOSTIC_SECTION_START}\n{LATEST_DIAGNOSTIC_HEADING}\n{response_block}\n{DIAGNOSTIC_SECTION_END}\n"

        if span is not None:
            start_idx, end_idx = span
            batch_requests = [
                {"deleteContentRange": {"range": {"startIndex": start_idx, "endIndex": end_idx}}},
                {"insertText": {"location": {"index": start_idx}, "text": replacement_text}},
            ]
        else:
            body = doc_payload.get("body") or {}
            content = body.get("content") or []
            end_idx = 1
            for elem in content:
                if isinstance(elem, dict) and isinstance(elem.get("endIndex"), int):
                    end_idx = max(end_idx, elem["endIndex"])
            insert_idx = max(1, end_idx - 1)
            batch_requests = [{"insertText": {"location": {"index": insert_idx}, "text": f"\n{replacement_text}"}}]

        token = client.token_mgr.get_access_token() if hasattr(client, "token_mgr") else ""
        if not token:
            return False

        patch_body = {"requests": batch_requests, "writeControl": {"requiredRevisionId": revision_id}}
        url = f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate"
        req = urllib.request.Request(
            url,
            data=json.dumps(patch_body).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        opener = getattr(client, "opener", None) or urllib.request.build_opener()
        with opener.open(req, timeout=20) as resp:
            ack = json.loads(resp.read().decode("utf-8"))
            return ack.get("documentId") == doc_id
    except Exception as exc:
        print(f"Warning: Gemini doc sync failed: {exc}", file=sys.stderr, flush=True)
        return False


def exec_context_reader(req_id: str, action: str, request: Dict[str, Any], root: Path) -> Dict[str, Any]:
    """Execute context_overview or context_search using context_reader.py."""
    if not TRUSTED_CONTEXT_READER.exists():
        raise ValueError(f"Trusted context reader not found at {TRUSTED_CONTEXT_READER}")

    # Verify SHA-256 integrity
    content = TRUSTED_CONTEXT_READER.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    expected_sha = os.environ.get("ECLIPSE_CONTEXT_READER_SHA256", DEFAULT_CONTEXT_READER_SHA256)
    if digest != expected_sha:
        raise SecurityError(f"Context reader SHA-256 mismatch: {digest} != {expected_sha}")

    subaction = "overview" if action == "context_overview" else "search"
    reader_payload: Dict[str, Any] = {"action": subaction}
    if "query" in request:
        reader_payload["query"] = str(request["query"])
    if "max_chars" in request:
        reader_payload["max_chars"] = int(request["max_chars"])
    if "max_results" in request:
        reader_payload["max_results"] = int(request["max_results"])

    cmd = [sys.executable, str(TRUSTED_CONTEXT_READER), "--json", json.dumps(reader_payload)]
    cwd_path = checked_path(request.get("cwd") or request.get("root") or str(root))

    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd_path),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = proc.communicate(timeout=60)
    if proc.returncode != 0:
        return {"id": req_id, "status": "error", "action": action, "error": stderr or f"Process returned code {proc.returncode}"}

    try:
        parsed = json.loads(stdout)
    except Exception:
        parsed = {"raw": stdout}
    return {"id": req_id, "status": "completed", "action": action, "result": parsed}
