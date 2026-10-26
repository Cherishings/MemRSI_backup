"""Bounded 12-run serial-robot pilot on GPU6/7. No automatic case reruns."""
import argparse, concurrent.futures, hashlib, json, os, signal, subprocess, threading, time
from pathlib import Path
from run_queue import ROOT, dump, identity, env
from physical_runner import PhysicalRunner, PORTS, AGENT_PYTHON, wait_for_policy
from memory_policy import load
from twenty_protocol import plan

PHYSICAL_FILES = ('native_world.py', 'world_client.py', 'check_case.py',
                  'paired_sampling.py', 'serve_paired_policy.py', 'retry_recovery.py', 'osc_handoff.py')

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def schedule():
    first, evolved = [], []
    for init in (0, 1):
        for hi, history in enumerate(('alpha', 'beta')):
            arms = ('native', 'memrsi_fixed') if (hi + init) % 2 == 0 else ('memrsi_fixed', 'native')
            for arm in arms + ('memrsi_evolved',):
                row = {'trial_id': f'i{init}-{history}/{arm}', 'init': init, 'history': history,
                       'gpu': 6 + init, 'arm': arm, 'variant': 0}
                (evolved if arm == 'memrsi_evolved' else first).append(row)
    return first + evolved

def qualification(first, second):
    records, audits = {}, []
    for root in (Path(first), Path(second)):
        report = json.loads((root/'report.json').read_text())
        if not report.get('qualification_passed'): raise RuntimeError('physics_not_qualified')
        for init in (0, 1):
            row = json.loads((root/f'init{init}/result.json').read_text())
            records[(init, row['history'])] = row
    for init in (0, 1):
        a, b = [records[(init, h)] for h in ('alpha', 'beta')]
        sa, sb = a['recovery_snapshot'], b['recovery_snapshot']
        equal = (sa['current_input_sha256'] == sb['current_input_sha256'] and
                 sa['station_state_sha256'] == sb['station_state_sha256'] and
                 sa['action_contract_sha256'] == sb['action_contract_sha256'])
        opposite = sa['expected_first_private'] != sb['expected_first_private']
        audits.append({'init': init, 'same_present': equal, 'different_required_action': opposite,
                       'both_complete_physically': a['status'] == b['status'] == 'success'})
    # End-to-end trials need physical feasibility. Exact historical A/B claims
    # additionally need matching observed input/state, audited per actual pair.
    # Do not normalize small simulator differences away or call them identical.
    if not all(x['different_required_action'] and x['both_complete_physically'] for x in audits) or not any(x['same_present'] for x in audits):
        raise RuntimeError('information_pair_not_qualified')
    return audits

def summarize(rows, planned):
    result = {}
    for arm in ('native', 'memrsi_fixed', 'memrsi_evolved'):
        group = [r for r in rows if r['arm'] == arm]
        counts = {}
        for row in group: counts[row['status']] = counts.get(row['status'], 0) + 1
        n, reached, answered, correct = (sum(r.get(k, 0) for r in group) for k in
            ('planned_checkpoints', 'reached_checkpoints', 'answered_checkpoints', 'correct_checkpoints'))
        result[arm] = {'planned_trials': sum(r['arm'] == arm for r in planned), 'terminal_trials': len(group),
            'status_counts': counts, 'planned_checkpoints_in_terminal_trials': n,
            'reached': reached, 'answered': answered, 'correct': correct,
            'arrival_coverage': reached/n if n else None,
            'decision_accuracy_given_answer': correct/answered if answered else None}
    return result

def paired_audit(rows):
    groups = {}
    for r in rows: groups.setdefault((r['arm'], r['init']), {})[r['history']] = r
    results = []
    for (arm, init), histories in groups.items():
        if set(histories) != {'alpha', 'beta'}: continue
        a, b = [histories[h] for h in ('alpha', 'beta')]
        sa, sb = a.get('recovery_snapshot'), b.get('recovery_snapshot')
        equal = bool(sa and sb and sa['current_input_sha256'] == sb['current_input_sha256'] and
                     sa['station_state_sha256'] == sb['station_state_sha256'])
        answers = [[d for d in x.get('decisions', []) if d['checkpoint']] for x in (a, b)]
        both_answer = all(bool(x) for x in answers)
        results.append({'arm': arm, 'init': init, 'same_present_verified': equal,
            'both_answered_first_recovery': both_answer,
            'both_correct_first_recovery': all(x[0]['correct'] for x in answers) if both_answer else None,
            'both_end_to_end_success': a['status'] == b['status'] == 'success'})
    return results

