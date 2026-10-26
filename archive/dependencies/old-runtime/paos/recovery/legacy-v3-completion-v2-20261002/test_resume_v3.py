import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest

spec = importlib.util.spec_from_file_location('resume_v3_test', Path(__file__).with_name('resume_v3.py'))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def setup(tmp_path, monkeypatch, *, unknown=False):
    repo, original, output = [tmp_path / n for n in ('repo', 'original', 'continuation')]
    (repo / 'scripts').mkdir(parents=True)
    script = repo / 'scripts' / 'run_continuous_mission.py'
    script.write_text('''import json\nfrom pathlib import Path\nasync def trial(args, case, output, key):\n assert args.max_calls == 180 and args.max_skills == 10\n assert args.skill_steps == 520 and args.total_steps == 4000\n assert args.rollover_after_skills == 3 and not hasattr(args, 'provider_timeout_s')\n assert case['seed'] == 42\n p=Path(output)/'cases'/case['id']; p.mkdir(parents=True)\n attempt=int(Path(output).name.split('-')[-1])\n if case.get('unknown'):\n  result={'status':'error','error_type':'RuntimeError','error':'Unrecognized simulator failure'}\n elif (case['id']=='missing' and attempt==1) or (case['id']=='retry' and attempt==2):\n  result={'status':'error','error_type':'RuntimeError','error':'Native archival failed '+key}\n  (p/'requests.jsonl').write_text(json.dumps({'response':{'finish_reason':'error','content':'Error: Request timed out.'}})+'\\n')\n else:\n  result={'status':'completed','mission_success':case['id']=='retry','termination_reason':'model_protocol_error' if case['id']=='missing' else 'success'}\n (p/'result.json').write_text(json.dumps(result))\n return result\n''')
    (repo / 'scripts' / 'loguru.py').write_text('class Logger:\n def remove(self): pass\n def add(self,*a,**kw): assert kw==dict(diagnose=False,backtrace=False)\nlogger=Logger()\n')
    jobs = [{'id': str(i), 'seed': 42} for i in range(6)]
    jobs[1]['id'] = 'completed'
    jobs[3].update(id='missing', unknown=unknown)
    jobs[5]['id'] = 'retry'
    budgets = dict(model_calls_per_case=180,max_skills=10,skill_steps=520,total_steps=4000,rollover_after_skills=3)
    manifest = {'jobs': jobs, 'sources': {str(script): r.digest(script)}, 'budgets': budgets}
    save(original / 'manifest.json', manifest)
    save(original / 'cases' / 'completed' / 'result.json', {'status': 'completed', 'mission_success': False})
    save(original / 'cases' / 'retry' / 'result.json', {'status': 'error', 'error_type': 'RuntimeError', 'error': 'Native archival failed'})
    (original / 'cases' / 'retry' / 'requests.jsonl').write_text(json.dumps({'response':{'finish_reason':'error','content':'Error: Request timed out.'}})+'\n')
    key = tmp_path / 'key'
    key.write_text('TEST_PRIVATE_KEY_DO_NOT_LOG')
    cli = SimpleNamespace(original=str(original), repo=str(repo), output=str(output), worker=1,
        policy_port=18887, policy_pid=os.getpid(), api_key_file=str(key), runtime_file='frozen_runtime',
        libero_python='fake', case_timeout=20, original_parent_pid=None)
    monkeypatch.setattr(r, 'verify_policy', lambda *a: None)
    return cli, manifest, original, output


def test_fake_trial_continues_only_missing_and_explicit_transport_preserving_failed_results(tmp_path, monkeypatch):
    cli, manifest, original, output = setup(tmp_path, monkeypatch)
    before = {str(p): r.digest(p) for p in original.rglob('*') if p.is_file()}
    assert r.run(cli) == 0
    progress = json.loads((output / 'progress.json').read_text())
    assert list(progress['cases']) == ['missing', 'retry']
    assert progress['finished'] == 2
    assert len(progress['cases']['missing']['attempts']) == 2
    assert len(progress['cases']['retry']['attempts']) == 2
    assert progress['cases']['missing']['attempts'][-1]['result']['mission_success'] is False
    assert 'TEST_PRIVATE_KEY_DO_NOT_LOG' not in (output / 'progress.json').read_text()
    assert before == {str(p): r.digest(p) for p in original.rglob('*') if p.is_file()}
    assert (output / 'exit-code.txt').read_text().strip() == '0'
    assert (output / 'progress.json').stat().st_mode & 0o077 == 0


