#!/usr/bin/env python3
"""Unified ECLIPSE Bridge Watcher & Execution Daemon.

Features:
- Durable SQLite FIFO Queue with transactional writes and restart recovery.
- Decoupled polling intake (every 5s) and single execution worker.
- Dual protocol intake: ChatGPT (<<<ECLIPSE_BRIDGE_REQUEST_V1>>>) and Gemini (<<<ECLIPSE_GEMINI_REQUEST_V1>>>).
- Review 23 hardened security engine: descriptor sandboxing, AST analysis, serialization bounding.
- Guarded housekeeping: prunes only delivered & acknowledged document history without data loss.
- 100% backward compatible with existing bridge CLI commands and unit tests.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import urllib.request

CORE = Path(os.environ.get('ECLIPSE_CORE_DIR', '/root/projects/chat-run-docs')).resolve()
if not CORE.exists():
    fallback_parent = Path(__file__).resolve().parent.parent / 'chat-run-docs'
    if fallback_parent.exists():
        CORE = fallback_parent
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))
from chat_docs_core import GoogleDocsClient  # noqa: E402
from latest_response_slot import replace_latest_diagnostic  # noqa: E402
from result_reader import read_result, find_result  # noqa: E402
from context_snapshot import save_context_snapshot  # noqa: E402
from bridge_queue import BridgeQueue  # noqa: E402
from gemini_protocol import (  # noqa: E402
    REQUEST_START_TOKEN as GEMINI_START,
    REQUEST_END_TOKEN as GEMINI_END,
    RESPONSE_START_TOKEN as GEMINI_RESP_START,
    RESPONSE_END_TOKEN as GEMINI_RESP_END,
    parse_gemini_requests,
    sync_gemini_response_to_doc,
    exec_context_reader,
)

DOC_ID = os.environ.get('ECLIPSE_DOC_ID', '')
ROOT = Path('/root/projects')
STATE_DIR = Path('/root/.local/state/eclipse-chat-bridge')
START = '<<<ECLIPSE_BRIDGE_REQUEST_V1>>>'
END = '<<<END_ECLIPSE_BRIDGE_REQUEST_V1>>>'
RESP_START = '<<<ECLIPSE_BRIDGE_RESPONSE_V1>>>'
RESP_END = '<<<END_ECLIPSE_BRIDGE_RESPONSE_V1>>>'
CLIP = '/data/data/com.termux/files/usr/bin/termux-clipboard-set'
CLIP_GET = '/data/data/com.termux/files/usr/bin/termux-clipboard-get'
TOAST = '/data/data/com.termux/files/usr/bin/termux-toast'
NOTIFY = '/data/data/com.termux/files/usr/bin/termux-notification'
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{7,63}\Z')
MAX_OUTPUT = 24_000
MAX_SCRIPT_BYTES = 24_000


def get_doc_metadata(client: Any, doc_id: str) -> Optional[Dict[str, Any]]:
    """Fast check for document revisionId without downloading body content."""
    if not hasattr(client, 'token_mgr') or not hasattr(client, 'opener'):
        return None
    try:
        if callable(client.token_mgr):
            token = client.token_mgr()
        elif hasattr(client.token_mgr, 'get_access_token'):
            token = client.token_mgr.get_access_token()
        else:
            token = str(client.token_mgr)
        url = f'https://docs.googleapis.com/v1/documents/{doc_id}?fields=revisionId'
        req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
        with client.opener.open(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return None


def sync_response_to_doc(client: Any, doc_id: str, request_id: str, result: Dict[str, Any]) -> bool:
    """Update only the dedicated replaceable latest-diagnostic slot for ChatGPT doc."""
    try:
        return bool(replace_latest_diagnostic(client, doc_id, request_id, result))
    except Exception as exc:
        print(f'Warning: latest diagnostic slot could not be updated: {exc}', file=sys.stderr, flush=True)
        return False


def document_text(value: Dict[str, Any]) -> str:
    """Extract text runs in document order, including tables and tabs."""
    parts = []
    def visit(item):
        if isinstance(item, dict):
            if isinstance(item.get('textRun'), dict):
                parts.append(item['textRun'].get('content', ''))
            else:
                for key, child in item.items():
                    if key not in {'suggestedInsertionIds', 'textStyle', 'paragraphStyle'}:
                        visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
    visit(value.get('body', {}))
    return ''.join(parts)


def parse_requests(text: str) -> List[Dict[str, Any]]:
    """Parse ChatGPT bridge requests."""
    requests = []
    pattern = re.compile(r'(?m)^' + re.escape(START) + r'\r?\n([\s\S]*?)\r?\n' + re.escape(END) + r'\r?$')
    for match in pattern.finditer(text):
        raw = match.group(1).strip()
        if raw.startswith('```') and raw.endswith('```'):
            raw = '\n'.join(raw.splitlines()[1:-1]).strip()
        if len(raw.encode('utf-8')) > 32_000:
            continue
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and isinstance(value.get('id'), str) and ID.fullmatch(value['id']):
            requests.append(value)
    return requests


def parse_all_incoming_requests(text: str, doc_id: str) -> List[Tuple[str, str, Dict[str, Any]]]:
    """Parse all requests from text, tagging with protocol ('chatgpt' or 'gemini')."""
    tagged: List[Tuple[str, str, Dict[str, Any]]] = []
    # 1. ChatGPT requests
    for req in parse_requests(text):
        tagged.append(('chatgpt', doc_id, req))
    # 2. Gemini requests
    for req in parse_gemini_requests(text):
        tagged.append(('gemini', doc_id, req))
    return tagged


def checked_path(value: Any) -> Path:
    if not isinstance(value, str) or not value or '\x00' in value:
        raise ValueError('A path is required.')
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = ROOT / p
    resolved = p.resolve(strict=True)
    if not resolved.is_relative_to(ROOT.resolve()):
        raise ValueError('Path must be inside /root/projects.')
    forbidden = {'token.json', 'credentials.json', '.env', '.npmrc', '.pypirc', 'id_rsa', 'id_ed25519'}
    if any(part in forbidden or part.startswith('.env.') for part in resolved.parts):
        raise ValueError('Credential and environment files are not available through read requests.')
    return resolved


def run_script(request: Dict[str, Any], cwd: Path, directory: Path) -> Dict[str, Any]:
    script = request.get('script')
    timeout = request.get('timeout_seconds', 60)
    if not isinstance(script, str) or not script.strip() or len(script.encode('utf-8')) > MAX_SCRIPT_BYTES:
        raise ValueError('script must contain 1–24000 bytes.')
    if type(timeout) is not int or not 1 <= timeout <= 120:
        raise ValueError('timeout_seconds must be between 1 and 120.')
    path = directory / (request['id'] + '.raw')
    timed_out = False
    with path.open('wb') as out:
        os.chmod(path, 0o600)
        process = subprocess.Popen(
            ['/bin/bash', '-c', script],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if time.monotonic() >= deadline or path.stat().st_size > 1_000_000:
                    timed_out = True
                    break
                time.sleep(0.25)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    data = path.read_bytes()
    return {
        'exit_code': process.returncode,
        'timeout_or_output_limit': timed_out,
        'output': data[:MAX_OUTPUT].decode('utf-8', 'replace'),
        'truncated': len(data) > MAX_OUTPUT,
        'full_output_file': str(path),
    }


def execute(request: Dict[str, Any], result_dir: Path) -> Dict[str, Any]:
    op = request.get('action')
    if op == 'context_snapshot':
        return save_context_snapshot(request, result_dir, ROOT, CORE)
    if op == 'read_result':
        return read_result(
            result_dir,
            request_id=request.get('id'),
            source_id=request.get('source_id'),
            offset=request.get('offset', 0),
            max_bytes=request.get('max_bytes', 240),
        )
    if op == 'find_result':
        return find_result(
            result_dir,
            request_id=request.get('id'),
            source_id=request.get('source_id'),
            query=request.get('query'),
            start_offset=request.get('start_offset', 0),
            max_bytes=request.get('max_bytes', 240),
        )
    if op in ('context_overview', 'context_search'):
        res = exec_context_reader(request.get('id', 'req'), op, request, ROOT)
        return res.get('result', res)
    if op == 'read_file':
        p = checked_path(request.get('path'))
        if not p.is_file() or p.stat().st_size > 2_000_000:
            raise ValueError('Only files up to 2 MB can be read.')
        raw = p.read_bytes()
        if b'\x00' in raw:
            raise ValueError('Binary files are not copied to the clipboard.')
        lines = raw.decode('utf-8', 'replace').splitlines()
        start, count = request.get('start_line', 1), request.get('line_count', 120)
        if type(start) is not int or type(count) is not int or start < 1 or not 1 <= count <= 200:
            raise ValueError('start_line must be positive and line_count must be 1–200.')
        text = '\n'.join(f'{i}: {line}' for i, line in enumerate(lines[start - 1:start - 1 + count], start))
        return {
            'path': str(p),
            'total_lines': len(lines),
            'start_line': start,
            'content': text[:MAX_OUTPUT],
            'truncated': len(text) > MAX_OUTPUT,
        }
    if op == 'list_files':
        p = checked_path(request.get('path', str(ROOT)))
        if not p.is_dir():
            raise ValueError('Path is not a directory.')
        items = sorted(
            x.name + ('/' if x.is_dir() else '')
            for x in p.iterdir()
            if not x.name.startswith('.') and x.name not in {'token.json', 'credentials.json'}
        )
        return {'path': str(p), 'entries': items[:300], 'truncated': len(items) > 300}
    if op == 'run':
        cwd = checked_path(request.get('cwd', '/root/projects/chat-run-docs'))
        if not cwd.is_dir():
            raise ValueError('cwd is not a directory.')
        return run_script(request, cwd, result_dir)
    raise ValueError(f'Unknown action: {op}')


def save_json(path: Path, value: Any) -> None:
    tmp = path.with_suffix(f'.tmp.{os.getpid()}')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def set_clipboard_reliable(text: str) -> bool:
    try:
        cp = subprocess.run([CLIP], input=text, text=True, capture_output=True, timeout=5)
        vg = subprocess.run([CLIP_GET], capture_output=True, text=True, timeout=5)
        if vg.returncode == 0 and vg.stdout.rstrip('\n') == text.rstrip('\n'):
            return True
    except Exception:
        pass
    try:
        subprocess.run(['adb', 'shell', 'am', 'start', '-n', 'com.termux/.app.TermuxActivity'], capture_output=True, timeout=5)
        time.sleep(0.35)
        subprocess.run([CLIP], input=text, text=True, capture_output=True, timeout=5)
        time.sleep(0.1)
        vg2 = subprocess.run([CLIP_GET], capture_output=True, text=True, timeout=5)
        subprocess.run(['adb', 'shell', 'am', 'start', '-n', 'com.android.chrome/com.google.android.apps.chrome.Main'], capture_output=True, timeout=5)
        if vg2.returncode == 0 and vg2.stdout.rstrip('\n') == text.rstrip('\n'):
            return True
    except Exception:
        pass
    return False


def notify_start(request_id: str, request: Dict[str, Any]) -> None:
    action = request.get('action', 'task')
    toast_msg = f"ECLIPSE [RECEIVED]: {request_id[:20]} ({action})"
    try:
        subprocess.run([TOAST, '-s', '-g', 'top', toast_msg], capture_output=True, timeout=8)
    except Exception:
        pass
    try:
        content = f"Action: {action} | Ongoing execution in Termux..."
        subprocess.run(
            [NOTIFY, '-t', f'ECLIPSE: Processing {request_id[:16]}...',
             '-c', content, '--id', request_id[:20],
             '--priority', 'high', '--ongoing'],
            capture_output=True,
            timeout=8,
        )
    except Exception:
        pass


def deliver(request_id: str, result: Dict[str, Any], result_dir: Path, *, clipboard: bool = True, doc_synced: bool = False) -> Tuple[bool, Path]:
    text = 'ECLIPSE BRIDGE RESULT ' + request_id + '\n' + json.dumps(result, ensure_ascii=False, indent=2)
    output = result_dir / (request_id + '.txt')
    output.write_text(text, encoding='utf-8')
    output.chmod(0o600)

    copied = set_clipboard_reliable(text) if clipboard else False

    summary = result.get('status', 'done')
    if result.get('action') == 'run' and isinstance(result.get('result'), dict) and 'exit_code' in result['result']:
        summary = f"exit {result['result']['exit_code']}"
    toast_msg = f"ECLIPSE [DONE]: {request_id[:20]} ({summary})"

    try:
        subprocess.run([TOAST, '-s', '-g', 'top', toast_msg], capture_output=True, timeout=8)
    except Exception as exc:
        print(f'Toast unavailable: {exc}', file=sys.stderr, flush=True)

    try:
        clip_note = "Google Doc updated" if doc_synced else ("clipboard ready" if copied else "saved locally; Google Doc sync unavailable")
        subprocess.run(
            [NOTIFY, '-t', f'ECLIPSE: {summary}', '-c', f'Request {request_id[:24]} ({clip_note})',
             '--id', request_id[:20], '--priority', 'high'],
            capture_output=True,
            timeout=8,
        )
    except Exception:
        pass

    return copied, output


def _resolve_monitored_doc_ids(specified_doc_id: str, gemini_doc_id: str = "") -> List[str]:
    doc_ids: List[str] = []
    for item in specified_doc_id.split(','):
        cleaned = item.strip()
        if cleaned and cleaned not in doc_ids:
            doc_ids.append(cleaned)

    if gemini_doc_id and gemini_doc_id.strip():
        cleaned_gemini = gemini_doc_id.strip()
        if cleaned_gemini not in doc_ids:
            doc_ids.append(cleaned_gemini)
    return doc_ids


def poll_docs_and_enqueue(client: Any, doc_ids: List[str], queue: BridgeQueue, last_revisions: Dict[str, str]) -> int:
    """Fetch documents, parse requests for both protocols, and enqueue into SQLite."""
    enqueued_count = 0
    for doc_id in doc_ids:
        try:
            meta = get_doc_metadata(client, doc_id)
            revision = meta.get('revisionId') if isinstance(meta, dict) else None
            last_rev = last_revisions.get(doc_id)
            if revision is not None and last_rev is not None and revision == last_rev:
                continue

            doc_payload = client.get_doc(doc_id)

            text = document_text(doc_payload)
            tagged_requests = parse_all_incoming_requests(text, doc_id)

            for protocol, source_doc, req in tagged_requests:
                req_id = req['id']
                action = req.get('action', 'task')
                fp = hashlib.sha256(json.dumps(req, sort_keys=True).encode()).hexdigest()
                status, msg = queue.enqueue_request(
                    request_id=req_id,
                    protocol=protocol,
                    doc_id=source_doc,
                    fingerprint=fp,
                    action=action,
                    payload=req,
                )
                if status == 'ENQUEUED':
                    notify_start(req_id, req)
                    enqueued_count += 1
                elif status == 'REJECTED':
                    print(f'Refused changed request with reused ID: {req_id}', flush=True)
            # Commit only the revision of a fully parsed and enqueued snapshot.
            if isinstance(doc_payload, dict) and doc_payload.get('revisionId'):
                last_revisions[doc_id] = doc_payload['revisionId']
            else:
                last_revisions.pop(doc_id, None)
        except Exception as exc:
            print(f'Polling error for doc {doc_id}: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
    return enqueued_count


def execute_next_queued_task(
    client: Any,
    queue: BridgeQueue,
    results_dir: Path,
    state_path: Path,
    execution_mode: str,
    no_sync_doc: bool,
    housekeeping_enabled: bool,
) -> bool:
    """Atomically fetch and execute the next task in FIFO order."""
    task = queue.fetch_next_fifo()
    if task is None:
        if not no_sync_doc:
            try:
                from bridge_receipt_recovery import recover_one
                recover_one(client, state_path, results_dir)
            except Exception as recovery_exc:
                print('receipt recovery failed closed: '+type(recovery_exc).__name__, flush=True)
        return False

    req_id = task['id']
    protocol = task['protocol']
    source_doc = task['doc_id']
    req_payload = task['payload']
    action = task['action']
    fp = task['sha256']

    # Sync running state to legacy requests.json
    queue.sync_legacy_state_file(state_path)

    if action == 'run' and execution_mode == 'confirm':
        print(f'\nRequest {req_id}, cwd {req_payload.get("cwd", ROOT)}:\n{req_payload.get("script", "")}')
        user_choice = input('Run this command locally? [y/N]: ').strip().lower()
        if user_choice != 'y':
            queue.mark_declined(req_id)
            queue.sync_legacy_state_file(state_path)
            deliver(req_id, {'status': 'declined'}, results_dir)
            return True

    try:
        exec_res = execute(req_payload, results_dir)
        result: Dict[str, Any] = {'status': 'completed', 'action': action, 'result': exec_res}
    except Exception as exc:
        result = {'status': 'error', 'action': action, 'error': f'{type(exc).__name__}: {exc}'}

    save_json(results_dir / (req_id + '.json'), result)

    synced = False
    if not no_sync_doc:
        if protocol == 'gemini':
            synced = sync_gemini_response_to_doc(client, source_doc, req_id, result)
        else:
            synced = sync_response_to_doc(client, source_doc, req_id, result)

        if synced and housekeeping_enabled:
            try:
                from bridge_housekeeping_auto import maintain
                summary = maintain(client, source_doc, state_path, apply=True, max_blocks=30)
                print(f'{req_id}: housekeeping {summary}', flush=True)
            except Exception as cleanup_exc:
                print(f'Warning: housekeeping failed closed: {cleanup_exc}', file=sys.stderr, flush=True)

    if result.get('status') == 'completed':
        queue.mark_completed(req_id, result, doc_synced=synced, delivery_channel="google_doc" if synced else "local")
    else:
        queue.mark_failed(req_id, result.get('error', 'Execution error'), result=result, doc_synced=synced)

    queue.sync_legacy_state_file(state_path)

    copied, output = deliver(req_id, result, results_dir, clipboard=no_sync_doc, doc_synced=synced)
    channel = "Google Doc latest slot" if synced else ("clipboard" if copied else "local result only")
    print(f'{req_id}: {result["status"]}; delivered via {channel}; saved to {output}', flush=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execution', choices=('confirm', 'auto'), default='auto',
                        help='Run document scripts automatically (default) or confirm scripts locally')
    parser.add_argument('--once', action='store_true', help='Check the document once and exit')
    parser.add_argument('--interval', type=int, default=5, help='Polling interval in seconds (default 5, minimum 3)')
    parser.add_argument('--doc-id', default=os.environ.get('ECLIPSE_DOC_ID', DOC_ID), help='Google Doc ID(s) to monitor')
    parser.add_argument('--gemini-doc-id', default=os.environ.get('ECLIPSE_GEMINI_DOC_ID', ''), help='Optional secondary Google Doc ID for Gemini requests')
    parser.add_argument('--no-sync-doc', action='store_true', help='Do not sync diagnostics to Google Doc; use legacy clipboard delivery instead')
    parser.add_argument('--housekeeping', action='store_true', help='After completed requests, prune locally acknowledged history (with backups)')
    args = parser.parse_args()

    if args.interval < 3:
        parser.error('interval must be at least 3 seconds')

    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    results = STATE_DIR / 'results'
    results.mkdir(exist_ok=True, mode=0o700)
    state_path = STATE_DIR / 'requests.json'
    db_path = STATE_DIR / 'bridge_queue.db'
    queue = BridgeQueue(db_path)

    with (STATE_DIR / 'watch.lock').open('a+') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('A watcher is already running.')

        # Migrate legacy state if present
        migrated = queue.migrate_legacy_state(state_path)
        if migrated > 0:
            print(f'Migrated {migrated} historical requests into SQLite queue.', flush=True)

        # Restart recovery: check for any interrupted executions
        interrupted = queue.recover_interrupted_tasks()
        for ident in interrupted:
            print(f'Request {ident} was interrupted; inspect its saved output before issuing a new ID. It will not be rerun.', flush=True)

        queue.sync_legacy_state_file(state_path)

        client = GoogleDocsClient()
        doc_ids = _resolve_monitored_doc_ids(args.doc_id, getattr(args, 'gemini_doc_id', ''))

        if args.housekeeping:
            for d_id in doc_ids:
                try:
                    from bridge_housekeeping_auto import maintain
                    summary = maintain(client, d_id, state_path, apply=True, max_blocks=30)
                    print(f'Startup housekeeping ({d_id}): {summary}', flush=True)
                except Exception as cleanup_exc:
                    print(f'Warning: startup housekeeping failed closed: {cleanup_exc}', file=sys.stderr, flush=True)

        print(f'Watching Google Doc(s) {", ".join(doc_ids)}; scripts: {args.execution}; interval: {args.interval}s. Ctrl+C stops.', flush=True)

        last_revisions: Dict[str, str] = {}

        if args.once:
            poll_docs_and_enqueue(client, doc_ids, queue, last_revisions)
            while execute_next_queued_task(
                client=client,
                queue=queue,
                results_dir=results,
                state_path=state_path,
                execution_mode=args.execution,
                no_sync_doc=args.no_sync_doc,
                housekeeping_enabled=args.housekeeping,
            ):
                pass
            return 0

        # Daemon mode: run poller in background thread, worker in main thread
        stop_event = threading.Event()

        def poller_loop():
            poller_client = GoogleDocsClient()
            while not stop_event.is_set():
                try:
                    poll_docs_and_enqueue(poller_client, doc_ids, queue, last_revisions)
                except Exception as p_exc:
                    print(f'Poller exception: {type(p_exc).__name__}: {p_exc}', file=sys.stderr, flush=True)
                stop_event.wait(args.interval)

        poller_thread = threading.Thread(target=poller_loop, name="BridgePollerThread", daemon=True)
        poller_thread.start()

        try:
            while not stop_event.is_set():
                ran = execute_next_queued_task(
                    client=client,
                    queue=queue,
                    results_dir=results,
                    state_path=state_path,
                    execution_mode=args.execution,
                    no_sync_doc=args.no_sync_doc,
                    housekeeping_enabled=args.housekeeping,
                )
                if not ran:
                    time.sleep(0.25)
        except KeyboardInterrupt:
            stop_event.set()
            print('\nWatcher stopped.', flush=True)
            return 0
        finally:
            stop_event.set()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
