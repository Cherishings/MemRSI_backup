import pathlib,subprocess,sys,json,time
b=pathlib.Path('/data/songziying/paos-libero-20261023');r=pathlib.Path(json.loads((b/'active-study.json').read_text())['root']);assert not (r/'policy-reconnect-launch.json').exists()
with (r/'policy-reconnect.log').open('x') as f:p=subprocess.Popen([sys.executable,str(b/'policy-reconnect-incoming/apply_after_case.py')],stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
(r/'policy-reconnect-launch.json').write_text(json.dumps({'pid':p.pid,'time':time.time()}));print(p.pid)
