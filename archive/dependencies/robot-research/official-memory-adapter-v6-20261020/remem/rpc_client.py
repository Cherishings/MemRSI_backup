import base64,json,urllib.request,urllib.error

class ActorInstructionError(ValueError):pass
def post(port,method,payload):
    req=urllib.request.Request(f'http://127.0.0.1:{port}/{method}',data=json.dumps(payload,allow_nan=False).encode(),headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=240) as r:return json.load(r)
    except urllib.error.HTTPError as e:
        info=json.loads(e.read())
        if info.get('actor_protocol_error'):raise ActorInstructionError(info['error_code']) from None
        raise RuntimeError('shared_controller_interface_failure') from None
def cameras(public):
    import numpy as np
    return [np.frombuffer(base64.b64decode(x['rgb_base64'],validate=True),dtype=np.uint8).reshape(x['shape']).copy() for x in public['cameras']]
