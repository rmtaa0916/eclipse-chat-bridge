#!/usr/bin/env python3
"""ECLIPSE bridge guardian. Does not submit ChatGPT/Gemini critic prompts."""
from __future__ import annotations
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

WATCHER = "/root/projects/eclipse-chat-bridge/watch.py"
GEMINI_DOC = os.environ.get("ECLIPSE_GEMINI_DOC_ID", "")
WATCH_ARGS = [sys.executable, "-u", WATCHER, "--housekeeping"] + (["--gemini-doc-id", GEMINI_DOC] if GEMINI_DOC else [])
STATE = Path("/root/.local/state/eclipse-chat-bridge")
STATUS = STATE / "supervisor-health.json"
LOCK = STATE / "supervisor.lock"
RESULTS = STATE / "results"
STOP = False

def utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def existing_watchers():
    """Only count a real, separate watch.py argv; never match a shell string."""
    found = []
    for ent in Path("/proc").iterdir():
        if not ent.name.isdigit():
            continue
        try:
            argv = (ent / "cmdline").read_bytes().split(b"\0")
        except (OSError, PermissionError):
            continue
        if os.fsencode(WATCHER) in argv:
            found.append(int(ent.name))
    return sorted(set(found))

def last_result():
    try:
        paths = (p for p in RESULTS.iterdir() if p.is_file() and p.name.endswith(".raw"))
        newest = max(paths, key=lambda p: p.stat().st_mtime, default=None)
        if newest is None:
            return {"id": None, "age_seconds": None}
        return {"id": newest.stem, "age_seconds": round(time.time() - newest.stat().st_mtime, 1)}
    except OSError:
        return {"id": None, "age_seconds": None}

def publish(mode, watcher=None, pids=(), restarts=0, note=""):
    STATE.mkdir(parents=True, exist_ok=True)
    report = {
        "utc": utc(), "mode": mode, "supervisor_pid": os.getpid(),
        "managed_watcher_pid": watcher, "watcher_pids": list(pids),
        "restarts": restarts, "note": note, "last_result": last_result(),
        "critic_automatic_resume": False,
        "replay_uncertain_submissions": False,
    }
    tmp = STATUS.with_name(STATUS.name + "." + str(os.getpid()) + ".tmp")
    tmp.write_text(json.dumps(report, separators=(",", ":")) + "\n")
    os.replace(tmp, STATUS)

def signal_stop(*_):
    global STOP
    STOP = True

def main():
    STATE.mkdir(parents=True, exist_ok=True)
    if "--check" in sys.argv:
        print("SUPERVISOR_CHECK_OK")
        print("EXISTING_WATCHERS", existing_watchers())
        print("RECENT_RESULT", last_result())
        return 0
    fd = os.open(LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    while not STOP:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            # Another supervisor owns the lock. Never spawn another watcher.
            print("SUPERVISOR_LOCK_HELD_STANDBY", flush=True)
            time.sleep(30)
    if STOP:
        return 0
    signal.signal(signal.SIGTERM, signal_stop)
    signal.signal(signal.SIGINT, signal_stop)
    child = None
    restarts = 0
    attempts = []
    try:
        while not STOP:
            pids = existing_watchers()
            managed_pid = child.pid if child and child.poll() is None else None
            if child and managed_pid is None:
                print("MANAGED_WATCHER_EXIT", child.returncode, flush=True)
                child = None
            outside = [pid for pid in pids if pid != managed_pid]
            if outside:
                mode = "STANDBY_EXISTING_WATCHER" if managed_pid is None else "WARNING_MULTIPLE_WATCHERS"
                publish(mode, managed_pid, pids, restarts,
                        "Manual watcher active; no duplicate watcher will be started")
            elif child is None:
                now = time.monotonic()
                attempts = [t for t in attempts if now - t < 300]
                if len(attempts) >= 5:
                    publish("BACKOFF", None, pids, restarts, "Five starts in five minutes")
                else:
                    try:
                        child = subprocess.Popen(WATCH_ARGS, stdin=subprocess.DEVNULL)
                        attempts.append(now)
                        restarts += 1
                        print("MANAGED_WATCHER_STARTED", child.pid, flush=True)
                        publish("MANAGED_RUNNING", child.pid, existing_watchers(), restarts)
                    except OSError as exc:
                        publish("SPAWN_ERROR", None, pids, restarts, type(exc).__name__)
            else:
                publish("MANAGED_RUNNING", managed_pid, pids, restarts)
            for _ in range(10):
                if STOP:
                    break
                time.sleep(1)
    finally:
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                print("MANAGED_WATCHER_DID_NOT_EXIT_CLEANLY", flush=True)
        publish("STOPPED", None, existing_watchers(), restarts)
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
