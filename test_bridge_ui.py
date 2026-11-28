import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import bridge_ui


class BridgeUITests(unittest.TestCase):
    def test_render_bridge_scene_wide(self):
        lines = bridge_ui.render_bridge_scene(frame=5, cols=80, lines=30, is_active=True)
        self.assertGreaterEqual(len(lines), 10)
        text = "\n".join(lines)
        self.assertIn("ECLIPSE CHAT BRIDGE", text)
        self.assertIn("GOOGLE DOCS", text)
        self.assertIn("TERMUX", text)
        self.assertIn("Down:", text)
        self.assertIn("Uplk:", text)
        self.assertIn("Wave:", text)

    def test_render_bridge_scene_compact(self):
        lines = bridge_ui.render_bridge_scene(frame=2, cols=60, lines=20, is_active=False)
        self.assertGreaterEqual(len(lines), 4)
        text = "\n".join(lines)
        self.assertIn("DOCS", text)
        self.assertIn("TERMUX", text)

    def test_generate_telemetry_wave(self):
        wave = bridge_ui.generate_telemetry_wave(frame=0, width=16, active=True)
        self.assertTrue(any(g in wave for g in bridge_ui.WAVE_GLYPHS))

    def test_get_bridge_state_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            state_dir = Path(temp)
            requests = {
                "req1": {"status": "completed"},
                "req2": {"status": "completed"},
                "req3": {"status": "running"},
                "req4": {"status": "error"},
            }
            (state_dir / "requests.json").write_text(json.dumps(requests))
            (state_dir / "watcher.pid").write_text("99999999")
            with patch.object(bridge_ui, "STATE_DIR", state_dir), \
                 patch("os.kill", side_effect=ProcessLookupError), \
                 patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, ["pgrep"])):
                st = bridge_ui.get_bridge_state()
                self.assertEqual(st["total"], 4)
                self.assertEqual(st["completed"], 2)
                self.assertEqual(st["running_tasks"], 1)
                self.assertEqual(st["errors"], 1)
                self.assertFalse(st["running"])

    def test_zero_flicker_buffer_and_responsive_height(self):
        state = {
            "running": True,
            "pid": 1234,
            "total": 1,
            "completed": 1,
            "running_tasks": 0,
            "errors": 0,
            "requests": {"task_abc": {"status": "completed"}},
            "doc_id": "doc123",
        }
        with patch.object(bridge_ui, "get_terminal_dimensions", return_value=(80, 24)), \
             patch("sys.stdout.write") as mock_write, \
             patch("sys.stdout.flush"):
            bridge_ui.render_dashboard_inplace(state, frame=0, flash_message="[TEST FLASH]")
            written = "".join(call.args[0] for call in mock_write.call_args_list)
            # Must use in-place cursor home \033[H
            self.assertIn("\033[H", written)
            # Must NOT call clear screen \033[2J
            self.assertNotIn("\033[2J", written)
            # Must include flash message
            self.assertIn("[TEST FLASH]", written)

    def test_non_tty_menu_fallback(self):
        with patch("sys.stdin.isatty", return_value=False), \
             patch("sys.stdout.isatty", return_value=False), \
             patch("bridge_ui.render_dashboard_inplace") as mock_render:
            bridge_ui.interactive_menu_loop()
            mock_render.assert_called_once()


if __name__ == "__main__":
    unittest.main()
