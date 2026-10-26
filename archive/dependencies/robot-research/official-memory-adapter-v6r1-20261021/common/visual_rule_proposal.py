"""Prepare one generic G/U proposal from explicitly allowlisted development data.

This module performs no model call. The caller supplies the existing provider
and cumulative ledger. A syntactically valid proposal is only a candidate: it
still needs paired development evaluation and the one-shot reserved gate.
"""
import copy
import hashlib
import json
from pathlib import Path
import re

from adaptation_protocol import BENCHMARKS, SPLITS, VALID_STATUSES, ROW_FIELDS, paired_effect, complete_records
from observation_evidence import validate_observation


MODEL = "gpt-5.6-luna"
MANIFEST_SCHEMA = "visual_rsi_development_v1"
FEEDBACK_SCHEMA = "visual_rsi_previous_development_feedback_v1"
MAX_JSON_BYTES = 2_000_000
MAX_PUBLIC_RECEIPT_CHARS = 512
MAX_PUBLIC_REQUEST_CHARS = 1024
MAX_PUBLIC_ACTION_CHARS = 512
MAX_MEMORY_TEXT_CHARS = 4096
MAX_MEMORY_SNAPSHOTS = 8
MEMORY_FIELDS = ("memory_before", "memory_after", "guidance_selected")
SNAPSHOT_SCOPE = "decision_boundary_not_archive_attribution"
INPUT_SNAPSHOT_SCOPE = "before_decision_not_archive_attribution"
MAX_EVENTS_PER_CASE = 2000
MAX_UNTOKENIZED_REQUEST_CHARS = 18000
KINDS = {"guidance": "procedure_guidance_v2", "update": "procedure_update_v2"}
PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "operator": {"type": "string", "enum": ["guidance", "update"]},
        "anchor": {"type": "string", "minLength": 1, "maxLength": 450},
        "replacement": {"type": "string", "maxLength": 1200},
        "rationale": {"type": "string", "minLength": 1, "maxLength": 1200},
        "evidence_case_ids": {"type": "array", "minItems": 1, "maxItems": 24,
                              "items": {"type": "string"}, "uniqueItems": True},
    },
    "required": ["operator", "anchor", "replacement", "rationale", "evidence_case_ids"],
    "additionalProperties": False,
}
SYSTEM = (
    "Propose ONE local edit to one existing memory operator, Guidance or Update. "
    "Guidance selects at most five existing evidence fragments; Update uses the native "
    "save_memory archive. The architecture, execution interface, budgets and actor are fixed. "
    "Use only the provided public DEVELOPMENT evidence and current frozen parent policy. "
    "Observation notes are unverified pre-action claims made by the actor, not objective truth. "
    "Public receipts describe execution; they do not establish unreported task success. "
    "An optional official full-trajectory success bit is developer feedback, never actor input. "
    "Official terminal status may describe a failure before any valid action. An empty event "
    "list means zero recorded valid actions, not an omitted successful trajectory. Public "
    "pre-decision inputs may be available even then; missing requests or memory are unknown. "
    "Only first/last public events may be shown; omitted middle history is unknown. "
    "Optional memory snapshots are taken at decision boundaries, not pure archive transitions; "
    "changes can include both archive updates and actor writes. A before/after difference alone "
    "does not identify Update as the cause. Selected guidance is the actual material supplied "
    "to the actor. Each snapshot text has a truncation flag; truncated or omitted content is "
    "unknown, not evidence of absence. Do not invent findings from missing text. "
    "Do not infer an archival loss or retrieval error from task failure alone. "
    "Preserve working rules and use successful controls as well as failures. "
    "For a second proposal, previous_development_feedback records the first edit and all "
    "twelve paired DEVELOPMENT outcomes, including regressions and whether it was accepted. "
    "Use that feedback to revise the next edit; do not blindly repeat a rejected edit. "
    "These outcomes do not identify the internal cause of failure or prove generalization. "
    "Return operator, one exact unique anchor copied from that operator's procedure, "
    "replacement, rationale, and supporting evidence_case_ids. "
    "Anchor must be at most 450 characters and 35 percent of the existing procedure; "
    "replacement and rationale at most1200 characters; final procedure at most1600. "
    "Make a generic memory-management edit, not a task plan or action sequence. "
    "No benchmark names, concrete targets, seed identities, evaluator answers, paths, "
    "new tools, executable code, or compulsory finish/continue rules in the procedure. "
    "Do not claim a diagnosis is proven. The candidate will be tested independently; "
    "a heuristic screen does not establish that it is safe, correct, or an improvement."
)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _json(text):
    def reject_constant(_):
        raise ValueError("nonfinite_json")
    try:
        return json.loads(text, object_pairs_hook=_unique_object, parse_constant=reject_constant)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("invalid_json") from error


