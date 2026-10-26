#!/usr/bin/env python3
"""Read-only matched-pair audit for continuous mission v4 result directories."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def read(path):
    return json.loads(path.read_text())


def arm(root):
    root = Path(root)
    manifest, config = read(root / "manifest.json"), read(root / "launch.json")
    sources = read(root / "sources.json")
    episode = root / "episode"
    result_path = episode / "result.json"
    result = read(result_path) if result_path.exists() else read(episode / "progress.json")
    contract = result.get("contract") or {}
    checkpoints = contract.get("checkpoints") or {}
    return {
        "root": str(root),
        "stage": read(root / "launcher-status.json").get("stage"),
        "controller": config["controller"],
        "executor": config["executor"],
        "gpu": config["gpu"],
        "seed": config["seed"],
        "limits": {k: config[k] for k in ("max_steps", "max_actions", "max_calls",
                                           "action_steps", "wall_seconds")},
        "task_sha256": digest(root / "task.json"),
        "scene_sha256": digest(episode / "physics" / "scene.bddl"),
        "initial_physics_sha256": digest(episode / "physics" / "initial-state.npy"),
        "relevant_code_sha256": {k: v for k, v in sources.items()
            if k in ("scripts/mission_v4_contract.py", "scripts/mission_v4_worker.py",
                     "scripts/run_mission_v4.py", "PhyAgentOS/agent/task_memory.py",
                     "PhyAgentOS/agent/loop.py", "PhyAgentOS/agent/context.py")},
        "result": {k: result.get(k) for k in (
            "status", "evidence_kind", "mission_success", "long_horizon_success",
            "workflow_qualified", "horizon_qualified", "failure_domain", "reason",
            "actions", "successful_moves", "failed_moves", "archives", "model_calls",
            "simulation_seconds", "wall_seconds")},
        "checkpoint_planned": contract.get("checkpoint_planned"),
        "checkpoint_reached": contract.get("checkpoint_reached"),
        "checkpoint_correct": contract.get("checkpoint_correct"),
        "checkpoint_coverage": contract.get("checkpoint_coverage"),
        "checkpoint_accuracy_given_reached": contract.get("checkpoint_accuracy"),
        "checkpoint_detail": {k: {f: row.get(f) for f in (
            "boundary_reached", "decision_correct", "action_outcome_observed",
            "selected_action_physical_success", "correct_decision_and_physical_success")}
            for k, row in checkpoints.items()},
        "obsolete_mission_action_count": contract.get("obsolete_mission_action_count"),
        "invalid_mission_decision_count": contract.get("invalid_mission_decision_count"),
        "physical_mission_violation_count": contract.get("physical_mission_violation_count"),
        "manifest_protocol": manifest.get("protocol"),
    }


def compare(native, memory):
    n, m = arm(native), arm(memory)
    checks = {
        "correct_controllers": n["controller"] == "paos"
                               and m["controller"] == "paos_task_memory",
        "same_executor": n["executor"] == m["executor"],
        "same_seed": n["seed"] == m["seed"],
        "same_limits": n["limits"] == m["limits"],
        "same_task": n["task_sha256"] == m["task_sha256"] and n["task_sha256"] is not None,
        "same_scene": n["scene_sha256"] == m["scene_sha256"] and n["scene_sha256"] is not None,
        "same_initial_physics": (n["initial_physics_sha256"] == m["initial_physics_sha256"]
                                 and n["initial_physics_sha256"] is not None),
        "same_relevant_code": n["relevant_code_sha256"] == m["relevant_code_sha256"],
    }
    return {"comparability_checks": checks, "matched": all(checks.values()),
            "native": n, "task_memory": m,
            "interpretation_rule": "Report reach coverage with conditional accuracy; an unreached boundary is not a memory error. Separate physical execution and provider failures from mission decisions."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("native")
    parser.add_argument("task_memory")
    args = parser.parse_args()
    print(json.dumps(compare(args.native, args.task_memory), ensure_ascii=False, indent=2))
