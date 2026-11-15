#!/usr/bin/env python3
"""Watch one Google Doc for explicit, uniquely identified local requests."""
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
import time
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

DOC_ID = '1N_TYeHUTexHaU2eiZ40hMWsaNNl-GaZJ-6H1MxHPPYM'
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


def get_doc_metadata(client, doc_id):
    """Fast check for document revisionId without downloading body content."""
    if not hasattr(client, 'token_mgr') or not hasattr(client, 'opener'):
        return None
    try:
        token = client.token_mgr.get_access_token()
        url = f'https://docs.googleapis.com/v1/documents/{doc_id}?fields=revisionId'
        req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
        with client.opener.open(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return None


def sync_response_to_doc(client, doc_id, request_id, result):
    """Update only the dedicated replaceable latest-diagnostic slot."""
    try:
        return bool(replace_latest_diagnostic(client, doc_id, request_id, result))
    except Exception as exc:
        print(f'Warning: latest diagnostic slot could not be updated: {exc}', file=sys.stderr, flush=True)
        return False


def document_text(value):
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


def parse_requests(text):
    requests = []
    pattern = re.compile(re.escape(START) + r'\s*(.*?)\s*' + re.escape(END), re.S)
    for match in pattern.finditer(text):
        raw = match.group(1).strip()
        if raw.startswith('```') and raw.endswith('```'):
            raw = '\n'.join(raw.splitlines()[1:-1]).strip()
        if len(raw.encode()) > 32_000:
            continue
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and isinstance(value.get('id'), str) and ID.fullmatch(value['id']):
            requests.append(value)
    return requests


def checked_path(value):
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


def run_script(request, cwd, directory):
    script = request.get('script')
    timeout = request.get('timeout_seconds', 60)
    if not isinstance(script, str) or not script.strip() or len(script.encode()) > MAX_SCRIPT_BYTES:
        raise ValueError('script must contain 1–24000 bytes.')
    if type(timeout) is not int or not 1 <= timeout <= 120:
        raise ValueError('timeout_seconds must be between 1 and 120.')
    path = directory / (request['id'] + '.raw')
    timed_out = False
    with path.open('wb') as out:
        os.chmod(path, 0o600)
        process = subprocess.Popen(['/bin/bash', '-c', script], cwd=cwd, stdin=subprocess.DEVNULL,
                                   stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
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
    return {'exit_code': process.returncode, 'timeout_or_output_limit': timed_out,
            'output': data[:MAX_OUTPUT].decode('utf-8', 'replace'),
            'truncated': len(data) > MAX_OUTPUT, 'full_output_file': str(path)}


def execute(request, result_dir):
    op = request.get('action')
    if op == 'context_snapshot':
        return save_context_snapshot(request, result_dir, ROOT, CORE)
    if op == 'find_result':
        return find_result(
            result_dir,
            request_id=request.get('id'),
            source_id=request.get('source_id'),
            query=request.get('query'),
            start_offset=request.get('start_offset', 0),
            max_bytes=request.get('max_bytes', 240),
        )
    if op == 'read_result':
        return read_result(
            result_dir,
            request_id=request.get('id'),
            source_id=request.get('source_id'),
            offset=request.get('offset', 0),
            max_bytes=request.get('max_bytes', 240),
        )
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
        text = '\n'.join(f'{i}: {line}' for i, line in enumerate(lines[start-1:start-1+count], start))
        return {'path': str(p), 'total_lines': len(lines), 'start_line': start,
                'content': text[:MAX_OUTPUT], 'truncated': len(text) > MAX_OUTPUT}
    if op == 'list_files':
        p = checked_path(request.get('path', str(ROOT)))
        if not p.is_dir():
            raise ValueError('Path is not a directory.')
        items = sorted(x.name + ('/' if x.is_dir() else '') for x in p.iterdir()
                       if not x.name.startswith('.') and x.name not in {'token.json', 'credentials.json'})
        return {'path': str(p), 'entries': items[:300], 'truncated': len(items) > 300}
    if op == 'run':
        cwd = checked_path(request.get('cwd', '/root/projects/chat-run-docs'))
        if not cwd.is_dir():
            raise ValueError('cwd is not a directory.')
        return run_script(request, cwd, result_dir)
    raise ValueError('Unknown action; use read_file, list_files, read_result, find_result, context_snapshot, or run.')


def save_json(path, value):
    tmp = path.with_suffix('.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush(); os.fsync(stream.fileno())
    os.replace(tmp, path)


def set_clipboard_reliable(text):
    try:
        cp = subprocess.run([CLIP], input=text, text=True, capture_output=True, timeout=5)
        vg = subprocess.run([CLIP_GET], capture_output=True, text=True, timeout=5)
        if vg.returncode == 0 and vg.stdout.rstrip('\n') == text.rstrip('\n'):
            return True
    except Exception:
        pass
    # If background clipboard access was blocked by Android, use seamless ADB focus assist
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


def notify_start(request_id, request):
    action = request.get('action', 'task')
    toast_msg = f"ECLIPSE [RECEIVED]: {request_id[:20]} ({action})"
    try:
        subprocess.run([TOAST, '-s', '-g', 'top', toast_msg], capture_output=True, timeout=8)
    except Exception:
        pass
    try:
        content = f"Action: {action} | Ongoing execution in Termux..."
        subprocess.run([NOTIFY, '-t', f'ECLIPSE: Processing {request_id[:16]}...',
                        '-c', content, '--id', request_id[:20],
                        '--priority', 'high', '--ongoing'], capture_output=True, timeout=8)
    except Exception:
        pass


def deliver(request_id, result, result_dir, *, clipboard=True, doc_synced=False):
    text = 'ECLIPSE BRIDGE RESULT ' + request_id + '\n' + json.dumps(result, ensure_ascii=False, indent=2)
    output = result_dir / (request_id + '.txt')
    output.write_text(text, encoding='utf-8'); output.chmod(0o600)
    
    copied = set_clipboard_reliable(text) if clipboard else False
    
    summary = result.get('status', 'done')
    if result.get('action') == 'run' and isinstance(result.get('result'), dict) and 'exit_code' in result['result']:
        summary = f"exit {result['result']['exit_code']}"
    toast_msg = f"ECLIPSE [DONE]: {request_id[:20]} ({summary})"

    # Always fire toast notification
    try:
        subprocess.run([TOAST, '-s', '-g', 'top', toast_msg], capture_output=True, timeout=8)
    except Exception as exc:
        print(f'Toast unavailable: {exc}', file=sys.stderr, flush=True)

    # Always update Android system notification tray (dismissible, removes --ongoing)
    try:
        clip_note = "Google Doc updated" if doc_synced else ("clipboard ready" if copied else "saved locally; Google Doc sync unavailable")
        subprocess.run([NOTIFY, '-t', f'ECLIPSE: {summary}', '-c', f'Request {request_id[:24]} ({clip_note})',
                        '--id', request_id[:20], '--priority', 'high'], capture_output=True, timeout=8)
    except Exception:
        pass

    return copied, output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execution', choices=('confirm', 'auto'), default='auto',
                        help='Run document scripts automatically (default) or confirm scripts locally')
    parser.add_argument('--once', action='store_true', help='Check the document once and exit')
    parser.add_argument('--interval', type=int, default=5, help='Polling interval in seconds (default 5, minimum 3)')
    parser.add_argument('--doc-id', default=os.environ.get('ECLIPSE_DOC_ID', DOC_ID), help='Google Doc ID to monitor')
    parser.add_argument('--no-sync-doc', action='store_true', help='Do not sync diagnostics to Google Doc; use legacy clipboard delivery instead')
    args = parser.parse_args()
    if args.interval < 3:
        parser.error('interval must be at least 3 seconds')
    doc_id = args.doc_id
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700); STATE_DIR.chmod(0o700)
    results = STATE_DIR / 'results'; results.mkdir(exist_ok=True, mode=0o700)
    state_path = STATE_DIR / 'requests.json'
    with (STATE_DIR / 'watch.lock').open('a+') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('A watcher is already running.')
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        client = GoogleDocsClient()
        print(f'Watching Google Doc {doc_id}; scripts: {args.execution}; interval: {args.interval}s. Ctrl+C stops.', flush=True)
        for ident, receipt in state.items():
            if receipt.get('status') == 'running':
                print(f'Request {ident} was interrupted; inspect its saved output before issuing a new ID. It will not be rerun.', flush=True)
        last_revision = None
        while True:
            try:
                # Fast metadata check to avoid downloading entire document when unchanged
                meta = get_doc_metadata(client, doc_id)
                revision = meta.get('revisionId') if isinstance(meta, dict) else None
                if revision is not None and last_revision is not None and revision == last_revision:
                    if args.once:
                        return 0
                    time.sleep(args.interval)
                    continue

                requests = parse_requests(document_text(client.get_doc(doc_id)))
                if revision is not None:
                    last_revision = revision

                for request in requests:
                    ident = request['id']; fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
                    if ident in state:
                        if state[ident].get('sha256') != fingerprint:
                            print(f'Refused changed request with reused ID: {ident}', flush=True)
                        continue
                    action = request.get('action')
                    notify_start(ident, request)
                    if action == 'run' and args.execution == 'confirm':
                        print(f'\nRequest {ident}, cwd {request.get("cwd", ROOT)}:\n{request.get("script", "")}')
                        if input('Run this command locally? [y/N]: ').strip().lower() != 'y':
                            state[ident] = {'sha256': fingerprint, 'status': 'declined'}; save_json(state_path, state)
                            deliver(ident, {'status': 'declined'}, results)
                            continue
                    state[ident] = {'sha256': fingerprint, 'status': 'running'}; save_json(state_path, state)
                    try:
                        result = {'status': 'completed', 'action': action, 'result': execute(request, results)}
                    except Exception as exc:
                        result = {'status': 'error', 'action': action, 'error': f'{type(exc).__name__}: {exc}'}
                    save_json(results / (ident + '.json'), result)
                    state[ident]['status'] = result['status']; save_json(state_path, state)
                    synced = False
                    if not args.no_sync_doc:
                        synced = sync_response_to_doc(client, doc_id, ident, result)
                        if synced:
                            new_meta = get_doc_metadata(client, doc_id)
                            if isinstance(new_meta, dict) and new_meta.get('revisionId'):
                                last_revision = new_meta['revisionId']
                    copied, output = deliver(ident, result, results, clipboard=args.no_sync_doc,
                                             doc_synced=synced)
                    channel = "Google Doc latest slot" if synced else ("clipboard" if copied else "local result only")
                    print(f'{ident}: {result["status"]}; delivered via {channel}; saved to {output}', flush=True)
            except KeyboardInterrupt:
                print('\nWatcher stopped.', flush=True); return 0
            except Exception as exc:
                print(f'Watch error: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
                if args.once:
                    return 1
            if args.once:
                return 0
            time.sleep(args.interval)


if __name__ == '__main__':
    raise SystemExit(main())
