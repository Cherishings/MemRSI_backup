"""New text conditioning without erasing the controller's executed history."""
import hashlib,json
import numpy as np

class BoundaryError(ValueError):pass
class InstructionError(ValueError):pass

HISTORY_FIELDS=('last_observation','last_action','seq_history','action_calls','first_obs','start_pos')

def history_signature(model):
    def sig(x):
        if isinstance(x,dict):return {k:sig(v) for k,v in sorted(x.items())}
        if isinstance(x,(list,tuple)):return [sig(v) for v in x]
        if hasattr(x,'shape') and hasattr(x,'data_ptr'):
            try:version=x._version
            except RuntimeError:version='inference_tensor'
            return dict(object=id(x),data_ptr=x.data_ptr(),shape=list(x.shape),version=version)
        if isinstance(x,np.ndarray):return dict(object=id(x),shape=list(x.shape),sha=hashlib.sha256(x.tobytes()).hexdigest())
        return x
    return {k:sig(getattr(model,k,None)) for k in HISTORY_FIELDS}

def history_digest(model):
    """Stronger audit for tests only; tensor contents never enter actor inputs."""
    h=hashlib.sha256()
    def add(x):
        if isinstance(x,dict):
            for k,v in sorted(x.items()):h.update(k.encode());add(v)
        elif isinstance(x,(list,tuple)):
            for v in x:add(v)
        elif hasattr(x,'detach'):
            h.update(str(x.dtype).encode());a=x.detach().float().cpu().contiguous().numpy();h.update(str(a.shape).encode());h.update(a.tobytes())
        else:h.update(repr(x).encode())
    for key in HISTORY_FIELDS:h.update(key.encode());add(getattr(model,key,None))
    return h.hexdigest()

def replace_conditioning(model,language_tensor):
    """Apply at the next full-compute boundary. No reset(), prompt(), or replay."""
    if model.action_calls % model.downsample_obs:
        raise BoundaryError('instruction_change_requires_full_compute_boundary')
    if model.start_pos!=0:raise BoundaryError('unsupported_nonzero_transformer_start')
    before=history_signature(model)
    dropped_outer=len(model.action_queue)
    dropped_decoder=model.prism_action_decoder.action_queue.qsize()
    # Both queues contain predicted, not yet executed actions, not history.
    model.action_queue.clear()
    model.prism_action_decoder.reset()
    model.language_embedding=language_tensor
    after=history_signature(model)
    if before!=after:raise RuntimeError('executed_history_mutated_during_conditioning')
    return dict(history_preserved=True,history_fields=list(HISTORY_FIELDS),dropped_unexecuted_outer=dropped_outer,dropped_unexecuted_decoder=dropped_decoder,action_calls=model.action_calls)

class HistoryController:
    def __init__(self,asset_dir,clip_dir):
        from live_policy import PRISMExecutor
        from text_conditioning import AuthorCLIPTextEncoder
        self.executor=PRISMExecutor(asset_dir)
        self.encoder=AuthorCLIPTextEncoder(clip_dir)
        self.text=None;self.embedding_cache={};self.recondition_count=0

    def _encode(self,text):
        if not isinstance(text,str) or not text.strip():raise InstructionError('nonempty_instruction_required')
        tokens=self.encoder.tokenizer(text,add_special_tokens=True,truncation=False)['input_ids']
        if len(tokens)>77:raise InstructionError('instruction_exceeds_77_clip_tokens')
        if text not in self.embedding_cache:self.embedding_cache[text]=self.encoder.encode(text)
        emb=self.executor.torch.from_numpy(self.embedding_cache[text]).to(self.executor.model.device).reshape(1,1,512)
        return emb

    def instruct(self,text):
        if text==self.text:return dict(changed=False,history_preserved=True,action_calls=self.executor.model.model.action_calls)
        emb=self._encode(text);model=self.executor.model.model
        if self.text is None:
            # The constructor starts a fresh controller. Do not reset it again.
            if model.action_calls!=0 or model.last_observation is not None:raise RuntimeError('first_instruction_requires_fresh_controller')
            self.executor.model.prompt(task_emb=emb,language_str=text)
            receipt=dict(changed=True,initial=True,history_preserved=True,action_calls=0)
        else:
            receipt=dict(changed=True,initial=False,**replace_conditioning(model,emb));self.recondition_count+=1
        self.executor.instruction=text;self.text=text
        return receipt

    def act(self,obs):return self.executor.act(obs)
