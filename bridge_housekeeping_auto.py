"""Revision-protected, locally backed-up Google Docs bridge housekeeping."""
import hashlib,json,os,re,time,urllib.request
from pathlib import Path
import housekeeping

RESPONSE_START="<<<ECLIPSE_BRIDGE_RESPONSE_V1>>>"
RESPONSE_END="<<<END_ECLIPSE_BRIDGE_RESPONSE_V1>>>"
response_pat=re.compile(r"(?m)^"+re.escape(RESPONSE_START)+r"\r?\n(.*?)\r?\n"+re.escape(RESPONSE_END)+r"(?=\r?\n|$)",re.S)

def response_candidates(text,state,receipts,keep=5):
    matches=[]
    for m in response_pat.finditer(text):
        try:x=json.loads(m.group(1))
        except ValueError:continue
        ident=x.get("id") if isinstance(x,dict) else None
        if not isinstance(ident,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}",ident):continue
        st=state.get(ident,{})
        f=receipts/(ident+".json")
        if st.get("status") not in ("completed","error") or not f.is_file() or f.is_symlink():continue
        try:local=json.loads(f.read_text())
        except (OSError,ValueError):continue
        if x.get("result")!=local:continue
        matches.append((m.start(),m.end(),ident))
    return matches[:-keep] if len(matches)>keep else []


# Only normalize redundant empty paragraphs at known protocol boundaries.
# Treat nested Gemini diagnostic/response markers as protected and fail closed
# on mismatched boundaries; never modify payloads or the managed instruction header.
PAIRS = {
    housekeeping.A: housekeeping.B,
    RESPONSE_START: RESPONSE_END,
    "<<<ECLIPSE_BRIDGE_LATEST_DIAGNOSTIC_START_V1>>>": "<<<ECLIPSE_BRIDGE_LATEST_DIAGNOSTIC_END_V1>>>",
    "<<<ECLIPSE_GEMINI_REQUEST_V1>>>": "<<<END_ECLIPSE_GEMINI_REQUEST_V1>>>",
    "<<<ECLIPSE_GEMINI_RESPONSE_V1>>>": "<<<END_ECLIPSE_GEMINI_RESPONSE_V1>>>",
    "<<<ECLIPSE_DIAGNOSTIC_SECTION_V1>>>": "<<<END_ECLIPSE_DIAGNOSTIC_SECTION_V1>>>",
    "[BRIDGE MANAGED INSTRUCTIONS START V1]": "[BRIDGE MANAGED INSTRUCTIONS END V1]",
}
RECEIPT = "<<<ECLIPSE_BRIDGE_RECOVERY_RECEIPT_V1>>> "

def whitespace_candidates(text):
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    stack, candidates = [], []
    ends = set(PAIRS.values())
    def receipt(line):
        if not line.startswith(RECEIPT):
            return False
        try:
            value = json.loads(line[len(RECEIPT):])
            return isinstance(value, dict) and isinstance(value.get("request_id"), str)
        except ValueError:
            return False
    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\r\n")
        if line in PAIRS:
            stack.append(PAIRS[line])
        elif line in ends:
            if not stack or stack.pop() != line:
                return []
        elif line == "" and not stack and lines[i] in ("\n", "\r\n"):
            j = i + 1
            while j < len(lines) and lines[j] in ("\n", "\r\n"):
                j += 1
            prev = lines[i-1].rstrip("\r\n") if i else ""
            nxt = lines[j].rstrip("\r\n") if j < len(lines) else ""
            if j-i >= 2 and (prev in ends or receipt(prev)) and (
                    nxt in PAIRS or receipt(nxt) or j == len(lines)):
                # Preserve one empty paragraph, including the mandatory final newline.
                candidates.append((offsets[i+1], offsets[j]))
                if j == len(lines):
                    candidates[-1] = (offsets[i], offsets[j-1])
            i = j
            continue
        i += 1
    return [] if stack else candidates


