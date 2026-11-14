import unittest
import json
from unittest.mock import patch
import latest_response_slot as slot

def doc(text, rev="r1"):
    length=slot._u16(text)
    return {"revisionId":rev, "body":{"content":[{"paragraph":{"elements":[{
        "startIndex":1, "endIndex":1+length, "textRun":{"content":text}
    }]}}]}}

class SlotTests(unittest.TestCase):
    def text(self, before="begin\n", middle="\nold\n"):
        return before+slot.START+middle+slot.END+"\n"
    def test_replace_only_middle_preserves_markers_and_prefix(self):
        content=self.text()
        patch=slot.build_slot_patch(doc(content),"req_123456",{"status":"completed"})
        requests=patch["requests"]
        self.assertEqual(patch["writeControl"]["requiredRevisionId"],"r1")
        x=requests[0]["deleteContentRange"]["range"]
        self.assertEqual(content[x["startIndex"]-1:x["endIndex"]-1],"\nold\n")
        self.assertEqual(requests[1]["insertText"]["location"]["index"],x["startIndex"])
        self.assertIn("req_123456", requests[1]["insertText"]["text"])
        self.assertNotIn("old", requests[1]["insertText"]["text"])
    def test_inline_request_code_mentions_do_not_confuse_slot(self):
        before="Request JSON mentions "+slot.START+" and "+slot.END+" inline.\n"
        content=self.text(before=before)
        patch=slot.build_slot_patch(doc(content),"req_123456",{"status":"completed"})
        x=patch["requests"][0]["deleteContentRange"]["range"]
        self.assertEqual(content[x["startIndex"]-1:x["endIndex"]-1],"\nold\n")
    def test_utf16_before_marker(self):
        content=self.text(before="start 😀\n")
        patch=slot.build_slot_patch(doc(content),"req_123456",{"status":"completed"})
        x=patch["requests"][0]["deleteContentRange"]["range"]
        prefix=content[:content.index(slot.START)+len(slot.START)]
        self.assertEqual(x["startIndex"],1+slot._u16(prefix))
    def test_missing_or_duplicate_markers_fail_closed(self):
        for content in ("regular document", self.text()+slot.START, self.text().replace(slot.END,"")):
            with self.subTest(content=content[:15]),self.assertRaises(slot.SlotError):
                slot.build_slot_patch(doc(content),"req_123456",{})
    def test_bad_revision_rejected(self):
        with self.assertRaises(slot.SlotError):
            slot.build_slot_patch(doc(self.text(),rev=""),"req_123456",{})
    def test_paragraph_splits_are_handled(self):
        txt=self.text()
        cut=txt.index("old")+1
        chunks=[txt[:cut],txt[cut:]]
        offset=1; blocks=[]
        for chunk in chunks:
            end=offset+slot._u16(chunk)
            blocks.append({"paragraph":{"elements":[{"startIndex":offset,"endIndex":end,"textRun":{"content":chunk}}]}})
            offset=end
        patch=slot.build_slot_patch({"revisionId":"r1","body":{"content":blocks}},"req_123456",{"status":"completed"})
        self.assertEqual(patch["requests"][0]["deleteContentRange"]["range"]["startIndex"],1+txt.index(slot.START)+len(slot.START))
    def test_noncontiguous_doc_indices_rejected(self):
        txt=self.text()
        cut=txt.index("old")+1
        chunks=[txt[:cut],txt[cut:]]
        a=1+slot._u16(chunks[0])
        record={"revisionId":"r1","body":{"content":[
          {"paragraph":{"elements":[{"startIndex":1,"endIndex":a,"textRun":{"content":chunks[0]}}]}},
          {"paragraph":{"elements":[{"startIndex":a+4,"endIndex":a+4+slot._u16(chunks[1]),"textRun":{"content":chunks[1]}}]}}
        ]}}
        with self.assertRaises(slot.SlotError):
            slot.build_slot_patch(record,"req_123456",{})

if __name__=="__main__":
    unittest.main()
