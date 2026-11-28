import unittest
import io
import json
from unittest.mock import Mock
from bridge_doc_sync import fetch_document, plan, managed_text, START, END, TITLES

COMMIT = 'a' * 40
PAYLOAD = 'Old header\n<<<ECLIPSE_BRIDGE_REQUEST_V1>>>\n{"id":"test_12345678"}\n<<<END_ECLIPSE_BRIDGE_REQUEST_V1>>>\n'


def doc(text, provider='chatgpt'):
    return {'title': TITLES[provider], 'revisionId': 'rev1', 'body': {'content': [
        {'paragraph': {'elements': [{'startIndex': 1, 'endIndex': 1 + len(text.encode('utf-16-le')) // 2,
                                    'textRun': {'content': text}}]}}]}}


class SyncTests(unittest.TestCase):
    def test_bootstrap_requires_opt_in(self):
        with self.assertRaises(ValueError):
            plan(doc(PAYLOAD), 'chatgpt', 'New', COMMIT)
        p = plan(doc(PAYLOAD), 'chatgpt', 'New', COMMIT, bootstrap=True)
        self.assertEqual(p['writeControl']['requiredRevisionId'], 'rev1')
        self.assertEqual(p['requests'][0]['insertText']['location']['index'], 1)

    def test_replace_only_header_utf16(self):
        old = managed_text('chatgpt', 'Old 🚀', COMMIT)
        p = plan(doc(old + '\n' + PAYLOAD), 'chatgpt', 'New', COMMIT)
        end = p['requests'][0]['deleteContentRange']['range']['endIndex']
        self.assertEqual(end, 1 + len(old.encode('utf-16-le')) // 2)
        self.assertEqual((old + '\n' + PAYLOAD).encode('utf-16-le')[(end-1)*2:].decode('utf-16-le'), '\n' + PAYLOAD)

    def test_idempotent(self):
        old = managed_text('chatgpt', 'New', COMMIT)
        self.assertEqual(plan(doc(old + PAYLOAD), 'chatgpt', 'New', COMMIT)['requests'], [])

    def test_malformed_duplicate_and_misplaced_markers(self):
        old = managed_text('chatgpt', 'Old', COMMIT)
        for text in (START + '\n' + PAYLOAD, old + old + PAYLOAD, PAYLOAD + old):
            with self.subTest(text=text), self.assertRaises(ValueError):
                plan(doc(text), 'chatgpt', 'New', COMMIT)

    def test_protected_protocol_and_wrong_provider(self):
        for text in (START + '\nProvider: chatgpt\n' + PAYLOAD + END + '\n',
                     managed_text('gemini', 'Old', COMMIT) + PAYLOAD):
            with self.subTest(text=text), self.assertRaises(ValueError):
                plan(doc(text), 'chatgpt', 'New', COMMIT)
        with self.assertRaises(ValueError):
            plan(doc(PAYLOAD, 'gemini'), 'chatgpt', 'New', COMMIT, bootstrap=True)

    def test_template_injection(self):
        with self.assertRaises(ValueError):
            managed_text('chatgpt', PAYLOAD, COMMIT)

    def test_gemini_separate_header(self):
        p = plan(doc('Gemini\n', 'gemini'), 'gemini', 'Gemini only', COMMIT, bootstrap=True)
        self.assertIn('Provider: gemini', p['requests'][0]['insertText']['text'])

    def test_fetch_document_identity_and_fields(self):
        client = Mock()
        client.token_mgr.get_access_token.return_value = 'test-token'
        payload = dict(doc(PAYLOAD), documentId='authorized')
        client.opener.open.return_value = io.BytesIO(json.dumps(payload).encode())
        self.assertEqual(fetch_document(client, 'authorized'), payload)
        request = client.opener.open.call_args.args[0]
        self.assertIn('fields=documentId,title,revisionId,body(content)', request.full_url)
        client.opener.open.return_value = io.BytesIO(json.dumps(payload).encode())
        with self.assertRaises(ValueError):
            fetch_document(client, 'different')


if __name__ == '__main__':
    unittest.main()
