#!/usr/bin/env python3
import json
from pathlib import Path
import tempfile
import unittest

from gemini_protocol import (
    REQUEST_START_TOKEN,
    REQUEST_END_TOKEN,
    RESPONSE_START_TOKEN,
    RESPONSE_END_TOKEN,
    MAX_RESPONSE_PAYLOAD_CHARS,
    parse_gemini_requests,
    format_gemini_response,
    checked_path,
    SecurityError,
)


class TestGeminiProtocol(unittest.TestCase):
    def test_parse_gemini_requests(self):
        req = {"id": "gemini_req_001", "action": "list_files", "path": "/root/projects"}
        text = f"Some header chat\n{REQUEST_START_TOKEN}\n{json.dumps(req)}\n{REQUEST_END_TOKEN}\nTail chat"
        parsed = parse_gemini_requests(text)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["id"], "gemini_req_001")
        self.assertEqual(parsed[0]["action"], "list_files")

    def test_format_gemini_response_bounded(self):
        # 100,000 character output must be strictly bounded to <= 32,768 characters
        large_content = "X" * 100_000
        res = {"status": "completed", "action": "read_file", "result": {"content": large_content}}
        formatted = format_gemini_response("gemini_req_large", res)
        self.assertLessEqual(len(formatted), MAX_RESPONSE_PAYLOAD_CHARS)
        self.assertTrue(formatted.startswith(RESPONSE_START_TOKEN))
        self.assertTrue(formatted.endswith(RESPONSE_END_TOKEN))

    def test_format_gemini_response_json_expansion_bounded(self):
        # Null bytes expand 6x in JSON (\u0000)
        tricky_content = "\x00" * 15_000
        res = {"status": "completed", "action": "read_file", "result": {"content": tricky_content}}
        formatted = format_gemini_response("gemini_req_nulls", res)
        self.assertLessEqual(len(formatted), MAX_RESPONSE_PAYLOAD_CHARS)

    def test_checked_path_rejects_sensitive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "token.json").write_text("secret")
            with self.assertRaises(SecurityError):
                checked_path(root / "token.json", allowed_roots=[root])


if __name__ == "__main__":
    unittest.main()
