"""Two actual development windows; plumbing only, excluded from full episodes."""
import argparse,asyncio,json
from pathlib import Path
from learning_v14 import prepare
from feedback_learning import evaluate
from memory_policy import BASE
from replay import dump
async def main(output):
    p=Path(output);p.mkdir(parents=True,exist_ok=False)
    dev,_=prepare();rows=[]
    for f in dev[:2]:
        r=await evaluate(f,p/f['id'],BASE)
        rows.append({k:r.get(k) for k in ('fixture','mode','status','correct','error_code','calls')})
        dump(p/'result.json',{'scope':'development plumbing; not full workflow success or RSI gain','rows':rows})
        if r['status']!='answered':break
    print(json.dumps({'all_answered':len(rows)==2 and all(r['status']=='answered' for r in rows),'rows':rows}))
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);asyncio.run(main(ap.parse_args().output))