def prepare(doc,state,receipts,keep=5,max_blocks=30):
    text,runs=housekeeping.flatten(doc)
    request_payload,request_info=housekeeping.plan(doc,state,receipts,keep=keep,limit=max_blocks)
    selections=[(x["deleteContentRange"]["range"]["startIndex"],
                 x["deleteContentRange"]["range"]["endIndex"],"request")
                for x in request_payload["requests"]]
    if len(selections)<max_blocks:
        for a,b,ident in response_candidates(text,state,receipts,keep):
            selections.append((housekeeping.pos_at(runs,a),housekeeping.pos_at(runs,b),"response"))
            if len(selections)>=max_blocks:break
    # Validate contiguous UTF-16 indexing before mapping any deletions.
    expected=1
    for _,_,lo,chunk in runs:
        if lo != expected:raise ValueError("Noncontiguous cleanup indices")
        expected += len(chunk.encode("utf-16-le"))//2
    selections.sort(reverse=True)
    encoded=text.encode("utf-16-le")
    for k,(a,b,_) in enumerate(selections):
        if a>=b or (k and b>selections[k-1][0]):
            raise ValueError("Invalid/overlapping cleanup ranges")
        segment=encoded[(a-1)*2:(b-1)*2].decode("utf-16-le")
        if not (segment.startswith(housekeeping.A) or segment.startswith(RESPONSE_START)):
            raise ValueError("Cleanup range fails exact marker validation")
        if not (segment.rstrip().endswith(housekeeping.B) or segment.rstrip().endswith(RESPONSE_END)):
            raise ValueError("Cleanup range fails end-marker validation")
        if re.search(r"(?m)^<<<ECLIPSE_BRIDGE_LATEST_DIAGNOSTIC_START_V1>>>\r?$",segment):
            raise ValueError("Cleanup intersects active diagnostic slot")
    # Include the pruned block's line terminator, but never delete the final
    # paragraph newline. Existing marker and receipt validation remains intact.
    revised=[]
    for a,b,kind in selections:
        tail=encoded[(b-1)*2:]
        sep=4 if tail.startswith(b"\r\x00\n\x00") else 2 if tail.startswith(b"\n\x00") else 0
        if sep and len(tail)>sep:
            b+=sep//2
        revised.append((a,b,kind))
    # Existing blank gaps are independent of block acknowledgments. Bound the
    # number of additional ranges and preserve all protected protocol contents.
    for x,y in whitespace_candidates(text)[:max_blocks]:
        a,b=housekeeping.pos_at(runs,x),housekeeping.pos_at(runs,y)
        if a<b and all(b<=lo or a>=hi for lo,hi,_ in revised):
            revised.append((a,b,"whitespace"))
    revised.sort(reverse=True)
    for k,(a,b,_) in enumerate(revised):
        if a>=b or (k and b>revised[k-1][0]):
            raise ValueError("Invalid/overlapping final cleanup ranges")
    return {"requests":[{"deleteContentRange":{"range":{"startIndex":a,"endIndex":b}}} for a,b,_ in revised],
            "writeControl":{"requiredRevisionId":doc["revisionId"]}},{"removed_planned":len(selections),
            "request_blocks":sum(t=="request" for *_,t in selections),
            "response_blocks":sum(t=="response" for *_,t in selections),
            "whitespace_ranges":sum(t=="whitespace" for *_,t in revised),
            "whitespace_units":sum(b-a for a,b,t in revised if t=="whitespace")}

def normalize_failed_for_housekeeping(state, db_path, receipts):
    import sqlite3
    from pathlib import Path
    import json
    import re
    if not isinstance(state, dict):
        raise ValueError('invalid state')
    db_path, receipts = Path(db_path), Path(receipts)
    if not db_path.is_file() or db_path.is_symlink():
        return state
    result = dict(state)
    from contextlib import closing
    with closing(sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True, timeout=3)) as conn:
        cols = {r[1] for r in conn.execute('PRAGMA table_info(queue)')}
        key = 'request_id' if 'request_id' in cols else 'id'
        if not {key, 'sha256', 'status', 'completed_at', 'doc_synced'} <= cols:
            return state
        for ident, rec in state.items():
            if not isinstance(ident, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{7,63}', ident):
                continue
            if not isinstance(rec, dict) or rec.get('status') != 'failed':
                continue
            fingerprint = rec.get('sha256')
            if not isinstance(fingerprint, str) or not re.fullmatch('[0-9a-f]{64}', fingerprint):
                continue
            row = conn.execute('SELECT status, completed_at, doc_synced, sha256 FROM queue WHERE ' + key + '=?', (ident,)).fetchone()
            if row is None or row[0] != 'FAILED' or row[1] is None or row[2] != 1 or row[3] != fingerprint:
                continue
            receipt = receipts / (ident + '.json')
            if not receipt.is_file() or receipt.is_symlink():
                continue
            try:
                saved = json.loads(receipt.read_text())
            except (OSError, ValueError):
                continue
            if not isinstance(saved, dict) or saved.get('status') != 'error':
                continue
            result[ident] = dict(rec, status='error')
    return result

def maintain(client,doc_id,state_path,*,apply=False,max_blocks=30):
    base=Path(state_path)
    state=json.loads(base.read_text())
    state = normalize_failed_for_housekeeping(state, base.parent / 'bridge_queue.db', base.parent / 'results')
    doc=client.get_doc(doc_id)
    patch,summary=prepare(doc,state,base.parent/"results",max_blocks=max_blocks)
    summary["status"]="DRY_RUN"
    if not apply or not patch["requests"]:return summary
    archive=Path(__file__).parent/"backups"
    archive.mkdir(exist_ok=True)
    name="bridge_auto_pre_"+time.strftime("%Y%m%d_%H%M%S",time.gmtime())+"_"+str(os.getpid())+".json"
    dest=archive/name
    with dest.open("x") as f:json.dump({"document_id":doc_id,"document":doc},f,ensure_ascii=False)
    os.chmod(dest,0o600)
    if json.loads(dest.read_text())["document"]["revisionId"]!=doc["revisionId"]:
        raise RuntimeError("Backup verification failed")
    token=client.token_mgr.get_access_token()
    request=urllib.request.Request("https://docs.googleapis.com/v1/documents/"+doc_id+":batchUpdate",
        data=json.dumps(patch).encode(),headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"},method="POST")
    with client.opener.open(request,timeout=25) as reply:
        ack=json.load(reply)
    if ack.get("documentId")!=doc_id:raise RuntimeError("Docs did not acknowledge cleanup")
    summary["status"]="APPLIED"
    summary["backup"]=str(dest)
    if apply:
        try:
            from bridge_archive_compression import maintain_archives
            maintain_archives(Path(__file__).parent/"backups", replace=False, limit=1)
        except Exception as archive_exc:
            print("archive compression failed closed: "+type(archive_exc).__name__, flush=True)
    return summary