def test_unknown_new_infrastructure_stops_before_remaining_cases(tmp_path, monkeypatch):
    cli, manifest, original, output = setup(tmp_path, monkeypatch, unknown=True)
    assert r.run(cli) == 2
    progress = json.loads((output / 'progress.json').read_text())
    assert list(progress['cases']) == ['missing']
    assert progress['cases']['missing']['status'] == 'blocked'
    assert len(progress['cases']['missing']['attempts']) == 1
    assert not (output / 'attempts' / 'retry').exists()


def test_archival_failure_alone_is_not_transport_evidence(tmp_path):
    result = {'status': 'error', 'error_type': 'RuntimeError', 'error': 'Native archival failed'}
    assert not r.known_transport(result)
    requests = tmp_path / 'requests.jsonl'
    requests.write_text(json.dumps({'response': {'finish_reason': 'length', 'content': 'truncated model archive'}}))
    assert not r.known_transport(result, requests)
    requests.write_text(json.dumps({'response': {'finish_reason': 'error', 'content': 'Error: Request timed out.'}}))
    assert r.known_transport(result, requests)


def test_source_change_is_rejected(tmp_path, monkeypatch):
    cli, manifest, original, output = setup(tmp_path, monkeypatch)
    sha = r.digest(original / 'manifest.json')
    Path(next(iter(manifest['sources']))).write_text('changed')
    with pytest.raises(RuntimeError, match='Frozen source changed'):
        r.verify_sources(manifest, original, sha)


def test_identity_reuse_rejected():
    assert r.same_identity({'pid': 1, 'start_ticks': '7'}, {'pid': 1, 'start_ticks': 7})
    assert not r.same_identity({'pid': 1, 'start_ticks': '8'}, {'pid': 1, 'start_ticks': 7})
    assert not r.same_identity(None, {'pid': 1, 'start_ticks': 7})


@pytest.mark.parametrize("worker", [0, 1])
def test_sigterm_reaps_trial_session_and_simulator_grandchild(tmp_path, monkeypatch, worker):
    import subprocess
    import sys
    import time
    cli, manifest, original, output = setup(tmp_path, monkeypatch)
    script = Path(cli.repo) / 'scripts' / 'run_continuous_mission.py'
    script.write_text('''import asyncio,json,os,subprocess,sys\nfrom pathlib import Path\nasync def trial(args,case,output,key):\n p=Path(output)/'cases'/case['id']; p.mkdir(parents=True)\n child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(600)'])\n (p/'pids.json').write_text(json.dumps({'trial':os.getpid(),'simulator':child.pid}))\n await asyncio.sleep(600)\n''')
    manifest['sources'][str(script)] = r.digest(script)
    save(original / 'manifest.json', manifest)
    policy_file = tmp_path / 'serve_mission_policy.py'
    policy_file.write_text('import time\ntime.sleep(600)\n')
    port = '18888' if worker == 0 else '18887'
    env = dict(os.environ, PAOS_DIAG_PORT=port)
    policy = subprocess.Popen([sys.executable, str(policy_file)], env=env)
    runner = None
    pids = None
    try:
        command = [sys.executable, str(Path(r.__file__).resolve()), '--original', str(original),
                   '--repo', cli.repo, '--output', str(output), '--worker', str(worker),
                   '--policy-port', port, '--policy-pid', str(policy.pid),
                   '--api-key-file', cli.api_key_file, '--runtime-file', 'frozen_runtime',
                   '--libero-python', 'fake', '--case-timeout', '300']
        runner = subprocess.Popen(command, start_new_session=True)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            found = list(output.glob('attempts/*/attempt-*/cases/*/pids.json'))
            if found:
                pids = json.loads(found[0].read_text())
                break
            if runner.poll() is not None:
                pytest.fail('Resume process exited before fake trial started')
            time.sleep(.05)
        assert pids is not None
        assert r.identity(pids['trial']) and r.identity(pids['simulator'])
        runner.terminate()
        assert runner.wait(timeout=25) == 2
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and (r.identity(pids['trial']) or r.identity(pids['simulator'])):
            time.sleep(.05)
        assert r.identity(pids['trial']) is None
        assert r.identity(pids['simulator']) is None
        assert policy.poll() is None, 'Resume cleanup must not kill caller-owned policy'
        assert (output / 'exit-code.txt').read_text().strip() == '2'
    finally:
        if runner and runner.poll() is None:
            runner.kill(); runner.wait()
        if pids:
            import signal
            try: os.killpg(pids['trial'], signal.SIGKILL)
            except ProcessLookupError: pass
        policy.terminate(); policy.wait(timeout=5)
