"""MemRSI-only evidence-cited transactions; no task/order/finish semantics in code.
Requirements and progress are separate records. Models decide all semantic edits.
Native PAOS, task selection, physical execution, and scoring are untouched.
"""
import copy,json
from pathlib import Path
from memory_budget import BoundedStore,pair,write_pair
from token_accounting import memory_tokens

EMPTY={'requirements':{},'progress':{}}
RECORD={'type':'object','properties':{
 'section':{'type':'string','enum':['requirements','progress']},
 'id':{'type':'string','minLength':1,'maxLength':60},
 'op':{'type':'string','enum':['set','delete']},
 'expected_revision':{'type':'integer','minimum':0},
 'text':{'type':'string','maxLength':500},
 'status':{'type':'string','enum':['active','pending','partial','completed','cancelled','superseded','uncertain']},
 'links':{'type':'array','items':{'type':'string'},'maxItems':8},
 'evidence':{'type':'array','minItems':1,'maxItems':3,'items':{'type':'string'}}},
 'required':['section','id','op','expected_revision','text','status','links','evidence'],'additionalProperties':False}
SCHEMA={'type':'object','properties':{'edits':{'type':'array','maxItems':20,'items':RECORD}},'required':['edits'],'additionalProperties':False}
TOOL=[{'type':'function','function':{'name':'apply_memory_delta','description':'Submit evidence-cited local changes. Unmentioned records stay byte-equivalent.','parameters':SCHEMA}}]
BASE=('Maintain bounded long-term memory using apply_memory_delta. requirements stores user-authorized outcomes '
 'and constraints; progress stores observations, completed components and unfinished components, linked to requirements. '
 'These are records, not two independently invented plans. Propose only changed records; untouched records persist. '
 'Use expected_revision=0 for a new ID, otherwise the displayed revision. A set replaces ONE record, not the document. '
 'Every change selects evidence IDs from the supplied source catalog; do not copy or invent quotes. The program stores the selected exact text. Record citations confirm provenance, not truth. '
 'Use a user revision to change an authorized requirement; execution receipts update progress at their stated scope. '
 'When needed, compact or delete records using evidence; the model chooses what to retain, including cancelled history. '
 'Do not invent tasks from tool capabilities. Do not write a guessed next action or a second order into progress. '
 'Follow the learned policy below; output one tool call, no prose. Unchanged edits=[] is valid.')


def decode(text):
    d=json.loads(text) if text.strip() else copy.deepcopy(EMPTY)
    if not isinstance(d,dict) or set(d)!=set(EMPTY) or any(not isinstance(d[s],dict) for s in EMPTY):raise ValueError('delta_memory_schema')
    for section in d:
        for key,record in d[section].items():
            if not isinstance(key,str) or not isinstance(record,dict) or set(record)!={'revision','text','status','links','evidence'}:raise ValueError('delta_record_schema')
            if type(record['revision']) is not int or record['revision']<1:raise ValueError('delta_revision')
            if not isinstance(record['text'],str) or not isinstance(record['links'],list) or not isinstance(record['evidence'],list):raise ValueError('delta_record_schema')
    return d


def encode(d):
    # One record per line, reducing incidental mixing in the shared 480-char fragmenter.
    return '{'+',\n'.join(json.dumps(s)+':{'+',\n'.join(json.dumps(k)+':'+json.dumps(v,ensure_ascii=False,separators=(',',':')) for k,v in d[s].items())+'}' for s in EMPTY)+'}'


def sources_for(messages,state):
    raw={f'input:{i}':str(m.get('content','')) for i,m in enumerate(messages) if m.get('content')}
    raw.update({f'{s}:{k}':json.dumps(v,ensure_ascii=False) for s in EMPTY for k,v in state[s].items()})
    catalog={}
    for source,text in raw.items():
        for offset in range(0,len(text),180):
            catalog[f'e{len(catalog)}']={'source':source,'offset':offset,'quote':text[offset:offset+180]}
    return catalog



