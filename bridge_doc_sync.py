"""Explicit, revision-guarded synchronization of the BRIDGE instruction header."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request

START = '[BRIDGE MANAGED INSTRUCTIONS START V1]'
END = '[BRIDGE MANAGED INSTRUCTIONS END V1]'
TITLES = {'chatgpt': 'ECLIPSE — ChatGPT Termux Bridge and Handoff',
          'gemini': 'ECLIPSE Gemini Bridge'}
ENV = {'chatgpt': 'ECLIPSE_DOC_ID', 'gemini': 'ECLIPSE_GEMINI_DOC_ID'}
ROOT = Path(__file__).resolve().parent


def flatten(doc):
    chunks = []
    index = 1
    for block in doc['body']['content']:
        if 'sectionBreak' in block and block.get('endIndex') == 1 and not chunks:
            continue
        for element in block['paragraph']['elements']:
            value = element['textRun']['content']
            size = len(value.encode('utf-16-le')) // 2
            if element['startIndex'] != index or element['endIndex'] != index + size:
                raise ValueError('Noncontiguous document indices')
            index += size
            chunks.append(value)
    text = ''.join(chunks)
    if not text.endswith('\n'):
        raise ValueError('Missing final paragraph newline')
    return text


def managed_text(provider, instructions, commit, *, deployment=None):
    if provider not in TITLES or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Invalid provider or installed commit')
    if any(token in instructions for token in (START, END, '<<<', '>>>')):
        raise ValueError('Instructions contain protocol delimiters')
    if not instructions.strip():
        raise ValueError('Empty instructions')
    identity = (f'Verified reconciled deployment: {commit}\nDeployment manifest SHA-256: {deployment}\n'
                if deployment else f'Operator-validated checkout: {commit}\n')
    if deployment is not None and not re.fullmatch(r'[0-9a-f]{64}', deployment):
        raise ValueError('Invalid deployment manifest digest')
    return (f'{START}\nProvider: {provider}\n{identity}'
            f'{instructions.strip()}\n{END}\n')


def plan(doc, provider, instructions, commit, *, bootstrap=False, deployment=None):
    if doc.get('title') != TITLES.get(provider) or not doc.get('revisionId'):
        raise ValueError('Wrong document title or missing revision')
    text = flatten(doc)
    block = managed_text(provider, instructions, commit, deployment=deployment)
    if not (START in text or END in text):
        if not bootstrap:
            raise ValueError('Explicit bootstrap required')
        requests = [{'insertText': {'location': {'index': 1}, 'text': block + '\n'}}]
    else:
        if (text.count(START) != 1 or text.count(END) != 1
                or not text.startswith(START + '\n') or END + '\n' not in text):
            raise ValueError('Ambiguous managed header')
        end = text.index(END + '\n') + len(END) + 1
        old = text[:end]
        if '<<<' in old or '>>>' in old or not old.startswith(START + f'\nProvider: {provider}\n'):
            raise ValueError('Managed header contains protected content or wrong provider')
        if old == block:
            requests = []
        else:
            end_index = 1 + len(old.encode('utf-16-le')) // 2
            requests = [{'deleteContentRange': {'range': {'startIndex': 1, 'endIndex': end_index}}},
                        {'insertText': {'location': {'index': 1}, 'text': block}}]
    return {'requests': requests, 'writeControl': {'requiredRevisionId': doc['revisionId']}}


def fetch_document(client, doc_id):
    # The watcher's get_doc uses a restricted field mask that omits title.
    # Obtain title, identity, revision and body in the same snapshot.
    from urllib.parse import quote
    token = client.token_mgr.get_access_token()
    url = ('https://docs.googleapis.com/v1/documents/' + quote(doc_id, safe='')
           + '?fields=documentId,title,revisionId,body(content)')
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token})
    with client.opener.open(req, timeout=25) as reply:
        doc = json.load(reply)
    if doc.get('documentId') != doc_id:
        raise ValueError('Document identity mismatch')
    return doc


def sync(client, doc_id, provider, instructions, commit, *, bootstrap=False, apply=False, deployment=None):
    if not doc_id or doc_id != os.environ.get(ENV[provider]):
        raise ValueError('Document must match configured provider ID')
    other = 'gemini' if provider == 'chatgpt' else 'chatgpt'
    if doc_id == os.environ.get(ENV[other]):
        raise ValueError('Provider IDs must be distinct')
    doc = fetch_document(client, doc_id)
    patch = plan(doc, provider, instructions, commit, bootstrap=bootstrap, deployment=deployment)
    if not apply or not patch['requests']:
        return {'status': 'DRY_RUN' if not apply else 'UNCHANGED', 'operations': len(patch['requests'])}
    req = urllib.request.Request('https://docs.googleapis.com/v1/documents/' + doc_id + ':batchUpdate',
        data=json.dumps(patch).encode(), headers={'Authorization': 'Bearer ' + client.token_mgr.get_access_token(),
        'Content-Type': 'application/json'}, method='POST')
    with client.opener.open(req, timeout=25) as reply:
        ack = json.load(reply)
    if ack.get('documentId') != doc_id:
        raise RuntimeError('Update acknowledgment mismatch; inspect before retrying')
    check = plan(fetch_document(client, doc_id), provider, instructions, commit, deployment=deployment)
    if check['requests']:
        raise RuntimeError('Readback mismatch; inspect before retrying')
    return {'status': 'APPLIED', 'operations': len(patch['requests'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('provider', choices=TITLES)
    parser.add_argument('--validated-commit', required=True, help='Operator-attested live-tested installed commit')
    parser.add_argument('--deployment-manifest', type=Path, help='Verified reconciled installation manifest')
    parser.add_argument('--bootstrap', action='store_true')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT, text=True)
    deployment = None
    if args.deployment_manifest:
        from bridge_deployment import verify_manifest
        deployment = verify_manifest(ROOT, args.deployment_manifest, args.validated_commit)
        head = args.validated_commit
    elif head != args.validated_commit or dirty:
        parser.error('Installed checkout must match attested commit and have no tracked changes')
    from watch import GoogleDocsClient
    instructions = (ROOT / 'docs' / ('BRIDGE_' + args.provider.upper() + '.md')).read_text()
    print(json.dumps(sync(GoogleDocsClient(), os.environ.get(ENV[args.provider]), args.provider,
                          instructions, head, bootstrap=args.bootstrap, apply=args.apply, deployment=deployment)))


if __name__ == '__main__':
    main()