def main(a):
    out = Path(a.output); out.mkdir(parents=True, exist_ok=False)
    stop = threading.Event(); active = {}; rows = []; lock = threading.RLock(); runners = []
    planned = schedule(); status = 'interrupted'
    def state(status='running', **extra):
        with lock: dump(out/'progress.json', dict(status=status, planned=len(planned), terminal=len(rows),
            active=dict(active), updated_unix=time.time(), **extra))
    def signal_stop(*_):
        stop.set()
        for runner in runners: runner.stop.set()
    for sig in (signal.SIGINT, signal.SIGTERM): signal.signal(sig, signal_stop)
    dump(out/'coordinator.json', identity(os.getpid()))
    def wait_file(path, seconds=7200):
        deadline = time.monotonic()+seconds
        while not Path(path).is_file():
            if stop.wait(5): raise RuntimeError('queue_cancelled')
            if time.monotonic()>deadline: raise RuntimeError('prerequisite_wait_exhausted')
            state('waiting_prerequisite', path=str(path))
    try:
        for p in (Path(a.qualification)/'report.json', Path(a.reverse)/'report.json', a.budget): wait_file(p)
        audits = qualification(a.qualification, a.reverse)
        config = json.loads(Path(a.budget).read_text()); dump(out/'budget.json', config)
        (out/'selected-orders.json').write_bytes(Path(a.orders).read_bytes())
        (out/'policies').mkdir(); dump(out/'policies/fixed.json', load(a.base_policy))
        files = {p.name: sha(p) for p in ROOT.glob('*.py')}
        manifest = {'version': 'memrsi-twenty-v3', 'schedule': planned, 'gpus': [6,7],
            'planned_trials': 12, 'sessions_per_trial': 20, 'session_switches_per_trial': 19,
            'planned_checkpoints_per_trial': 7, 'source_sha256': files,
            'physical_source_sha256': {n: sha(ROOT/n) for n in PHYSICAL_FILES},
            'budget': config, 'orders_sha256': sha(out/'selected-orders.json'),
            'physical_reference_sources': [a.qualification, a.reverse], 'information_pair_qualification': audits,
            'strict_pair_scope': 'Reference init1 matched exactly; init0 had ~2mm mug-position/one-step differences. Actual evaluation pairs qualify independently by hashes. Unmatched pairs retain end-to-end outcomes but are not strict identical-present evidence.',
            'public_protocol': {h: plan(h) for h in ('alpha','beta')},
            'calibration_protocol_change': 'Initial instruction explicitly defines Continue-without-new-order as resuming service; physical sequence and all native skills unchanged from qualification.',
            'baseline': 'Original PAOS core and archive/session logic, shared declared action and capacity adapters, no G/U policy.',
            'scope': 'One serial simulated robot per independent trial; program scene routing, no navigation claim.',
            'evolved_policy_source': a.evolution_policy, 'eval_feedback_to_evolution': False,
            'guidance_runtime': 'One fallible G generation, bounded format repair only; no semantic judge or hard veto. Actor chooses using original public records and tool contract.',
            'tool_contract_revision': 'Single public catalog in tool schema, TOOLS, G and MemRSI U. Native archive prompt unchanged.',
            'case_retries': 0, 'policy_restarts': 0,
            'stopping': 'One lane stops after two consecutive infra/protocol/budget/guidance failures; capability failure is terminal and not retried.',
            'phase_order': '8 native/fixed trials, then 4 evolved; GPU resources released while waiting for evolution.',
            'temporal_confound': 'Evolved trials run later; policy freeze and service/model identity recorded.'}
        dump(out/'manifest.json', manifest)
        def guard():
            if any(sha(ROOT/n) != h for n,h in files.items()): raise RuntimeError('source_changed_after_launch')
        def phase(phase_name, selected, policies):
            if stop.is_set(): return
            directory = out/phase_name; directory.mkdir()
            runner = PhysicalRunner(directory); runners.append(runner)
            def lane(gpu):
                bad = 0
                for row in [x for x in selected if x['gpu'] == gpu]:
                    if stop.is_set() or runner.stop.is_set(): break
                    guard(); dest = out/'evaluation'/row['trial_id']; dest.parent.mkdir(parents=True, exist_ok=True)
                    if dest.exists(): raise RuntimeError('episode_output_already_exists')
                    cmd = [AGENT_PYTHON, str(ROOT/'twenty_workflow.py'), '--output',str(dest),
                        '--orders',str(out/'selected-orders.json'),'--port',str(PORTS[gpu]),'--init',str(row['init']),
                        '--history',row['history'],'--variant','0','--arm','native' if row['arm']=='native' else 'memrsi',
                        '--budget',str(out/'budget.json')]
                    if row['arm'] != 'native': cmd += ['--memory-policy',str(policies[row['arm']])]
                    with dest.with_suffix('.log').open('xb') as log:
                        p = subprocess.Popen(cmd,cwd=ROOT,env=env(gpu),stdout=log,stderr=log,
                            stdin=subprocess.DEVNULL,start_new_session=True)
                    ident = runner.track(p,'worker')
                    with lock: active[str(gpu)] = dict(row,worker=ident,output=str(dest));state(phase_name)
                    start = time.monotonic(); error = None
                    try:
                        while p.poll() is None:
                            if stop.wait(2): error='queue_cancelled';break
                            if time.monotonic()-start > a.episode_timeout: error='worker_timeout';break
                        if error: runner.stop_owned(p)
                        result = json.loads((dest/'result.json').read_text()) if (dest/'result.json').exists() else {
                            'status':'infrastructure_failure','error_code':'worker_exit','return_code':p.poll()}
                        if error: result.update(status='infrastructure_failure',error_code=error)
                        result.update(row,output=str(dest),worker=ident)
                    finally:
                        if p.poll() is None: runner.stop_owned(p)
                        runner.release_process(p)
                    with lock:
                        rows.append(result);dump(out/'rows.json',rows);dump(out/'summary.json',summarize(rows,planned))
                        dump(out/'history-pairs.json',paired_audit(rows));active.pop(str(gpu),None);state(phase_name)
                    bad = bad+1 if result['status'] in ('infrastructure_failure','budget_failure','protocol_failure','guidance_failure') else 0
                    if bad >= 2:
                        with lock: active[str(gpu)] = {'status':'held_after_two_technical_failures'};state('technical_hold')
                        break
            try:
                runner.acquire(state); guard()
                with concurrent.futures.ThreadPoolExecutor(2) as pool:
                    futures = [pool.submit(lane,g) for g in (6,7)]
                    for f in concurrent.futures.as_completed(futures): f.result()
            finally: runner.close()
        phase('native_fixed', planned[:8], {'memrsi_fixed':out/'policies/fixed.json'})
        if len(rows)==8 and not stop.is_set():
            evolved = wait_for_policy(a.evolution_policy,time.monotonic()+12*3600,stop,state)
            dump(out/'policies/evolved.json',evolved)
            dump(out/'frozen-policies.json', {'fixed_sha256':sha(out/'policies/fixed.json'),
                'evolved_sha256':sha(out/'policies/evolved.json'),
                'identical': evolved == load(out/'policies/fixed.json'),
                'interpretation':'Identical procedures provide no evidence of learned rule change.'})
            phase('evolved',planned[8:],{'memrsi_evolved':out/'policies/evolved.json'})
        status = 'completed' if len(rows)==12 else 'cancelled' if stop.is_set() else 'technical_hold'
    except Exception as exc:
        safe = {'physics_not_qualified','information_pair_not_qualified','source_changed_after_launch',
                'evolution_failed','evolution_wait_budget_exhausted','queue_cancelled','prerequisite_wait_exhausted'}
        code = str(exc) if str(exc) in safe else 'inspect_structured_outputs'
        dump(out/'queue-failure.json',{'type':type(exc).__name__,'code':code});status='failed'
    finally:
        for runner in runners: runner.close()
        done = {x['trial_id'] for x in rows}
        dump(out/'report.json',{'status':status,'terminal':len(rows),'planned':12,'summary':summarize(rows,planned),
            'history_pairs':paired_audit(rows),'pending':[x['trial_id'] for x in planned if x['trial_id'] not in done]})
        state(status)

if __name__ == '__main__':
    p=argparse.ArgumentParser()
    for arg in ('output','qualification','reverse','budget','orders','base-policy','evolution-policy'):p.add_argument('--'+arg,required=True)
    p.add_argument('--episode-timeout',type=int,default=10800)
    main(p.parse_args())
