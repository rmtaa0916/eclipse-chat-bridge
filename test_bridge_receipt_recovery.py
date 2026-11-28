
import unittest,json,copy
from bridge_receipt_recovery import envelope,matches
class Recovery(unittest.TestCase):
    def setUp(self):
        self.row=['request_123','COMPLETED',json.dumps({'action':'run','status':'completed','result':{'exit_code':0,'output':'ok'}}),1,'doc123',0]
    def test_valid(self):
        r=envelope(self.row);self.assertTrue(matches(r,copy.deepcopy(r)))
    def test_wrong_id(self):
        r=envelope(self.row);o=copy.deepcopy(r);o['request_id']='request_456';self.assertFalse(matches(r,o))
    def test_wrong_doc(self):
        r=envelope(self.row);o=copy.deepcopy(r);o['doc_id']='other';self.assertFalse(matches(r,o))
    def test_tampered(self):
        r=envelope(self.row);o=copy.deepcopy(r);o['result']['result']['output']='wrong';self.assertFalse(matches(r,o))
    def test_nonterminal(self):
        self.row[1]='RUNNING';self.assertRaises(ValueError,envelope,self.row)
    def test_synced(self):
        self.row[-1]=1;self.assertRaises(ValueError,envelope,self.row)
    def test_oversize(self):
        self.assertRaises(ValueError,envelope,self.row,10)
    def test_bad_json(self):
        self.row[2]='not-json';self.assertRaises(ValueError,envelope,self.row)
    def test_status_mismatch(self):
        self.row[1]='FAILED';self.assertRaises(ValueError,envelope,self.row)
    def test_missing_completion(self):
        self.row[3]=None;self.assertRaises(ValueError,envelope,self.row)



import unittest,copy,json
from bridge_receipt_recovery import envelope
from bridge_receipt_recovery import publish
class Fake:
    def __init__(self):
        self.rev=0;self.rows=[];self.latest='newer request';self.fail=0;self.writes=0;self.lost=False
    def read(self):return self.rev,copy.deepcopy(self.rows)
    def append(self,rev,row):
        if self.fail:self.fail-=1;self.rev+=1;return False
        if self.rev!=rev:return False
        self.writes+=1;self.rev+=1
        if not self.lost:self.rows.append(copy.deepcopy(row))
        return True
class Tests(unittest.TestCase):
    def setUp(self):
        self.r=envelope(('request_123','COMPLETED',json.dumps({'action':'run','status':'completed','result':{'exit_code':0}}),1,'doc123',0));self.f=Fake()
    def runit(self,**kw):return publish(self.r,self.f.read,self.f.append,**kw)
    def test_success(self):
        self.assertEqual(self.runit(),'VERIFIED');self.assertEqual(self.f.latest,'newer request')
    def test_idempotent(self):
        self.runit();self.assertEqual(self.runit(),'VERIFIED');self.assertEqual(self.f.writes,1)
    def test_conflict(self):
        x=copy.deepcopy(self.r);x['doc_id']='wrong';self.f.rows=[x];self.assertEqual(self.runit(),'CONFLICT');self.assertEqual(self.f.writes,0)
    def test_revision_race(self):
        self.f.fail=2;self.assertEqual(self.runit(),'VERIFIED');self.assertEqual(self.f.writes,1)
    def test_exhausted(self):
        self.f.fail=3;self.assertEqual(self.runit(),'RETRY_LATER');self.assertEqual(self.f.writes,0)
    def test_missing_readback(self):
        self.f.lost=True;self.assertEqual(self.runit(),'UNCONFIRMED')
    def test_capacity(self):
        self.assertEqual(self.runit(max_total=1),'CAPACITY');self.assertEqual(self.f.writes,0)
    def test_duplicate(self):
        self.f.rows=[self.r,self.r];self.assertEqual(self.runit(),'CONFLICT')

class AdapterTests(unittest.TestCase):
    def test_revision_required(self):
        from bridge_receipt_recovery import read_journal
        with self.assertRaises(ValueError):
            read_journal({'body':{'content':[{'paragraph':{'elements':[{'startIndex':1,'endIndex':2,'textRun':{'content':'\n'}}]}}]}})
    def test_document_scope(self):
        from bridge_receipt_recovery import DocsJournal
        with self.assertRaises(ValueError):DocsJournal(None,'other-doc')
    def test_db_compare_and_swap(self):
        import tempfile,sqlite3
        from pathlib import Path
        from bridge_receipt_recovery import mark_verified
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'queue.db';c=sqlite3.connect(db)
            c.execute('create table queue(id,status,result,completed_at,doc_id,doc_synced)')
            row=('request_123','COMPLETED','{}',1,'doc123',0)
            c.execute('insert into queue values(?,?,?,?,?,?)',row);c.commit();c.close()
            wrong=list(row);wrong[2]='changed'
            self.assertFalse(mark_verified(db,wrong))
            self.assertTrue(mark_verified(db,row))
            self.assertFalse(mark_verified(db,row))

if __name__=='__main__':unittest.main()
