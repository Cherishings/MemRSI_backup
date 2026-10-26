"""Build a bounded optimizer feedback view exclusively from registered training."""
import json,hashlib
from pathlib import Path

def read(p): return json.loads(p.read_text())
def excerpt(p,limit=12000):
    text=p.read_text();return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
        'text':text if len(text)<=limit else text[-limit:], 'truncated':len(text)>limit,'retained_region':'full' if len(text)<=limit else 'tail'}
def build(root):
    root=Path(root).resolve(); folder=(root/'learning/training').resolve()
    manifest=read(folder/'manifest.json');rows=read(folder/'rows.json')
    assert len(rows)==len(manifest['schedule'])==32,'Training must finish before feedback'
    allowed={(r['source_id'],r['arm'],r['repeat'],r['policy_sha256']) for r in manifest['schedule']}
    summaries=[];traces=[]
    for r in rows:
        assert (r['source_id'],r['arm'],r['repeat'],r['policy_sha256']) in allowed
        p=Path(r['output']).resolve();assert p.is_relative_to(folder/'replays'),'Nontraining path rejected'
        result=read(p/'result.json');assert result['policy_sha256']==r['policy_sha256']
        summaries.append({k:r.get(k) for k in ['source_id','arm','repeat','status','correct','planned','decisions','error_code','logical_calls','model_cost_complete','policy_sha256']})
        if r['arm']!='joint':continue
        e={'source_id':r['source_id'],'repeat':r['repeat'],'status':r['status'],'excerpts':[]}
        # Include both successful and failing joint replays by manifest membership, not cherry-picked score.
        for name in ['guidance-events.jsonl','guidance-advice-attempts.jsonl']:
            if (p/name).exists():e['excerpts'].append(excerpt(p/name))
        archives=sorted(p.glob('rollover-*'),key=lambda q:int(q.name.split('-')[-1]))
        for a in archives[-2:]:
            for name in ['memory-before.md','memory-after.md','messages-before.json']:
                if (a/name).exists():e['excerpts'].append(excerpt(a/name,6000))
        traces.append(e)
    return {'scope':'training-only candidate feedback; all 32 summaries and all 8 joint terminal contexts',
       'previous_joint_policy':read(root/'learning/policies/joint.json'),
       'manifest_sha256':hashlib.sha256((folder/'manifest.json').read_bytes()).hexdigest(),
       'rows_sha256':hashlib.sha256((folder/'rows.json').read_bytes()).hexdigest(),
       'summaries':summaries,'joint_contexts':traces,'validation_read':False,'test_read':False}
