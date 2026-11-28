import hashlib,json,os,tempfile,unittest
from pathlib import Path
from bridge_deployment import verify_manifest,REQUIRED
from bridge_doc_sync import managed_text,plan,START,END,TITLES

class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name); self.root=self.base/'root';self.root.mkdir()
        self.files={}
        for p in REQUIRED:
            q=self.root/p;q.parent.mkdir(parents=True,exist_ok=True);q.write_text(p)
            self.files[p]=hashlib.sha256(q.read_bytes()).hexdigest()
        log=self.base/'installed-regression.log';log.write_text('Ran 7 tests in 0.1s\n\nOK\n')
        self.value={'schema':1,'kind':'reconciled-deployment','release':'a'*40,'root':str(self.root),'files':self.files,
                    'regression':{'passed':True,'tests':7,'sha256':hashlib.sha256(log.read_bytes()).hexdigest()}}
        self.path=self.base/'deployment.json';self.save()
    def save(self):
        self.path.write_text(json.dumps(self.value));self.path.chmod(0o600)
    def verify(self):
        return verify_manifest(self.root,self.path,'a'*40)
    def test_valid_operator_manifest(self):
        self.assertEqual(self.verify(),hashlib.sha256(self.path.read_bytes()).hexdigest())
    def test_drift(self):
        (self.root/'watch.py').write_text('changed')
        with self.assertRaises(ValueError):self.verify()
    def test_wrong_release_or_root(self):
        for key,val in [('release','b'*40),('root','/other')]:
            original=self.value[key];self.value[key]=val;self.save()
            with self.assertRaises(ValueError):self.verify()
            self.value[key]=original
    def test_required_coverage(self):
        del self.value['files']['watch.py'];self.save()
        with self.assertRaises(ValueError):self.verify()
    def test_path_escape(self):
        self.value['files']['../outside']='0'*64;self.save()
        with self.assertRaises(ValueError):self.verify()
    def test_source_symlink(self):
        p=self.root/'watch.py';p.unlink();p.symlink_to(self.root/'bridge.py')
        with self.assertRaises(ValueError):self.verify()
    def test_public_manifest(self):
        self.path.chmod(0o644)
        with self.assertRaises(ValueError):self.verify()
    def test_manifest_symlink(self):
        target=self.base/'link.json';target.symlink_to(self.path)
        with self.assertRaises(ValueError):verify_manifest(self.root,target,'a'*40)
    def test_regression_drift(self):
        (self.base/'installed-regression.log').write_text('FAILED')
        with self.assertRaises(ValueError):self.verify()
    def test_false_regression(self):
        self.value['regression']['passed']=False;self.save()
        with self.assertRaises(ValueError):self.verify()
    def test_manifest_header_and_idempotence(self):
        digest=self.verify(); text=managed_text('chatgpt','Instructions','a'*40,deployment=digest)
        self.assertIn('Verified reconciled deployment:',text)
        self.assertNotIn('Operator-validated checkout:',text)
        document={'title':TITLES['chatgpt'],'revisionId':'r','body':{'content':[{'paragraph':{'elements':[
            {'startIndex':1,'endIndex':1+len(text),'textRun':{'content':text}}]}}]}}
        self.assertEqual(plan(document,'chatgpt','Instructions','a'*40,deployment=digest)['requests'],[])
    def test_header_rejects_invalid_digest(self):
        with self.assertRaises(ValueError):managed_text('gemini','Instructions','a'*40,deployment='bad')
