"""Register finite development, automatic learning, then frozen physical evaluation."""
import hashlib, json, shutil, sys, time
from pathlib import Path
R=Path(__file__).resolve().parent.parent
OLD=Path('/media/disks/disk1/share/ext_songzhiying/PAOS-LIBERO-study-20261023')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n')

def main():
    assert not (R/'registration.json').exists(),'registration_exists'
    for name in ('source','paos-core'):
        shutil.copytree(OLD/name,R/name,ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('orders.json','budget.json'):shutil.copy2(OLD/name,R/name)
    train=['EADCB','EDABC','DBACE','ABDEC']; val=['DABCE','EBCAD']
    test=['ABCED','BCADE','CDEAB','DEABC','EABCD','ABDCE','BDAEC','CEABD','DAEBC','EBACD','ACEBD','BECAD']
    assert len(set(train+val+test))==18
    def dev_conditions(histories):
        return [dict(condition_id=f'h{h}-v{(n+i)%2}-i{i}',history=h,variant=(n+i)%2,init=i)
            for n,h in enumerate(histories) for i in (0,1)]
    test_conditions=[dict(condition_id=f'h{h}-v{v}-i{i}',history=h,variant=v,init=i)
        for h in test for v in (0,1) for i in (20,21)]
    frozen={str(p.relative_to(R)):sha(p) for folder in ('code','source','paos-core')
        for p in (R/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    for name in ('orders.json','budget.json','parent-policy.json'):frozen[name]=sha(R/name)
    m=dict(version='libero-method-improvement-rsi-20261023-v1',registered_at=time.time(),
        gpus=[2,3,4,6,7],all_histories=train+val+test,training_conditions=dev_conditions(train),
        validation_conditions=dev_conditions(val),test_conditions=test_conditions,
        frozen_files=frozen,call_limit_per_case=480,episode_timeout_seconds=10800,
        total_timeout_seconds=96*3600,learning_call_limit=12000,
        final_arms=['native','g_only','u_only','gu_parent','gu_learned','rsi_g_only','rsi_u_only','think_u'],
        max_final_episodes=384,development_physical_episodes=12,
        stages=['12 fixed parent development episodes; preserve all results',
            'At most four training source trajectories and two validation source trajectories; two replay repetitions',
            'Exactly one bounded model proposal for G and one for U, each independently checked; no human candidate rewriting',
            'Compare parent, G-edit, U-edit, joint on training and validation; reject regressions and excess cost',
            'Freeze selected policy, runtime and aliases before reading any final result',
            '48 paired physical conditions per distinct final policy, original 20 sessions/19 boundaries/7 checkpoints'],
        primary_comparisons=[['gu_learned','u_only'],['gu_learned','g_only'],['gu_learned','gu_parent'],['gu_learned','think_u']],
        secondary_learning_comparisons=[['rsi_g_only','gu_parent'],['rsi_u_only','gu_parent']],
        rules=['No method changes during this registered cycle',
            'Manual parent design is not RSI; only traced model-generated accepted edits count',
            'Equal physical seeds, initial states, context/storage/output caps and request cap across arms',
            'Think control has the same advisor schema, public inputs and one extra call per decision; observed tokens are reported',
            'Identical exported policies are aliases of one run, never additional independent evidence',
            'Keep method/decision/physical failures. No outcome-dependent retry or stopping',
            'Infrastructure failure pauses dispatch and requires root-cause repair, never an auxiliary experiment tree'],
        analysis=dict(primary='full-episode success out of all 48 planned per distinct arm',
            pairing='same history, initial state and kitchen variant',
            dependence='12 mission-history blocks; four conditions within each block; shared physical tasks limit generalization',
            uncertainty='report paired discordances, effect size, history-cluster bootstrap intervals with fixed seed; Holm adjustment for four primary comparisons',
            robustness='report every history and leave-one-history-out differences; one net case is not robust superiority',
            secondary='seven checkpoints are nested endpoints, not 336 independent trials; report calls/tokens/latency and failure classes'),
        scope='LIBERO-based long-horizon multi-session missions using selected official tasks, not official whole-suite LIBERO. Physical states had historical exposure; final combinations are separated from this cycle learning. Casa 47/48 vs46/48 is prior development evidence only.')
    write(R/'registration.json',m);(R/'registration.sha256').write_text(sha(R/'registration.json')+'\n')
    print(json.dumps({'training':8,'validation':4,'test_per_arm':48,'max_test':384,'sha256':sha(R/'registration.json')}))
if __name__=='__main__':main()
