exec(open('/tmp/paos-comparability-audit.py').read().split('for key in sorted')[0])
import difflib
key=('hABDEC-v1-i0',0)
a=first[N[0],key]['request']['messages'];z=first[N[-1],key]['request']['messages']
print('messages',len(a),len(z))
for i,(x,y) in enumerate(zip(a,z)):
 if x!=y:
  print('index',i)
  print(''.join(difflib.unified_diff(json.dumps(x,ensure_ascii=False,indent=2).splitlines(True),json.dumps(y,ensure_ascii=False,indent=2).splitlines(True)))[:12000])
