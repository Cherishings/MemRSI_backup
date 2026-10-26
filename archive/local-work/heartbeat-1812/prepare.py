from pathlib import Path
s=Path('work/contract-validation/stage.py').read_text()
s=s.replace("old=b/'study-rsi-v4-sources';r=b/'study-contract-validation-v1';inc=b/'contract-validation-incoming'", "old=b/'study-contract-feasible-pilot-v1';r=b/'study-feedback-v2-physical-pilot';inc=b/'feedback-v2-pilot-incoming'")
s=s.replace("assert q['phase']=='development_complete'", "assert q['phase'] in ('development_complete','reuse_original_results_no_rerun')\nassert q['completed']==8")
s=s.replace("assert not pathlib.Path('/proc/'+str(q['pid'])).exists()", "assert not q.get('pid') or not pathlib.Path('/proc/'+str(q['pid'])).exists()")
s=s.replace("'init':idx+2", "'init':2").replace('i{idx+2}', 'i2')
s=s.replace("r.mkdir()", """report=read(inc/'report.json')
assert report['status']=='training_complete_pending_independent_selection' and report['training']['joint']['passed']
assert method_digest_expected=='a2e1bc92a3db7fccb65fbef7928f1ce7a6bca17f4dc78a565d2d47b5fa0e810f'
r.mkdir()
shutil.copy2(inc/'report.json',r/'training-report.json')
shutil.copy2(old/'physical-qualification.json',r/'physical-qualification.json')""")
s=s.replace("read=lambda p:", "method_digest_expected='a2e1bc92a3db7fccb65fbef7928f1ce7a6bca17f4dc78a565d2d47b5fa0e810f'\nread=lambda p:")
s=s.replace("assert parent!=learned", "assert parent!=learned\nassert method.digest(learned)==method_digest_expected")
s=s.replace("'contract-physical-selection-v1'", "'feedback-v2-physical-pilot-v1'")
s=s.replace("'selection_rule':'Complete all 16 episodes; require joint checkpoints and full-episode completions no worse than parent, plus training gate; report all six comparisons and extra-call control without claiming superiority from two conditions'", "'selection_rule':'Complete all 16 paired episodes. Expand only if verified joint full success count strictly exceeds every other arm. No checkpoint substitution, no early stopping, no repeat sampling. Small-sample lead is not statistical proof'")
s=s.replace("'physical_exposure_caveat':'New instruction permutations for this registered study, not a claim that LIBERO scenes or init indices are globally unseen'", "'physical_exposure_caveat':'Next two lexicographic unregistered instruction histories, init2 fixed by prior executor feasibility evidence. New comparison for candidate selection, not final test; scenes are previously exposed', 'training_report_sha256':sha(r/'training-report.json'), 'prior_results_retained_at':str(old), 'init_selection_basis':'Previously registered physical feasibility only, not method ranking'")
s=s.replace("names+=['orders.json'", "names+=['training-report.json','physical-qualification.json','orders.json'")
Path('work/heartbeat-1812/stage.py').write_text(s)
compile(s,'stage.py','exec')
assert "'init':2" in s and "strictly exceeds every other arm" in s
print('Syntax and configuration checks passed')
