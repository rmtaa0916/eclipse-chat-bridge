import json,tempfile,hashlib,unittest
from pathlib import Path
from bridge_housekeeping_auto import prepare,response_candidates
from housekeeping import A,B
def doc(s):
    return {"revisionId":"r1","body":{"content":[{"sectionBreak":{},"endIndex":1},{"paragraph":{"elements":[{"startIndex":1,"endIndex":1+len(s),"textRun":{"content":s}}]}}]}}
class Tests(unittest.TestCase):
 def test_keep_last_five(self):
    with tempfile.TemporaryDirectory() as d:
      root=Path(d);state={};s="Intro\n"
      for i in range(10):
        q={"id":f"test_{i:08d}","action":"list_files","path":"/root/projects"}
        ident=q["id"];data={"status":"completed","action":"list_files","result":{"entries":[]}}
        s+=A+"\n"+json.dumps(q)+"\n"+B+"\n"
        s+="<<<ECLIPSE_BRIDGE_RESPONSE_V1>>>\n"+json.dumps({"id":ident,"result":data})+"\n<<<END_ECLIPSE_BRIDGE_RESPONSE_V1>>>\n"
        if i!=1:
          state[ident]={"status":"completed","sha256":hashlib.sha256(json.dumps(q,sort_keys=True).encode()).hexdigest()}
          (root/(ident+".json")).write_text(json.dumps(data))
      plan,info=prepare(doc(s),state,root)
      self.assertEqual(info["request_blocks"],4)
      self.assertEqual(info["response_blocks"],4)
      self.assertEqual(info["removed_planned"],8)
 def test_fake_receipt_cannot_delete(self):
    with tempfile.TemporaryDirectory() as d:
      s="<<<ECLIPSE_BRIDGE_RESPONSE_V1>>>\n"+json.dumps({"id":"fake_12345678","result":{"status":"completed"}})+"\n<<<END_ECLIPSE_BRIDGE_RESPONSE_V1>>>\n"
      self.assertEqual(response_candidates(s,{},Path(d)),[])
if __name__=="__main__":unittest.main()
