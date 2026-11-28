"""Fail-closed cleanup of acknowledged bridge requests."""
import hashlib,json,re
from pathlib import Path
A="<<<ECLIPSE_BRIDGE_REQUEST_V1>>>"
B="<<<END_ECLIPSE_BRIDGE_REQUEST_V1>>>"
pattern=re.compile(r"(?m)^"+re.escape(A)+r"\r?\n(\{[^\n]*\})\r?\n"+re.escape(B)+r"(?=\r?\n|$)")
def flatten(doc):
    out=[]; chunks=[]; pos=0
    for block in doc["body"]["content"]:
        if "paragraph" not in block:
            if "sectionBreak" in block and block.get("endIndex")==1 and not chunks:
                continue
            raise ValueError("complex document element")
        for el in block["paragraph"].get("elements",[]):
            tr=el.get("textRun",{})
            t=tr.get("content")
            if t is None: raise ValueError("non-text element")
            lo,hi=el["startIndex"],el["endIndex"]
            if hi-lo!=len(t.encode("utf-16-le"))//2: raise ValueError("invalid indices")
            chunks.append((pos,pos+len(t),lo,t));pos+=len(t);out.append(t)
    return "".join(out),chunks
def pos_at(chunks,n):
    for a,b,lo,t in chunks:
        if a<=n<=b:return lo+len(t[:n-a].encode("utf-16-le"))//2
    raise ValueError("invalid mapped position")
def plan(doc,state,receipts,keep=5,limit=25):
    text,chunks=flatten(doc); found=[]
    for match in pattern.finditer(text):
        try:q=json.loads(match.group(1))
        except ValueError:continue
        ident=q.get("id") if isinstance(q,dict) else None
        if not isinstance(ident,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}",ident):continue
        found.append((match,q,ident))
    # Preserve newest five requests whether completed or not.
    recent={i for _,_,i in found[-keep:]}
    picked=[]
    for match,q,ident in found:
        if ident in recent:continue
        rec=state.get(ident,{})
        if rec.get("status") not in ("completed","error"):continue
        fingerprint=hashlib.sha256(json.dumps(q,sort_keys=True).encode()).hexdigest()
        if fingerprint!=rec.get("sha256"):continue
        file=receipts/(ident+".json")
        if not file.is_file() or file.is_symlink():continue
        try:saved=json.loads(file.read_text())
        except (ValueError,OSError):continue
        if saved.get("status")!=rec["status"]:continue
        picked.append((match.start(),match.end(),ident))
        if len(picked)>=limit:break
    rev=doc.get("revisionId")
    if not rev:raise ValueError("missing revisionId")
    requests=[{"deleteContentRange":{"range":{"startIndex":pos_at(chunks,a),"endIndex":pos_at(chunks,b)}}} for a,b,_ in reversed(picked)]
    return {"requests":requests,"writeControl":{"requiredRevisionId":rev}},{"found":len(found),"remove":len(picked),"kept_recent":keep,"selected":[x[2] for x in picked[:5]]}
