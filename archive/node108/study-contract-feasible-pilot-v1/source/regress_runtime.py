"""Fixed four-case repair check, including both observed failures. No physics claim."""
import argparse, asyncio, json, re
from pathlib import Path
from twenty_agent import TwentyAgent
from run_queue import dump

def guides(path):
    return [json.loads(s) for s in (Path(path)/'guidance-events.jsonl').read_text().splitlines()]

async def run(a):
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    bowl=next(r for r in guides(a.old_bowl) if r['current_request'].startswith('Event 4:'))
    table=next(r for r in guides(a.old_table) if r['current_request'].startswith('Event 6:'))
    cases=[('old_bowl_decision',bowl,'execute_order'),
           ('false_veto_table_B',table,'serve_B'),
           ('rebuilt_archive_bowl',bowl,'execute_order'),
           ('valid_completion',{'long_memory':'The user requested only table A service. '
              'Execution receipts confirmed the whole native task complete. '
              'The user cancelled the optional table G request. No other service was requested.',
              'current_request':'Continue.'},'finish')]
    results=[]
    for name,fixture,expected in cases:
        agent=TwentyAgent('memrsi',out/name,a.policy,a.budget)
        try:
            if name=='rebuilt_archive_bowl':
                session=agent.loop.sessions.get_or_create(agent.session_key)
                session.messages=json.loads((Path(a.old_bowl)/'rollover-1/messages-before.json').read_text())
                agent.loop.sessions.save(session);await agent.rollover()
            else:(agent.workspace/'memory/MEMORY.md').write_text(fixture['long_memory'])
            current=re.sub(r'^Event \d+: ', '',fixture['current_request'])
            choice=await agent.turn(current,decision=True)
            results.append({'case':name,'choice':choice,'expected_evaluator_only':expected,
                'passed':choice['skill']==expected,'calls':agent.provider.calls,
                'format_repairs':agent.provider.format_repairs,
                'native_session_archive_success':all(r['success'] for r in agent.rollovers)})
            dump(out/'progress.json',results)
        finally:await agent.close()
    dump(out/'report.json',{'passed':all(x['passed'] for x in results),'rows':results,
        'scope':'engineering regression on known failure states plus a legitimate-completion control; '
                'no physical execution, no independent efficacy measurement, no retries of failed choices'})

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('old-bowl','old-table','output','policy','budget'):p.add_argument('--'+n,required=True)
    a=p.parse_args()
    try:asyncio.run(run(a))
    except Exception as e:
        dump(Path(a.output)/'failure.json',{'error_type':type(e).__name__,'code':'inspect_structured_regression_outputs'})
        raise SystemExit(2)
