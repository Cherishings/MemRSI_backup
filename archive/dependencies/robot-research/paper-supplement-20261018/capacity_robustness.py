"""Finite Casa capacity/semantic evaluation using the frozen, public trial engine.

No rule learning, goal injection, score changes, or physical action replacement.
Each setting contains the original 24 instruction conditions x 2 repeats x 2 arms.
Run prepare once, then one run-worker process per explicitly allocated GPU.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime

VERSION = "casa-capacity-robustness-v1-20261018"
SETTINGS = {
    "base": {"persistent_tokens": 1024, "transform": "identity"},
    "cap_half": {"persistent_tokens": 512, "transform": "identity"},
    "cap_double": {"persistent_tokens": 2048, "transform": "identity"},
    "paraphrase": {"persistent_tokens": 1024, "transform": "paraphrase"},
    "distractor": {"persistent_tokens": 1024, "transform": "distractor"},
}
BASE_BUDGET = {"persistent_tokens": 1024, "active_input_tokens": 12288,
               "output_tokens_per_call": 2048}
MAX_ATTEMPTS = 3
CALL_LIMIT = 480  # Unchanged original per-attempt logical request limit.
TECHNICAL_CODES = {"physical_worker_exit", "physical_worker_timeout", "physical_startup",
                   "provider_error", "cancelled"}
DEFAULT_SOURCE = "/data/stormlab/xi/robot/memory-scale-v2_2"
DEFAULT_CORE = "/data/stormlab/xi/paos/worktrees/memrsi-bounded-v2_2"
DEFAULT_START_BEFORE = "2026-10-28T23:59:00+08:00"


def read(path, default=None):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else default


def write(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(p)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@contextmanager
def locked(path, nonblocking=False):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
        yield


def identity(pid=None):
    pid = pid or os.getpid()
    parts = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return {"pid": pid, "start_ticks": parts[19]}


def alive(who):
    try:
        p = Path(f"/proc/{who['pid']}/stat").read_text().rsplit(")", 1)[1].split()
        return p[0] != "Z" and p[19] == str(who["start_ticks"])
    except (FileNotFoundError, ProcessLookupError, KeyError):
        return False


def source_identity(source, core):
    result = {}
    for label, root in (("engine", Path(source)), ("core", Path(core))):
        if not root.is_dir():
            raise RuntimeError("source_directory_missing")
        files = {}
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.is_symlink() or "__pycache__" in p.parts:
                continue
            if (p.suffix == ".py" or ("templates" in p.parts and p.suffix == ".md") or
                    (p.suffix == ".json" and p.parent.name == "configs")):
                files[str(p.relative_to(root))] = file_sha(p)
        if not files:
            raise RuntimeError("empty_source_manifest")
        result[label] = files
    return {"files": result, "sha256": digest(result)}


def load_plans(source):
    """Import only pure protocol builders, without model or environment imports."""
    root = Path(source)
    old = sys.modules.get("protocol")
    try:
        spec = importlib.util.spec_from_file_location("protocol", root / "protocol.py")
        protocol = importlib.util.module_from_spec(spec)
        sys.modules["protocol"] = protocol
        spec.loader.exec_module(protocol)
        spec = importlib.util.spec_from_file_location("_supplement_scale", root / "scale_protocol.py")
        scale = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scale)
        if protocol.BUDGET != BASE_BUDGET:
            raise RuntimeError("source_base_budget_changed")
        plans = scale.cases("casa")
        if len(plans) != 48 or len({p["id"] for p in plans}) != 48:
            raise RuntimeError("source_case_count_changed")
        return plans
    finally:
        if old is None:
            sys.modules.pop("protocol", None)
        else:
            sys.modules["protocol"] = old


PARAPHRASES = (
    ("Complete the three assigned kitchen storage jobs.",
     "Carry out all three kitchen storage jobs assigned to you."),
    ("Begin by completing station_A; station_C and station_D remain part of this same original mission.",
     "Complete station_A first; station_C and station_D are still included in that original mission."),
    ("After any temporary work is finished, complete the remaining original stations in this order:",
     "When the temporary work is over, complete the original stations still pending in the following order:"),
    ("Finish only after this mission is complete. Start station_A now.",
     "End the workflow only once this mission is complete. Begin station_A now."),
    ("The remaining original services are a deferred request: perform them only after",
     "The remaining original services are scheduled for later: carry them out only once"),
    ("upcoming temporary work orders have been completed, not earlier.",
     "upcoming temporary work orders have all been completed; do not perform them earlier."),
    ("Temporary work order", "Temporary assignment"),
    ("put the assigned object from the counter into the cabinet.",
     "place the assigned object in the cabinet after taking it from the counter."),
    ("Use execute_current for this work order.",
     "For this assignment, invoke execute_current."),
    ("Change to the original mission: its remaining services must now be completed in this order:",
     "Revise the original mission: complete its remaining services in this new order:"),
    ("This replaces the earlier order.", "This order supersedes the previous one."),
    ("Continue processing temporary orders when assigned.",
     "Carry out temporary assignments as they are given."),
    ("Cancel the first service in the remaining-service order I originally gave you.",
     "Withdraw the first service from the remaining-service order I originally specified."),
    ("Do not return to finish that service. The second service is still required.",
     "Do not come back to complete that service. The second service remains required."),
    ("This cancellation has no replacement task. Continue the assigned temporary work.",
     "There is no replacement for this cancelled service. Proceed with the assigned temporary work."),
)
DISTRACTORS = (
    "Administrative note: today's log label is amber; the label assigns no work and changes no request.",
    "Administrative note: the stationery folder has a blue cover; this information assigns no work and changes no request.",
    "Administrative note: the reference sheet uses a sans-serif font; this information assigns no work and changes no request.",
    "Administrative note: the bulletin has a narrow margin; this information assigns no work and changes no request.",
)


def public_text(text, transform, index):
    """Only receives already public instruction text; never receives an answer."""
    if transform == "identity":
        return text
    if transform == "distractor":
        return text + " " + DISTRACTORS[index % len(DISTRACTORS)]
    if transform != "paraphrase":
        raise ValueError("unknown_public_transform")
    if text == "Continue.":
        return "Proceed."
    result = text
    for before, after in PARAPHRASES:
        result = result.replace(before, after)
    if result == text:
        raise RuntimeError("unrecognized_paraphrase_instruction")
    # Public entity names/numbers are invariant. No station/choice can be introduced.
    tokens = r"station_[A-Z]|execute_current|\b\d+\b"
    if re.findall(tokens, result) != re.findall(tokens, text):
        raise RuntimeError("paraphrase_entity_changed")
    return result


def transform_plan(plan, setting):
    new = copy.deepcopy(plan)
    for i, step in enumerate(new["steps"]):
        step["text"] = public_text(step["text"], SETTINGS[setting]["transform"], i)
    return new


def budget_for(setting):
    return dict(BASE_BUDGET, persistent_tokens=SETTINGS[setting]["persistent_tokens"])


def capacity_contract(original_contract, platform, tokens):
    text, ids = original_contract(platform)
    old = "together limited to 1024 tokens."
    if text.count(old) != 1:
        raise RuntimeError("unrecognized_capacity_contract")
    return text.replace(old, f"together limited to {tokens} tokens."), ids


@contextmanager
def trial_setting(engine, setting):
    """The existing engine passes this actual budget to TwentyAgent/BoundedStore."""
    original_budget, original_contract = engine.BUDGET, engine.contract
    engine.BUDGET = budget_for(setting)
    engine.contract = lambda platform: capacity_contract(
        original_contract, platform, engine.BUDGET["persistent_tokens"])
    try:
        yield
    finally:
        engine.BUDGET, engine.contract = original_budget, original_contract


def baseline_reuse(baseline, proof, plans, source_stamp, policy_sha):
    """Never infer historical source equality merely from currently equal files."""
    if not baseline:
        return None, "no_baseline_requested"
    base = Path(baseline)
    manifest = read(base / "manifest.json", {})
    if (manifest.get("platform") != "casa" or manifest.get("plans") != plans or
            manifest.get("budget") != BASE_BUDGET or manifest.get("methods") != ["native", "memrsi"]):
        return None, "baseline_protocol_mismatch"
    if read(base / "rsi-source.json", {}).get("sha256") != policy_sha:
        return None, "baseline_policy_mismatch"
    if proof:
        historical = read(proof, {})
        # Optional explicit proof binds prior result files and historical source identity.
        if (historical.get("source") != source_stamp or
                historical.get("baseline_manifest_sha256") != file_sha(base / "manifest.json") or
                not (base / "rows.json").exists() or
                historical.get("baseline_rows_sha256") != file_sha(base / "rows.json")):
            return None, "historical_source_identity_unproven"
    else:
        # Existing Casa and its frozen core each have a contemporaneous code manifest.
        source_root = Path(read(base / "rsi-source.json")["source"])
        historical_engine = read(base / "code-manifest.json", {})
        historical_core = read(source_root.parent / "code-manifest.json", {})
        if (historical_engine != source_stamp["files"]["engine"] or
                historical_core != source_stamp["files"]["core"]):
            return None, "historical_source_identity_unproven"
    rows = []
    original_rows = read(base / "rows.json", [])
    for plan in plans:
        for arm in ("native", "memrsi"):
            path = base / arm / plan["id"] / "result.json"
            row = read(path)
            if (not row or row.get("arm") != arm or row.get("case") != plan["id"] or
                    row not in original_rows or row.get("status") in (None, "running")):
                return None, "baseline_incomplete_or_unbound"
            rows.append((plan, arm, row, str(path)))
    return rows, "exact_historical_source_protocol_policy_match"


def jobs(plans):
    result = []
    # Interleave settings and arms to avoid making one setting a separate time block.
    names = list(SETTINGS)
    for i, plan in enumerate(plans):
        for j in range(len(names)):
            setting = names[(j + i) % len(names)]
            for arm in (("native", "memrsi") if (i + j) % 2 == 0 else ("memrsi", "native")):
                result.append({"key": f"{setting}/{arm}/{plan['id']}", "setting": setting,
                               "arm": arm, "plan": transform_plan(plan, setting)})
    return result


def prepare(a):
    out, source, core = Path(a.output), Path(a.source).resolve(), Path(a.core).resolve()
    out.mkdir(parents=True, exist_ok=True)
    plans = load_plans(source)
    policy = read(a.policy)
    if not policy or set(policy) != {"schema", "guidance", "update"}:
        raise RuntimeError("invalid_frozen_policy")
    stamp = source_identity(source, core)
    historical, reason = baseline_reuse(a.baseline, a.baseline_proof, plans, stamp, digest(policy))
    manifest = {"version": VERSION, "platform": "casa", "source": str(source), "core": str(core),
                "source_identity": stamp, "policy_sha256": digest(policy),
                "wrapper_sha256": file_sha(__file__), "settings": SETTINGS,
                "budgets": {k: budget_for(k) for k in SETTINGS},
                "case_plans": plans, "instruction_conditions": 24, "repeats_per_condition": 2,
                "arms": ["native", "memrsi"], "scheduled_total": 480,
                "new_physical_trials": 384 if historical else 480,
                "base_reuse": {"accepted": historical is not None, "reason": reason,
                               "source": str(Path(a.baseline).resolve()) if a.baseline else None},
                "max_attempts_per_case": MAX_ATTEMPTS, "logical_calls_per_attempt": CALL_LIMIT,
                "evaluation_call_ceiling": (384 if historical else 480) * MAX_ATTEMPTS * CALL_LIMIT,
                "learning_calls": 0, "test_feedback_to_learning": False,
                "start_before_epoch": parse_deadline(a.start_before),
                "start_before_iso": datetime.fromtimestamp(parse_deadline(a.start_before)).astimezone().isoformat(),
                "native_archive_and_frozen_gu_unchanged": True,
                "executor": "official_open_loop_actions_through_gripper_not_VLA",
                "scope": "custom Casa mission workflows, not official benchmark score; same qualified layouts",
                "base_fallback": "new-protocol calibration if exact historical reuse is unproven"}
    with locked(out / "dispatch.lock"):
        prior = read(out / "manifest.json")
        if prior is not None:
            if prior != manifest:
                raise RuntimeError("immutable_manifest_changed")
            return {"status": "already_prepared", "new_physical_trials": manifest["new_physical_trials"]}
        write(out / "manifest.json", manifest)
        write(out / "frozen-policy.json", policy)
        write(out / "jobs.json", jobs(plans))
        write(out / "claims.json", {})
        if historical:
            for plan, arm, row, path in historical:
                final = dict(row, setting="base", source_result=path, source_result_sha256=file_sha(path),
                             inherited_immutable=True, source_runtime_identity=stamp["sha256"])
                write(out / "base" / arm / plan["id"] / "result.json", final)
        update_summary(out)
    return {"status": "prepared", "new_physical_trials": manifest["new_physical_trials"],
            "base_reuse": manifest["base_reuse"]}


def technical_retry_allowed(row):
    # A generic technical_failure is insufficient: receipt provenance is required.
    if row.get("status") != "technical_failure":
        return False
    if row.get("error_code") in TECHNICAL_CODES:
        return True
    return any(e.get("result", {}).get("technical_failure") is True
               for e in row.get("executions", []))


def parse_deadline(value):
    try:
        return float(value)
    except ValueError:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if d.tzinfo is None:
            raise ValueError("deadline_requires_timezone")
        return d.timestamp()


def attempt_state(case):
    """Read all prior attempts; never erase a crash or resample a capability failure."""
    saved = []
    for index in range(1, MAX_ATTEMPTS + 1):
        d = Path(case) / f"attempt-{index:02d}"
        row = read(d / "result.json")
        if row is None:
            if d.exists():
                raise RuntimeError("unfinished_attempt_requires_audit")
            return saved, index
        saved.append({"path": str(d), "row": row})
        if row.get("error_code") == "unclassified_exception":
            raise RuntimeError("unclassified_trial_failure")
        if row.get("status") == "technical_failure" and not technical_retry_allowed(row):
            raise RuntimeError("unaudited_technical_failure")
        if row.get("status") != "technical_failure":
            return saved, None
    return saved, None


def attempt_calls(directory):
    directory = Path(directory)
    provider = {}
    # The unchanged provider writes this live counter in place. A brief partial
    # write is not a code failure and must not silently become zero consumption.
    for retry in range(3):
        try:
            provider = read(directory / "agent/calls.json", {})
            break
        except json.JSONDecodeError:
            if retry < 2:
                time.sleep(.01)
    result = read(directory / "result.json", {})
    n = provider.get("calls")
    m = result.get("logical_calls")
    if n is not None and m is not None and n != m:
        raise RuntimeError("attempt_call_ledger_mismatch")
    count = n if n is not None else m
    if count is None:
        # No provider has been created if the simulator itself failed to start.
        if not (directory / "agent").exists():
            return 0, "provider_not_initialized"
        return None, "unknown_calls_preserved"
    if type(count) is not int or count < 0 or count > CALL_LIMIT:
        raise RuntimeError("invalid_attempt_call_count")
    return count, "provider_calls" if n is not None else "final_logical_calls"


def update_summary(out):
    out = Path(out)
    rows, observed_calls, unknown_attempts = [], 0, []
    for job in read(out / "jobs.json", []):
        case = out / job["key"]
        row = read(case / "result.json")
        if row:
            rows.append(row)
        for p in sorted(case.glob("attempt-*")):
            count, evidence = attempt_calls(p)
            if count is None:
                unknown_attempts.append(str(p))
            else:
                observed_calls += count
    groups = {}
    for setting in SETTINGS:
        rr = [r for r in rows if r["setting"] == setting]
        pairs = {}
        for arm in ("native", "memrsi"):
            selected = [r for r in rr if r["arm"] == arm]
            groups[f"{setting}/{arm}"] = {"planned": 48, "terminal": len(selected),
                "success": sum(r["status"] == "success" for r in selected),
                "status_counts": dict(collections.Counter(r["status"] for r in selected)),
                "planned_checkpoints": sum(p["planned_checkpoints"] for p in read(out / "manifest.json")["case_plans"]),
                "reached": sum(r.get("answered", 0) for r in selected),
                "correct": sum(r.get("correct", 0) for r in selected)}
            for r in selected:
                pairs.setdefault(r["case"], {})[arm] = r
        paired = [v for v in pairs.values() if set(v) == {"native", "memrsi"}]
        valid = [v for v in paired if all(r["status"] != "technical_failure" for r in v.values())]
        groups[setting + "/paired"] = {"complete": len(paired), "nontechnical": len(valid),
            "native_success": sum(v["native"]["status"] == "success" for v in valid),
            "memrsi_success": sum(v["memrsi"]["status"] == "success" for v in valid)}
    write(out / "rows.json", rows)
    write(out / "evaluation-ledger.json", {"time": time.time(), "observed_logical_calls": observed_calls,
        "ceiling": read(out / "manifest.json")["evaluation_call_ceiling"],
        "counting": "all new attempts, including failed and active attempts; inherited baseline excluded",
        "unknown_call_attempts": unknown_attempts,
        "learning_calls": 0, "attempts_preserved": True})
    report = {"time": time.time(), "status": "completed" if len(rows) == 480 else "in_progress",
              "terminal": len(rows), "planned": 480, "summary": groups}
    write(out / "progress.json", report)
    if len(rows) == 480:
        write(out / "report.json", report)
    return report


def gpu_observation(pid, gpu):
    """Read only public nvidia-smi process identifiers, never process environment."""
    audit = {"host_gpu_requested": gpu, "launch_cuda_visible_devices": str(gpu),
             "declared_child_cuda_ordinal": 0, "physical_pid": pid,
             "launch_environment_source": "unchanged engine.Physical.__init__",
             "observed_compute_gpu_uuids": [], "actual_mapping_verified": False}
    try:
        target = subprocess.check_output(["nvidia-smi", "-i", str(gpu), "--query-gpu=uuid",
                                          "--format=csv,noheader"], text=True, timeout=10).strip()
        processes = subprocess.check_output(["nvidia-smi", "--query-compute-apps=pid,gpu_uuid",
                                             "--format=csv,noheader,nounits"], text=True, timeout=10)
        matches = []
        for line in processes.splitlines():
            parts = [x.strip() for x in line.split(",")]
            if len(parts) == 2 and parts[0] == str(pid):
                matches.append(parts[1])
        audit.update(target_gpu_uuid=target, observed_compute_gpu_uuids=matches,
                     actual_mapping_verified=bool(matches) and set(matches) == {target})
        if matches and set(matches) != {target}:
            raise RuntimeError("physical_process_gpu_mismatch")
        if not matches:
            audit["observation_limit"] = "graphics-only EGL workers may not be listed by query-compute-apps"
    except (OSError, subprocess.SubprocessError):
        audit["observation_limit"] = "nvidia_process_query_unavailable"
    return audit


def claim_job(out, me, gpu):
    out = Path(out)
    with locked(out / "dispatch.lock"):
        if (out / "blocked.json").exists():
            return None
        claims = read(out / "claims.json", {})
        for job in read(out / "jobs.json"):
            if (out / job["key"] / "result.json").exists():
                continue
            prior = claims.get(job["key"])
            if prior and alive(prior["identity"]):
                continue
            # A stale lease alone is not permission to discard an unfinished run.
            attempt_state(out / job["key"])
            claims[job["key"]] = {"identity": me, "gpu": gpu, "state": "claimed", "time": time.time(),
                                  "prior_claim": prior}
            write(out / "claims.json", claims)
            return job
    return None


def load_engine(source, core):
    sys.path.insert(0, str(Path(source).resolve()))
    spec = importlib.util.spec_from_file_location("_capacity_trial_engine", Path(source) / "run.py")
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    if engine.CORE.resolve() != Path(core).resolve():
        raise RuntimeError("engine_core_path_mismatch")
    import model_provider
    if model_provider.CALL_LIMIT != CALL_LIMIT or model_provider.MODEL != "gpt-5.6-luna":
        raise RuntimeError("source_model_or_call_budget_changed")
    if Path(sys.modules["twenty_agent"].__file__).resolve().parent != Path(core).resolve():
        raise RuntimeError("wrong_agent_import")
    return engine


def verify_runtime(out, source, core):
    m = read(Path(out) / "manifest.json")
    if (str(Path(source).resolve()) != m["source"] or str(Path(core).resolve()) != m["core"] or
            source_identity(source, core) != m["source_identity"] or
            file_sha(__file__) != m["wrapper_sha256"] or
            digest(read(Path(out) / "frozen-policy.json")) != m["policy_sha256"]):
        raise RuntimeError("frozen_runtime_changed")
    return m


def run_worker(a):
    out = Path(a.output)
    manifest = verify_runtime(out, a.source, a.core)
    if parse_deadline(a.start_before) != manifest["start_before_epoch"]:
        raise RuntimeError("start_deadline_differs_from_manifest")
    engine = load_engine(a.source, a.core)
    original_physical = engine.Physical
    class AuditedPhysical(original_physical):
        def __init__(self, platform, gpu, output):
            self.host_gpu = gpu
            super().__init__(platform, gpu, output)
        def ready(self):
            result = super().ready()
            write(self.out / "gpu-mapping.json", gpu_observation(self.process.pid, self.host_gpu))
            return result
    engine.Physical = AuditedPhysical
    import setproctitle
    setproctitle.setproctitle("robot")
    me = identity()
    worker_path = out / f"worker-gpu{a.gpu}.json"
    policy = read(out / "frozen-policy.json")
    with locked(out / f"worker-gpu{a.gpu}.lock", nonblocking=True):
        while not engine.STOP.is_set():
            if time.time() >= manifest["start_before_epoch"]:
                write(worker_path, {"identity": me, "gpu": a.gpu, "phase": "start_deadline_reached", "time": time.time()})
                return
            job = claim_job(out, me, a.gpu)
            if job is None:
                blocked = read(out / "blocked.json")
                write(worker_path, {"identity": me, "gpu": a.gpu,
                    "phase": "blocked_by_queue_audit" if blocked else "no_unclaimed_work",
                    "queue_block": blocked, "time": time.time()})
                return
            case = out / job["key"]
            saved, next_attempt = attempt_state(case)
            while next_attempt is not None:
                if engine.STOP.is_set():
                    return
                if time.time() >= manifest["start_before_epoch"]:
                    write(worker_path, {"identity": me, "gpu": a.gpu, "phase": "start_deadline_reached", "time": time.time(), "case": job["key"]})
                    return
                verify_runtime(out, a.source, a.core)
                status = lambda phase: write(worker_path, {"identity": me, "gpu": a.gpu,
                    "phase": phase, "case": job["key"], "attempt": next_attempt, "time": time.time()})
                engine.gateway_contract(engine.STOP, lambda: status("waiting_gateway"))
                status("waiting_gpu")
                used = lambda: int(subprocess.check_output(["nvidia-smi", "-i", str(a.gpu),
                    "--query-gpu=memory.used", "--format=csv,noheader,nounits"], text=True).strip())
                with engine.acquire(engine.LEASES / engine.lock_name(a.gpu), True, used):
                    if engine.STOP.is_set():
                        return
                    if time.time() >= manifest["start_before_epoch"]:
                        write(worker_path, {"identity": me, "gpu": a.gpu,
                            "phase": "start_deadline_reached", "time": time.time(), "case": job["key"]})
                        return
                    status("trial")
                    directory = case / f"attempt-{next_attempt:02d}"
                    with trial_setting(engine, job["setting"]):
                        row = asyncio.run(engine.trial(job["plan"], job["arm"],
                            policy if job["arm"] == "memrsi" else None, a.gpu, directory))
                    # Resource configuration is an execution invariant, not just a manifest label.
                    recorded = read(directory / "agent" / "resource-budget.json")
                    if recorded is not None and any(recorded.get(k) != v for k, v in budget_for(job["setting"]).items()):
                        raise RuntimeError("applied_capacity_mismatch")
                saved, next_attempt = attempt_state(case)
                with locked(out / "dispatch.lock"):
                    update_summary(out)
            if not saved:
                raise RuntimeError("no_terminal_attempt")
            row = saved[-1]["row"]
            final = dict(row, setting=job["setting"], kind=job["plan"]["kind"],
                condition=job["plan"]["condition"], repeat=job["plan"]["repeat"],
                paired_history_id=job["plan"]["paired_history_id"], gpu=a.gpu,
                public_plan_sha256=digest(job["plan"]),
                source_runtime_identity=manifest["source_identity"]["sha256"],
                policy_sha256=manifest["policy_sha256"] if job["arm"] == "memrsi" else None,
                attempts=[{"path": x["path"], "status": x["row"]["status"],
                           "error_code": x["row"].get("error_code"),
                           "logical_calls": x["row"].get("logical_calls"),
                           "technical_retry_eligible": technical_retry_allowed(x["row"])} for x in saved])
            with locked(out / "dispatch.lock"):
                if (case / "result.json").exists():
                    raise RuntimeError("final_result_already_exists")
                write(case / "result.json", final)
                claims = read(out / "claims.json")
                claims[job["key"]].update(state="finished", time=time.time())
                write(out / "claims.json", claims)
                update_summary(out)
            write(worker_path, {"identity": me, "gpu": a.gpu, "phase": "case_finished",
                               "case": job["key"], "status": row["status"], "time": time.time()})


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("prepare", "run-worker", "status"):
        q = sub.add_parser(name)
        q.add_argument("--output", required=True)
        if name != "status":
            q.add_argument("--source", default=DEFAULT_SOURCE)
            q.add_argument("--core", default=DEFAULT_CORE)
            q.add_argument("--start-before", default=DEFAULT_START_BEFORE)
        if name == "prepare":
            q.add_argument("--policy", required=True)
            q.add_argument("--baseline")
            q.add_argument("--baseline-proof")
        elif name == "run-worker":
            q.add_argument("--gpu", type=int, choices=range(8), required=True)
    return p


def main():
    a = parser().parse_args()
    try:
        if a.command == "prepare":
            print(json.dumps(prepare(a), ensure_ascii=False))
        elif a.command == "status":
            with locked(Path(a.output) / "dispatch.lock"):
                print(json.dumps(update_summary(Path(a.output)), ensure_ascii=False))
        else:
            run_worker(a)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, RuntimeError) and re.fullmatch(r"[a-z_]{1,90}", str(exc)) else "supplement_scheduler_exception"
        if a.command == "run-worker":
            write(Path(a.output) / "blocked.json", {"time": time.time(), "gpu": a.gpu,
                  "reason": reason, "error_type": type(exc).__name__, "identity": identity(),
                  "existing_attempts_preserved": True, "automatic_restart": False})
        print(json.dumps({"status": "blocked", "reason": reason, "error_type": type(exc).__name__}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
