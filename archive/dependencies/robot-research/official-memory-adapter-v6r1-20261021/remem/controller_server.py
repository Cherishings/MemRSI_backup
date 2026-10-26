"""Loopback-only shared physical controller. No evaluator state in public input."""
import argparse,base64,hashlib,json,os,threading,time,traceback
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
import numpy as np

def main():
    p=argparse.ArgumentParser();p.add_argument('--seed',type=int,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--port',type=int,default=19253);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    import setproctitle;setproctitle.setproctitle('robot')
    import imageio.v2 as imageio
    from environment import load_controller,load_scene,public_packet
    from audit import seed_all,initial_evidence,code_hashes
    seeds=seed_all(a.seed)
    (a.output/'source-hashes.json').write_text(json.dumps(code_hashes(),indent=2))
    from history_controller import InstructionError,BoundaryError
    c=load_controller();env,obs,instruction,horizon=load_scene(c,a.seed)
    state=dict(obs=obs,steps=0,success=False,closed=False,close_reason=None)
    initial=public_packet(obs,0,horizon,instruction)
    (a.output/'initial-evidence.json').write_text(json.dumps(initial_evidence(env,initial,a.seed),indent=2))
    writer=imageio.get_writer(a.output/'physical.mp4',fps=20)
    events=(a.output/'control-events.jsonl').open('a')
    def finish(reason):
        if state['closed']:return
        state['closed']=True;state['close_reason']=reason
        writer.close();events.close()
        result=dict(status='success' if state['success'] else 'policy_failure',official_check_success=state['success'],steps=state['steps'],horizon=horizon,close_reason=reason,seed=a.seed,policy_action_calls=c.executor.action_calls,instruction_changes=c.recondition_count,recorded_actions_used=0,state_injections_after_reset=0,time=time.time(),scope='fixed published whole-task PRISM condition with PAOS continue/finish supervisor')
        (a.output/'result.json').write_text(json.dumps(result,indent=2));env.close()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<=size<=8192:raise ValueError('request_size_exceeded')
                payload=json.loads(self.rfile.read(size) or b'{}')
                if self.path=='/observe':
                    if payload:raise ValueError('observe_has_no_arguments')
                    answer={'public':public_packet(state['obs'],state['steps'],horizon,instruction if state['steps']==0 else None)}
                elif self.path=='/chunk':
                    if set(payload)!={'instruction'}:raise ValueError('chunk_accepts_instruction_only')
                    if state['closed']:raise ValueError('episode_closed')
                    if payload['instruction']!=instruction:raise InstructionError('whole_task_condition_must_remain_fixed')
                    change=c.instruct(instruction);count=min(32,horizon-state['steps']);executed=0
                    for _ in range(count):
                        if state['success']:break
                        ob=state['obs'];writer.append_data(np.concatenate([ob['robot0_agentview_center_image'][::-1],ob['robot0_eye_in_hand_image'][::-1]],axis=1))
                        action=c.act(ob)
                        if state['steps']==0:(a.output/'first-action.json').write_text(json.dumps(dict(execution_seed=a.seed,instruction=payload['instruction'],action=np.asarray(action).tolist()),indent=2))
                        ob,_,_,_=env.step(action);state['obs']=ob;state['steps']+=1;executed+=1
                        state['success']=bool(env._check_success());setproctitle.setproctitle('robot')
                    row=dict(time=time.time(),steps=state['steps'],executed=executed,instruction=payload['instruction'],conditioning=change,policy_calls=c.executor.action_calls)
                    events.write(json.dumps(row)+'\n');events.flush();(a.output/'progress.json').write_text(json.dumps(row,indent=2))
                    answer=dict(public=public_packet(state['obs'],state['steps'],horizon),receipt=f'Executed {executed} robot control steps. Use the new camera observations to judge the outcome.',evaluator=dict(done=state['success'] or state['steps']>=horizon))
                elif self.path=='/close':
                    if set(payload)-{'reason'}:raise ValueError('close_argument_invalid')
                    finish(payload.get('reason','caller_close'));answer=dict(closed=True)
                    threading.Thread(target=self.server.shutdown,daemon=True).start()
                else:raise ValueError('unknown_method')
                body=json.dumps(answer,allow_nan=False).encode();self.send_response(200)
            except (InstructionError,BoundaryError) as e:
                body=json.dumps(dict(error_type=type(e).__name__,error_code=str(e),actor_protocol_error=isinstance(e,InstructionError))).encode();self.send_response(422)
            except Exception as e:
                with (a.output/'exception.private.txt').open('a') as f:f.write(traceback.format_exc())
                body=json.dumps(dict(error_type=type(e).__name__,error_code='controller_interface_failure')).encode();self.send_response(500)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=HTTPServer(('127.0.0.1',a.port),Handler)
    (a.output/'ready.json').write_text(json.dumps(dict(pid=os.getpid(),start_ticks=Path(f'/proc/{os.getpid()}/stat').read_text().rsplit(')',1)[1].split()[19],port=a.port,seed=a.seed),indent=2))
    try:server.serve_forever()
    finally:
        finish(state.get('close_reason') or 'server_exit');server.server_close()
if __name__=='__main__':main()
