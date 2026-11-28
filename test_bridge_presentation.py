import io
import os
import unittest
from unittest.mock import patch

import bridge_presentation as view
import bridge_ui


class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.state = {'running': True, 'running_tasks': 0, 'completed': 42, 'total': 43,
                      'requests': {'request_previous': {'status': 'completed'}}}
        self.health = {'service': 'RUNNING', 'heartbeat': 'FRESH', 'watcher_count': 1,
                       'heartbeat_age_s': 2}

    def text(self, state=None, health=None, **kwargs):
        lines = view.render(self.state if state is None else state,
                            self.health if health is None else health, 80, 24, **kwargs)
        return view._ANSI.sub('', '\n'.join(lines))

    def test_terminal_bounds_including_unicode_and_resize(self):
        self.state['requests']['研究_🛰️_task' * 10] = {'status': 'queued'}
        for width in [1, 2, 20, 32, 40, 65, 66, 80, 100, 180]:
            for height in [1, 5, 12, 14, 20, 24, 35, 60]:
                with self.subTest(width=width, height=height):
                    lines = view.render(self.state, self.health, width, height, frame=17)
                    self.assertLessEqual(len(lines), max(1, height - 1))
                    self.assertTrue(all(view.cells(x) <= max(1, width - 1) for x in lines))

    def test_idle_is_ready_without_inventing_progress(self):
        text = self.text()
        self.assertIn('READY', text)
        self.assertIn('IDLE · waiting for requests', text)
        self.assertNotIn('%', text)
        self.assertNotIn('Working', text)

    def test_running_request_and_queue_are_real(self):
        self.state['running_tasks'] = 1
        self.state['requests'].update({'request_active': {'status': 'running'}, 'request_waiting': {'status': 'queued'}})
        text = self.text()
        self.assertIn('WORKING', text)
        self.assertIn('request_active', text)
        self.assertIn('RUN 1', text)
        self.assertIn('WAIT 1', text)

    def test_stale_running_record_does_not_claim_execution(self):
        self.state['requests']['stale'] = {'status': 'running'}
        self.assertNotIn('WORKING', self.text())

    def test_offline_overrides_stale_running_count(self):
        self.state.update(running_tasks=1, running=False, watcher_count=0, process_probe='ABSENT')
        text = self.text(health={'service': 'DOWN'})
        self.assertIn('OFFLINE', text)
        self.assertNotIn('Working', text)

    def test_absent_health_is_not_presented_as_ready(self):
        self.state.update(running=False, watcher_count=0, process_probe='UNKNOWN')
        self.assertIn('CHECK', self.text(health={}))

    def test_animation_changes_without_reordering_records(self):
        self.assertNotEqual(view.orbit(0), view.orbit(10))
        self.assertNotEqual(self.text(frame=0), self.text(frame=20))
        for frame in [0, 20, 40]:
            self.assertIn('request_previous', self.text(frame=frame))

    def test_reduced_motion_is_still(self):
        with patch.dict(os.environ, {'BRIDGE_UI_REDUCED_MOTION': '1'}):
            self.assertEqual(self.text(frame=0), self.text(frame=99))

    def test_no_color_has_no_sgr(self):
        with patch.dict(os.environ, {'NO_COLOR': '1'}):
            self.assertNotIn('\x1b', '\n'.join(view.render(self.state, self.health, 80, 24)))

    def test_untrusted_text_cannot_move_cursor_or_set_terminal_title(self):
        self.state['requests'] = {'bad\x1b[2J\x1b]0;owned\x07\nname': {'status': 'completed'}}
        text = self.text(flash_message='\x1b[Hnotice\nnext')
        self.assertNotIn('\x1b', text)
        self.assertNotIn('owned', text)
        self.assertIn('notice next', text)

    def test_flash_and_exit_remain_visible_on_short_screen(self):
        for rows in [13, 14, 16, 20]:
            lines = view.render(self.state, self.health, 40, rows, flash_message='Saved successfully')
            plain = view._ANSI.sub('', '\n'.join(lines))
            self.assertIn('Saved successfully', plain)
            self.assertIn('Q close', plain)

    def test_redraw_is_one_write_and_never_scrolls_last_line(self):
        with patch.object(bridge_ui, 'get_terminal_dimensions', return_value=(40, 20)), \
                patch.object(bridge_ui, '_bridge_v3_status', return_value=self.health), \
                patch('sys.stdout', new_callable=io.StringIO) as stream:
            bridge_ui.render_dashboard_inplace(self.state)
            output = stream.getvalue()
        self.assertTrue(output.startswith('\x1b[H'))
        self.assertNotIn('\x1b[2J', output)
        self.assertFalse(output.endswith('\n'))
        self.assertLessEqual(output.count('\r\n'), 18)
        self.assertNotIn('\n', output)
        self.assertIn('\x1b[?7l', output)
        self.assertTrue(output.endswith('\x1b[?7h'))
        self.assertIn('\x1b[19;1H', output)

    def test_piped_monitor_renders_once_and_returns(self):
        with patch('sys.stdin.isatty', return_value=False), \
                patch.object(bridge_ui, 'get_bridge_state', return_value=self.state), \
                patch.object(bridge_ui, 'render_dashboard_inplace') as render:
            bridge_ui.run_live_monitor()
            render.assert_called_once_with(self.state)

    def test_classic_layout_remains_available(self):
        with patch.dict(os.environ, {'BRIDGE_UI_STYLE': 'classic'}), \
                patch.object(bridge_ui, '_bridge_dashboard_classic', return_value=['classic']) as classic:
            self.assertEqual(bridge_ui.build_dashboard_lines(self.state), ['classic'])
            classic.assert_called_once()

    def test_real_tty_size_wins_over_stale_environment(self):
        with patch.dict(os.environ, {'COLUMNS': '200', 'LINES': '100'}), \
                patch('sys.stdout.isatty', return_value=True), \
                patch('sys.stdout.fileno', return_value=1), \
                patch('os.get_terminal_size', return_value=os.terminal_size((40, 20))):
            self.assertEqual(bridge_ui.get_terminal_dimensions(), (40, 20))

    def test_continuous_resize_reflows_every_frame(self):
        sizes = [(120, 36), (40, 24), (80, 16), (20, 8), (100, 30), (35, 20)] * 5
        with patch.object(bridge_ui, '_bridge_v3_status', return_value=self.health), \
                patch.object(bridge_ui, 'get_terminal_dimensions', side_effect=sizes) as dimensions:
            for frame, (width, height) in enumerate(sizes):
                lines = bridge_ui.build_dashboard_lines(self.state, frame)
                self.assertLessEqual(len(lines), height - 1)
                self.assertTrue(all(view.cells(x) <= width - 1 for x in lines))
                self.assertIn('ECLIPSE', view._ANSI.sub('', '\n'.join(lines)))
            self.assertEqual(dimensions.call_count, len(sizes))
