import importlib.util,types
from pathlib import Path
s=importlib.util.spec_from_file_location('mapping',Path(__file__).with_name('study-map.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
calls=[];f=types.SimpleNamespace(one=lambda *a:('original',None),policy_sha256=lambda p:p,read=lambda p:p,run_trial=types.SimpleNamespace(native_policy_hash=lambda:m.NATIVE),checked_cached_row=lambda *a:(calls.append(a) or {'status':'task_failure'}));m.install(f);a=types.SimpleNamespace(benchmark='rmbench',output=Path('/evidence'))
assert f.one(a,'test','native',m.INITIAL,4217)[1].name=='4217-attempt02';assert calls[-1][4]==4217
assert f.one(a,'development','pre',m.INITIAL,4000)[1].name=='4000-attempt02'
for phase,method,policy,seed in [('test','post',m.INITIAL,4217),('test','native',m.INITIAL,4216),('development','native',m.INITIAL,4217),('development','post','other',4000)]:assert f.one(a,phase,method,policy,seed)[0]=='original'
a.benchmark='remem';assert f.one(a,'test','native',m.INITIAL,4217)[0]=='original'
print('7 exact mapping checks passed; checked_cached_row retained')
