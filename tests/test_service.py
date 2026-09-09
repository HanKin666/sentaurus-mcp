import json,sys,time,subprocess,os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from sentaurus_mcp.service import Service

@pytest.fixture
def service(tmp_path):
    config=tmp_path/'config.json'
    config.write_text(json.dumps({'root':str(tmp_path/'data'),'max_parallel':1,'tools':{'demo':[sys.executable,'{input}']}}))
    service=Service(config)
    worker=subprocess.Popen([sys.executable,'-m','sentaurus_mcp.worker'],env={**os.environ,'SENTAURUS_MCP_CONFIG':str(config)})
    for _ in range(100):
        with service.connect() as db:ready=db.execute('SELECT 1 FROM worker').fetchone()
        if ready:break
        time.sleep(.05)
    try:yield service
    finally:worker.terminate();worker.wait(timeout=5)

def prepare(s,rid='demo',script='print("synthetic only")'):
    return s.create('project',rid,{'input.py':script},[{'tool':'demo','input_file':'input.py'}])

def wait_done(s,rid):
    end=time.monotonic()+15
    while time.monotonic()<end:
        result=s.get(rid)
        if result['state'] in ('completed','failed'):return result
        time.sleep(.1)
    pytest.fail('Synthetic runner did not finish')

def test_duplicate_and_persistence(service):
    prepare(service)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:service.submit('demo'),range(2)))
    assert sum(r['submitted'] for r in results)==1
    assert wait_done(service,'demo')['state']=='completed'
    assert Service(service.config_path).get('demo')['status']['validation']=='not_reviewed'
    assert 'synthetic' in service.log('demo')['text']

def test_inputs_and_paths(service):
    with pytest.raises(ValueError):prepare(service,'../outside')
    row=prepare(service)
    Path(row['directory'],'input.py').write_text('changed')
    with pytest.raises(ValueError,match='changed'):service.submit('demo')
    with pytest.raises(ValueError):service.get('unknown')

def test_capacity_and_failed_stage(service):
    prepare(service,'first','import time; time.sleep(1)')
    prepare(service,'second','raise SystemExit(3)')
    service.submit('first')
    assert service.submit('second')['state']=='queued'
    wait_done(service,'first')
    result=wait_done(service,'second')
    assert result['state']=='failed' and result['status']['stages'][0]['returncode']==3
    assert result['status']['started_at']>=service.get('first')['status']['finished_at']
