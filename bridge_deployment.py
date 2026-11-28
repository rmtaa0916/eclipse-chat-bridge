"""Verify operator-created reconciled deployment evidence without claiming Git cleanliness."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re

REQUIRED = frozenset({
    'watch.py', 'bridge.py', 'bridge_queue.py', 'bridge_supervisor.py',
    'bridge_housekeeping_auto.py', 'bridge_doc_sync.py', 'bridge_deployment.py',
    'bridge_presentation.py', 'bridge_ui_state.py',
    'bridge_receipt_recovery.py', 'bridge_ui.py', 'latest_response_slot.py',
    'docs/BRIDGE_CHATGPT.md', 'docs/BRIDGE_GEMINI.md', 'docs/BRIDGE_DOC_SYNC.md',
})


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_manifest(root, manifest_path, release):
    """Validate private operator evidence and every recorded file; fail closed on drift.

    This is an operator attestation, not a signature from a remote release authority.
    The trusted local operator creates it after source reconciliation and regression.
    No Git index or execution state is changed.
    """
    root, path = Path(root).resolve(), Path(manifest_path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Manifest must be a regular file')
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('Manifest must be private and owned by the operator')
    raw = path.read_bytes()
    value = json.loads(raw)
    if (value.get('schema') != 1 or value.get('kind') != 'reconciled-deployment'
            or not re.fullmatch('[0-9a-f]{40}', release)
            or value.get('release') != release or value.get('root') != str(root)):
        raise ValueError('Manifest identity mismatch')
    files = value.get('files')
    if not isinstance(files, dict) or not REQUIRED <= files.keys():
        raise ValueError('Incomplete deployment coverage')
    for name, expected in files.items():
        parts = PurePosixPath(name)
        if (parts.is_absolute() or '..' in parts.parts or str(parts) != name
                or not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected)):
            raise ValueError('Invalid deployment file record')
        target = root / name
        if any(p.is_symlink() for p in [target, *target.parents] if p != root.parent):
            raise ValueError('Symlink in deployed source')
        if not target.is_file() or digest(target) != expected:
            raise ValueError('Deployment source drift: ' + name)
    evidence = value.get('regression', {})
    log = path.parent / 'installed-regression.log'
    if (evidence.get('passed') is not True or not isinstance(evidence.get('tests'), int)
            or evidence['tests'] < 1 or log.is_symlink() or not log.is_file()
            or digest(log) != evidence.get('sha256')):
        raise ValueError('Missing verified installed regression evidence')
    text = log.read_text()
    if not re.search(r'Ran ' + str(evidence['tests']) + r' tests? in ', text) or not text.rstrip().endswith('OK'):
        raise ValueError('Regression evidence does not record success')
    return hashlib.sha256(raw).hexdigest()
