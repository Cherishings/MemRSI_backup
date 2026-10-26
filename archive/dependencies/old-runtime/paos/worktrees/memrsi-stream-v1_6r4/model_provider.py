"""Shared frozen-model transport outside the pristine PAOS package.

Do not delegate chat() to CustomProvider: its upstream implementation does not
call the _complete hook added by older local experiments. The wire request here
matches upstream CustomProvider; only bounded transport handling and audit differ.
"""
import asyncio
import fcntl
import hashlib
import json
import os
import time
from contextvars import ContextVar
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from network_wait import WaitClock, transient, probe, BACKOFF
from PhyAgentOS.providers.base import LLMResponse
from PhyAgentOS.providers.custom_provider import CustomProvider

GATEWAY_URL = 'http://127.0.0.1:19099/v1'
MODEL = 'gpt-5.6-luna'
OUTPUT_CAP = 2048
MAX_REQUEST_ATTEMPTS = 5
MAX_TRANSPORT_RETRIES = 20
CALL_LIMIT = 480
RETRY_DELAYS = (5, 10, 20, 30)
MODEL_LOCK_PATH = Path('/data/stormlab/xi/paos/qwen-deploy/memrsi-model-request.lock')
MODEL_ADMISSION_TIMEOUT = 600.0
MODEL_ADMISSION_POLL = 0.025
MODEL_RELEASE_YIELD = 0.06
LEARNING_LEDGER = ContextVar('learning_call_ledger', default=None)

def reserve_learning_call():
    path = LEARNING_LEDGER.get()
    if path is None:
        return
    path = Path(path)
    with path.with_suffix('.lock').open('a') as lease:
        fcntl.flock(lease,fcntl.LOCK_EX)
        data=json.loads(path.read_text()) if path.exists() else {'calls':0,'limit':6000}
        if data['calls']>=data['limit']:raise RuntimeError('optimizer_call_budget')
        data['calls']+=1
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data));tmp.replace(path)



def read_api_key():
    """Read on the execution server only; never include this value in artifacts."""
    return Path('/data/stormlab/xi/paos/qwen-deploy/gpt-gateway-token').read_text().strip()


def retry_transport(error, attempt, total_retries):
    # chat.completions.create is nonstreaming to this actor. The gateway buffers
    # model output; on HTTP failure no function call/physical action is delivered.
    # A narrowly identified interrupted upstream stream can therefore be retried
    # with exactly the same request, even if upstream had generated partial text.
    buffered_disconnect = (error.get('http_status') == 502
        and error.get('stage') == 'stream'
        and error.get('upstream_http_status') == 200
        and error.get('upstream_error_type') in ('ConnectionError','ReadTimeout','ChunkedEncodingError')
        and error.get('output_started') is True and not error.get('code'))
    before_output = (error.get('retryable') is True and error.get('output_started') is False)
    return ((before_output or buffered_disconnect)
        and error.get('http_status') in (408,429,500,502,503,504)
        and error.get('code') != 'generation_output_limit'
        and attempt + 1 < MAX_REQUEST_ATTEMPTS and total_retries < MAX_TRANSPORT_RETRIES)


