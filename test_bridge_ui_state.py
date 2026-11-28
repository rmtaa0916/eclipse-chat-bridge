from datetime import datetime, timedelta, timezone
import json
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from bridge_ui_state import read_state, probe_watchers
from bridge_presentation import render, status_model, _ANSI, cells


class StateEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name);self.state = self.root / 'state';self.state.mkdir()
        self.proc = self.root / 'proc';self.proc.mkdir();self.script = self.root / 'project/watch.py'

    def process(self, pid=12, argv=None):
        p = self.proc / str(pid);p.mkdir()
        (p / 'cmdline').write_bytes(b'\0'.join(x.encode() for x in (argv or ['python3', str(self.script)])))
        return p

    def read(self):
        return read_state(self.state, self.script, 'primary-configured', proc_root=self.proc)

    def test_live_watcher_does_not_depend_on_stale_pid_cache(self):
        self.process();(self.state / 'watcher.pid').write_text('99999')
        value = self.read()
        self.assertEqual(value['pid'], 12);self.assertEqual(value['watcher_count'], 1)
        self.assertEqual((self.state / 'watcher.pid').read_text(), '99999')

    def test_shell_containing_watch_path_is_not_a_watcher(self):
        self.process(argv=['bash', '-c', 'python3 ' + str(self.script)])
        self.assertEqual(self.read()['watcher_count'], 0)

    def test_unrelated_watch_file_is_not_a_watcher(self):
        self.process(argv=['python3', '/other/project/watch.py'])
        self.assertEqual(self.read()['watcher_count'], 0)

    def test_relative_script_requires_matching_working_directory(self):
        self.script.parent.mkdir();self.script.touch()
        p = self.process(argv=['python3', 'watch.py']);(p / 'cwd').symlink_to(self.script.parent)
        self.assertEqual(self.read()['pid'], 12)

    def test_stale_supervisor_does_not_claim_current_ownership(self):
        self.process();(self.state / 'supervisor-health.json').write_text(json.dumps({
            'utc': (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
            'mode': 'MANAGED_RUNNING', 'managed_watcher_pid': 12}))
        value = self.read();self.assertFalse(value['managed']);self.assertFalse(value['supervisor_fresh'])

    def test_fresh_owner_is_matched_to_actual_watcher(self):
        self.process();(self.state / 'supervisor-health.json').write_text(json.dumps({
            'utc': datetime.now(timezone.utc).isoformat(), 'managed_watcher_pid': 12}))
        self.assertTrue(self.read()['managed'])

    def test_sqlite_beats_outdated_legacy_snapshot_without_writes(self):
        self.process();(self.state / 'requests.json').write_text('{}')
        database = self.state / 'bridge_queue.db'
        c = sqlite3.connect(database);c.execute('create table queue(id text,status text,enqueued_at real)')
        c.executemany('insert into queue values(?,?,?)', [('active_one','RUNNING',2),('prior_one','COMPLETED',1),('waiting_one','QUEUED',3)]);c.commit();c.close()
        before = database.read_bytes();value = self.read()
        self.assertEqual(value['running_tasks'], 1);self.assertEqual(value['queued'], 1)
        self.assertEqual(value['total'], 3);self.assertEqual(value['completed'], 1)
        self.assertEqual(value['queue_source'], 'SQLite');self.assertEqual(database.read_bytes(), before)

    def test_missing_database_is_not_created(self):
        value = self.read();self.assertFalse((self.state / 'bridge_queue.db').exists())
        self.assertEqual(value['queue_source'], 'Legacy snapshot')

    def test_provider_configuration_comes_from_actual_flags(self):
        self.process(argv=['python3', str(self.script), '--gemini-doc-id', 'secondary-configured'])
        self.assertTrue(self.read()['providers']['Gemini'])
        self.assertEqual(self.read()['gemini_doc_id'], 'secondary-configured')
        self.assertEqual(self.read()['doc_id'], 'primary-configured')

    def test_process_visibility_failure_is_unknown_not_offline(self):
        self.assertEqual(probe_watchers(self.script, self.root / 'unavailable')[2], 'UNKNOWN')

    def test_manual_watcher_overrides_down_service_and_stale_heartbeat(self):
        self.process();value = self.read();value['running_tasks'] = 1
        model = status_model(value, {'service':'DOWN','watcher_count':0,'heartbeat':'STALE'})
        self.assertEqual(model[3], 'WORKING')


class CompleteDashboardTests(unittest.TestCase):
    def setUp(self):
        self.state = {'running':True,'watcher_count':1,'process_probe':'PRESENT','pid':12,
            'running_tasks':1,'queued':2,'completed':99,'errors':3,'interrupted':4,'total':109,
            'requests':{'request_active':{'status':'running'}}, 'providers':{'ChatGPT':True,'Gemini':True},
            'task':{'id':'task_linked','phase':'review','attempt':3,'pending':'critic'},'queue_source':'SQLite',
            'doc_id':'primary_binding','gemini_doc_id':'secondary_binding'}
        self.health = {'service':'DOWN','heartbeat':'STALE','watcher_count':0}

    def plain(self, page=0, width=80, height=24):
        return _ANSI.sub('', '\n'.join(render(self.state, self.health, width, height, page=page)))

    def test_overview_restores_all_six_operational_panels(self):
        text = self.plain()
        for title in ['WATCHER / SERVICE','RECENT EXECUTIONS','ECLIPSE TASK','RECOVERY / HEALTH','PROVIDER LINKS','CONTROLS']:
            self.assertIn(title, text)
        self.assertIn('WORKING',text);self.assertIn('Service DOWN',text);self.assertNotIn('Watcher offline',text)

    def test_phone_detail_views_retain_task_health_and_provider_details(self):
        for page, expected in [(1,'request_active'),(2,'task_linked'),(2,'review'),(2,'critic'),(3,'stale'),(4,'ChatGPT'),(4,'Gemini'),(4,'primary_binding'),(4,'secondary_binding')]:
            self.assertIn(expected, self.plain(page,40,24))

    def test_all_views_fit_continuous_resize(self):
        for width,height in [(1,1),(20,8),(40,24),(80,16),(80,24),(120,36)] * 3:
            for page in range(5):
                lines = render(self.state,self.health,width,height,frame=15,page=page)
                self.assertLessEqual(len(lines),max(1,height-1))
                self.assertTrue(all(cells(x)<=max(1,width-1) for x in lines))

    def test_navigation_changes_views_without_service_actions(self):
        import bridge_ui as ui
        with patch.object(ui, 'UI_VIEW', 0), patch.object(ui, 'UI_SCROLL', 0):
            self.assertTrue(ui.navigation_key('2'));self.assertEqual(ui.UI_VIEW, 1)
            self.assertTrue(ui.navigation_key('j'));self.assertEqual(ui.UI_SCROLL, 1)
            self.assertTrue(ui.navigation_key('\t'));self.assertEqual(ui.UI_VIEW, 2)
            self.assertEqual(ui.UI_SCROLL, 0);self.assertFalse(ui.navigation_key('q'))

    def test_alternate_screen_restores_once(self):
        import bridge_ui as ui
        class TTY(io.StringIO):
            def isatty(self):return True
        stream = TTY()
        with patch('sys.stdout', stream), patch.object(ui, '_ALT_SCREEN_ACTIVE', False), patch.object(ui, '_ORIGINAL_TERMIOS', None):
            ui.enter_screen();ui.enter_screen();ui.restore_terminal();ui.restore_terminal()
        self.assertEqual(stream.getvalue().count('\x1b[?1049h'), 1)
        self.assertEqual(stream.getvalue().count('\x1b[?1049l'), 1)
