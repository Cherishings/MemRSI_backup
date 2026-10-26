"""One provenance-checked development, validation, or frozen test trajectory.

A durable registry prevents a different output directory from resetting an
attempt. Global learning-budget exhaustion pauses the experiment; it is never
scored as a capability failure. This launcher does not resume simulator state.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROBOT = Path('/data/stormlab/xi/robot')
PY_AGENT = '/home/xi/envs/agent/bin/python'
POLICY = Path('/data/stormlab/xi/paos/results/memrsi-bounded-v2_2-20261015T175555Z/experiment/frozen-policy.json')
SEEDS = {'development': range(3000, 3012), 'validation': range(3100, 3112), 'test': range(3200, 3248)}
DEFAULT_ATTEMPT_LEDGER = ROBOT / 'runs/official-memory-v5-20261017-attempts.json'
MAX_ATTEMPTS = 3
TECHNICAL_STATUSES = {'technical_failure', 'unclassified_failure'}
NATIVE_POLICY_HASH = hashlib.sha256(json.dumps({'method': 'native', 'memory_policy': None}, sort_keys=True).encode()).hexdigest()


def native_policy_hash():
    return NATIVE_POLICY_HASH


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def policy_sha(path):
    return hashlib.sha256(json.dumps(json.loads(Path(path).read_text()), sort_keys=True).encode()).hexdigest()


def write(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp.' + str(os.getpid()))
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def identity(pid):
    return {'pid': pid, 'start_ticks': Path('/proc/' + str(pid) + '/stat').read_text().rsplit(')', 1)[1].split()[19]}


def matches_identity(expected):
    try:
        current = identity(expected['pid'])
        return str(current['start_ticks']) == str(expected['start_ticks'])
    except (OSError, KeyError, IndexError, TypeError, ValueError):
        return False


def stop(child):
    """Signal only the dedicated session created and identified by this run."""
    if child is None or child.poll() is not None:
        return
    expected = getattr(child, '_trial_identity', None)
    if not expected or not matches_identity(expected):
        raise RuntimeError('child_identity_changed_cleanup_refused')
    if os.getpgid(child.pid) != child.pid:
        raise RuntimeError('child_not_owned_process_group_cleanup_refused')
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        child.wait()
        return
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        # A still-running unreaped child cannot have its PID reused; verify
        # birth time again before escalating the signal nonetheless.
        if not matches_identity(expected):
            raise RuntimeError('child_identity_changed_cleanup_refused')
        os.killpg(child.pid, signal.SIGKILL)
        child.wait()


@contextmanager
def interrupt_cleanup():
    previous = {}
    def interrupted(signum, frame):
        raise InterruptedError('launcher_interrupted')
    for signum in (signal.SIGTERM, signal.SIGINT):
        previous[signum] = signal.signal(signum, interrupted)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def source_hashes():
    """Hash deployed runtime code plus explicit protocol configuration.

    Missing deployed directories cannot yield a vacuous valid release. Runtime
    result/ready files are intentionally outside the frozen source manifest.
    """
    required = [HERE / 'run_trial.py', HERE / 'common/visual_actor.py',
                HERE / 'remem/pair_episode.py', HERE / 'rmbench/pair_episode.py',
                HERE / 'remem/protocol.json']
    if not all(path.is_file() for path in required):
        raise ValueError('deployed_source_layout_incomplete')
    paths = set(HERE.glob('*.py'))
    for name in ('common', 'remem', 'rmbench'):
        paths.update((HERE / name).rglob('*.py'))
        paths.update((HERE / name).rglob('protocol.json'))
        paths.update((HERE / name).rglob('runtime-config.json'))
    return {str(path.relative_to(HERE)): sha(path) for path in sorted(paths)}


def verify_release(args, hashes):
    if args.phase != 'test':
        return
    release = json.loads((HERE / 'release.json').read_text())
    if release.get('source_hashes') != hashes or release.get('gate') != 'passed':
        raise ValueError('formal_release_not_validated')
    policies = release.get('policy_hashes', {}).get(args.benchmark, {})
    selection = release.get('selection', {}).get(args.benchmark, {})
    initial = selection.get('initial_policy_sha256')
    if (not isinstance(initial, str) or len(initial) != 64
            or any(c not in '0123456789abcdef' for c in initial)
            or policies.get('pre') != initial):
        raise ValueError('formal_release_initial_policy_mismatch')
    basis = selection.get('basis')
    if basis == 'unchanged_parent_fallback':
        # The unchanged rule still receives the full formal cohort. No new
        # domain adaptation is claimed, and failed validation is retained.
        if (policies.get('post') != initial
                or selection.get('evolution_supported') is not False
                or selection.get('new_domain_rule_adopted') is not False):
            raise ValueError('formal_release_fallback_mismatch')
    elif basis == 'validated_candidate':
        validation = release.get('validation', {}).get(args.benchmark)
        if (not isinstance(validation, dict) or validation.get('passed') is not True
                or not policies.get('post') or policies['post'] == initial
                or validation.get('candidate_policy_sha256') != policies['post']
                or selection.get('evolution_supported') is not True
                or selection.get('new_domain_rule_adopted') is not True):
            raise ValueError('formal_release_reserved_gate_mismatch')
        effect = validation.get('effect', {})
        per_benchmark = effect.get('by_benchmark', {}).get(args.benchmark, {})
        if (effect.get('split') != 'validation'
                or effect.get('planned_pairs') != len(SEEDS['validation'])
                or effect.get('valid_pairs') != len(SEEDS['validation'])
                or per_benchmark.get('pairs') != len(SEEDS['validation'])
                or type(effect.get('success_gain')) is not int
                or effect['success_gain'] < 0
                or effect.get('new_protocol_or_capacity_failures') != []):
            raise ValueError('formal_release_reserved_gate_mismatch')
    else:
        raise ValueError('formal_release_selection_basis_missing')
    if args.method != 'native':
        expected = policies.get(args.method)
        if not expected or policy_sha(args.policy) != expected:
            raise ValueError('frozen_test_policy_mismatch')


def learning_budget_remaining(path):
    """Read remaining calls under the ledger lock; never reserve/reset them."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not path.exists():
            return 9745 - 8986  # charge() initializes the inherited ledger.
        data = json.loads(path.read_text())
        if data.get('inherited_used') != 8986 or type(data.get('used')) is not int or data['used'] < 8986:
            raise ValueError('learning_ledger_inheritance_mismatch')
        limit = data.get('authorized_limit')
        if type(limit) is not int or limit < 9745:
            raise ValueError('learning_budget_authorization_missing')
        if limit != 9745:
            approval = data.get('additional_authorization')
            if not isinstance(approval, dict) or not approval.get('user_message') or approval.get('total_limit') != limit:
                raise ValueError('learning_budget_authorization_missing')
        return max(0, limit - data['used'])