def apply(state,submission,sources):
    if not isinstance(submission,dict) or set(submission)!={'edits'} or not isinstance(submission['edits'],list) or len(submission['edits'])>20:raise ValueError('delta_edit_schema')
    new=copy.deepcopy(state);seen=set()
    for e in submission['edits']:
        if not isinstance(e,dict) or set(e)!=set(RECORD['required']):raise ValueError('delta_edit_schema')
        section,key=e['section'],e['id']
        if section not in EMPTY or not isinstance(key,str) or not 1<=len(key)<=60 or (section,key) in seen:raise ValueError('delta_duplicate_or_invalid_id')
        seen.add((section,key));old=state[section].get(key)
        if type(e['expected_revision']) is not int or e['expected_revision']!=(old['revision'] if old else 0):raise ValueError('delta_stale_revision')
        if e['op'] not in ('set','delete') or (e['op']=='delete' and old is None):raise ValueError('delta_invalid_operation')
        if not isinstance(e['text'],str) or len(e['text'])>500 or e['status'] not in RECORD['properties']['status']['enum']:raise ValueError('delta_record_schema')
        if not isinstance(e['links'],list) or len(e['links'])>8 or any(not isinstance(x,str) for x in e['links']):raise ValueError('delta_link_schema')
        evidence=e['evidence']
        if not isinstance(evidence,list) or not 1<=len(evidence)<=3:raise ValueError('delta_evidence_schema')
        if any(not isinstance(q,str) or q not in sources for q in evidence):raise ValueError('delta_evidence_unknown_id')
        resolved=[copy.deepcopy(sources[q]) for q in evidence]
        if e['op']=='delete':del new[section][key]
        else:
            if not e['text'].strip():raise ValueError('delta_empty_record')
            new[section][key]={k:copy.deepcopy(e[k]) for k in ('text','status','links','evidence')}
            new[section][key]['evidence']=resolved
            new[section][key]['revision']=e['expected_revision']+1
    for s in new:
        for r in new[s].values():
            if any(k not in new['requirements'] for k in r['links']):raise ValueError('delta_dangling_link')
    return new


class DeltaStore(BoundedStore):
    def __init__(self,workspace,limit,audit,policy):
        super().__init__(workspace,limit,audit);self.policy=policy
    async def consolidate(self,messages,provider,model):
        if not messages:return True
        original=pair(self);self.last_failure=None
        try:state=decode(original[0])
        except ValueError:
            self.last_failure='delta_memory_schema';return False
        sources=sources_for(messages,state)
        procedure=json.loads(self.policy['update'])['procedure']
        data={'state':state,'source_catalog':sources,'combined_storage_token_limit':self.limit}
        query=[{'role':'system','content':BASE+'\nLearned Update policy:\n'+procedure},
               {'role':'user','content':json.dumps(data,ensure_ascii=False)}]
        for attempt in range(2):
            tool=copy.deepcopy(TOOL)
            tool[0]['function']['parameters']['properties']['edits']['items']['properties']['evidence']['items']['enum']=list(sources)
            response=await provider.chat(messages=query,tools=tool,tool_choice='required',model=model)
            calls=response.tool_calls or [];size=None
            try:
                if response.finish_reason not in ('stop','tool_calls') or len(calls)!=1 or calls[0].name!='apply_memory_delta':raise ValueError('delta_tool_protocol')
                updated=apply(state,calls[0].arguments,sources);text=encode(updated);size=memory_tokens(text,'')
                if size>self.limit:raise ValueError('delta_capacity')
            except ValueError as e:
                code=str(e);self.audit('delta-updates.jsonl',dict(accepted=False,attempt=attempt+1,error_code=code,tokens=size,limit=self.limit))
                provider.format_repairs+=1
                query=query[:2]+[{'role':'user','content':f'Format, provenance, revision or capacity repair only: {code}; size={size}, limit={self.limit}. Resubmit the full transaction against the SAME original state. No new task answer is supplied. Aim below 80% capacity.'}]
                continue
            # Two files retain the original shared storage budget. No duplicate narrative history.
            try:write_pair(self,(text,''))
            except BaseException:write_pair(self,original);raise
            self.audit('delta-updates.jsonl',dict(accepted=True,attempt=attempt+1,before=state,edits=calls[0].arguments['edits'],after=updated,tokens=size,limit=self.limit,semantic_veto=False))
            return True
        self.last_failure='persistent_memory_budget_exhausted' if code=='delta_capacity' else 'delta_update_protocol_failure'
        return False
