"""Offline request assembly. No network/model calls or runtime mutations."""
import copy,json,hashlib

def line_pack(view):
 out=copy.deepcopy(view);line_ids={};lines=[];memories=[];ids={}
 for h,s in sorted(view['shared_text'].items()):
  seq=[]
  for line in s.splitlines(keepends=True):
   if line not in line_ids:line_ids[line]=len(lines);lines.append(line)
   seq.append(line_ids[line])
  ids[h]=len(memories);memories.append(seq)
 for group in out['paired']+[out['diagnostic']]:
  for d in group['details']:d['refs']={n:ids[h] for n,h in d['refs'].items()}
 out.pop('shared_text');out['memory_lines']=lines;out['memories']=memories
 out['encoding']='Each memories entry lists memory_lines indices in original order. Concatenate these exact lines including newlines to read the full memory. No memory lines were summarized or removed.'
 return out

def assemble(view,parent_text,schema,runtime,diagnostics,system):
 data={'parent':parent_text,'existing_runtime_contract':runtime,'training_archive_transitions':line_pack(view),'training_failure_diagnostics':diagnostics,'validation_feedback_provided':False,'test_feedback_provided':False}
 messages=[{'role':'system','content':system},{'role':'user','content':json.dumps(data,ensure_ascii=False,separators=(',',':'))}]
 tools=[{'type':'function','function':{'name':'submit','description':'Submit one bounded result.','parameters':schema}}]
 return {'messages':messages,'tools':tools}
