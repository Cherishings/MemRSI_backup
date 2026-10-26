import unittest,tempfile,json,hashlib,sys
from pathlib import Path
R=Path('/data/stormlab/xi/robot');sys.path[:0]=[str(R/'paper-evolution-20261018r1'),str(R/'paper-evolution-20261018r1/frozen_runtime'),str(R/'paper-completion-20261020/archive-transport-repair')]
from regression_cache_r2 import reuse_regression
from transition_diagnosis import DIAG_SYSTEM,DIAG_SCHEMA
class CacheTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);base=Path(self.tmp.name);self.old=base/'old';self.out=base/'new';self.rel=Path('cycle-1/diagnosis/regression-dev-08/window-00/diagnosis');self.prior=self.old/self.rel;self.prior.mkdir(parents=True)
  self.data={'case':'dev-08','role':'previous_rejected_candidate_regression','documents':{'a':'abc'}}
  self.value={'target':'actor','witness_a':'a','witness_b':'a','quote_a':'abc','quote_b':'abc','finding':'observed'}
  self.sig=hashlib.sha256(json.dumps([DIAG_SYSTEM,self.data,DIAG_SCHEMA],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
  self.write(self.prior.parent/'evidence.json',self.data);self.write(self.prior/'value.json',self.value);self.write(self.prior/'request-identity.json',{'sha256':self.sig})
 def write(self,p,d):p.write_text(json.dumps(d))
 def call(self,**kw):
  args=dict(path=self.out/self.rel,out=self.out,old=self.old,system=DIAG_SYSTEM,data=self.data,schema=DIAG_SCHEMA,signature=self.sig);args.update(kw);return reuse_regression(**args)
 def test_exact_cache_no_new_attempt(self):
  self.assertEqual(self.call(),self.value);self.assertFalse(list(self.out.glob('**/attempt-*')))
 def test_quote_rejection_preserved(self):
  self.value['quote_a']='unsupported';self.write(self.prior/'value.json',self.value);self.assertEqual(self.call(),self.value)
  a=json.loads((self.out/self.rel/'historical-cache-reuse-r2.json').read_text());self.assertFalse(a['quote_valid'])
 def test_parent_denied(self):
  with self.assertRaises(RuntimeError):self.call(path=self.out/'cycle-1/diagnosis/dev-08/window-00/diagnosis')
 def test_proposal_denied(self):
  with self.assertRaises(RuntimeError):self.call(path=self.out/'cycle-1/proposal')
 def test_changed_input_denied(self):
  with self.assertRaises(RuntimeError):self.call(data={**self.data,'extra':'changed'})
 def test_missing_response_no_retry(self):
  (self.prior/'value.json').unlink()
  with self.assertRaises(RuntimeError):self.call()
 def test_changed_cached_value_detected(self):
  self.call();self.value['finding']='changed';self.write(self.prior/'value.json',self.value)
  with self.assertRaises(RuntimeError):self.call()
if __name__=='__main__':unittest.main()
