"""Read-only, structured status. Never emit raw logs or credentials."""
import json
from pathlib import Path
from start_v13 import POINTER
from feedback_queue import summarize

def main():
    if not POINTER.exists():print('v1.3 尚未启动。');return
    record=json.loads(POINTER.read_text());root=Path(record['result'])
    out={'launch':record}
    for name in ('progress.json','report.json'):
        if (root/name).exists():out[name]=json.loads((root/name).read_text())
    path=root/'evaluation/rows.json'
    if path.exists():
        rows=json.loads(path.read_text());plan=json.loads((root/'evaluation/schedule.json').read_text())
        out['evaluation']={'planned':len(plan),'terminal':len(rows),'summary':summarize(rows,plan)}
    print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
