import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from dataclasses import asdict
from PhyAgentOS.providers.base import LLMResponse,ToolCallRequest
from structured_feedback import PROPOSAL,CRITIC,parse_response,recover_response,structured,StructuredFailure
from feedback_protocol import schedule
from resume_support import validate_rows
from memory_policy import BASE,digest
from feedback_learning import aggregate,run

def wire(value,name='submit',reason='tool_calls'):
    return {'finish_reason':reason,'tool_calls':[{'name':name,'arguments':value}]}

def provider_response(value):
    return LLMResponse(content=None,finish_reason='tool_calls',tool_calls=[ToolCallRequest('call-test','submit',value)])

class ParserTest(unittest.TestCase):
    def test_explanations_optional_rules_unchanged(self):
        value={'guidance':'Read the current verified state.','update':'Preserve confirmed progress.'}
        self.assertEqual(parse_response(wire(value),PROPOSAL),value)
        self.assertEqual(parse_response(wire(dict(value,update_hypothesis='reason')),PROPOSAL),dict(value,update_hypothesis='reason'))
    def test_essential_fields_types_and_truncation_still_rejected(self):
        value={'guidance':'Use verified records.','update':'Keep progress.'}
        for wrong in ({'guidance':'x'},dict(value,update=''),dict(value,update=5),dict(value,extra='x'),dict(value,guidance='x'*1801)):
            with self.assertRaises(StructuredFailure):parse_response(wire(wrong),PROPOSAL)
        with self.assertRaises(StructuredFailure):parse_response(wire(value,reason='length'),PROPOSAL)
        with self.assertRaises(StructuredFailure):parse_response(wire(value,name='other'),PROPOSAL)
        self.assertEqual(parse_response(wire({'generic':True,'no_task_answers':False,'preserves_user_authority':True}),CRITIC)['no_task_answers'],False)
        with self.assertRaises(StructuredFailure):parse_response(wire({'generic':'true','no_task_answers':True,'preserves_user_authority':True}),CRITIC)
    def test_archived_proposal_recovered_once_without_changing_rules(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'source';source.mkdir();value={k:BASE[k] for k in ('guidance','update')}
            log=source/'model-trace.jsonl';log.write_text(json.dumps({'response':wire(value)})+'\n');before=log.read_bytes()
            result=recover_response(source,root/'recovered',PROPOSAL)
            self.assertEqual(digest(dict(schema=1,**result)),digest(BASE));self.assertEqual(log.read_bytes(),before)
            with self.assertRaises(FileExistsError):recover_response(source,root/'recovered',PROPOSAL)
            log.write_text(log.read_text()*2)
            with self.assertRaisesRegex(StructuredFailure,'ambiguous'):recover_response(source,root/'second',PROPOSAL)
    def test_resume_keeps_failed_trials_and_rejects_duplicates_or_changed_condition(self):
        planned=schedule();rows=[dict(planned[0],status='decision_failure'),dict(planned[1],status='success')]
        done=validate_rows(rows,planned)
        self.assertEqual(len([r for r in planned if r['trial_id'] not in done]),118)
        with self.assertRaises(ValueError):validate_rows(rows+rows[:1],planned)
        with self.assertRaises(ValueError):validate_rows([dict(rows[0],history='ABCDE')],planned)
        with self.assertRaises(ValueError):validate_rows([dict(rows[0],status='running')],planned)

class RepairCallsTest(unittest.IsolatedAsyncioTestCase):
    async def test_only_one_format_resubmission_and_no_fabricated_missing_rule(self):
        with tempfile.TemporaryDirectory() as d:
            seen=[];result={'guidance':'Choose from verified memory.','update':'Keep verified feedback.'}
            async def chat(provider,**kwargs):
                seen.append(copy.deepcopy(kwargs))
                return provider_response({'guidance':result['guidance']} if len(seen)==1 else result)
            with patch('model_provider.read_api_key',return_value='offline-key'),patch('model_provider.Provider.chat',chat):
                got=await structured(Path(d)/'out','rules',{},PROPOSAL)
            self.assertEqual(got,result);self.assertEqual(len(seen),2)
            self.assertNotIn(result['update'],json.dumps(seen[-1]))
    async def test_malformed_required_fields_stop_after_two_calls(self):
        with tempfile.TemporaryDirectory() as d:
            seen=[]
            async def chat(provider,**kwargs):seen.append(kwargs);return provider_response({'guidance':'only one'})
            with patch('model_provider.read_api_key',return_value='offline-key'),patch('model_provider.Provider.chat',chat):
                with self.assertRaises(StructuredFailure):await structured(Path(d)/'out','rules',{},PROPOSAL)
            self.assertEqual(len(seen),2)
    async def test_resume_reuses_base_and_candidate_then_validates_without_reproposal(self):
        def stats(fs,correct):
            return aggregate([{'fixture':f['id'],'status':'answered','correct':i<correct,'model_cost_complete':True,
                        'model_input_tokens':100,'model_output_tokens':10} for rep in range(2) for i,f in enumerate(fs)])
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);prior=root/'prior';(prior/'base-development').mkdir(parents=True);(prior/'candidate-0/proposal').mkdir(parents=True)
            dev=[{'id':'d'+str(i),'source':'dev'} for i in range(4)];valid=[{'id':'v'+str(i),'source':'valid'} for i in range(4)]
            (prior/'fixtures.json').write_text(json.dumps({'development':dev,'validation':valid}))
            (prior/'base-development/summary.json').write_text(json.dumps(stats(dev,1)))
            value={'guidance':'Use the latest verified mission state to guide current work.','update':'Keep verified progress and distinguish it from plans.'}
            (prior/'candidate-0/proposal/model-trace.jsonl').write_text(json.dumps({'response':wire(value)})+'\n')
            (prior/'candidate-0/proposal/calls.json').write_text('{"calls":1}')
            (prior/'failure.json').write_text('{"code":"old_schema_failure"}')
            calls=[]
            async def model(out,system,data,schema):
                self.assertEqual(schema,CRITIC);return {'generic':True,'no_task_answers':True,'preserves_user_authority':True}
            async def batch(fs,out,policy):
                calls.append(str(out));return stats(fs,1 if out.name=='base-validation' else 4)
            with patch('feedback_learning.prepare',return_value=(dev,valid)),patch('feedback_learning.evidence',return_value=[]),\
                 patch('feedback_learning.batch',batch),patch('feedback_learning.structured',model):
                await run(root/'new',prior)
            self.assertEqual(len(calls),3)
            self.assertFalse((root/'new/base-development').exists())
            self.assertTrue((prior/'failure.json').exists())
            self.assertEqual(json.loads((root/'new/report.json').read_text())['status'],'accepted')
            self.assertEqual(json.loads((root/'new/resume.json').read_text())['prior_calls'],1)

if __name__=='__main__':unittest.main()
