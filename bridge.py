#!/usr/bin/env python3
"""Unified ECLIPSE bridge entry point.

The launcher and service manager are native Termux components. This file
owns operator commands; watch.py retains the existing request/replay protocol.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
PREFIX = Path(os.environ.get("ECLIPSE_TERMUX_PREFIX", "/data/data/com.termux/files/usr"))
SERVICE = PREFIX / "var/service/eclipse-bridge"
STATE = Path(os.environ.get("ECLIPSE_BRIDGE_STATE", "/root/.local/state/eclipse-chat-bridge"))
WATCHER = Path(os.environ.get("ECLIPSE_BRIDGE_WATCHER_PATH", str(ROOT / "watch.py")))
SUPERVISOR = ROOT / "bridge_supervisor.py"

ACTIONS = ("menu", "start", "status", "doctor", "logs", "ui", "run", "supervise", "setup")


def capture(argv: list[str], timeout: int = 7) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, type(exc).__name__


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


def health_snapshot() -> dict:
    result = {"service": "UNKNOWN", "service_detail": "", "watcher_count": 0,
              "heartbeat": "UNKNOWN", "heartbeat_age_s": None,
              "supervisor": "UNKNOWN", "last_request": None, "recoveries": None}
    rc, output = capture([str(PREFIX / "bin/sv"), "status", str(SERVICE)])
    if rc == 0 and output.startswith("run:"):
        result["service"] = "RUNNING"
    elif output.startswith("down:") or rc != 0:
        result["service"] = "DOWN" if output.startswith("down:") else "UNAVAILABLE"
    result["service_detail"] = output[:160]
    file = STATE / "supervisor-health.json"
    try:
        data = json.loads(file.read_text())
    except (OSError, ValueError, TypeError):
        return result
    result["supervisor"] = data.get("mode") or "UNKNOWN"
    pids = data.get("watcher_pids") or []
    result["watcher_count"] = len([pid for pid in pids if isinstance(pid, int) and pid_alive(pid)])
    result["recoveries"] = data.get("restarts", 0)
    result["last_request"] = (data.get("last_result") or {}).get("id") if isinstance(data.get("last_result"), dict) else None
    try:
        stamp = datetime.fromisoformat(data["utc"])
        age = max(0, int((datetime.now(timezone.utc) - stamp).total_seconds()))
        result["heartbeat_age_s"] = age
        result["heartbeat"] = "FRESH" if age <= 90 else "STALE"
    except (TypeError, ValueError, KeyError):
        pass
    return result


def healthy(data: dict) -> bool:
    return (data["service"] == "RUNNING" and
            data["heartbeat"] == "FRESH" and
            data["watcher_count"] == 1 and
            data["supervisor"] in ("MANAGED_RUNNING", "STANDBY_EXISTING_WATCHER"))


def mark(value: bool) -> str:
    return "OK" if value else "CHECK"


def print_status(*, as_json: bool = False) -> dict:
    data = health_snapshot()
    if as_json:
        print(json.dumps({"ok": healthy(data), **data}, sort_keys=True))
    else:
        print("ECLIPSE BRIDGE  |  LOCAL STATUS")
        print("-" * 48)
        print(f"Termux service : {data['service']}")
        print(f"Watcher        : {data['watcher_count']} live")
        print(f"Supervisor     : {data['supervisor']}")
        print(f"Heartbeat      : {data['heartbeat']} ({data['heartbeat_age_s']} s)")
        print(f"Auto recoveries: {data['recoveries']}")
        print(f"Health         : {mark(healthy(data))}")
    return data


def doctor() -> int:
    data = print_status()
    print()
    print("DIAGNOSTICS  |  Read-only")
    print("-" * 48)
    checks = [
        ("Python", sys.version_info >= (3, 10)),
        ("Existing request watcher", WATCHER.is_file()),
        ("Guardian source", SUPERVISOR.is_file()),
        ("Core module", Path(os.environ.get("ECLIPSE_CORE_DIR", "/root/projects/chat-run-docs"), "chat_docs_core.py").is_file()),
        ("Helper modules", all((Path(os.environ.get("ECLIPSE_BRIDGE_HELPERS_DIR", "/root/projects/unified-bridge-lab")) / x).is_file()
                               for x in ("result_reader.py", "context_snapshot.py", "bridge_queue.py"))),
        ("Termux Services CLI", (PREFIX / "bin/sv").exists()),
        ("Service registered", (SERVICE / "run").exists()),
        ("Supervisor heartbeat", data["heartbeat"] == "FRESH"),
        ("Exactly one watcher", data["watcher_count"] == 1),
    ]
    for label, ok in checks:
        print(f"[{mark(ok):5s}] {label}")
    print("\nNote: Doze can interrupt network activity during screen sleep.")
    return 0 if all(ok for _, ok in checks) and healthy(data) else 1


def recent_logs(limit: int) -> int:
    paths = [SERVICE / "log/main/current", PREFIX / "var/log/sv/eclipse-bridge/current"]
    source = next((p for p in paths if p.is_file()), None)
    print("ECLIPSE BRIDGE  |  SERVICE LOGS")
    print("-" * 48)
    if source is None:
        print("No local service log found. The service can still be running.")
        return 1
    # Read last lines, no network or Google Docs interactions.
    for line in source.read_text(errors="replace").splitlines()[-max(1, min(limit, 40)):]:
        print(line[:240])
    return 0


def prepare_runtime_imports() -> None:
    """Give the preserved watcher its existing core and helper modules."""
    core = Path(os.environ.get("ECLIPSE_CORE_DIR", "/root/projects/chat-run-docs"))
    helpers = Path(os.environ.get("ECLIPSE_BRIDGE_HELPERS_DIR", "/root/projects/unified-bridge-lab"))
    required = {
        core: ("chat_docs_core.py",),
        helpers: ("result_reader.py", "context_snapshot.py", "bridge_queue.py"),
    }
    missing = [
        str(base / name)
        for base, modules in required.items()
        for name in modules
        if not (base / name).is_file()
    ]
    if missing:
        raise RuntimeError("Bridge module dependencies missing: " + ", ".join(missing))
    current = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, (str(core), str(helpers), current)))
    config_path = Path(os.environ.get("ECLIPSE_BRIDGE_PRIVATE_CONFIG", "/root/.config/eclipse-bridge/runtime.json"))
    if not os.environ.get("ECLIPSE_GEMINI_DOC_ID") and config_path.is_file():
        if config_path.stat().st_mode & 0o077:
            raise RuntimeError("Private bridge config permissions must be 0600")
        config = json.loads(config_path.read_text())
        doc_id = config.get("gemini_doc_id", "")
        if doc_id and re.fullmatch(r"[A-Za-z0-9_-]{20,120}", doc_id):
            os.environ["ECLIPSE_GEMINI_DOC_ID"] = doc_id


def direct_run(argv: list[str]) -> int:
    data = health_snapshot()
    if data["service"] == "RUNNING" or data["watcher_count"] > 0:
        print("Bridge service already running; direct run would risk a duplicate.")
        print("Use BRIDGE status, BRIDGE ui, or BRIDGE doctor.")
        return 3
    if not WATCHER.is_file():
        print("Bridge watcher source not found.")
        return 2
    try:
        prepare_runtime_imports()
    except RuntimeError as exc:
        print(str(exc))
        return 2
    os.execv(sys.executable, [sys.executable, "-u", str(WATCHER), *argv])
    return 0


def supervise(*, managed_service: bool = False) -> int:
    if not managed_service and os.environ.get("ECLIPSE_BRIDGE_RUNIT") != "1":
        data = health_snapshot()
        if data["service"] == "RUNNING":
            print("Supervision is already managed by Termux Services.")
            return 0
        print("Foreground supervision is reserved for the service launcher.")
        print("Use BRIDGE start from native Termux.")
        return 3
    if not SUPERVISOR.is_file():
        print("Supervisor source unavailable.")
        return 2
    try:
        prepare_runtime_imports()
    except RuntimeError as exc:
        print(str(exc))
        return 2
    os.execv(sys.executable, [sys.executable, "-u", str(SUPERVISOR)])
    return 0


def ensure_background_menu() -> int:
    data = health_snapshot()
    if data["service"] == "RUNNING":
        print("Bridge service is already running; no duplicate will be started.")
        print_status()
        return 0
    status, response = capture([str(PREFIX / "bin/sv"), "up", str(SERVICE)], timeout=8)
    print("Service start:", "requested" if status == 0 else "unavailable")
    result = print_status()
    return 0 if result["service"] == "RUNNING" else 1


def show_menu() -> int:
    # ANSI only for a real interactive TTY. Pipe/CI is a clean status report.
    if not sys.stdin.isatty():
        return 0 if healthy(print_status()) else 1
    while True:
        data = health_snapshot()
        os.system("clear" if os.environ.get("TERM", "") else "true")
        print("  E C L I P S E   |   B R I D G E")
        print("  Background control center")
        print("  " + "-" * 44)
        print(f"  SERVICE   {data['service']:<13} WATCHER   {data['watcher_count']}")
        print(f"  GUARDIAN  {data['supervisor'][:22]:<22}")
        print(f"  HEARTBEAT {data['heartbeat']:<13} RECOVERIES {data['recoveries']}")
        print("  " + "-" * 44)
        print("  1  Start / check background bridge")
        print("  2  View full bridge status")
        print("  3  Run health diagnostics")
        print("  4  Open existing live monitor")
        print("  5  View local service logs")
        print("  6  Show setup and command guide")
        print("  0  Exit menu (bridge keeps running)")
        print()
        try:
            choice = input("  Select: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBridge continues running in background.")
            return 0
        if choice == "0":
            print("Bridge continues running in background.")
            return 0
        if choice == "1":
            ensure_background_menu()
        elif choice == "2":
            print_status()
        elif choice == "3":
            doctor()
        elif choice == "4":
            return open_legacy_ui()
        elif choice == "5":
            recent_logs(12)
        elif choice == "6":
            print_setup()
            print("Other commands: BRIDGE run, BRIDGE supervise, BRIDGE --help")
        else:
            print("Invalid selection.")
        try:
            input("\n  Press Enter to return...")
        except (EOFError, KeyboardInterrupt):
            return 0


def open_legacy_ui() -> int:
    try:
        import bridge_ui
        return bridge_ui.main() or 0
    except (ImportError, AttributeError, OSError) as exc:
        print("Live monitor is unavailable:", type(exc).__name__)
        return 2


def print_setup() -> int:
    data = health_snapshot()
    print("ECLIPSE BRIDGE  |  ONE-TIME SETUP")
    print("-" * 48)
    print(f"Termux Services: {mark((PREFIX / 'bin/sv').exists())}")
    print(f"Service folder : {mark((SERVICE / 'run').exists())}")
    print(f"Current service: {data['service']}")
    print("BRIDGE (native Termux) will use the installed service.")
    print("Termux:Boot is separate and must be installed before reboot auto-start.")
    print("Wake-lock helps CPU continuity but does not bypass Android Doze.")
    print("No setup scripts or service files were changed.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="BRIDGE", description="Unified ECLIPSE bridge controls")
    parser.add_argument("command", nargs="?", default="menu", choices=ACTIONS)
    parser.add_argument("extra", nargs="*")
    parser.add_argument("--service", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--lines", type=int, default=15)
    ns = parser.parse_args(argv)
    cmd = ns.command
    if cmd == "menu":
        return show_menu()
    if cmd == "status":
        print_status(as_json=ns.json)
        return 0
    if cmd == "doctor":
        return doctor()
    if cmd == "logs":
        return recent_logs(ns.lines)
    if cmd == "ui":
        return open_legacy_ui()
    if cmd == "setup":
        return print_setup()
    if cmd == "run":
        return direct_run(ns.extra)
    if cmd == "supervise":
        return supervise(managed_service=ns.service)
    if cmd == "start":
        print("Start is managed by the native Termux BRIDGE launcher.")
        data = print_status()
        return 0 if data["service"] == "RUNNING" else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