def _read_json(path):
    path = Path(path)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("evidence_json_too_large")
    return _json(path.read_text())


def policy_sha256(policy):
    validate_parent_policy(policy)
    # Matches memory_policy.digest in the existing frozen core.
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()


def validate_parent_policy(policy):
    if (not isinstance(policy, dict) or set(policy) != {"schema", "guidance", "update"}
            or type(policy["schema"]) is not int or policy["schema"] != 1):
        raise ValueError("parent_policy_schema")
    for operator, kind in KINDS.items():
        if not isinstance(policy[operator], str) or len(policy[operator]) > 1800:
            raise ValueError("parent_policy_wrapper_length")
        spec = _json(policy[operator])
        if (not isinstance(spec, dict) or set(spec) != {"kind", "procedure"}
                or spec["kind"] != kind):
            raise ValueError("unsupported_parent_operator_kind")
        if not isinstance(spec["procedure"], str) or not spec["procedure"].strip() or len(spec["procedure"]) > 1600:
            raise ValueError("parent_procedure_length")
    return copy.deepcopy(policy)


def _check_parent(policy, expected_parent_hash):
    if (not isinstance(expected_parent_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_parent_hash)
            or policy_sha256(policy) != expected_parent_hash):
        raise ValueError("parent_policy_hash_mismatch")


