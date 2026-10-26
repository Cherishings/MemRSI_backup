"""One audited fourth transport attempt for exactly five quota-failed requests."""
import sys,json,hashlib,asyncio,runpy
from pathlib import Path

def eligible(path,entry,signature):
    path=Path(path)
    if entry['sha256']!=signature or json.loads((path/'request-identity.json').read_text())['sha256']!=signature:
        raise RuntimeError('optimizer_request_changed')
    for n in range(1,4):
        d=path/f'attempt-{n:02d}'
        if (d/'value.json').exists() or (d/'model-trace.jsonl').exists():raise RuntimeError('cannot_retry_answered_request')
        rows=[json.loads(x) for x in (d/'model-errors.jsonl').read_text().splitlines()]
        if not rows or any(r.get('http_status')!=429 or r.get('output_started') is not False or r.get('generated_chars') not in (None,0) or r.get('partial_items') or r.get('code')!='subscription_sharing_usage_limit_exceeded' for r in rows):
            raise RuntimeError('not_audited_quota_only_failure')

def main():
    auth=Path(sys.argv.pop(1));code=Path(sys.argv.pop(1));allowed=json.loads(auth.read_text())['requests']
    sys.path.insert(0,str(code));sys.path.insert(0,str(code/'frozen_runtime'))
    import targeted_requests as tr
    original=tr.cached_structured
    async def resume(path,system,data,schema,wait_gateway):
        path=Path(path);key=str(path.resolve())
        if key not in allowed:return await original(path,system,data,schema,wait_gateway)
        signature=hashlib.sha256(json.dumps([system,data,schema],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        eligible(path,allowed[key],signature)
        if (path/'value.json').exists():return tr.read(path/'value.json')
        dest=path/'attempt-04'
        if (dest/'value.json').exists():
            value=tr.read(dest/'value.json');tr.dump(path/'value.json',value);return value
        if dest.exists():raise RuntimeError('fourth_attempt_already_used_requires_audit')
        await asyncio.to_thread(wait_gateway)
        try:
            value=await tr.structured(dest,system,data,schema)
        except Exception:
            tr.dump(path/'fourth-attempt-failed.json',{'attempt':4,'automatic_retry':False,'authorization':str(auth)})
            raise
        tr.dump(path/'value.json',value);tr.dump(path/'completion.json',{'attempt':4,'all_prior_attempts_retained':True,'authorization':str(auth),'request_unchanged':True})
        return value
    tr.cached_structured=resume
    runpy.run_path(str(code/'run_learning.py'),run_name='__main__')
if __name__=='__main__':main()
