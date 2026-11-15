"""Offline tests of the bridge context snapshot safety and evidence contract."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import stat
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import context_snapshot as context
from result_reader import read_result


class SmallDigraph:
    def __init__(self):
        self.nodes = {}
        self.edges = set()

    def add_node(self, name, **attrs):
        self.nodes[name] = attrs

    def __contains__(self, name):
        return name in self.nodes

    def add_edge(self, a, b, **attrs):
        self.edges.add((a, b))

    def number_of_nodes(self):
        return len(self.nodes)

    def number_of_edges(self):
        return len(self.edges)

    def in_degree(self, name):
        return sum(1 for _a, b in self.edges if b == name)

    def predecessors(self, name):
        return iter(a for a, b in self.edges if b == name)

    def successors(self, name):
        return iter(b for a, b in self.edges if a == name)


class FakeGraphEngine:
    def __init__(self, root):
        self.root = root
        self.graph = SmallDigraph()
        self.file_modules = {}

    def _parse_python_ast(self, content, rel, _filename):
        tree = ast.parse(content)
        for item in ast.walk(tree):
            if isinstance(item, ast.ImportFrom) and item.module in self.file_modules:
                self.graph.add_edge(rel, self.file_modules[item.module], type="imports")

    def _parse_javascript_source(self, content, rel):
        return None

    def _parse_html_source(self, content, rel):
        return None

    def _parse_json_source(self, content, rel):
        return None


class FakeRequestError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class FakeReader:
    RequestError = FakeRequestError
    MAX_TOTAL_DIR_ENUMERATION_ENTRIES = 65536
    MAX_DIR_ENUMERATION_ENTRIES = 16384
    MAX_VISITED_ENTRIES = 2000
    MAX_TRAVERSAL_DEPTH = 16
    MAX_ENTRIES_PER_DIR = 512
    MAX_FILE_BYTES = 256 * 1024
    MAX_AGGREGATE_READ_BYTES = 2 * 1024 * 1024

    class _ScanBudgetState:
        def __init__(self):
            self.aggregate_bytes = 0
            self.aggregate_bytes_truncated = False
            self.any_truncated = False

    @staticmethod
    def _require_descriptor_primitives():
        return (os.O_NOFOLLOW, os.O_DIRECTORY, os.O_NONBLOCK)

    @staticmethod
    def _open_dir_relative(parent_fd, name, nofollow, directory):
        return os.open(name, os.O_RDONLY | nofollow | directory, dir_fd=parent_fd)

    @staticmethod
    def _has_sensitive_component(parts):
        return any(
            part.startswith(".") or any(
                x in part.casefold() for x in ("credential", "secret", "password", "token", "private")
            )
            for part in parts
        )

    @staticmethod
    def _is_allowed_extension(name):
        return Path(name).suffix.lower() in {".py", ".js", ".ts", ".md", ".txt"}

    @staticmethod
    def _open_validated_relative_file(root_fd, rel):
        current = os.open(".", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        parts = Path(rel).parts
        try:
            for part in parts[:-1]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                  dir_fd=current)
                os.close(current)
                current = next_fd
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW,
                         dir_fd=current)
            info = os.fstat(fd)
            if info.st_nlink != 1 or not stat.S_ISREG(info.st_mode):
                os.close(fd)
                raise FakeRequestError("INVALID_FILE")
            return fd, rel
        finally:
            os.close(current)

    @staticmethod
    def _read_and_screen_fd(fd, rel, budget=None):
        data = os.read(fd, FakeReader.MAX_FILE_BYTES + 1)
        if len(data) > FakeReader.MAX_FILE_BYTES:
            raise FakeRequestError("FILE_TOO_LARGE")
        if b"FAKE_UNSCREENED_SECRET" in data:
            raise FakeRequestError("SECRET_CONTENT_DENIED")
        if budget is not None:
            budget.aggregate_bytes += len(data)
            if budget.aggregate_bytes > FakeReader.MAX_AGGREGATE_READ_BYTES:
                budget.aggregate_bytes_truncated = True
                budget.any_truncated = True
                raise FakeRequestError("AGGREGATE_READ_LIMIT")
        text = data.decode("utf-8")
        return text, hashlib.sha256(data).hexdigest(), text.splitlines()


def _backend():
    def root_fd(path):
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def open_file(fd, rel):
        return os.open(rel, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd), rel

    def screen_file(fd, rel, budget=None):
        data = os.read(fd, 200000)
        txt = data.decode("utf-8")
        return txt, hashlib.sha256(data).hexdigest(), txt.splitlines()

    def process_request(fd, raw):
        req = json.loads(raw)
        root = Path(os.readlink(f"/proc/self/fd/{fd}"))
        if req["action"] == "overview":
            rows = []
            for p in sorted(root.rglob("*.py")):
                data = p.read_bytes()
                rows.append({"path": p.relative_to(root).as_posix(), "sha256": hashlib.sha256(data).hexdigest(),
                             "line_count": len(data.splitlines())})
            return {"ok": True, "files": rows, "symbols": [],
                    "truncated": False, "scan_errors": 0}
        if req["action"] == "search":
            hits = []
            for p in sorted(root.rglob("*.py")):
                for n, txt in enumerate(p.read_text().splitlines(), 1):
                    if req["query"].casefold() in txt.casefold():
                        hits.append({"path": p.relative_to(root).as_posix(), "line": n,
                                     "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                                     "content": txt})
            return {"ok": True, "matches": hits, "truncated": False}
        if req["action"] == "read":
            p = root / req["path"]
            data = p.read_bytes()
            lines = p.read_text().splitlines()
            return {"ok": True, "truncated": False, "excerpt": {
                "sha256": hashlib.sha256(data).hexdigest(),
                "total_lines": len(lines),
                "lines": [{"line": i, "text": lines[i-1]} for i in range(
                    req.get("start_line", 1), min(req.get("end_line", len(lines)), len(lines))+1)],
            }}
        raise ValueError("unsupported")

    def dot_name(rel):
        return rel.removesuffix(".py")

    def route_sources(goal, root, *, graph=None, max_files=None):
        return SimpleNamespace(hits=[
            SimpleNamespace(path="main.py", kind="CODE", score=100),
            SimpleNamespace(path="helper.py", kind="CODE", score=80),
            # An untrusted router must never authorize an outside-reader file:
            SimpleNamespace(path="unknown.py", kind="CODE", score=500),
        ])

    from priority_discovery import _terms, _name_terms
    return (root_fd, open_file, screen_file, process_request,
            FakeGraphEngine, dot_name, _terms, _name_terms, FakeReader)


class ContextSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / "projects"
        self.workspace.mkdir()
        self.project = self.workspace / "demo-project"
        self.project.mkdir()
        (self.project / "main.py").write_text(
            "from helper import calculate\n"
            "def run():\n"
            "    return calculate(1)\n", encoding="utf-8",
        )
        (self.project / "helper.py").write_text(
            "def calculate(value):\n"
            "    return value + 1\n", encoding="utf-8",
        )
        self.state = Path(self.temp.name) / "state"
        self.state.mkdir()
        self.results = self.state / "results"
        self.results.mkdir()
        self.patch_backend = patch.object(context, "_backend", return_value=_backend())
        self.patch_backend.start()
        self.addCleanup(self.patch_backend.stop)

    def report(self, **options):
        return context.build_context_snapshot(
            project=options.pop("project", "demo-project"),
            goal=options.pop("goal", "find calculate failure"),
            workspace_root=self.workspace, core_root=self.workspace,
            **options,
        )

    def test_snapshot_combines_reader_router_and_graph(self):
        report = self.report()
        self.assertEqual(report["schema"], "ECLIPSE_BRIDGE_CONTEXT_SNAPSHOT_V2")
        self.assertEqual(report["reader"]["file_count_returned"], 2)
        self.assertEqual(report["graph"]["screened_source_files"], 2)
        self.assertGreaterEqual(report["graph"]["edges"], 1)
        self.assertTrue(any(x["path"] == "main.py" for x in report["route"]))
        self.assertFalse(any(x["path"] == "unknown.py" for x in report["route"]))
        self.assertTrue(report["excerpts"])
        self.assertTrue(report["selected_sources"])
        self.assertTrue(report["matches"])
        self.assertEqual(report["capture"]["status"], "NOT_ATTACHED")
        dep = next(x for x in report["graph"]["dependencies"] if x["path"] == "main.py")
        self.assertIn("helper.py", dep["downstream"])

    def test_excludes_backup_files_from_graph_and_matches(self):
        backup = self.project / "backups"
        backup.mkdir()
        (backup / "legacy_helper.py").write_text(
            "def calculate(value):\n    return value - 999\n", encoding="utf-8"
        )
        report = self.report()
        self.assertEqual(report["reader"]["file_count_returned"], 2)
        self.assertEqual(report["reader"]["file_count_after_backup_filter"], 2)
        self.assertEqual(report["reader"]["eligible_candidates"], 2)
        self.assertEqual(report["graph"]["screened_source_files"], 2)
        self.assertFalse(any(
            "backups" in x["path"] for x in report["route"] + report["matches"] + report["excerpts"]
        ))
        self.assertFalse(any(
            "backups" in n for d in report["graph"]["dependencies"]
            for n in [d["path"], *d["upstream"], *d["downstream"]]
        ))

    def test_snapshot_exposes_screened_inventory_not_denied_sources(self):
        (self.project / "study_notes.md").write_text(
            "# Clinical research notes\nRelevant study methods\n", encoding="utf-8")
        (self.project / "suspicious_source.py").write_text(
            "FAKE_UNSCREENED_SECRET\n", encoding="utf-8")
        report = self.report(goal="research clinical study notes")
        self.assertTrue(report["reader"]["research_intent"])
        self.assertEqual(report["reader"]["screen_denied_count"], 1)
        paths = [x["path"] for x in report["selected_sources"]]
        self.assertIn("study_notes.md", paths)
        self.assertNotIn("suspicious_source.py", paths)
        self.assertIn("REV11_CONTENT_SCREENING_EXCLUSIONS", report["gaps"])
        self.assertNotIn("FAKE_UNSCREENED_SECRET", json.dumps(report))

    def test_rejects_untrusted_project_roots(self):
        for name in ("", "../bad", ".hidden", "/tmp", "x/y", "a"*65, None):
            with self.subTest(name=name), self.assertRaises(context.ContextSnapshotError):
                self.report(project=name)
        (self.workspace / "linked").symlink_to(self.project, target_is_directory=True)
        with self.assertRaises(context.ContextSnapshotError):
            self.report(project="linked")

    def test_rejects_bad_or_overlong_goals(self):
        for goal in ("", " ", "X"*401, None):
            with self.subTest(goal=goal), self.assertRaises(context.ContextSnapshotError):
                self.report(goal=goal)

    def test_persists_snapshot_without_modifying_project(self):
        before = {x.name: x.read_bytes() for x in self.project.iterdir() if x.is_file()}
        out = context.save_context_snapshot(
            {"id": "snapshot_test_20261115", "project": "demo-project",
             "goal": "find calculate failure"},
            self.results, self.workspace, self.workspace,
        )
        self.assertEqual(out["project"], "demo-project")
        raw = (self.results / "snapshot_test_20261115.raw").read_bytes()
        self.assertEqual(out["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(json.loads(raw)["graph"]["screened_source_files"], 2)
        after = {x.name: x.read_bytes() for x in self.project.iterdir() if x.is_file()}
        self.assertEqual(before, after)

    def test_snapshot_can_be_retrieved_by_verified_id(self):
        source = "snapshot_test_20261115"
        meta = context.save_context_snapshot(
            {"id": source, "project": "demo-project",
             "goal": "calculate failure"},
            self.results, self.workspace, self.workspace,
        )
        (self.state / "requests.json").write_text(json.dumps({
            source: {"status": "completed", "sha256": "a"*64},
        }))
        (self.results / (source + ".json")).write_text(json.dumps({
            "status": "completed", "action": "context_snapshot", "result": meta,
        }))
        packet = read_result(
            self.results,
            request_id="read_snapshot_20261115",
            source_id=source,
            offset=0, max_bytes=160,
        )
        self.assertTrue(packet["content"].startswith("{"))
        self.assertEqual(packet["sha256"], meta["sha256"])

    def test_does_not_overwrite_existing_snapshot(self):
        source = "snapshot_test_20261115"
        req = {"id": source, "project": "demo-project", "goal": "find calculate failure"}
        context.save_context_snapshot(req, self.results, self.workspace, self.workspace)
        with self.assertRaises(FileExistsError):
            context.save_context_snapshot(req, self.results, self.workspace, self.workspace)


if __name__ == "__main__":
    unittest.main()
