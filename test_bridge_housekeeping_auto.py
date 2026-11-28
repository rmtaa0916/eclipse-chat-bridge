import json,tempfile,hashlib,unittest
from pathlib import Path
from bridge_housekeeping_auto import prepare,response_candidates,whitespace_candidates
from housekeeping import A,B
def doc(s):
    return {"revisionId":"r1","body":{"content":[{"sectionBreak":{},"endIndex":1},{"paragraph":{"elements":[{"startIndex":1,"endIndex":1+len(s.encode('utf-16-le'))//2,"textRun":{"content":s}}]}}]}}
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

 def apply(self,s,plan):
    data=s.encode("utf-16-le")
    for req in plan["requests"]:
      r=req["deleteContentRange"]["range"]
      a,b=(r["startIndex"]-1)*2,(r["endIndex"]-1)*2
      data=data[:a]+data[b:]
    return data.decode("utf-16-le")
 def test_whitespace_only_with_protected_payloads(self):
    with tempfile.TemporaryDirectory() as d:
      a=A+'\n{"id":"active_123456"}\n'+B+'\n'
      g="<<<ECLIPSE_GEMINI_REQUEST_V1>>>\n{\n\n\n  \"id\":\"gemini_123456\"\n}\n<<<END_ECLIPSE_GEMINI_REQUEST_V1>>>\n"
      s="Unicode 🚀\n"+a+"\n"*100+g+"\n"*50
      plan,info=prepare(doc(s),{},Path(d))
      after=self.apply(s,plan)
      self.assertEqual(after,"Unicode 🚀\n"+a+"\n"+g+"\n")
      self.assertEqual(info["whitespace_ranges"],2)
      self.assertEqual(info["removed_planned"],0)
      self.assertEqual(plan["writeControl"]["requiredRevisionId"],"r1")
      self.assertEqual(prepare(doc(after),{},Path(d))[0]["requests"],[])
 def test_ambiguous_or_open_blocks_do_not_normalize(self):
    s=A+'\n{"id":"active_123456"}\n'+B+'\n\n\n\n'+A+'\n'
    self.assertEqual(whitespace_candidates(s),[])
 def test_prose_and_header_preserved(self):
    s="[BRIDGE MANAGED INSTRUCTIONS START V1]\nhello\n\n\nthere\n[BRIDGE MANAGED INSTRUCTIONS END V1]\n\n\n\nordinary prose\n\n\n"
    self.assertEqual(whitespace_candidates(s),[])
 def test_pruning_consumes_terminator(self):
    with tempfile.TemporaryDirectory() as d:
      root=Path(d);state={};blocks=[]
      for i in range(6):
        q={"id":f"test_{i:08d}","action":"list_files"}
        state[q["id"]]={"status":"completed","sha256":hashlib.sha256(json.dumps(q,sort_keys=True).encode()).hexdigest()}
        (root/(q["id"]+".json")).write_text(json.dumps({"status":"completed"}))
        blocks.append(A+"\n"+json.dumps(q)+"\n"+B+"\n")
      s="Intro\n"+"".join(blocks)
      plan,info=prepare(doc(s),state,root)
      self.assertEqual(self.apply(s,plan),"Intro\n"+"".join(blocks[1:]))
      self.assertEqual(info["request_blocks"],1)
if __name__=="__main__":unittest.main()