class Provider(CustomProvider):
    def __init__(self, output, *, api_key=None):
        key = read_api_key() if api_key is None else api_key
        super().__init__(api_key=key, api_base=GATEWAY_URL,
                         default_model=MODEL, timeout_s=270)
        self._client.max_retries = 0
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.calls = 0
        self.key = key
        self.transport_retries = 0
        self.format_repairs = 0
        self.last_transport_error = {}
        self.wait_clock = WaitClock(self.output)
        self.wire_attempts = 0

    def _append(self, name, record):
        text = json.dumps(record, ensure_ascii=False)
        if self.key:
            text = text.replace(self.key, '[REDACTED]')
        with (self.output / name).open('a') as stream:
            stream.write(text + '\n')

    async def _complete(self, request):
        try:
            return self._parse(await self._client.chat.completions.create(**request))
        except Exception as error:
            self.last_transport_error = {
                'exception_type': type(error).__name__,
                'http_status': getattr(error, 'status_code', None),
            }
            body = getattr(error, 'body', None)
            detail = body.get('error', body) if isinstance(body, dict) else None
            if isinstance(detail, dict):
                for field in ('code', 'stage', 'retryable', 'output_started',
                              'request_sha256', 'usage', 'output_limit',
                              'returned_output_limit', 'partial_items',
                              'generated_chars', 'upstream_http_status',
                              'upstream_error_type', 'generation_repetition_observed'):
                    if field in detail:
                        self.last_transport_error[field] = detail[field]
            # Never log exception strings, headers, auth, or client objects.
            self._append('failed-model-requests.jsonl', {'call': self.calls, 'request': request})
            return LLMResponse(content='Provider transport failure', finish_reason='error')

    async def chat_with_retry(self, **kwargs):
        return await self.chat(**kwargs)

    async def chat(self, **kwargs):
        return await self._chat_attempts(**kwargs)

    @asynccontextmanager
    async def _request_lease(self):
        """Two process-safe slots, matching the gateway's existing capacity.

        Request content, model, retry and per-episode budgets are unchanged.
        """
        started=time.monotonic();stream=None;slot=None
        paths=[Path(MODEL_LOCK_PATH),Path(str(MODEL_LOCK_PATH)+'.slot-1')]
        try:
            while stream is None:
                for i,path in enumerate(paths):
                    path.parent.mkdir(parents=True,exist_ok=True)
                    handle=path.open('a')
                    try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    except BlockingIOError:handle.close();continue
                    stream=handle;slot=i;break
                if stream is None:
                    remaining=MODEL_ADMISSION_TIMEOUT-(time.monotonic()-started)
                    if remaining<=0:
                        self._append('model-admission.jsonl',{'status':'wait_timeout','pid':os.getpid(),
                            'wait_seconds':time.monotonic()-started,'timeout_seconds':MODEL_ADMISSION_TIMEOUT,
                            'model_calls_before_admission':self.calls})
                        raise RuntimeError('model_admission_wait_timeout')
                    await asyncio.sleep(min(MODEL_ADMISSION_POLL,remaining))
            self._append('model-admission.jsonl',{'status':'acquired','pid':os.getpid(),'slot':slot,
                'wait_seconds':time.monotonic()-started,'model_calls_before_admission':self.calls})
            yield
        finally:
            if stream is not None:
                fcntl.flock(stream.fileno(),fcntl.LOCK_UN);stream.close()
                await asyncio.sleep(MODEL_RELEASE_YIELD)

    async def _chat_attempts(self, **kwargs):
        return await self._chat_attempts_locked(**kwargs)

    async def _chat_attempts_locked(self, *, messages, tools=None, model=None,
                                    max_tokens=OUTPUT_CAP, temperature=0.,
                                    reasoning_effort=None, tool_choice=None):
        # These are shared experiment model settings, not memory hints.
        request = {
            'model': model or self.default_model,
            'messages': self._sanitize_empty_content(messages),
            'max_tokens': OUTPUT_CAP,
            'temperature': 0.,
        }
        if reasoning_effort:
            request['reasoning_effort'] = reasoning_effort
        if tools:
            request.update(tools=tools, tool_choice=tool_choice or 'auto')
        request_hash = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        # One logical request, unchanged across transport retries. No tool is
        # delivered until a complete successful response exists.
        reserved = False
        outage_round = 0
        ordinary_attempt = 0
        try:
            while True:
                if not await asyncio.to_thread(probe):
                    self.wait_clock.begin('upstream_unreachable', request_hash)
                    await asyncio.sleep(BACKOFF[min(outage_round,len(BACKOFF)-1)])
                    outage_round += 1
                    continue
                self.wait_clock.end()
                async with self._request_lease():
                    if not reserved:
                        if self.calls >= CALL_LIMIT:raise RuntimeError('agent_call_budget_exhausted')
                        reserve_learning_call()
                        self.calls += 1
                        reserved = True
                    self.wire_attempts += 1
                    (self.output/'calls.json').write_text(json.dumps({
                        'calls':self.calls,'limit':CALL_LIMIT,'transport_retries':self.transport_retries,
                        'wire_attempts':self.wire_attempts,'format_repairs':self.format_repairs,
                        'budget_unit':'logical requests; all wire attempts and unknown costs retained'}))
                    begin=time.time();begin_mono=time.monotonic()
                    self.last_transport_error={}
                    response=await self._complete(request)
                if response.finish_reason != 'error':
                    self.wait_clock.end()
                    self._append('model-trace.jsonl',{
                        'call':self.calls,'wire_attempt':self.wire_attempts,'elapsed':time.time()-begin,
                        'request':request,'response':asdict(response)})
                    return response
                error=self.last_transport_error
                network=transient(error)
                retry=network or (retry_transport(error,ordinary_attempt,self.transport_retries)
                                   and ordinary_attempt+1 < MAX_REQUEST_ATTEMPTS)
                self._append('model-errors.jsonl',dict(error,call=self.calls,wire_attempt=self.wire_attempts,
                    elapsed=time.time()-begin,type='provider_error',request_sha256=request_hash,
                    retry_same_input=retry,network_wait=network))
                if error.get('code')=='generation_output_limit':raise RuntimeError('generation_output_limit')
                if not retry:raise RuntimeError('provider_error')
                self.transport_retries += 1
                if network:
                    # The failed call may have generated tokens, but no action
                    # was delivered. Keep unknown usage; never label it zero.
                    self.wait_clock.begin('interrupted_model_request',request_hash,since=begin_mono)
                    delay=BACKOFF[min(outage_round,len(BACKOFF)-1)];outage_round+=1
                else:
                    delay=RETRY_DELAYS[min(ordinary_attempt,len(RETRY_DELAYS)-1)]
                    ordinary_attempt+=1
                # Crucially this occurs OUTSIDE the shared model lease.
                await asyncio.sleep(delay)
        finally:
            self.wait_clock.end()
