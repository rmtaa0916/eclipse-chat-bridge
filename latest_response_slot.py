"""Replace the one dedicated ECLIPSE diagnostic slot without changing other text.

Local full receipts remain in the bridge results directory. No browser sessions,
credentials, or provider tabs are touched by this module.
"""
from __future__ import annotations
import json
import re
import time
import urllib.error
import urllib.request

START = "<<<ECLIPSE_BRIDGE_LATEST_DIAGNOSTIC_START_V1>>>"
END = "<<<ECLIPSE_BRIDGE_LATEST_DIAGNOSTIC_END_V1>>>"

class SlotError(ValueError):
    pass

def _u16(s):
    return len(s.encode("utf-16-le")) // 2

def _runs(document):
    """Return text segments and Docs UTF-16 indices for top-level paragraphs."""
    body = document.get("body")
    if not isinstance(body, dict) or not isinstance(body.get("content"), list):
        raise SlotError("Document body was not returned; cannot safely replace slot.")
    result = []
    offset = 0
    for block in body["content"]:
        paragraph = block.get("paragraph") if isinstance(block, dict) else None
        if not isinstance(paragraph, dict):
            continue
        for element in paragraph.get("elements", []):
            if not isinstance(element, dict):
                continue
            text_run = element.get("textRun")
            if not isinstance(text_run, dict):
                continue
            content = text_run.get("content")
            if not isinstance(content, str):
                continue
            start, end = element.get("startIndex"), element.get("endIndex")
            if type(start) is not int or type(end) is not int or end-start != _u16(content):
                raise SlotError("Cannot safely map text to Docs UTF-16 positions.")
            result.append((offset, offset+len(content), start, end, content))
            offset += len(content)
    if not result:
        raise SlotError("Document has no indexed text runs.")
    return "".join(row[4] for row in result), result

def _location(rows, offset):
    for offset_start, offset_end, doc_start, doc_end, chunk in rows:
        if offset_start <= offset <= offset_end:
            return doc_start + _u16(chunk[:offset-offset_start])
    raise SlotError("Slot marker index cannot be resolved.")

MAX_SLOT_RESULT_LEN = 1800

def _bound_slot_result(result, max_len=MAX_SLOT_RESULT_LEN):
    """Ensure result fits comfortably inside slot without blowing Docs API document limits."""
    if not isinstance(result, dict):
        return result
    dumped = json.dumps(result, ensure_ascii=False)
    if len(dumped) <= max_len:
        return result

    bounded = dict(result)
    sub = bounded.get("result")
    if isinstance(sub, dict):
        sub_copy = dict(sub)
        if isinstance(sub_copy.get("output"), str) and len(sub_copy["output"]) > 800:
            out = sub_copy["output"]
            sub_copy["output"] = out[:400] + "\n... [truncated for slot display] ...\n" + out[-350:]
            sub_copy["truncated"] = True
        if isinstance(sub_copy.get("entries"), list) and len(sub_copy["entries"]) > 15:
            entries = sub_copy["entries"]
            sub_copy["total_entries"] = len(entries)
            sub_copy["sample_entries"] = entries[:15]
            sub_copy.pop("entries", None)
            sub_copy["truncated"] = True
        if isinstance(sub_copy.get("content"), str) and len(sub_copy["content"]) > 800:
            cont = sub_copy["content"]
            sub_copy["content"] = cont[:400] + "\n... [truncated for slot display] ...\n" + cont[-350:]
            sub_copy["truncated"] = True
        bounded["result"] = sub_copy

    dumped2 = json.dumps(bounded, ensure_ascii=False)
    if len(dumped2) > max_len:
        raw_file = None
        if isinstance(bounded.get("result"), dict):
            raw_file = bounded["result"].get("full_output_file")
        return {
            "status": bounded.get("status", "completed"),
            "action": bounded.get("action", "unknown"),
            "truncated": True,
            "note": "Output exceeds Google Docs slot capacity; full raw output preserved locally",
            "full_output_file": raw_file,
        }
    return bounded

def build_slot_patch(document, request_id, result):
    """Pure, validated batchUpdate payload; no network or mutation."""
    text, runs = _runs(document)
    # Live request JSON can mention these literal token names; only accept
    # markers occupying an entire document line (not inline source strings).
    starts = list(re.finditer(r"(?m)^" + re.escape(START) + r"\r?$", text))
    ends = list(re.finditer(r"(?m)^" + re.escape(END) + r"\r?$", text))
    if len(starts) != 1 or len(ends) != 1:
        raise SlotError("Expected exactly one standalone diagnostic start and end marker.")
    between_start = starts[0].end()
    between_end = ends[0].start()
    if between_end <= between_start:
        raise SlotError("Latest-diagnostic markers are not ordered.")
    start_index = _location(runs, between_start)
    end_index = _location(runs, between_end)
    if end_index <= start_index:
        raise SlotError("Latest-diagnostic replacement range is invalid.")
    covered = [row for row in runs if row[1] > between_start and row[0] < between_end]
    if not covered:
        raise SlotError("Latest-diagnostic slot has no text.")
    if any(left[3] != right[2] for left, right in zip(covered, covered[1:])):
        raise SlotError("Slot crosses non-text document elements.")
    if not isinstance(request_id, str) or not request_id:
        raise SlotError("Diagnostic request identity is required.")
    revision = document.get("revisionId")
    if not isinstance(revision, str) or not revision:
        raise SlotError("Document revision is required to prevent concurrent overwrites.")
    safe_result = _bound_slot_result(result)
    payload = "\n" + json.dumps({"id": request_id, "result": safe_result},
                                ensure_ascii=False, indent=2) + "\n"
    return {
        "requests": [
            {"deleteContentRange": {"range": {
                "startIndex": start_index, "endIndex": end_index}}},
            {"insertText": {"location": {"index": start_index}, "text": payload}},
        ],
        "writeControl": {"requiredRevisionId": revision},
    }

def replace_latest_diagnostic(client, doc_id, request_id, result):
    """Update the slot only, failing closed if markers or revision are invalid."""
    if not all(hasattr(client, name) for name in ("get_doc", "token_mgr", "opener")):
        raise SlotError("Docs write capabilities unavailable.")
    token = client.token_mgr.get_access_token()
    url = f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate"
    for attempt in range(3):
        doc = client.get_doc(doc_id, token)
        payload = build_slot_patch(doc, request_id, result)
        req = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST")
        try:
            with client.opener.open(req, timeout=20) as response:
                parsed = json.loads(response.read().decode("utf-8"))
            if not isinstance(parsed, dict):
                raise SlotError("Google Docs did not acknowledge the replacement.")
            return True
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            if attempt < 2 and (exc.code in (409, 412) or (exc.code == 400 and ("revision" in detail.lower() or "precondition" in detail.lower()))):
                time.sleep(0.5)
                continue
            raise SlotError(f"Google Docs rejected slot update (HTTP {exc.code}): {detail}") from exc
    return False
