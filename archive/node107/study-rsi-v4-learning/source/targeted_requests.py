"""Three lifetime technical attempts per unchanged optimizer request; no best-of."""
import asyncio,hashlib,json
from pathlib import Path
from durable_queue import read
from replay import dump
from structured_feedback import structured

def errors(path):
    f=Path(path)/'model-errors.jsonl'
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

async def cached_structured(path,system,data,schema,wait_gateway):
    path=Path(path)
    signature=hashlib.sha256(json.dumps([system,data,schema],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    path.mkdir(parents=True,exist_ok=True)
    old=read(path/'request-identity.json')
    if old and old['sha256']!=signature:raise RuntimeError('optimizer_request_changed')
    if (path/'value.json').exists():return read(path/'value.json')
    if not old:dump(path/'request-identity.json',{'sha256':signature,'max_technical_attempts':3})
    # r1 stopped after a failed wire request before nested attempt journals existed.
    # Preserve that as attempt1; do not pretend it never consumed a request.
    if (path/'calls.json').exists():
        if not errors(path):raise RuntimeError('legacy_partial_optimizer_requires_audit')
        target=path/'attempt-01'
        if target.exists():raise RuntimeError('ambiguous_legacy_optimizer_attempt')
        target.mkdir()
        for f in list(path.iterdir()):
            if f.is_file() and f.name!='request-identity.json':f.rename(target/f.name)
        dump(target/'technical-failure.json',{'code':'provider_error','inherited_original_attempt':True})
    for n in range(1,4):
        dest=path/f'attempt-{n:02d}'
        if (dest/'value.json').exists():
            value=read(dest/'value.json');dump(path/'value.json',value);return value
        if dest.exists():
            if errors(dest) or read(dest/'technical-failure.json'):continue
            raise RuntimeError('partial_optimizer_requires_audit')
        await asyncio.to_thread(wait_gateway)
        try:
            value=await structured(dest,system,data,schema)
            dump(path/'value.json',value);dump(path/'completion.json',{'attempt':n,'all_prior_attempts_retained':True});return value
        except RuntimeError as ex:
            if str(ex)!='provider_error' or not errors(dest):raise
            dump(dest/'technical-failure.json',{'code':'provider_error','remaining':3-n})
            if n<3:await asyncio.sleep(10)
    raise RuntimeError('optimizer_technical_attempts_exhausted')
