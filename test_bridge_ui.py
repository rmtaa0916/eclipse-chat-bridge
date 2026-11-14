import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import bridge_ui


class BridgeUITests(unittest.TestCase):
    def test_render_bridge_scene_wide(self):
        lines = bridge_ui.render_bridge_scene(frame=5, width=80)
        self.assertGreaterEqual(len(lines), 10)
        text = "\n".join(lines)
        self.assertIn("ECLIPSE CHAT BRIDGE", text)
        self.assertIn("GOOGLE DOCS", text)
        self.assertIn("TERMUX", text)

    def test_render_bridge_scene_compact(self):
        lines = bridge_ui.render_bridge_scene(frame=2, width=60)
        self.assertGreaterEqual(len(lines), 4)
        text = "\n".join(lines)
        self.assertIn("DOCS", text)
        self.assertIn("TERMUX", text)

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

    def test_render_dashboard_does_not_crash(self):
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
        with patch("os.system"):
            bridge_ui.render_dashboard(state, frame=0)


if __name__ == "__main__":
    unittest.main()