def _manifest_entries(manifest, root, expected_parent_hash):
    if (not isinstance(manifest, dict)
            or set(manifest) != {"schema", "split", "parent_policy_sha256", "cases"}
            or manifest["schema"] != MANIFEST_SCHEMA):
        raise ValueError("development_manifest_schema")
    if manifest["split"] != "development":
        raise ValueError("optimizer_split_contamination")
    if manifest["parent_policy_sha256"] != expected_parent_hash:
        raise ValueError("manifest_parent_policy_hash_mismatch")
    if not isinstance(manifest["cases"], list) or not manifest["cases"]:
        raise ValueError("development_cases_required")
    entries, ids, pairs = [], set(), set()
    for case in manifest["cases"]:
        if not isinstance(case, dict) or set(case) != {"case_id", "benchmark", "seed", "role", "evidence_file"}:
            raise ValueError("development_manifest_case_fields")
        # All metadata is checked in a first pass, before opening ANY evidence.
        if case["role"] != "development":
            raise ValueError("optimizer_split_contamination")
        if (case["benchmark"] not in BENCHMARKS or type(case["seed"]) is not int
                or case["seed"] not in SPLITS["development"]):
            raise ValueError("optimizer_non_development_seed")
        if not isinstance(case["case_id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", case["case_id"]):
            raise ValueError("development_case_id")
        key = case["benchmark"], case["seed"]
        if case["case_id"] in ids or key in pairs:
            raise ValueError("duplicate_development_case")
        ids.add(case["case_id"]); pairs.add(key)
        value = case["evidence_file"]
        if not isinstance(value, str) or "://" in value:
            raise ValueError("development_evidence_path")
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts or relative.name != "evidence.json":
            raise ValueError("development_evidence_path")
        resolved = (root / relative).resolve()
        if not resolved.is_relative_to(root) or resolved.name != "evidence.json":
            raise ValueError("development_evidence_path_escape")
        entries.append((case, resolved))
    expected = {(b, s) for b in {b for b, _ in pairs} for s in SPLITS["development"]}
    if pairs != expected:
        raise ValueError("incomplete_development_manifest")
    return sorted(entries, key=lambda item: (item[0]["benchmark"], item[0]["seed"]))


def _checked_evidence(value, entry, expected_parent_hash):
    required = {"case_id", "benchmark", "seed", "split", "parent_policy_sha256", "events"}
    if (not isinstance(value, dict) or not required <= set(value)
            or set(value) - required - {"official_success", "public_initial_request", "memory_evidence",
                                        "terminal_status", "public_decision_inputs"}):
        raise ValueError("development_evidence_fields")
    if value["split"] != "development":
        raise ValueError("optimizer_split_contamination")
    if any(value[k] != entry[k] for k in ("case_id", "benchmark", "seed")):
        raise ValueError("development_evidence_identity")
    if type(value["seed"]) is not int or value["parent_policy_sha256"] != expected_parent_hash:
        raise ValueError("evidence_parent_policy_hash_mismatch")
    if "official_success" in value and type(value["official_success"]) is not bool:
        raise ValueError("official_success_must_be_bool")
    if "terminal_status" in value:
        if (not isinstance(value['terminal_status'],str) or value['terminal_status'] not in VALID_STATUSES or type(value.get('official_success')) is not bool
                or value['official_success'] != (value['terminal_status']=='success')):
            raise ValueError('official_terminal_status_inconsistent')
    if "public_initial_request" in value:
        request = value["public_initial_request"]
        if not isinstance(request, str) or len(request) > MAX_PUBLIC_REQUEST_CHARS:
            raise ValueError("public_initial_request_length")
    events = value["events"]
    if not isinstance(events, list) or not 0 <= len(events) <= MAX_EVENTS_PER_CASE:
        raise ValueError("development_public_events")
    if not events and 'terminal_status' not in value:
        raise ValueError('empty_events_require_official_terminal_status')
    checked, previous = [], 0
    for event in events:
        required_event = {"event_id", "observation", "public_receipt"}
        if (not isinstance(event, dict) or not required_event <= set(event)
                or set(event) - required_event - {"public_action"}):
            raise ValueError("non_public_event_fields")
        eid = event["event_id"]
        if type(eid) is not int or eid <= previous:
            raise ValueError("public_event_order")
        previous = eid
        receipt = event["public_receipt"]
        if not isinstance(receipt, str) or len(receipt) > MAX_PUBLIC_RECEIPT_CHARS:
            raise ValueError("public_receipt_length")
        # No raw trace, image bytes, environment state or evaluator answer fields
        # are accepted. Text provenance still depends on the public collector.
        item = {"event_id": eid, "observation": validate_observation(event["observation"]),
                "public_receipt": receipt}
        if "public_action" in event:
            action = event["public_action"]
            if not isinstance(action, dict) or set(action) != {"skill", "instruction", "reason"}:
                raise ValueError("non_public_action_fields")
            if any(not isinstance(action[k], str) or len(action[k]) > MAX_PUBLIC_ACTION_CHARS
                   for k in action):
                raise ValueError("public_action_text_length")
            if action["skill"] not in ("execute", "finish"):
                raise ValueError("public_action_skill")
            if ((action["skill"] == "execute" and not action["instruction"].strip())
                    or (action["skill"] == "finish" and action["instruction"] != "")):
                raise ValueError("public_action_instruction")
            item["public_action"] = copy.deepcopy(action)
        checked.append(item)
    result = {k: value[k] for k in ("case_id", "benchmark", "seed", "split", "parent_policy_sha256")}
    result["public_event_count"] = len(checked)
    result["events"] = checked if len(checked) <= 1 else [checked[0], checked[-1]]
    result["zero_recorded_valid_actions"] = len(checked)==0
    result["omitted_middle_history_is_unknown"] = len(checked) > 2
    result["observation_claims_are_unverified"] = True
    if "official_success" in value:
        result["official_success"] = value["official_success"]
    if 'terminal_status' in value:result['terminal_status']=value['terminal_status']
    if "public_initial_request" in value:
        result["public_initial_request"] = value["public_initial_request"]
    result['public_initial_request_availability']='observed' if 'public_initial_request' in value else 'unknown'
    if 'public_decision_inputs' in value:
        inputs=value['public_decision_inputs']
        if not isinstance(inputs,list) or len(inputs)>MAX_MEMORY_SNAPSHOTS:
            raise ValueError('public_decision_inputs_capacity')
        last=0
        for item in inputs:
            if (not isinstance(item,dict) or set(item)!={'event_id','public_request','memory_before','snapshot_scope'}
                    or item['snapshot_scope']!=INPUT_SNAPSHOT_SCOPE):
                raise ValueError('public_decision_input_fields')
            if type(item['event_id']) is not int or item['event_id']<=last:
                raise ValueError('public_decision_input_event')
            last=item['event_id']
            if not isinstance(item['public_request'],str) or len(item['public_request'])>MAX_PUBLIC_REQUEST_CHARS:
                raise ValueError('public_initial_request_length')
            fragment=item['memory_before']
            if (not isinstance(fragment,dict) or set(fragment)!={'text','truncated'}
                    or not isinstance(fragment['text'],str) or len(fragment['text'])>MAX_MEMORY_TEXT_CHARS
                    or type(fragment['truncated']) is not bool):
                raise ValueError('memory_fragment_schema')
        result['public_decision_inputs']=copy.deepcopy(inputs if len(inputs)<=1 else [inputs[0],inputs[-1]])
        result['omitted_public_inputs_are_unknown']=len(inputs)>2
    result['pre_decision_memory_availability']='observed' if value.get('public_decision_inputs') else 'unknown'
    if "memory_evidence" in value:
        snapshots = value["memory_evidence"]
        if not isinstance(snapshots, list) or len(snapshots) > MAX_MEMORY_SNAPSHOTS:
            raise ValueError("memory_evidence_capacity")
        validated, last = [], 0
        event_ids = {e["event_id"] for e in checked}
        for snapshot in snapshots:
            if (not isinstance(snapshot, dict)
                    or set(snapshot) != {"event_id", "snapshot_scope", *MEMORY_FIELDS}):
                raise ValueError("memory_evidence_fields")
            eid = snapshot["event_id"]
            if type(eid) is not int or eid <= last or eid not in event_ids:
                raise ValueError("memory_evidence_event")
            last = eid
            if snapshot["snapshot_scope"] != SNAPSHOT_SCOPE:
                raise ValueError("memory_snapshot_scope")
            for key in MEMORY_FIELDS:
                fragment = snapshot[key]
                if (not isinstance(fragment, dict) or set(fragment) != {"text", "truncated"}
                        or not isinstance(fragment["text"], str)
                        or len(fragment["text"]) > MAX_MEMORY_TEXT_CHARS
                        or type(fragment["truncated"]) is not bool):
                    raise ValueError("memory_fragment_schema")
            validated.append(copy.deepcopy(snapshot))
        result["memory_snapshot_count"] = len(validated)
        result["memory_evidence"] = validated if len(validated) <= 1 else [validated[0], validated[-1]]
        result["omitted_memory_events_are_unknown"] = len(validated) > 2
    return result


def load_development_evidence(manifest_path, expected_parent_hash):
    path = Path(manifest_path).resolve()
    manifest = _read_json(path)
    entries = _manifest_entries(manifest, path.parent, expected_parent_hash)
    # Two passes are deliberate: a late heldout entry cannot cause earlier
    # evidence reads before the manifest contamination is noticed.
    return [_checked_evidence(_read_json(p), e, expected_parent_hash) for e, p in entries]


def checked_previous_development_feedback(value, current_parent_hash, cases,
                                          expected_source_hashes, proposal_round):
    """Validate a complete previous development round, then expose a bounded view.

    Provenance is checked by the collector against started/scored files. Here we
    independently check the whole schema, edit, every paired row and selection.
    The source map itself and old full policy stay in the immutable audit file;
    neither arbitrary metadata nor private evaluator fields reach the model.
    """
    if type(proposal_round) is not int or proposal_round not in (1, 2):
        raise ValueError('proposal_round')
    if value is None:
        if proposal_round != 1:raise ValueError('previous_development_feedback_required')
        return None
    if proposal_round != 2:raise ValueError('previous_feedback_round_mismatch')
    fields = {'schema', 'split', 'benchmark', 'round', 'source_hashes', 'parent_policy',
              'parent_policy_sha256', 'candidate_policy_sha256', 'proposal', 'rows', 'selection'}
    if not isinstance(value, dict) or set(value) != fields or value['schema'] != FEEDBACK_SCHEMA:
        raise ValueError('previous_feedback_schema')
    if value['split'] != 'development':raise ValueError('previous_feedback_split_contamination')
    if type(value['round']) is not int or value['round'] != proposal_round - 1:
        raise ValueError('previous_feedback_round_mismatch')
    benchmarks = {c['benchmark'] for c in cases}
    if len(benchmarks) != 1 or value['benchmark'] not in benchmarks:
        raise ValueError('previous_feedback_benchmark_mismatch')
    if (not isinstance(expected_source_hashes, dict) or not expected_source_hashes
            or value['source_hashes'] != expected_source_hashes):
        raise ValueError('previous_feedback_source_changed')
    old_hash = value['parent_policy_sha256']
    checked = validate_and_apply_proposal(value['parent_policy'], value['proposal'],
                                         {c['case_id'] for c in cases}, old_hash)
    candidate_hash = checked['candidate_policy_sha256']
    if value['candidate_policy_sha256'] != candidate_hash:
        raise ValueError('previous_feedback_candidate_hash_mismatch')
    expected = {'pre': old_hash, 'post': candidate_hash}
    if (not isinstance(value['rows'],list) or len(value['rows']) != 2*len(SPLITS['development'])
            or any(not isinstance(r,dict) or set(r)!=ROW_FIELDS
                   or type(r['seed']) is not int or type(r['official_success']) is not bool
                   or any(not isinstance(r[k],str) for k in ROW_FIELDS-{'seed','official_success'})
                   for r in value['rows'])):
        raise ValueError('previous_feedback_record_schema')
    rows = complete_records(value['rows'], 'development', ('pre', 'post'),
                            (value['benchmark'],), expected)
    effect = paired_effect(rows, 'development', (value['benchmark'],), expected)
    accepted = effect['success_gain'] > 0 and not effect['new_protocol_or_capacity_failures']
    selection = dict(round=value['round'], parent_policy_sha256=old_hash,
                     candidate_policy_sha256=candidate_hash, accepted=accepted, effect=effect)
    if (not isinstance(value['selection'],dict) or value['selection'] != selection
            or type(value['selection'].get('accepted')) is not bool):
        raise ValueError('previous_feedback_selection_mismatch')
    if current_parent_hash != (candidate_hash if accepted else old_hash):
        raise ValueError('previous_feedback_current_parent_mismatch')
    by_seed = {}
    for row in rows:by_seed.setdefault(row['seed'], {})[row['method']] = row
    return dict(round=value['round'], split='development', benchmark=value['benchmark'],
        parent_policy_sha256=old_hash, candidate_policy_sha256=candidate_hash,
        source_manifest_sha256=hashlib.sha256(json.dumps(expected_source_hashes, sort_keys=True).encode()).hexdigest(),
        source_manifest_checked=True, local_edit={k:value['proposal'][k] for k in ('operator','anchor','replacement')},
        proposal_rationale={'text':value['proposal']['rationale'], 'truncated':False},
        accepted=accepted, paired_effect=effect,
        paired_outcomes=[dict(seed=seed,
            parent_status=pair['pre']['status'], candidate_status=pair['post']['status'],
            parent_official_success=pair['pre']['official_success'],
            candidate_official_success=pair['post']['official_success'],
            success_change=int(pair['post']['official_success'])-int(pair['pre']['official_success']))
            for seed,pair in sorted(by_seed.items())],
        all_development_pairs_retained=True, paired_outcomes_truncated=False,
        evidence_scope='development_feedback_not_causal_diagnosis_or_heldout_performance')


def build_proposal_request(parent_policy, manifest_path, expected_parent_hash,
                           token_counter=None, max_input_units=9000,
                           previous_development_feedback=None, expected_source_hashes=None,
                           proposal_round=1):
    """Return provider kwargs only; caller applies the cumulative learning ledger.

    ``token_counter(messages, tools)`` should be the existing protocol counter.
    Without it a conservative character cap rejects large packets, but does not
    claim to have checked the model's token budget. Source event strings are
    never silently truncated to make a request fit.
    """
    _check_parent(parent_policy, expected_parent_hash)
    cases = load_development_evidence(manifest_path, expected_parent_hash)
    feedback = checked_previous_development_feedback(previous_development_feedback,
        expected_parent_hash, cases, expected_source_hashes, proposal_round)
    schema = copy.deepcopy(PROPOSAL_SCHEMA)
    schema["properties"]["evidence_case_ids"]["items"]["enum"] = [c["case_id"] for c in cases]
    data = {"parent_policy_sha256": expected_parent_hash, "parent_policy": parent_policy,
            "development_cases": cases, "selection": "all_predeclared_development_cases_first_and_last_public_event",
            "reserved_validation_and_test_access": False,
            "observations_are_model_claims_not_oracle_facts": True}
    data['proposal_round'] = proposal_round
    data['previous_development_feedback'] = feedback
    if token_counter is not None and (type(max_input_units) is not int or max_input_units <= 0):
        raise ValueError("proposal_input_limit")
    # Only memory excerpts and the previous proposal's explanatory rationale may
    # be shortened, explicitly marked; source files remain unchanged. The exact
    # local edit and every paired outcome stay intact. Public notes/actions/
    # receipts are never rewritten, nor are cases selected by apparent outcome.
    for cap in (4096, 2048, 1024, 512, 256, 128):
        packed = copy.deepcopy(data)
        packed["memory_excerpt_character_cap"] = cap
        if packed['previous_development_feedback'] is not None:
            rationale = packed['previous_development_feedback']['proposal_rationale']
            if len(rationale['text']) > cap:
                rationale['text'] = rationale['text'][:cap]; rationale['truncated'] = True
        for case in packed["development_cases"]:
            for item in case.get('public_decision_inputs',[]):
                fragment=item['memory_before']
                if len(fragment['text'])>cap:
                    fragment['text']=fragment['text'][:cap];fragment['truncated']=True
            for snapshot in case.get("memory_evidence", []):
                for key in MEMORY_FIELDS:
                    fragment = snapshot[key]
                    if len(fragment["text"]) > cap:
                        fragment["text"] = fragment["text"][:cap]
                        fragment["truncated"] = True
        request = {"model": MODEL, "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(packed, ensure_ascii=False, sort_keys=True)},
        ], "tools": [{"type": "function", "function": {
            "name": "propose_memory_rule_edit", "description": "Propose one generic local G/U text edit.",
            "parameters": schema}}], "tool_choice": "required"}
        if token_counter is not None:
            measured = token_counter(request["messages"], request["tools"])
            if type(measured) is not int or measured < 0:
                raise ValueError("proposal_input_counter")
            if measured <= max_input_units:
                return request
        elif len(json.dumps(request, ensure_ascii=False)) <= MAX_UNTOKENIZED_REQUEST_CHARS:
            return request
    # v5r2: after the unchanged lossless/public-text path cannot fit, use
    # explicitly marked public excerpts. All cases/outcomes and source files
    # remain intact; excerpts never constitute a complete causal diagnosis.
    for public_cap in (256, 128, 64, 32):
        compact = copy.deepcopy(packed)
        compact['public_text_excerpt_character_cap'] = public_cap
        compact['public_excerpt_warning'] = ('Public text fields may be head/tail excerpts. '
            'Missing content is unknown, not absent. Do not treat excerpts as complete evidence.')
        def excerpt(value):
            if len(value) <= public_cap: return value
            half = public_cap // 2
            return {'excerpt': [value[:half], value[-half:]], 'original_chars': len(value)}
        compact['memory_excerpt_character_cap'] = min(cap, public_cap)
        for case in compact['development_cases']:
            fragments = [item['memory_before'] for item in case.get('public_decision_inputs', [])]
            fragments += [item[key] for item in case.get('memory_evidence', []) for key in MEMORY_FIELDS]
            for fragment in fragments:
                if len(fragment['text']) > compact['memory_excerpt_character_cap']:
                    fragment['text'] = fragment['text'][:compact['memory_excerpt_character_cap']]
                    fragment['truncated'] = True
            if 'public_initial_request' in case:
                case['public_initial_request'] = excerpt(case['public_initial_request'])
            for item in case.get('public_decision_inputs', []):
                item['public_request'] = excerpt(item['public_request'])
            for event in case['events']:
                event['public_receipt'] = excerpt(event['public_receipt'])
                event['observation'] = {key: excerpt(value) for key, value in event['observation'].items()}
                if 'public_action' in event:
                    for key in ('instruction', 'reason'):
                        event['public_action'][key] = excerpt(event['public_action'][key])
        compact['evidence_tables'] = {
            'event_columns': ['event_id', 'visible_facts', 'progress_uncertainty', 'reference_to_preserve', 'public_action', 'public_receipt'],
            'memory_columns': ['event_id', 'memory_before', 'memory_after', 'guidance_selected'],
            'input_columns': ['event_id', 'public_request', 'memory_before'],
            'memory_fragment_columns': ['text', 'truncated'],
            'public_excerpt_encoding': {'excerpt': '[first half, last half]; middle omitted, unknown', 'original_chars': 'full source length'},
            'source_manifest': str(Path(manifest_path).name),
            'memory_scope': SNAPSHOT_SCOPE,
            'input_scope': INPUT_SNAPSHOT_SCOPE,
            'all_cases_are_development': True,
            'all_cases_parent_policy_sha256': expected_parent_hash,
            'all_cases_benchmark': cases[0]['benchmark'],
            'first_last_sampling': 'Only first and last recorded events/snapshots/inputs are shown. Omitted history is unknown.'}
        for case in compact['development_cases']:
            case['events'] = [[e['event_id'], *[e['observation'][k] for k in ('visible_facts','progress_uncertainty','reference_to_preserve')], e.get('public_action'), e['public_receipt']] for e in case['events']]
            if 'memory_evidence' in case:
                case['memory_evidence'] = [[e['event_id'], *[[e[k]['text'],e[k]['truncated']] for k in MEMORY_FIELDS]] for e in case['memory_evidence']]
            if 'public_decision_inputs' in case:
                case['public_decision_inputs'] = [[e['event_id'],e['public_request'],[e['memory_before']['text'],e['memory_before']['truncated']]] for e in case['public_decision_inputs']]
            for key in ('split','parent_policy_sha256','benchmark','observation_claims_are_unverified','omitted_middle_history_is_unknown','omitted_public_inputs_are_unknown','omitted_memory_events_are_unknown'):
                case.pop(key,None)
        request['messages'][1]['content'] = json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        if token_counter is not None:
            measured = token_counter(request['messages'], request['tools'])
            if type(measured) is not int or measured < 0: raise ValueError('proposal_input_counter')
            if measured <= max_input_units: return request
        elif len(json.dumps(request, ensure_ascii=False)) <= MAX_UNTOKENIZED_REQUEST_CHARS:
            return request
    if token_counter is not None:
        raise ValueError("proposal_input_budget")
    raise ValueError("proposal_packet_needs_token_counter_or_smaller_explicit_benchmark_scope")


