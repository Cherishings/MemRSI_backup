import json,tempfile,unittest
from pathlib import Path
from acceptance import inspect
from advisor import MODES
from interventions import ARMS
class GateTests(unittest.TestCase):
 def fixture(self,p):
  jobs=[]
  for arm in ARMS:
   jobs.append({'key':arm+'/c','arm':arm});c=p/arm/'c';a=c/'attempt-01/agent';a.mkdir(parents=True)
   (c/'result.json').write_text('{"status":"decision_failure"}')
   (a/'advisor-contract.json').write_text(json.dumps({'arm':arm,'same_U':True}))
   traces=[{'request':{'tools':[{'function':{'name':'save_memory'}}],'messages':[{'content':'Update procedure for the long/short memory interface.'}]}}]
   if arm!='off_u1':
    mode=arm.split('_')[0];ad=mode in MODES
    messages=[{'role':'system','content':MODES[mode] if ad else 'select'}, {'role':'user','content':json.dumps({'execution_api':'api','evidence':{'current':'q'}})}]
    traces+=[{'request':{'tools':[{'function':{'name':'report_advice' if ad else 'select_memory_evidence'}}],'messages':messages}},{'request':{'messages':[{'content':'# Nonbinding decision advice' if ad else '# Selected memory evidence'}]}}]
    (a/('advisor-prototype.jsonl' if ad else 'gu-exposure.jsonl')).write_text(json.dumps({'mode':mode,'native_short_messages':1})+'\n')
   (a/'model-trace.jsonl').write_text('\n'.join(map(json.dumps,traces)))
   (a/'receipt-correlations.jsonl').write_text('{"decision_event":1}\n')
  return jobs
 def test_all_failures_can_pass_mechanism_gate(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);self.assertEqual(inspect(p,self.fixture(p))['state'],'passed')
 def test_off_injection_blocks(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);jobs=self.fixture(p);f=p/'off_u1/c/attempt-01/agent/model-trace.jsonl'
   with f.open('a') as o:o.write('\n'+json.dumps({'request':{'messages':[{'content':'# Nonbinding decision advice'}]}}))
   self.assertEqual(inspect(p,jobs)['state'],'blocked')
if __name__=='__main__':unittest.main()
