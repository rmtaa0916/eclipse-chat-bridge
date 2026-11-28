"""Read-only monitor evidence: real watcher argv, SQLite, and supervisor heartbeat."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


def probe_watchers(script, proc_root=Path('/proc')):
    expected = str(Path(script).resolve())
    found, arguments, denied = [], {}, False
    try:
        processes = list(Path(proc_root).iterdir())
    except OSError:
        return [], {}, 'UNKNOWN'
    for process in processes:
        if not process.name.isdigit():
            continue
        try:
            argv = (process / 'cmdline').read_bytes().split(b'\0')
        except PermissionError:
            denied = True
            continue
        except OSError:
            continue
        # Match a separate path argument, never a shell command containing watch.py.
        matches = expected.encode() in argv
        if not matches and b'watch.py' in argv:
            try:
                matches = str(((process / 'cwd').resolve(strict=True) / 'watch.py').resolve()) == expected
            except OSError:
                pass
        if matches:
            pid = int(process.name)
            found.append(pid)
            arguments[pid] = [x.decode(errors='replace') for x in argv if x]
    return sorted(found), arguments, 'PRESENT' if found else 'UNKNOWN' if denied else 'ABSENT'


def _supervisor(path):
    try:
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            return {}, False
        stamp = datetime.fromisoformat(value['utc'])
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
        return value, -5 <= age <= 90
    except (OSError, ValueError, KeyError, TypeError):
        return {}, False


def _queue(path):
    if not path.is_file():
        raise OSError('queue unavailable')
    conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=.4)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        columns = {x[1] for x in conn.execute('PRAGMA table_info(queue)')}
        if not {'id', 'status'} <= columns:
            raise ValueError('queue schema unavailable')
        fields = [x for x in ('id', 'status', 'enqueued_at', 'started_at', 'completed_at', 'doc_synced', 'protocol') if x in columns]
        order = 'enqueued_at' if 'enqueued_at' in columns else 'rowid'
        counts = {str(k).lower(): int(v) for k, v in conn.execute('SELECT status,count(*) FROM queue GROUP BY status')}
        recent = conn.execute('SELECT ' + ','.join(fields) + ' FROM queue ORDER BY ' + order + ' DESC LIMIT 40').fetchall()
        active = conn.execute('SELECT ' + ','.join(fields) + " FROM queue WHERE status IN ('RUNNING','QUEUED') ORDER BY " + order).fetchall()
        rows = {str(x['id']): dict(x) for x in [*reversed(recent), *active]}
        for value in rows.values():
            value['status'] = value['status'].lower()
        return rows, counts
    finally:
        conn.close()


def read_state(state_dir, script, doc_id='', gemini_id='', proc_root=Path('/proc')):
    root = Path(state_dir)
    pids, args, probe = probe_watchers(script, proc_root)
    supervisor, fresh = _supervisor(root / 'supervisor-health.json')
    try:
        requests, counts = _queue(root / 'bridge_queue.db')
        source = 'SQLite'
    except (OSError, sqlite3.Error, ValueError):
        try:
            requests = json.loads((root / 'requests.json').read_text())
            if not isinstance(requests, dict):
                requests = {}
        except (OSError, ValueError):
            requests = {}
        counts = {}
        for value in requests.values():
            if isinstance(value, dict):
                status = str(value.get('status', 'unknown')).lower()
                counts[status] = counts.get(status, 0) + 1
        source = 'Legacy snapshot'
    bindings = {'ChatGPT': doc_id, 'Gemini': gemini_id}
    for argv in args.values():
        for name, flag in [('ChatGPT', '--doc-id'), ('Gemini', '--gemini-doc-id')]:
            if flag in argv:
                i = argv.index(flag)
                bindings[name] = argv[i + 1] if i + 1 < len(argv) else ''
    providers = {name: bool(value) for name, value in bindings.items()}
    managed = fresh and supervisor.get('managed_watcher_pid') in pids
    return {'running': bool(pids), 'pid': pids[0] if pids else None, 'watcher_count': len(pids),
            'watcher_pids': pids, 'process_probe': probe, 'requests': requests, 'queue_source': source,
            'total': sum(counts.values()), 'completed': counts.get('completed', 0),
            'running_tasks': counts.get('running', 0), 'queued': counts.get('queued', 0),
            'errors': counts.get('failed', 0) + counts.get('error', 0),
            'interrupted': counts.get('interrupted', 0), 'declined': counts.get('declined', 0),
            'doc_id': bindings['ChatGPT'], 'gemini_doc_id': bindings['Gemini'],
            'providers': providers, 'supervisor_health': supervisor,
            'supervisor_fresh': fresh, 'managed': managed,
            'ownership': 'managed' if managed else 'existing watcher' if pids else 'not verified'}