def heuristic_screen_procedure(text):
    """A deliberately limited text screen; it is not a semantic safety proof."""
    patterns = (
        r"```|<script\b|\bimport\s+\w+|\bfrom\s+[\w.]+\s+import\b|\b(?:def|class)\s+\w+",
        r"\b(?:exec|eval|compile|subprocess|os\.system)\s*\(",
        r"(?:/data/|/home/|/tmp/|https?://|file://)",
        r"\b(?:expected_private|expected_action|correct_checkpoint|ground_truth|evaluator_answer)\b",
        r"\b(?:rmbench|remembench|cover_blocks|samelocation|prism)\b",
        r"\b(?:always\s+(?:finish|continue)|never\s+finish|must\s+(?:finish|continue))\b",
    )
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
        raise ValueError("proposal_heuristic_screen")
    return {"passed": True, "semantic_guarantee": False,
            "requires_paired_development_and_reserved_validation": True}


def validate_and_apply_proposal(parent_policy, response, allowed_case_ids, expected_parent_hash):
    """Validate tool arguments and return one changed operator plus provenance."""
    _check_parent(parent_policy, expected_parent_hash)
    proposal = _json(response) if isinstance(response, str) else copy.deepcopy(response)
    if not isinstance(proposal, dict) or set(proposal) != set(PROPOSAL_SCHEMA["required"]):
        raise ValueError("proposal_fields")
    operator = proposal["operator"]
    if operator not in KINDS:
        raise ValueError("proposal_operator")
    for key, maximum in (("anchor", 450), ("replacement", 1200), ("rationale", 1200)):
        if not isinstance(proposal[key], str) or len(proposal[key]) > maximum:
            raise ValueError("proposal_text_length")
    if not proposal["anchor"].strip() or not proposal["rationale"].strip():
        raise ValueError("proposal_anchor_or_rationale_empty")
    ids = proposal["evidence_case_ids"]
    allowed = set(allowed_case_ids)
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 24
            or any(not isinstance(x, str) for x in ids)
            or len(ids) != len(set(ids)) or not set(ids) <= allowed):
        raise ValueError("proposal_evidence_ids")
    old_spec = _json(parent_policy[operator])
    old = old_spec["procedure"]
    anchor = proposal["anchor"]
    if len(anchor) > min(450, int(len(old) * .35)):
        raise ValueError("proposal_edit_not_local")
    if old.count(anchor) != 1:
        raise ValueError("proposal_anchor_not_unique")
    new = old.replace(anchor, proposal["replacement"], 1)
    if not new.strip() or len(new) > 1600:
        raise ValueError("candidate_procedure_length")
    if new == old:
        raise ValueError("unchanged_proposal")
    screen = heuristic_screen_procedure(new)
    candidate = copy.deepcopy(parent_policy)
    candidate[operator] = json.dumps(dict(old_spec, procedure=new), sort_keys=True, ensure_ascii=False)
    validate_parent_policy(candidate)
    untouched = "update" if operator == "guidance" else "guidance"
    if candidate[untouched] != parent_policy[untouched]:
        raise ValueError("more_than_one_operator_changed")
    return {"parent_policy_sha256": expected_parent_hash,
            "candidate_policy_sha256": policy_sha256(candidate),
            "candidate_policy": candidate, "proposal": proposal,
            "screen": screen, "adopted": False,
            "scope": "unvalidated_candidate_not_an_evolution_gain"}
