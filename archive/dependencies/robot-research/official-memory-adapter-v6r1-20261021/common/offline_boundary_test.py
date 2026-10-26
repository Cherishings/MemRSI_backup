"""Actual VisualAgent/PAOS paths, with all LLM/network execution blocked.

Synthetic history exists only in this isolated offline test, never in evaluation.
"""
import argparse
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import sys
import time


async def main(args):
    sys.path.insert(0, args.adapter)
    from visual_actor import VisualAgent
    from visual_accounting import accounting_messages
    from token_accounting import request_tokens
    import model_provider
    from PhyAgentOS.providers.base import LLMResponse, ToolCallRequest
    from PhyAgentOS.agent import context_budget
    import numpy as np

    wire = []
    model_provider.read_api_key = lambda: 'offline-stub-no-secret'
    model_provider.probe = lambda: True

    @asynccontextmanager
    async def no_lease(self):
        yield

    async def fake_complete(self, request):
        names = {t['function']['name'] for t in request.get('tools', [])}
        normalized, units, images = accounting_messages(request['messages'])
        actual = request_tokens(normalized, request.get('tools')) + units
        assert actual <= 12288
        wire.append(dict(names=sorted(names), actual_request_units=actual,
                         images=images, output_cap=request['max_tokens'],
                         native_counter_units=context_budget.request_tokens(request['messages'], request.get('tools')),
                         actual_task_guidance_present='# Selected memory evidence' in str(request['messages'][0].get('content',''))))
        if args.expect == 'fixed':
            assert wire[-1]['native_counter_units'] == actual
        if names == {'save_memory'}:
            return LLMResponse(None, [ToolCallRequest('archive', 'save_memory', {
                'history_entry': '[offline] Synthetic prior observations archived.',
                'memory_update': 'Offline boundary regression, no task answer.'})], 'tool_calls')
        if names == {'pack_storage'}:
            return LLMResponse(None, [ToolCallRequest('pack', 'pack_storage', {
                'memory': 'Offline boundary regression.', 'history': '[offline] Archived.'})], 'tool_calls')
        if names == {'select_memory_evidence'}:
            return LLMResponse(None, [ToolCallRequest('guide', 'select_memory_evidence', {'ids': []})], 'tool_calls')
        assert 'report_action' in names
        if request['messages'][-1].get('role') == 'tool':
            return LLMResponse('Decision submitted.')
        return LLMResponse(None, [ToolCallRequest('decision', 'report_action', {
            'skill': 'finish', 'instruction': '', 'reason': 'Offline stub decision.'})], 'tool_calls')

    model_provider.Provider._request_lease = no_lease
    model_provider.Provider._complete = fake_complete

    # Fail immediately if any regression escapes the local response stub.
    import httpx
    async def forbidden_send(*a, **k):
        raise AssertionError('network_forbidden_in_offline_regression')
    httpx.AsyncClient.send = forbidden_send

    async def disconnected():
        return None

    results = []
    for arm in ('native', 'memrsi'):
        output = args.output / arm / 'actor'
        agent = VisualAgent(arm, output, args.policy if arm == 'memrsi' else None,
            {'persistent_tokens':1024,'active_input_tokens':12288,'output_tokens_per_call':2048})
        agent.loop._connect_mcp = disconnected
        session = agent.loop.sessions.get_or_create(agent.session_key)
        # Tune a genuine native session into the gap: old text-only estimate is
        # below 12288, but its actual three-camera request is above the hard cap.
        while agent.loop.memory_consolidator.estimate_session_prompt_tokens(session)[0] < 10000:
            session.add_message('user', 'Synthetic past camera observation: ' + 'neutral surface reading; ' * 28)
            session.add_message('assistant', 'Recorded the synthetic observation.')
        agent.loop.sessions.save(session)
        before = agent.loop.memory_consolidator.estimate_session_prompt_tokens(session)[0]
        start = len(wire)
        outcome = {}
        try:
            decision = await agent.choose('Inspect the current public camera view.',
                [np.zeros((64, 64, 3), dtype=np.uint8) for _ in range(3)],
                {'joint_action':[0.0] * 14})
            outcome = dict(status='returned', decision=decision)
        except Exception as error:
            outcome = dict(status='raised', error_type=type(error).__name__,
                error_code=str(error) if str(error) in {
                    'active_context_budget_exceeded',
                    'Live context exceeds its input budget even after tool-result compaction'} else type(error).__name__)
        calls = wire[start:]
        archived = sum(row['names'] == ['save_memory'] for row in calls)
        outcome.update(arm=arm, old_text_only_estimate=before,
            native_archive_calls=archived, model_stub_calls=len(calls),
            logical_calls=agent.provider.calls, requests=calls,
            last_consolidated=session.last_consolidated,
            image_history_sanitized='data:image/' not in json.dumps(session.messages),
            pending_clear=getattr(agent, '_visual_pending', None) is None)
        if args.expect == 'fixed':
            assert outcome['status'] == 'returned', outcome
            assert archived > 0 and session.last_consolidated > 0
            assert any(row['images'] == 3 for row in calls)
            actor_calls = [row for row in calls if 'report_action' in row['names']]
            assert all(row['actual_task_guidance_present'] == (arm == 'memrsi') for row in actor_calls)
            estimates = [json.loads(line) for line in (output/'visual-archive-estimates.jsonl').read_text().splitlines()]
            assert any(row['phase']=='before_guidance' and row['shared_guidance_reserve_units']==2048 for row in estimates)
            assert any(row['phase']=='actor' and row['shared_guidance_reserve_units']==0 for row in estimates)
            assert estimates[-1]['actual_request_units'] == actor_calls[0]['actual_request_units']
            assert outcome['image_history_sanitized'] and outcome['pending_clear']
            # Observe-only and explicit native /new retain their normal no-image
            # route; neither carries a pending camera nor a lingering reserve.
            await agent.observe('Offline receipt only.')
            assert agent._visual_pending is None
            await agent.rollover()
            assert agent._visual_pending is None
            assert not agent.loop.sessions.get_or_create(agent.session_key).messages
            # The real provider logical budget still includes every guidance and
            # archive invocation, and rejects the request after the 480th one.
            agent.provider.calls = 479
            await agent.provider.chat(messages=[{'role':'user','content':'offline budget edge'}],
                tools=[{'type':'function','function':{'name':'select_memory_evidence','parameters':{}}}])
            assert agent.provider.calls == 480
            try:
                await agent.provider.chat(messages=[{'role':'user','content':'offline budget edge'}])
            except RuntimeError as error:
                assert str(error) == 'agent_call_budget_exhausted'
            else:
                raise AssertionError('logical_call_limit_not_enforced')
            outcome.update(observe_and_rollover_no_pending_reserve=True,
                logical_limit_480_enforced=True, native_and_provider_counter_equal=True,
                actual_post_G_TASK_in_actor_request=(arm == 'memrsi'),
                pending_Event_proprio_cameras_tools_exactly_counted=True,
                post_G_estimator_matches_first_actor_request=True)
        else:
            assert outcome['status'] == 'raised' and archived == 0, outcome
        await agent.close()
        results.append(outcome)

    if args.expect == 'fixed':
        # Oversized current input has no removable old history. Both native
        # pre-provider and MemRSI guidance boundaries retain the 12288 hard cap.
        for arm in ('native','memrsi'):
            output=args.output/('oversized-'+arm)/'actor'
            agent=VisualAgent(arm,output,args.policy if arm=='memrsi' else None,
                {'persistent_tokens':1024,'active_input_tokens':12288,'output_tokens_per_call':2048})
            agent.loop._connect_mcp=disconnected
            try:
                await agent.choose('oversized neutral current input; '*6000,
                    [np.zeros((64,64,3),dtype=np.uint8) for _ in range(3)],
                    {'joint_action':[0.0]*14})
            except RuntimeError as error:
                assert str(error)=='active_context_budget_exceeded'
            else:raise AssertionError('oversized_current_request_not_rejected')
            assert agent.provider.calls==0 and agent._visual_pending is None
            await agent.close()

    report = dict(status='pass', expected=args.expect, rows=results,
        real_llm_calls=0, real_network_calls=0, synthetic_history_only=True,
        actor_path=str(Path(args.adapter)/'visual_actor.py'),
        actor_sha256=hashlib.sha256((Path(args.adapter)/'visual_actor.py').read_bytes()).hexdigest(),
        native_archive_and_compaction_algorithms_unmodified=True,
        oversized_current_input_rejected_without_llm=(args.expect=='fixed'),
        finished=time.time())
    (args.output/'result.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k != 'rows'}))
    print(json.dumps([{k:v for k,v in r.items() if k != 'requests'} for r in results]))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--adapter',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--policy',type=Path,required=True)
    parser.add_argument('--expect',choices=['broken','fixed'],required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    asyncio.run(main(args))
