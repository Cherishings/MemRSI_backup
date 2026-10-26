import argparse,dataclasses,os,sys,json,time
from pathlib import Path
b=Path('/data/songziying/paos-libero-20261023');sys.path[:0]=[str(b/'study/source'),'/data/fba-closedloop-week-deps/openpi/src','/data/fba-closedloop-week-deps/openpi/packages/openpi-client/src']
import torch
from openpi.policies import policy_config
from openpi.training import config
from openpi.serving.websocket_policy_server import WebsocketPolicyServer
from paired_sampling import PairedPolicy
p=argparse.ArgumentParser();p.add_argument('--port',type=int,required=True);p.add_argument('--checkpoint',required=True);a=p.parse_args()
assert torch.cuda.is_available(),'DCU not available'
c=config.get_config('pi05_libero');c=dataclasses.replace(c,model=dataclasses.replace(c.model,pytorch_compile_mode=None))
policy=policy_config.create_trained_policy(c,a.checkpoint,pytorch_device='cuda:0')
w=PairedPolicy(policy,(c.model.action_horizon,c.model.action_dim))
print(json.dumps({'state':'ready','device':torch.cuda.get_device_name(0),'backend':'pytorch-dcu','paired_sampling':True,'port':a.port,'time':time.time()}),flush=True)
WebsocketPolicyServer(w,host='127.0.0.1',port=a.port,metadata=dict(policy.metadata,paired_sampling=True,noise_shape=list(w.shape),backend='pytorch-dcu')).serve_forever()