def learning_budget_available(path):
    return learning_budget_remaining(path) > 0


@contextmanager
def learning_admission(args):
    """Serialize development/validation episodes and admit 480-call capacity.

    Hold this lock before GPU acquisition until after episode cleanup. A small
    remaining balance must not start an episode that cannot be resumed in place.
    Formal test requests do not spend the cumulative learning ledger.
    """
    if os.environ.get('MEMRSI_PARALLEL_BUDGET') == '1':
        import types
        from parallel_budget import install_admission
        adapter = types.SimpleNamespace(write=write)
        install_admission(adapter)
        with adapter.learning_admission(args) as admitted:
            yield admitted
        return
    if args.phase == 'test':
        yield True
        return
    ledger = Path(args.ledger)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.with_suffix('.admission.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        remaining = learning_budget_remaining(ledger)
        if remaining < 480:
            record = {'phase': 'waiting_learning_budget', 'remaining': remaining,
                      'required_episode_capacity': 480, 'attempt_started': False, 'time': time.time()}
            write(args.output / 'waiting-learning-budget.json', record)
            write(args.output / 'progress.json', record)
            yield False
        else:
            args._learning_admission_fd = lock.fileno()
            try:
                yield True
            finally:
                del args._learning_admission_fd


def immutable_output_check(output):
    if (output / 'result.json').exists():
        raise ValueError('terminal_attempt_must_not_be_rerun')
    if (output / 'started.json').exists():
        raise ValueError('interrupted_attempt_requires_audit')
    if any((output / sub).exists() for sub in ('controller', 'simulator', 'actor')):
        raise ValueError('existing_child_artifacts_require_audit')


def register_attempt(args, info):
    """Reserve once across output directories; explicit audit for any retry."""
    path = Path(getattr(args, 'attempt_ledger', None) or DEFAULT_ATTEMPT_LEDGER)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = ':'.join(map(str, [args.benchmark, args.phase, args.seed, args.method, info['policy_sha256']]))
    output = str(args.output.resolve())
    audit_path = getattr(args, 'retry_audit', None)
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger = json.loads(path.read_text()) if path.exists() else {'version': 1, 'cases': {}}
        if ledger.get('version') != 1 or not isinstance(ledger.get('cases'), dict):
            raise ValueError('attempt_ledger_schema_mismatch')
        entries = ledger['cases'].get(key, [])
        if any(row.get('output') == output for rows in ledger['cases'].values() for row in rows):
            raise ValueError('attempt_output_already_registered')
        if entries:
            if len(entries) >= MAX_ATTEMPTS:
                raise ValueError('case_attempt_budget_exhausted')
            previous = entries[-1]
            if matches_identity(previous['identity']):
                raise ValueError('previous_attempt_process_still_alive')
            if not audit_path:
                raise ValueError('explicit_technical_retry_audit_required')
            audit = json.loads(Path(audit_path).read_text())
            if audit.get('approved') is not True or not audit.get('reason') or str(Path(audit.get('prior_output', '')).resolve()) != previous['output']:
                raise ValueError('technical_retry_audit_mismatch')
            prior_result = Path(previous['output']) / 'result.json'
            prior_status = json.loads(prior_result.read_text()).get('status') if prior_result.exists() else previous.get('status')
            if prior_status not in TECHNICAL_STATUSES | {'started'}:
                raise ValueError('capability_or_paused_attempt_retry_forbidden')
            # An interrupted launch may leave children; never start a retry
            # while a recorded child still exists with its original identity.
            children_path = Path(previous['output']) / 'child-processes.json'
            if children_path.exists():
                children = json.loads(children_path.read_text())
                if any(matches_identity(row.get('identity', {})) for row in children):
                    raise ValueError('previous_attempt_child_still_alive')
            progress_path = Path(previous['output']) / 'progress.json'
            if progress_path.exists():
                progress = json.loads(progress_path.read_text())
                if any(matches_identity(progress.get(name, {})) for name in ('actor', 'controller', 'simulator')):
                    raise ValueError('previous_attempt_child_still_alive')
        elif audit_path:
            raise ValueError('retry_audit_without_prior_attempt')
        attempt = len(entries) + 1
        info.update(attempt=attempt, previous_attempts=[{'output': row['output'], 'attempt': row['attempt']} for row in entries],
                    attempt_ledger=str(path.resolve()), attempt_key=key,
                    retry_audit_sha256=sha(audit_path) if audit_path else None)
        entries.append({'output': output, 'attempt': attempt, 'identity': info['identity'], 'status': 'started'})
        ledger['cases'][key] = entries
        write(path, ledger)
    return attempt


def settle_attempt(info, status):
    path = Path(info['attempt_ledger'])
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger = json.loads(path.read_text())
        row = ledger['cases'][info['attempt_key']][-1]
        if row['attempt'] != info['attempt'] or row['identity'] != info['identity']:
            raise RuntimeError('attempt_registry_ownership_mismatch')
        row.update(status=status, finished=time.time())
        write(path, ledger)


def is_learning_pause(result, phase):
    return phase != 'test' and (result.get('status') == 'paused_learning_budget' or result.get('error_type') == 'LearningBudgetExhausted' or result.get('error_code') == 'learning_budget_exhausted')


def normalized_status(result):
    status = result.get('status')
    if status == 'policy_failure':
        return 'task_failure'
    if status != 'agent_failure':
        return status
    code = result.get('error_code')
    if code in {'active_context_budget_exceeded', 'persistent_memory_budget_exhausted'}:
        return 'capacity_failure'
    if code == 'agent_call_budget_exhausted':
        return 'budget_failure'
    if code in {'native_session_archival_failed', 'action_protocol_failure', 'guidance_protocol_failure',
                'guidance_review_protocol_failure', 'guidance_grounding_failure', 'invalid_guidance',
                'generation_output_limit', 'delta_update_protocol_failure', 'delta_memory_schema'}:
        return 'protocol_failure'
    return 'unclassified_failure'


def record_outcome(output, result, info):
    """Keep actor evidence and omit incomplete learning attempts from scores."""
    # A native /new wrapper can hide a provider error behind archival failure.
    # Reclassify only with a same-call failed public archival receipt and provider error.
    if result.get('status') == 'agent_failure' and result.get('error_code') == 'native_session_archival_failed':
        sys.path.insert(0, str(HERE/'common'))
        from archive_transport_evidence import transport_evidence
        evidence = transport_evidence(output/'actor', result)
        if evidence:
            write(output/'original-actor-result.json', result)
            result = dict(result, status='technical_failure', error_code='provider_failure_wrapped_by_archival', confirmed_transport=evidence)
            write(output/'result.json', result)
    if is_learning_pause(result, info['split']):
        write(output / 'actor-result.json', result)
        result = dict(result, status='paused_learning_budget', pause_reason='cumulative_learning_budget_exhausted',
                      resume_requires_audit=True, simulator_state_checkpointed=False)
        write(output / 'result.json', result)
        write(output / 'trial-paused.json', {'phase': info['split'], 'status': result['status'], 'attempt': info['attempt'], 'time': time.time()})
        write(output / 'progress.json', {'phase': 'paused_learning_budget', 'attempt': info['attempt'], 'resume_requires_audit': True})
    else:
        write(output / 'scored-record.json', {'benchmark': info['benchmark'], 'seed': info['seed'], 'method': info['method'],
              'split': info['split'], 'status': normalized_status(result), 'official_success': bool(result.get('official_check_success', False)),
              'policy_sha256': info['policy_sha256']})
        write(output / 'trial-complete.json', {'phase': info['split'], 'status': result['status'], 'attempt': info['attempt'], 'time': time.time()})
    settle_attempt(info, result['status'])
    return result


def ready(path, child, limit=360):
    start = time.monotonic()
    while True:
        if child.poll() is not None:
            raise RuntimeError('controller_exited_before_ready')
        if path.exists():
            try:
                record = json.loads(path.read_text())
            except json.JSONDecodeError:
                record = None  # Writers do not all publish atomically.
            if record is not None:
                expected = child._trial_identity
                if record.get('pid') != expected['pid'] or str(record.get('start_ticks')) != str(expected['start_ticks']) or not matches_identity(expected):
                    raise RuntimeError('ready_process_identity_mismatch')
                return
        if time.monotonic() - start > limit:
            raise RuntimeError('controller_ready_timeout')
        time.sleep(2)


def run(args):
    import setproctitle
    setproctitle.setproctitle('robot')
    if args.seed not in SEEDS[args.phase]:
        raise ValueError('seed_outside_registered_split')
    if args.method not in ('native', 'pre', 'post'):
        raise ValueError('method')
    if args.phase != 'test' and not args.ledger:
        raise ValueError('learning_ledger_required')
    hashes = source_hashes()
    verify_release(args, hashes)
    args.output.mkdir(parents=True, exist_ok=True)
    bench = HERE / args.benchmark
    common = HERE / 'common'
    arm = 'native' if args.method == 'native' else 'memrsi'
    env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(args.gpu), ROBOT_GPU=str(args.gpu), OMP_NUM_THREADS='2',
               OPENBLAS_NUM_THREADS='2', HF_HUB_OFFLINE='1', HF_HUB_DISABLE_IMPLICIT_TOKEN='1', LITELLM_LOCAL_MODEL_COST_MAP='True')
    if args.phase != 'test':
        env.update(MEMRSI_LEARNING_LEDGER=str(args.ledger.resolve()), MEMRSI_PHASE=args.phase,
                   MEMRSI_CASE_ID=args.benchmark + ':' + str(args.seed) + ':' + args.method)
    else:
        for key in ('MEMRSI_LEARNING_LEDGER', 'MEMRSI_PHASE', 'MEMRSI_CASE_ID'):
            env.pop(key, None)
    deps = ROBOT / 'official-memory-common-20261017/deps'
    actor_overlay = ROBOT / ('official-memory-remem-r4-20261017' if args.benchmark == 'remem' else 'official-memory-rmbench-20261017r4') / 'actor-deps'
    env['PYTHONPATH'] = ':'.join(map(str, [actor_overlay, deps, common, bench]))

    children = []

    def spawn(command, filename, child_env, gpu_lock):
        inherited_locks = [gpu_lock.fileno()]
        admission_fd = getattr(args, '_learning_admission_fd', None)
        if admission_fd is not None:
            inherited_locks.append(admission_fd)
        with (args.output / filename).open('a') as log:
            child = subprocess.Popen(command, env=child_env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                     start_new_session=True, pass_fds=tuple(inherited_locks))
        child._trial_identity = identity(child.pid)
        children.append({'role': filename.split('.')[0], 'identity': child._trial_identity})
        write(args.output / 'child-processes.json', children)
        return child

    with interrupt_cleanup(), (args.output / 'trial.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Check after obtaining the lock, including stale ready/actor artifacts.
        immutable_output_check(args.output)
        with learning_admission(args) as admitted:
            if not admitted:
                return
            _run_admitted(args, hashes, arm, bench, env, spawn)


def _run_admitted(args, hashes, arm, bench, env, spawn):
    with (ROBOT.parent / 'paos/qwen-deploy' / ('gpt-gpu' + str(args.gpu) + '-run.lock')).open('a') as gpu:
        while True:
            try:
                fcntl.flock(gpu, fcntl.LOCK_EX | fcntl.LOCK_NB)
                used = int(subprocess.check_output(['nvidia-smi', '-i', str(args.gpu), '--query-gpu=memory.used', '--format=csv,noheader,nounits'], text=True).strip())
                if used <= 1024:
                    break
                fcntl.flock(gpu, fcntl.LOCK_UN)
            except BlockingIOError:
                pass
            write(args.output / 'progress.json', {'phase': 'waiting_gpu', 'gpu': args.gpu})
            time.sleep(15)
        if source_hashes() != hashes:
            raise ValueError('source_changed_while_waiting')
        verify_release(args, hashes)
        if args.phase != 'test' and learning_budget_remaining(args.ledger) < 480:
            record = {'phase': 'waiting_learning_budget', 'remaining': learning_budget_remaining(args.ledger), 'required_episode_capacity': 480, 'attempt_started': False, 'time': time.time()}
            write(args.output / 'waiting-learning-budget.json', record)
            write(args.output / 'progress.json', record)
            return
        info = dict(benchmark=args.benchmark, seed=args.seed, method=args.method, arm=arm, split=args.phase,
                    gpu=args.gpu, policy_sha256=NATIVE_POLICY_HASH if arm == 'native' else policy_sha(args.policy),
                    policy_file_sha256=None if arm == 'native' else sha(args.policy), source_hashes=hashes,
                    identity=identity(os.getpid()), time=time.time())
        attempt = register_attempt(args, info)
        write(args.output / 'started.json', info)
        # A per-attempt immutable copy prevents policy replacement while a
        # controller is loading from silently changing the evaluated arm.
        policy = args.policy
        if arm != 'native':
            policy = args.output / 'frozen-policy.json'
            policy.write_bytes(args.policy.read_bytes())
            if policy_sha(policy) != info['policy_sha256'] or sha(policy) != info['policy_file_sha256']:
                raise RuntimeError('policy_changed_during_snapshot')
        controller = simulator = actor = None
        try:
            if args.benchmark == 'remem':
                sys.path.insert(0, str(bench))
                from runtime import execution_env
                ctrl_env = execution_env(args.gpu)
                port = 19353 + args.gpu
                controller = spawn([str(ROBOT / 'official-memory-remem-20261017/venv/bin/robot'), str(bench / 'controller_server.py'), '--seed', str(args.seed), '--port', str(port), '--output', str(args.output / 'controller')], 'controller.private.log', ctrl_env, gpu)
                write(args.output / 'progress.json', dict(phase='loading_controller', controller=controller._trial_identity, gpu=args.gpu))
                ready(args.output / 'controller/ready.json', controller)
                command = [PY_AGENT, str(bench / 'pair_episode.py'), '--arm', arm, '--seed', str(args.seed), '--output', str(args.output), '--controller-output', str(args.output / 'controller'), '--policy', str(policy), '--attempt', str(attempt), '--port', str(port)]
            else:
                cp = 19400 + args.gpu * 2
                sp = cp + 1
                ctrl_env = dict(env, PYTHONPATH=':'.join(map(str, [HERE / 'executor-deps', bench])))
                controller = spawn([str(ROBOT / 'envs/rmbench-executor-20261017/bin/robot'), str(bench / 'controller_server.py'), '--port', str(cp), '--output', str(args.output / 'controller')], 'controller.private.log', ctrl_env, gpu)
                write(args.output / 'progress.json', dict(phase='loading_controller', controller=controller._trial_identity, gpu=args.gpu))
                ready(args.output / 'controller/controller-ready.json', controller, 600)
                sim_env = dict(env, PYTHONPATH=str(bench), MUJOCO_GL='egl', PYNPUT_BACKEND='dummy', PATH=str(ROBOT / 'envs/rmbench/bin') + ':' + os.environ['PATH'], LD_LIBRARY_PATH=str(ROBOT / 'envs/twin/lib'), CUDA_HOME=str(ROBOT / 'envs/twin'))
                simulator = spawn([str(ROBOT / 'envs/rmbench/bin/robot'), str(bench / 'bootstrap.py'), str(bench / 'simulator_server.py'), '--seed', str(args.seed), '--port', str(sp), '--output', str(args.output / 'simulator')], 'simulator.private.log', sim_env, gpu)
                write(args.output / 'progress.json', dict(phase='loading_simulator', controller=controller._trial_identity, simulator=simulator._trial_identity, gpu=args.gpu))
                ready(args.output / 'simulator/simulator-ready.json', simulator)
                command = [PY_AGENT, str(bench / 'pair_episode.py'), '--arm', arm, '--seed', str(args.seed), '--policy', str(policy), '--output', str(args.output), '--simulator-output', str(args.output / 'simulator'), '--controller-port', str(cp), '--simulator-port', str(sp)]
            actor = spawn(command, 'actor.private.log', env, gpu)
            write(args.output / 'progress.json', dict(phase='running', actor=actor._trial_identity, controller=controller._trial_identity,
                  simulator=simulator._trial_identity if simulator else None, gpu=args.gpu))
            actor.wait()
            if not (args.output / 'result.json').exists():
                raise RuntimeError('actor_exit_without_result')
        except Exception as error:
            if not (args.output / 'result.json').exists():
                # Error messages may include transport secrets: write only
                # the exception class and a fixed launcher-level code here.
                write(args.output / 'result.json', dict(status='technical_failure', error_type=type(error).__name__, error_code='trial_launcher_failure', attempt=attempt))
        finally:
            cleanup = []
            for name, child in (('actor', actor), ('simulator', simulator), ('controller', controller)):
                try:
                    stop(child)
                except Exception as error:
                    cleanup.append({'child': name, 'error_type': type(error).__name__})
            if cleanup:
                write(args.output / 'cleanup-errors.json', cleanup)
        result = json.loads((args.output / 'result.json').read_text())
        if source_hashes() != hashes:
            write(args.output / 'invalid-protocol.json', {'reason': 'source_changed_during_trial', 'time': time.time()})
            settle_attempt(info, 'technical_failure')
            return
        record_outcome(args.output, result, info)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--benchmark', choices=['remem', 'rmbench'], required=True)
    parser.add_argument('--phase', choices=SEEDS, required=True)
    parser.add_argument('--method', choices=['native', 'pre', 'post'], required=True)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--gpu', type=int, choices=range(8), required=True)
    parser.add_argument('--policy', type=Path, default=POLICY)
    parser.add_argument('--ledger', type=Path)
    parser.add_argument('--attempt-ledger', type=Path, default=DEFAULT_ATTEMPT_LEDGER)
    parser.add_argument('--retry-audit', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args())


if __name__ == '__main__':
    main()
