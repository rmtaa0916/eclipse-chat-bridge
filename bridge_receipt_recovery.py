
import json,hashlib,re
def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
def envelope(row,max_bytes=16384):
    request_id,status,result,completed_at,doc_id,synced=row
    if status not in ('COMPLETED','FAILED') or synced!=0 or not completed_at or not doc_id or not re.fullmatch(r'[A-Za-z0-9_-]{8,64}',request_id):
        raise ValueError('ineligible')
    data=json.loads(result)
    if not isinstance(data,dict) or not {'action','result','status'}<=data.keys():
        raise ValueError('invalid result')
    if (status=='COMPLETED')!=(data['status']=='completed'):
        raise ValueError('status mismatch')
    receipt={'version':1,'request_id':request_id,'doc_id':doc_id,'result':data,'result_sha256':hashlib.sha256(canonical(data)).hexdigest()}
    if len(canonical(receipt))>max_bytes:
        raise ValueError('oversize; use explicit result recovery')
    return receipt
def matches(expected,observed):
    try:
        return isinstance(observed,dict) and canonical(expected)==canonical(observed) and observed['result_sha256']==hashlib.sha256(canonical(observed['result'])).hexdigest()
    except (TypeError,ValueError,KeyError):
        return False



def publish(expected,read,compare_append,limit=3,max_total=262144):
    # read returns (revision, list of receipts); compare_append must
    # conditionally append without changing the existing latest slot.
    for _ in range(limit):
        revision,records=read()
        found=[r for r in records if r.get('request_id')==expected['request_id']]
        if found:
            return 'VERIFIED' if len(found)==1 and matches(expected,found[0]) else 'CONFLICT'
        if len(canonical(records+[expected]))>max_total:
            return 'CAPACITY'
        if compare_append(revision,expected):
            _,records=read()
            found=[r for r in records if r.get('request_id')==expected['request_id']]
            return 'VERIFIED' if len(found)==1 and matches(expected,found[0]) else 'UNCONFIRMED'
    return 'RETRY_LATER'


import sqlite3,time,urllib.request,urllib.error
from pathlib import Path
from latest_response_slot import _runs
import os
DOC_ID=os.environ.get('ECLIPSE_BRIDGE_RECOVERY_DOC_ID','')
PREFIX='<<<ECLIPSE_BRIDGE_RECOVERY_RECEIPT_V1>>> '
MAX_TOTAL=24576
_last=0.0
def read_journal(doc):
    text,_=_runs(doc)
    rows=[]
    for line in text.splitlines():
        if line.startswith(PREFIX):
            value=json.loads(line[len(PREFIX):])
            if not isinstance(value,dict):raise ValueError('invalid receipt')
            rows.append(value)
    if not doc.get('revisionId'):raise ValueError('missing revision')
    return doc['revisionId'],rows
class DocsJournal:
    def __init__(self,client,doc_id):
        if not DOC_ID or doc_id!=DOC_ID:raise ValueError('document not allowlisted')
        self.client=client;self.doc_id=doc_id
    def read(self):
        c=self.client
        return read_journal(c.get_doc(self.doc_id,c.token_mgr.get_access_token()))
    def append(self,revision,record):
        c=self.client
        payload={'requests':[{'insertText':{'endOfSegmentLocation':{},'text':'\n'+PREFIX+canonical(record).decode()+'\n'}}],'writeControl':{'requiredRevisionId':revision}}
        req=urllib.request.Request('https://docs.googleapis.com/v1/documents/'+self.doc_id+':batchUpdate',data=canonical(payload),headers={'Authorization':'Bearer '+c.token_mgr.get_access_token(),'Content-Type':'application/json'},method='POST')
        try:
            with c.opener.open(req,timeout=15) as resp:
                return isinstance(json.loads(resp.read()),dict)
        except urllib.error.HTTPError as e:
            if e.code in (400,409,412,429,500,502,503,504):return False
            raise
        except (urllib.error.URLError,TimeoutError):return False
def load_candidate(db,results_dir,request_id=None):
    with sqlite3.connect(Path(db).as_uri()+'?mode=ro',uri=True,timeout=2) as c:
        sql="select id,status,result,completed_at,doc_id,doc_synced from queue where doc_id=? and doc_synced=0 and status in ('COMPLETED','FAILED')"
        rows=c.execute(sql+(' and id=?' if request_id else '')+' order by completed_at,id limit 25',(DOC_ID,request_id) if request_id else (DOC_ID,)).fetchall()
    for row in rows:
        try:
            expected=envelope(row)
            p=Path(results_dir)/(row[0]+'.json')
            if p.is_symlink() or not p.is_file():continue
            saved=json.loads(p.read_text())
            if saved!=expected['result'] and not (isinstance(saved,dict) and saved.get('id')==row[0] and saved.get('result')==expected['result']):continue
            return row,expected
        except (OSError,ValueError,TypeError):continue
    return None
def mark_verified(db,row):
    with sqlite3.connect(db,timeout=2) as c:
        cur=c.execute("update queue set doc_synced=1 where id=? and status=? and result=? and completed_at=? and doc_id=? and doc_synced=?",(row[0],row[1],row[2],row[3],row[4],row[5]))
        return cur.rowcount==1
def recover(client,db,results_dir,request_id=None):
    candidate=load_candidate(db,results_dir,request_id)
    if candidate is None:return 'NO_ELIGIBLE'
    row,expected=candidate
    j=DocsJournal(client,row[4])
    outcome=publish(expected,j.read,j.append,limit=3,max_total=MAX_TOTAL)
    if outcome!='VERIFIED':return outcome
    return 'SYNCED' if mark_verified(db,row) else 'STATE_CHANGED'
def recover_one(client,state_path,results_dir):
    global _last
    if time.monotonic()-_last<60:return
    _last=time.monotonic()
    outcome=recover(client,Path(state_path).parent/'bridge_queue.db',results_dir)
    if outcome not in ('NO_ELIGIBLE','SYNCED'):print('receipt recovery:',outcome,flush=True)
