"""Detached runner; survives normal MCP client shutdown without a solver timeout."""
import json,os,subprocess,sys,time
from pathlib import Path
from .service import Service

def run(config,rid,token):
    service=Service(config);record=service.get(rid);status=record['status']
    if record['state']!='starting' or status.get('launch_token')!=token:return
    root=Path(record['directory']);start=time.monotonic()
    status.update(runner_pid=os.getpid(),started_at=time.time(),stages=[],cpu_count=os.cpu_count(),platform=sys.platform)
    service.update(rid,'running',status)
    try:
        for i,stage in enumerate(record['manifest']['stages']):
            tick=time.monotonic();status.update(stage_index=i,tool=stage['tool'])
            with (root/f'stage-{i}.log').open('wb') as log:
                proc=subprocess.Popen(stage['argv'],cwd=root,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,shell=False)
                status['solver_pid']=proc.pid;service.update(rid,'running',status)
                while proc.poll() is None:
                    status.update(elapsed_seconds=time.monotonic()-start,updated_at=time.time())
                    service.update(rid,'running',status);time.sleep(.5)
            status['stages'].append({'index':i,'tool':stage['tool'],'wall_seconds':time.monotonic()-tick,'returncode':proc.returncode})
            if proc.returncode:raise RuntimeError(f'Stage {i} exited with {proc.returncode}')
        state='completed'
    except Exception as exc:state='failed';status['error']=str(exc)
    status.update(finished_at=time.time(),elapsed_seconds=time.monotonic()-start,validation='not_reviewed')
    service.update(rid,state,status)
    (root/'state.json').write_text(json.dumps({'state':state,'status':status},indent=2),encoding='utf-8')

if __name__=='__main__':run(*sys.argv[1:])
