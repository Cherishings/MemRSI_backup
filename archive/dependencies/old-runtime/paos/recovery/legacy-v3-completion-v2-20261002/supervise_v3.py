#!/usr/bin/env python3
"""Bounded per-GPU recovery supervisor; never modifies or stops legacy processes."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time

STOP = threading.Event()
DEPLOY = Path("/data/stormlab/xi/paos/qwen-deploy")


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, path)


def identity(pid):
    try:
        path = Path("/proc") / str(int(pid))
        fields = (path / "stat").read_text().rsplit(") ", 1)[1].split()
        if fields[0] == "Z":
            return None
        return {"pid": int(pid), "start_ticks": fields[19],
                "cmdline": (path / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")}
    except (FileNotFoundError, PermissionError, ProcessLookupError, ValueError):
        return None


def alive(expected):
    current = identity(expected["pid"]) if expected else None
    return bool(current and current["start_ticks"] == str(expected["start_ticks"]))


def matching_worker(repo, original, worker, proc_root=Path("/proc")):
    """Read only candidate process arguments; return matching legacy workers only."""
    matches = []
    script = str(Path(repo) / "scripts/run_continuous_mission.py")
    for path in proc_root.iterdir():
        if not path.name.isdigit():
            continue
        try:
            argv = (path / "cmdline").read_bytes().decode(errors="replace").split("\0")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if script not in argv:
            continue
        options = dict(zip(argv, argv[1:]))
        if options.get("--output") == str(original) and options.get("--worker") == str(worker):
            matches.append(int(path.name))
    return matches


def verify_legacy_sources(original):
    manifest = read(Path(original) / "manifest.json")
    if not manifest or not manifest.get("sources"):
        raise RuntimeError("Original source manifest missing")
    for name, expected in manifest["sources"].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Frozen legacy source changed: {name}")
    return manifest


def stop_owned(process, grace_seconds=10):
    if process is None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)


def lease_holder(lock_path, marker, owner):
    """Acquire the standard GPU lock when the old launcher releases it."""
    mine = identity(os.getpid())
    with Path(lock_path).open("a") as handle:
        while not STOP.is_set() and alive(owner):
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                STOP.wait(0.2)
        else:
            return 130
        write(marker, {"holder": mine, "owner": owner, "acquired": True, "acquired_at": now(), "lock": str(lock_path)})
        while not STOP.is_set() and alive(owner):
            STOP.wait(0.5)
        write(marker, {"holder": mine, "owner": owner, "acquired": False, "released_at": now(), "lock": str(lock_path)})
    return 0


def lease_owned(marker):
    row = read(marker, {}) or {}
    return bool(row.get("acquired") is True and alive(row.get("holder")))


def gpu_lock_path(gpu):
    if gpu not in (0, 1):
        raise ValueError("Only GPUs 0 and 1 are authorized")
    return DEPLOY / ("robot-run.lock" if gpu == 0 else "gpt-gpu1-run.lock")


def runner_command(args, policy_pid, parent_file, lease_file):
    return [sys.executable, "-u", str(Path(args.resume_script).resolve()),
            "--repo", str(Path(args.repo).resolve()), "--original", str(Path(args.original).resolve()),
            "--output", str(Path(args.output).resolve()), "--worker", str(args.worker), "--policy-port", str(args.policy_port),
            "--policy-pid", str(policy_pid), "--original-parent-pid", str(args.original_parent_pid),
            "--original-parent-identity-file", str(parent_file), "--lease-acquired-file", str(lease_file)]


def supervise(args):
    repo, original, output = map(lambda x: Path(x).resolve(), (args.repo, args.original, args.output))
    output.mkdir(parents=True, exist_ok=True)
    policy = runner = holder = None
    handles = []
    exit_code, error, started = 1, None, time.monotonic()
    status = {"status": "starting", "started_at": now(), "original": str(original), "output": str(output)}
    progress_path = output / "supervisor-progress.json"
    owner = identity(os.getpid())
    with (output / "supervisor.lock").open("a") as own_lock, (DEPLOY / f"recovery-gpu{args.gpu}.lock").open("a") as recovery_lock:
        fcntl.flock(own_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(recovery_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        write(output / "launcher-identity.json", owner)
        (output / "launcher.pid").write_text(str(os.getpid()) + "\n")
        try:
            config = {"repo": str(repo), "original": str(original), "resume_script": str(Path(args.resume_script).resolve()),
                      "parent_pid": args.original_parent_pid, "parent_start_ticks": args.original_parent_start_ticks,
                      "policy_port": args.policy_port, "gpu": args.gpu, "worker": args.worker, "timeout_seconds": args.timeout_seconds}
            prior = read(output / "supervisor-config.json")
            if prior and prior != config:
                raise RuntimeError("Recovery supervisor configuration changed")
            write(output / "supervisor-config.json", config)
            verify_legacy_sources(original)
            live_workers = matching_worker(repo, original, args.worker)
            if live_workers:
                raise RuntimeError(f"Original worker {args.worker} still alive: {live_workers}")
            expected_parent = {"pid": args.original_parent_pid, "start_ticks": str(args.original_parent_start_ticks),
                               "cmdline": f"legacy launcher {repo}/scripts/launch_continuous_mission.sh {original}"}
            current_parent = identity(args.original_parent_pid)
            if current_parent and current_parent["start_ticks"] == expected_parent["start_ticks"]:
                if str(original) not in current_parent["cmdline"] or str(repo / "scripts/launch_continuous_mission.sh") not in current_parent["cmdline"]:
                    raise RuntimeError("Original parent identity does not match expected legacy run")
                expected_parent = current_parent
            parent_file, lease_file = output / "original-parent-identity.json", output / f"gpu{args.gpu}-lease.json"
            write(parent_file, expected_parent)
            if lease_owned(lease_file):
                raise RuntimeError("Another live recovery lease holder already exists")
            write(lease_file, {"acquired": False, "owner": owner, "status": "waiting"})
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", args.policy_port)) == 0:
                    raise RuntimeError(f"Port {args.policy_port} occupied; refusing unknown policy server")
            free = int(subprocess.check_output(["nvidia-smi", "-i", str(args.gpu), "--query-gpu=memory.free", "--format=csv,noheader,nounits"], text=True).strip())
            if free < 30000:
                raise RuntimeError(f"GPU{args.gpu} has only {free} MiB free; no processes will be evicted")
            holder_log = (output / "lease-holder.log").open("ab")
            handles.append(holder_log)
            holder = subprocess.Popen([sys.executable, "-u", str(Path(__file__).resolve()), "--lease-holder",
                                       "--lease-lock", str(gpu_lock_path(args.gpu)), "--lease-marker", str(lease_file),
                                       "--owner-pid", str(owner["pid"]), "--owner-start-ticks", owner["start_ticks"]],
                                      stdout=holder_log, stderr=subprocess.STDOUT, start_new_session=True)
            status["lease_holder"] = identity(holder.pid)
            write(progress_path, status)
            while not STOP.is_set() and not alive(expected_parent) and not lease_owned(lease_file):
                if holder.poll() is not None:
                    raise RuntimeError("GPU lease holder exited before acquiring lock")
                if time.monotonic() - started > args.timeout_seconds:
                    raise TimeoutError("Recovery wall-clock budget exhausted while waiting for GPU lock")
                status.update(status="waiting_for_gpu_lock")
                write(progress_path, status)
                STOP.wait(0.5)
            if STOP.is_set():
                raise InterruptedError("Recovery stopped before policy startup")
            status.update(status="starting_policy", borrowing_old_launcher_lock=alive(expected_parent) and not lease_owned(lease_file))
            write(progress_path, status)
            policy_log = (output / f"policy-{args.gpu}.log").open("ab")
            handles.append(policy_log)
            env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(args.gpu), PAOS_DIAG_PORT=str(args.policy_port), XLA_PYTHON_CLIENT_PREALLOCATE="false")
            policy = subprocess.Popen(["/data/stormlab/xi/paos/venvs/policy/bin/python", "-u", str(repo / "scripts/serve_mission_policy.py")],
                                      cwd=repo, env=env, stdout=policy_log, stderr=subprocess.STDOUT, start_new_session=True)
            policy_identity = identity(policy.pid)
            write(output / "policy-identity.json", policy_identity)
            status["policy"] = policy_identity
            write(progress_path, status)
            deadline = time.monotonic() + args.startup_timeout
            while not STOP.is_set():
                if not alive(policy_identity) or policy.poll() is not None:
                    raise RuntimeError("Owned recovery policy died during startup")
                if holder.poll() is not None:
                    raise RuntimeError("GPU lease holder exited during policy startup")
                with socket.socket() as sock:
                    ready = sock.connect_ex(("127.0.0.1", args.policy_port)) == 0
                if ready:
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError("Owned recovery policy startup timeout")
                STOP.wait(1)
            if STOP.is_set():
                raise InterruptedError("Recovery stopped during policy startup")
            runner_log = (output / "resume.log").open("ab")
            handles.append(runner_log)
            runner_env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(args.gpu), MUJOCO_EGL_DEVICE_ID=str(args.gpu))
            runner = subprocess.Popen(runner_command(args, policy.pid, parent_file, lease_file), cwd=repo,
                                      env=runner_env, stdout=runner_log, stderr=subprocess.STDOUT, start_new_session=True)
            status.update(status="running", policy=policy_identity, runner=identity(runner.pid), lease_holder=identity(holder.pid))
            write(progress_path, status)
            while runner.poll() is None and not STOP.is_set():
                if not alive(policy_identity) or policy.poll() is not None:
                    raise RuntimeError("Owned recovery policy died; stopping only recovery children")
                if holder.poll() is not None:
                    raise RuntimeError("GPU lease holder died; stopping recovery admission")
                if time.monotonic() - started > args.timeout_seconds:
                    raise TimeoutError("Recovery wall-clock budget exhausted")
                STOP.wait(0.5)
            if STOP.is_set():
                raise InterruptedError("Recovery supervisor interrupted")
            exit_code = runner.returncode
            status["status"] = "completed" if exit_code == 0 else "runner_failed"
        except BaseException as exc:
            error = f"{type(exc).__name__}: {exc}"
            exit_code = 130 if isinstance(exc, (InterruptedError, KeyboardInterrupt)) else 1
            status.update(status="interrupted" if exit_code == 130 else "blocked", error=error)
        finally:
            for role, process, grace in (("runner", runner, 30), ("policy", policy, 10), ("lease_holder", holder, 10)):
                try:
                    stop_owned(process, grace_seconds=grace)
                except Exception as exc:
                    status.setdefault("cleanup_errors", []).append({"role": role, "identity": status.get(role),
                                                                   "error": f"{type(exc).__name__}: {exc}"})
                    if exit_code == 0:
                        exit_code = 1
            for handle in handles:
                handle.close()
            status.update(finished_at=now(), exit_code=exit_code, wall_seconds=round(time.monotonic() - started, 3))
            write(progress_path, status)
            progress = read(output / "progress.json", {}) or {}
            progress["supervisor"] = status
            if error:
                progress["status"] = status["status"]
            write(output / "progress.json", progress)
            (output / "exit-code.txt").write_text(str(exit_code) + "\n")
    return exit_code


def main():
    os.umask(0o077)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: STOP.set())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lease-holder", action="store_true")
    parser.add_argument("--lease-lock")
    parser.add_argument("--lease-marker")
    parser.add_argument("--owner-pid", type=int)
    parser.add_argument("--owner-start-ticks")
    parser.add_argument("--gpu", type=int, choices=(0, 1), default=1)
    parser.add_argument("--worker", type=int, choices=(0, 1), default=1)
    parser.add_argument("--policy-port", type=int, default=18887)
    parser.add_argument("--repo")
    parser.add_argument("--original")
    parser.add_argument("--output")
    parser.add_argument("--resume-script")
    parser.add_argument("--original-parent-pid", type=int, default=1992877)
    parser.add_argument("--original-parent-start-ticks", default="201166461")
    parser.add_argument("--timeout-seconds", type=float, default=43200)
    parser.add_argument("--startup-timeout", type=float, default=480)
    args = parser.parse_args()
    if args.lease_holder:
        return lease_holder(args.lease_lock, args.lease_marker,
                            {"pid": args.owner_pid, "start_ticks": args.owner_start_ticks})
    if not all((args.repo, args.original, args.output, args.resume_script)):
        parser.error("--repo, --original, --output and --resume-script are required")
    if args.gpu != args.worker:
        parser.error("GPU and legacy worker must match")
    if not 1024 <= args.policy_port <= 65535:
        parser.error("policy port must be an unprivileged TCP port")
    return supervise(args)


if __name__ == "__main__":
    sys.exit(main())
