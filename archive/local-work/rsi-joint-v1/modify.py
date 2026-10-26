from pathlib import Path
p=Path(__file__).with_name('learn.py');s=p.read_text()
pos=s.index('\ndef read(')
addition='''
JOINT_SCHEMA = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
for _target in ("guidance", "update"):
    for _field in ("anchor", "replacement", "rationale"):
        _key = _target + "_" + _field
        JOINT_SCHEMA["properties"][_key] = {"type": "string", "maxLength": 450 if _field == "anchor" else 1200}
        if _field != "anchor": JOINT_SCHEMA["required"].append(_key)
JOINT_SYSTEM = PROPOSAL_SYSTEM.replace(
    "Improve the specified ONE memory operator", "Co-design BOTH memory operators"
).replace("Do not edit the other operator.", "Both local edits are required.").replace(
    "Return target, optional unique exact anchor, replacement and rationale.",
    "Return guidance_anchor (optional), guidance_replacement, guidance_rationale, "
    "update_anchor (optional), update_replacement, update_rationale."
) + (
    " Treat Update as a writer and Guidance as its reader: agree on how existing memory represents "
    "still-live authorization, completion receipts, cancellations, changed order and pending obligations. "
    "Ground changes in the training evidence, preserve native memory format and budget, and avoid "
    "duplicating instructions or requiring new tools/fields. Explain the interaction in the rationales. "
    "The frozen joint policy is the primary method. Single-edit arms remove exactly one of these "
    "same edits, rather than using independently optimized patches."
)

def joint_combinations(parent, response):
    validate_submission({"finish_reason": "tool_calls", "tool_calls": [
        {"name": "submit", "arguments": response}]}, JOINT_SCHEMA)
    edits = {}
    for target in ("guidance", "update"):
        patch = {"target": target, **{field: response[target + "_" + field]
                 for field in ("anchor", "replacement", "rationale") if target + "_" + field in response}}
        edits[target] = apply_edit(parent, patch, target)
    return make_combinations(parent, edits)

'''
s=s[:pos]+ '\n'+addition+s[pos:]
s=s.replace('advisor-rsi-two-proposals-compact-v2','advisor-rsi-joint-training-v1')
s=s.replace('"maximum_proposals": {"guidance": 1, "update": 1}', '"maximum_proposals": {"joint": 1}')
s=s.replace('"selection": "larger training checkpoint gain; fewer edited operators; fewer total train+validation calls; arm name"', '"selection": "training-only; joint is primary, single edits are ablations; no validation or test selection in this version"')
a=s.index('        validation, validation_audit = inspect_sources');b=s.index('        full_evidence =',a)
s=s[:a]+'''        freeze_json(out / "source-audit.json", {"training": train_audit, "validation": "not read"})
        if not training:
            raise ValueError("no_reconstructible_training_sources")
'''+s[b:]
a=s.index('        edits, decisions = {}, {}');b=s.index('        for arm, policy in combinations.items():',a)
s=s[:a]+'''        decisions = {}
        data = {"parent": parent_text, "actual_parent_evidence": full_evidence,
                "validation_feedback_provided": False, "test_feedback_provided": False}
        patch, rejection = await single_structured(out / "proposals" / "joint", JOINT_SYSTEM, data, JOINT_SCHEMA, module)
        combinations = {"parent": copy.deepcopy(parent)}
        critic = None
        if patch is not None:
            try:
                proposed = joint_combinations(parent, patch)
            except ValueError as error:
                rejection = {"code": str(error), "new_proposals_allowed": 0}
            else:
                critic, rejection = await single_structured(out / "critics" / "joint",
                    CRITIC_SYSTEM.replace("this one generic memory-rule edit", "these two coordinated generic memory-rule edits"),
                    {"parent": parent_text, "candidate": procedures(proposed["joint"]), "edit": patch}, CRITIC_SCHEMA, module)
                if critic and all(critic[k] for k in ("generic", "no_task_answers", "preserves_user_authority", "preserves_advisor_interface")):
                    combinations = proposed
                else:
                    rejection = rejection or {"code": "critic_rejected", "new_proposals_allowed": 0}
        decisions["joint"] = {"structurally_and_semantically_valid": "joint" in combinations,
                              "rejection": rejection, "critic": critic}
        write(out / "proposal-decisions.json", decisions)
'''+s[b:]
a=s.index('            # All structurally valid combinations');b=s.index('        write(out / "report.json", report)',a)
s=s[:a]+'''        # This development version must never re-use the exposed validation as unseen evidence.
        write(out / "selected-policy.json", parent)
        report = {"status": "training_complete_pending_independent_selection" if "joint" in combinations else "joint_proposal_rejected",
            "accepted": False, "selected_combination": "parent", "selected_sha256": digest(parent),
            "primary_candidate": "joint", "training": training_scores, "validation": {},
            "ledger": read(ledger), "proposal_decisions": decisions,
            "physical_evaluation_runs": 0, "test_feedback_used": False,
            "claim": "Joint candidate and exact component ablations evaluated on training only; no RSI success claimed."}
'''+s[b:]
p.write_text(s)
