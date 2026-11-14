import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import watch


class BridgeTests(unittest.TestCase):
    def test_marker_parser_ignores_normal_chat_and_placeholder(self):
        example = watch.START + '\n{"id":"<UNIQUE_ID_HERE>","action":"list_files"}\n' + watch.END
        real = watch.START + '\n{"id":"task_123456","action":"list_files"}\n' + watch.END
        self.assertEqual(watch.parse_requests('normal chat\n' + example + '\n' + real),
                         [{'id': 'task_123456', 'action': 'list_files'}])

    def test_read_path_cannot_escape_or_read_credentials(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as other:
            root = Path(temp); (root / 'source.py').write_text('one\ntwo\n')
            (root / 'token.json').write_text('secret')
            (root / 'escape').symlink_to(other, target_is_directory=True)
            with patch.object(watch, 'ROOT', root):
                result = watch.execute({'action': 'read_file', 'path': 'source.py', 'start_line': 2, 'line_count': 1}, root)
                self.assertEqual(result['content'], '2: two')
                with self.assertRaises(ValueError): watch.checked_path(str(root / 'token.json'))
                with self.assertRaises(ValueError): watch.checked_path(str(root / 'escape'))

    def test_script_reports_real_exit_and_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(watch, 'ROOT', root):
                result = watch.execute({'id': 'task_123456', 'action': 'run', 'cwd': str(root),
                                        'script': 'printf hello; exit 3', 'timeout_seconds': 10}, root)
            self.assertEqual(result['exit_code'], 3)
            self.assertEqual(result['output'], 'hello')

    def test_toast_only_after_successful_clipboard_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(watch.subprocess, 'run') as run:
                def calls(args, **kwargs):
                    if args[0] == watch.CLIP:
                        calls.text = kwargs.get('input', '')
                    return type('Result', (), {'returncode': 0, 'stdout': getattr(calls, 'text', '')})()
                run.side_effect = calls
                copied, _ = watch.deliver('task_123456', {'status': 'completed'}, Path(temp))
                self.assertTrue(copied)
                commands = [c.args[0][0] for c in run.call_args_list]
                self.assertIn(watch.TOAST, commands)
                self.assertIn(watch.NOTIFY, commands)


    def test_script_limit_accepts_18kb_and_rejects_over_24kb(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            good='printf large_ok\n' + '#' * 18_000
            request={'id':'large_request_1234','script':good,'timeout_seconds':12}
            result=watch.run_script(request,root,root)
            self.assertEqual(result['exit_code'],0)
            self.assertIn('large_ok',result['output'])
            bad={'id':'oversize_request_1234','script':'printf nope\n' + '#' * 24_000,'timeout_seconds':12}
            with self.assertRaisesRegex(ValueError,'24000'):
                watch.run_script(bad,root,root)

    def test_notify_start_fires_toast_and_ongoing_notification(self):
        with patch.object(watch.subprocess, 'run') as run:
            run.return_value = type('Result', (), {'returncode': 0, 'stdout': ''})()
            watch.notify_start('task_running_123', {'action': 'run'})
            commands = [c.args[0][0] for c in run.call_args_list]
            self.assertIn(watch.TOAST, commands)
            self.assertIn(watch.NOTIFY, commands)
            notify_args = [c.args[0] for c in run.call_args_list if c.args[0][0] == watch.NOTIFY][0]
            self.assertIn('--ongoing', notify_args)
            self.assertIn('--priority', notify_args)

    def test_one_shot_persists_id_and_does_not_repeat(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); state = root / 'state'; project = root / 'project'; project.mkdir()
            (project / 'file.txt').write_text('content')
            request = {'id': 'task_123456', 'action': 'list_files', 'path': str(project)}
            doc = {'body': {'content': [{'textRun': {'content': watch.START + '\n' + json.dumps(request) + '\n' + watch.END}}]}}
            class Client:
                def get_doc(self, doc_id): return doc
            with patch.object(watch, 'STATE_DIR', state), patch.object(watch, 'ROOT', root), \
                 patch.object(watch, 'GoogleDocsClient', Client), patch.object(watch, 'deliver', return_value=(True, root/'x')) as deliver, \
                 patch.object(watch.sys, 'argv', ['watch.py', '--once']):
                self.assertEqual(watch.main(), 0)
                self.assertEqual(watch.main(), 0)
                self.assertEqual(deliver.call_count, 1)
                self.assertEqual(json.loads((state/'requests.json').read_text())['task_123456']['status'], 'completed')


    def test_auto_execution_mode_runs_scripts_without_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); state = root / 'state'; project = root / 'project'; project.mkdir()
            request = {'id': 'auto_script_1', 'action': 'run', 'cwd': str(project), 'script': 'echo auto_ok', 'timeout_seconds': 5}
            doc = {'body': {'content': [{'textRun': {'content': watch.START + '\n' + json.dumps(request) + '\n' + watch.END}}]}}
            class Client:
                def get_doc(self, doc_id): return doc
            with patch.object(watch, 'STATE_DIR', state), patch.object(watch, 'ROOT', root), \
                 patch.object(watch, 'GoogleDocsClient', Client), patch.object(watch, 'deliver', return_value=(True, root/'x')), \
                 patch.object(watch.sys, 'argv', ['watch.py', '--once']), \
                 patch('builtins.input', side_effect=AssertionError("input() should not be called in auto mode")):
                self.assertEqual(watch.main(), 0)
                state_data = json.loads((state / 'requests.json').read_text())
                self.assertEqual(state_data['auto_script_1']['status'], 'completed')

    def test_confirm_execution_mode_prompts_user_and_declines(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); state = root / 'state'; project = root / 'project'; project.mkdir()
            request = {'id': 'confirm_script_1', 'action': 'run', 'cwd': str(project), 'script': 'echo confirm_test', 'timeout_seconds': 5}
            doc = {'body': {'content': [{'textRun': {'content': watch.START + '\n' + json.dumps(request) + '\n' + watch.END}}]}}
            class Client:
                def get_doc(self, doc_id): return doc
            with patch.object(watch, 'STATE_DIR', state), patch.object(watch, 'ROOT', root), \
                 patch.object(watch, 'GoogleDocsClient', Client), patch.object(watch, 'deliver', return_value=(True, root/'x')), \
                 patch.object(watch.sys, 'argv', ['watch.py', '--execution', 'confirm', '--once']), \
                 patch('builtins.input', return_value='n'):
                self.assertEqual(watch.main(), 0)
                state_data = json.loads((state / 'requests.json').read_text())
                self.assertEqual(state_data['confirm_script_1']['status'], 'declined')


    def test_sync_response_to_doc(self):
        with patch.object(watch, 'replace_latest_diagnostic', return_value=True) as write:
            res = watch.sync_response_to_doc(object(), 'doc123', 'req1', {'status': 'completed'})
        self.assertTrue(res)
        write.assert_called_once_with(write.call_args.args[0], 'doc123', 'req1', {'status': 'completed'})

    def test_doc_delivery_does_not_touch_clipboard_or_android_browser(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(watch, 'set_clipboard_reliable', side_effect=AssertionError('clipboard must not run')), \
                 patch.object(watch.subprocess, 'run') as run:
                copied, path = watch.deliver('task_123456', {'status': 'completed'},
                                            Path(temp), clipboard=False, doc_synced=True)
            self.assertFalse(copied)
            self.assertTrue(path.is_file())
            self.assertNotIn(watch.CLIP, [call.args[0][0] for call in run.call_args_list])
            self.assertNotIn('adb', [call.args[0][0] for call in run.call_args_list])

    def test_metadata_skips_reading_doc_when_version_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); state = root / 'state'
            class Client:
                def __init__(self):
                    self.get_doc_calls = 0
                def get_doc(self, doc_id):
                    self.get_doc_calls += 1
                    return {'body': {'content': []}}
            c = Client()
            with patch.object(watch, 'STATE_DIR', state), patch.object(watch, 'ROOT', root), \
                 patch.object(watch, 'GoogleDocsClient', lambda: c), \
                 patch.object(watch, 'get_doc_metadata', return_value={'revisionId': 'rev1'}), \
                 patch.object(watch.sys, 'argv', ['watch.py', '--once']):
                watch.main()
                self.assertEqual(c.get_doc_calls, 1)


if __name__ == '__main__':
    unittest.main()
