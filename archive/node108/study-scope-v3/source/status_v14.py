"""Read-only, structured status. Never emit raw logs or credentials."""
import json
from pathlib import Path
from start_v14 import POINTER
from feedback_queue import summarize

def main():
    if not POINTER.exists():print('v1.4 尚未启动。');return
    record=json.loads(POINTER.read_text());root=Path(record['result'])
    out={'launch':record}
    for name in ('progress.json','report.json'):
        if (root/name).exists():out[name]=json.loads((root/name).read_text())
    phases=[]
    for path in sorted((root/'learning').glob('**/rows.json')):
        if path.parent.name not in ('full-parent','full-candidate'):continue
        rows=json.loads(path.read_text())
        from collections import Counter
        phases.append({'phase':str(path.parent.relative_to(root)), 'terminal':len(rows),
                       'status_counts':dict(Counter(r['status'] for r in rows))})
    out['development']=phases
    lr=root/'learning/report.json'
    if lr.exists():
        learning=json.loads(lr.read_text());out['learning']={k:learning.get(k) for k in ('status','promotions','reason')}
    path=root/'evaluation/rows.json'
    if path.exists():
        rows=json.loads(path.read_text());plan=json.loads((root/'evaluation/schedule.json').read_text())
        out['evaluation']={'planned':len(plan),'terminal':len(rows),'summary':summarize(rows,plan)}
    print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
