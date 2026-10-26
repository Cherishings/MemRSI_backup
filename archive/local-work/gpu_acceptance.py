import json,subprocess,torch,time
from pathlib import Path
out=Path('/media/disks/disk1/share/ext_songzhiying/PAOS-validation-20261023');out.mkdir(parents=True,exist_ok=True)
rows=[]
for i in range(torch.cuda.device_count()):
 used=int(subprocess.check_output(['nvidia-smi','-i',str(i),'--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).strip())
 r={'gpu':i,'name':torch.cuda.get_device_name(i),'memory_before_mib':used}
 if used>1000:r['status']='occupied_not_tested'
 else:
  try:
   with torch.cuda.device(i):
    a=torch.ones((128,128),device=f'cuda:{i}');b=a@a;torch.cuda.synchronize();assert b[0,0].item()==128
    del a,b;torch.cuda.empty_cache()
   r['status']='cuda_matmul_passed'
  except Exception as e:r.update(status='failed',error_type=type(e).__name__)
 rows.append(r)
result={'time':time.time(),'torch':torch.__version__,'cuda':torch.version.cuda,'gpus':rows}
(out/'gpu-acceptance.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
