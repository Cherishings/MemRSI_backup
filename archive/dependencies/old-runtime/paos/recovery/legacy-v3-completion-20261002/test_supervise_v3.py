import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

SCRIPT = Path(__file__).with_name("supervise_v3.py")
spec = importlib.util.spec_from_file_location("supervise_v3", SCRIPT)
supervisor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervisor)


def test_only_matching_legacy_worker1_is_returned(tmp_path):
    repo, run = tmp_path / "repo", tmp_path / "original"
    for pid, script, output, worker in [(1, str(repo / "scripts/run_continuous_mission.py"), str(run), "0"),
                                        (2, str(repo / "scripts/run_continuous_mission.py"), str(run), "1"),
                                        (3, "unrelated.py", str(run), "1"),
                                        (4, str(repo / "scripts/run_continuous_mission.py"), "other-run", "1")]:
        folder = tmp_path / str(pid)
        folder.mkdir()
        (folder / "cmdline").write_bytes("\0".join(["python", script, "--output", output, "--worker", worker]).encode())
    assert supervisor.matching_worker1(repo, run, tmp_path) == [2]


def test_runner_plan_keeps_original_protocol_and_policy_identity(tmp_path):
    args = argparse.Namespace(resume_script=str(tmp_path / "resume_v3.py"), repo=str(tmp_path / "oldrepo"),
                              original=str(tmp_path / "oldrun"), output=str(tmp_path / "recovery"), original_parent_pid=1992877)
    command = supervisor.runner_command(args, 4321, tmp_path / "parent.json", tmp_path / "lease.json")
    options = dict(zip(command, command[1:]))
    assert options["--worker"] == "1"
    assert options["--policy-port"] == "18887"
    assert options["--policy-pid"] == "4321"
    assert options["--original-parent-pid"] == "1992877"
    assert "--max-tokens" not in command and "--timeout" not in command


def test_original_frozen_sources_must_match(tmp_path):
    source = tmp_path / "old.py"
    source.write_text("pass\n")
    supervisor.write(tmp_path / "manifest.json", {"sources": {str(source): hashlib.sha256(source.read_bytes()).hexdigest()}})
    supervisor.verify_legacy_sources(tmp_path)
    source.write_text("changed\n")
    with pytest.raises(RuntimeError, match="Frozen legacy source changed"):
        supervisor.verify_legacy_sources(tmp_path)


def test_identity_requires_start_ticks():
    mine = supervisor.identity(os.getpid())
    assert supervisor.alive(mine)
    assert not supervisor.alive({**mine, "start_ticks": "0"})


def test_lease_waits_for_old_owner_then_releases_on_shutdown(tmp_path):
    lock, marker = tmp_path / "gpu.lock", tmp_path / "lease.json"
    owner = supervisor.identity(os.getpid())
    with lock.open("a") as old_lock:
        fcntl.flock(old_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        holder = subprocess.Popen([sys.executable, str(SCRIPT), "--lease-holder", "--lease-lock", str(lock),
                                   "--lease-marker", str(marker), "--owner-pid", str(owner["pid"]),
                                   "--owner-start-ticks", owner["start_ticks"]], start_new_session=True)
        try:
            time.sleep(0.35)
            assert not supervisor.lease_owned(marker)
            fcntl.flock(old_lock, fcntl.LOCK_UN)
            deadline = time.monotonic() + 3
            while not supervisor.lease_owned(marker) and time.monotonic() < deadline:
                time.sleep(0.05)
            assert supervisor.lease_owned(marker)
            metadata = json.loads(marker.read_text())
            assert metadata["holder"]["pid"] == holder.pid
            supervisor.stop_owned(holder)
            assert not supervisor.lease_owned(marker)
            fcntl.flock(old_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            supervisor.stop_owned(holder)
