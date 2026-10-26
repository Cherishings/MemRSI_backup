import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import bounded_learning as m
from bounded_edits import apply_edit, recover_last_submission
from stream_design import SEED_PROCEDURES, compile_procedures
from structured_feedback import StructuredFailure
from replay import dump


class WiderEditTests(unittest.TestCase):
    def test_566_characters_accepted_without_changing_other_rule(self):
        prefix='Preserve relevant evidence. '
        replacement=prefix+('x'*(566-len(prefix)))
        self.assertEqual(len(replacement),566)
        changed,policy=apply_edit(SEED_PROCEDURES,dict(target='guidance',replacement=replacement,rationale='generic'))
        self.assertEqual(changed['update'],SEED_PROCEDURES['update'])
        self.assertTrue(changed['guidance'].endswith(replacement))
        self.assertEqual(json.loads(policy['guidance'])['kind'],'procedure_guidance_v2')

    def test_full_rule_limit_remains_enforced(self):
        with self.assertRaisesRegex(ValueError,'rule_length'):
            apply_edit(SEED_PROCEDURES,dict(target='guidance',replacement='x'*1200,rationale='generic'))
        with self.assertRaises(StructuredFailure):
            apply_edit(SEED_PROCEDURES,dict(target='guidance',replacement='x'*1201,rationale='generic'))

    def test_recovery_uses_last_submission_without_editing_it(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);a=root/'old/attempt-01';a.mkdir(parents=True)
            def response(text):
                return {'response':dict(finish_reason='tool_calls',tool_calls=[dict(name='submit',arguments=
                    dict(target='guidance',replacement=text,rationale='explanation'))])}
            trace=a/'model-trace.jsonl'
            trace.write_text('\n'.join(json.dumps(response(x)) for x in ('first text','x'*566)))
            original=trace.read_bytes()
            dump(a/'format-rejection-1.json',{'code':'optimizer_field_length_failure'})
            value=recover_last_submission(root/'old',root/'new')
            self.assertEqual(value['replacement'],'x'*566)
            self.assertEqual(trace.read_bytes(),original)
            audit=json.loads((root/'new/recovery.json').read_text())
            self.assertEqual(audit['new_model_calls'],0)


class ResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_format_failure_is_recorded_and_never_regenerated_on_resume(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(m,'cached_structured',side_effect=StructuredFailure('optimizer_field_length_failure')) as call:
                v,e=await m.safe_structured(Path(d),'',{}, {},lambda:None)
                v2,e2=await m.safe_structured(Path(d),'',{}, {},lambda:None)
            self.assertIsNone(v);self.assertIsNone(v2);self.assertEqual(e,e2);self.assertEqual(call.call_count,1)

    async def test_budget_and_network_failures_are_not_hidden_as_bad_candidates(self):
        for code in ('optimizer_call_budget','provider_error'):
            with tempfile.TemporaryDirectory() as d:
                with patch.object(m,'cached_structured',side_effect=RuntimeError(code)):
                    with self.assertRaisesRegex(RuntimeError,code):
                        await m.safe_structured(Path(d),'',{}, {},lambda:None)

    async def test_rejected_first_proposal_still_evaluates_second_cycle(self):
        class Control:
            def state(self,*a,**k):pass
            def wait_gateway(self):pass
        sources=[[dict(id='first',sha256='a')],[dict(id='second',sha256='b')]]
        seen=[]
        async def replay(f,*a):
            seen.append(f['id'])
            return dict(status='completed',correct=1,answered=1,planned=1,attempts=1,decisions=[],all_attempt_calls=10)
        async def propose(path,*a):
            if 'cycle-0' in str(path):raise StructuredFailure('optimizer_schema_failure')
            if str(path).endswith('critic'):return dict(generic=True,no_task_answers=True,preserves_user_authority=True)
            return dict(target='guidance',replacement=' Check source scope.',rationale='generic')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);dump(root/'prior/learning/learning-call-ledger.json',dict(calls=6807,limit=9745))
            with patch.object(m,'source_sets',return_value=(sources,[sources[1][0]])), \
                 patch.object(m,'replay_case',replay),patch.object(m,'packet',return_value={}), \
                 patch.object(m,'cached_structured',propose):
                result=await m.run(root/'new',Control(),{},'/unused',root/'prior')
            self.assertIn('second',seen)
            self.assertEqual(result['credits'][0]['reason'],'proposal_rejected')
            self.assertEqual(result['promotions'],0)
            self.assertEqual(json.loads((root/'new/selected-policy.json').read_text()),compile_procedures(SEED_PROCEDURES))
            self.assertEqual(json.loads((root/'new/learning-call-ledger.json').read_text())['calls'],6807)


if __name__=='__main__':unittest.main()
