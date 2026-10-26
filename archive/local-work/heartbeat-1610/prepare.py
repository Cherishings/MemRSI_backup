from pathlib import Path
p=Path('work/rsi-training-feedback-v2/feedback.py')
s=p.read_text().replace('summaries=[];traces=[]','summaries=[];traces=[];failures=[];seen=set()')
s=s.replace("assert (r['source_id'],r['arm'],r['repeat'],r['policy_sha256']) in allowed", "key=(r['source_id'],r['arm'],r['repeat'],r['policy_sha256'])\n        assert key in allowed and key not in seen,'Duplicate or unexpected training row'\n        seen.add(key)")
s=s.replace("if r['arm']!='joint':continue", """diagnostics=[]
        for name in ['guidance-advice-failures.jsonl','model-errors.jsonl']:
            f=p/name
            if f.exists():
                assert f.resolve().is_relative_to(folder/'replays'),'Nontraining diagnostic rejected'
                diagnostics.append({'path':str(f),'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),
                    'records':[json.loads(line) for line in f.read_text().splitlines() if line.strip()]})
        if diagnostics: failures.append({'source_id':r['source_id'],'arm':r['arm'],'repeat':r['repeat'],'diagnostics':diagnostics})
        if r['arm']!='joint':continue""")
s=s.replace("'summaries':summaries,'joint_contexts':traces", "'summaries':summaries,'joint_contexts':traces,'training_failure_diagnostics':failures")
p.write_text(s)
p=Path('work/rsi-training-feedback-v2/learn.py');s=p.read_text().replace('full_evidence.append({"candidate_training_feedback": feedback_data})','diagnostics = feedback_data.pop("training_failure_diagnostics")\n        full_evidence.append({"candidate_training_feedback": feedback_data})')
s=s.replace('data = {"parent": parent_text, "actual_parent_evidence": full_evidence,','data = {"parent": parent_text, "actual_parent_evidence": full_evidence,\n                "untruncated_training_failure_diagnostics": diagnostics,')
s=s.replace(' Candidate training feedback is supplied. Revise', ' Complete structured training failure diagnostics are supplied without field truncation. Use these observed protocol errors and successful controls to keep advice and memory concise and grounded; do not change the tool interface or suppress failure scoring. Candidate training feedback is supplied. Revise')
p.write_text(s)
p=Path('work/rsi-training-feedback-v2/launch.py');s=p.read_text()
s=s.replace("old=b/'study-rsi-joint-feedback-review-v2';training_root=b/'study-rsi-joint-v1';r=b/'study-rsi-contract-v1';incoming=b/'rsi-contract-v1-incoming'", "old=b/'study-rsi-contract-v1';training_root=old;r=b/'study-rsi-training-feedback-v2';incoming=b/'rsi-training-feedback-v2-incoming'")
s=s.replace("report['status']=='fixed_proposal_review_rejected'", "report['status']=='training_complete_pending_independent_selection'")
s=s.replace("old/'frozen-proposal.json'", "old/'learning/proposals/joint/value.json'")
s=s.replace("'joint-explicit-contract-training-v1'", "'joint-training-failure-feedback-v2'")
s=s.replace("'Explicit allowed procedural-edit scope; forbidden task answers/runtime changes require exact candidate quote; all pass needed'", "'Include all-arm structured training failure diagnostics without truncation, preserving the original critic unchanged'")
s=s.replace("'Previous critic rejected generic procedure changes under an unstated rule-preservation requirement; explicit contract removes that ambiguity, not a guarantee of candidate validity'", "'Static feedback builder omitted dedicated failure files and used older training; current training shows invalid citations and repetitive output-limit failures. Supplying these diagnostics may help, but efficacy is unproven'")
s=s.replace("'offline_tests_passed':27", "'offline_tests_passed':29")
s=s.replace("'joint_explicit_contract_training_only'", "'joint_training_failure_feedback_only'")
s=s.replace("'include_transitive_carried_costs':True", "'include_transitive_carried_costs':True,'additional_physical_cost_roots':[str(b/'study-contract-validation-v1'),str(b/'study-contract-feasible-pilot-v1')],'physical_costs_separate_from_learner_ledger':True")
p.write_text(s)
