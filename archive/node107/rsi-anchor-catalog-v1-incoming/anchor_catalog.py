"""Expose exact unique local sentence anchors; never repair a rejected proposal."""
import copy,re

def schema_for(parent, schema):
    result=copy.deepcopy(schema)
    for target in ('guidance','update'):
        text=parent[target];limit=min(450,int(len(text)*.35))
        anchors=['']
        for sentence in re.split(r'(?<=[.!?])\s+',text):
            if sentence and len(sentence)<=limit and text.count(sentence)==1:
                anchors.append(sentence)
        result['properties'][target+'_anchor']['enum']=anchors
    return result
