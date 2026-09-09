import asyncio,json,os,sys,time,subprocess
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from sentaurus_mcp.service import Service

def test_mcp_disconnect_does_not_stop_run(tmp_path):
    config=tmp_path/'config.json'
    config.write_text(json.dumps({'root':str(tmp_path/'data'),'tools':{'demo':[sys.executable,'{input}']}}))
    worker=subprocess.Popen([sys.executable,'-m','sentaurus_mcp.worker'],env={**os.environ,'SENTAURUS_MCP_CONFIG':str(config)})
    s=Service(config)
    for _ in range(100):
        with s.connect() as db:ready=db.execute('SELECT 1 FROM worker').fetchone()
        if ready:break
        time.sleep(.05)
    async def run():
        env={**os.environ,'SENTAURUS_MCP_CONFIG':str(config),'SENTAURUS_ENABLE_ACTIONS':'1'}
        params=StdioServerParameters(command=sys.executable,args=['-m','sentaurus_mcp.server'],env=env)
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as session:
                await session.initialize()
                assert 'submit_experiment' in {t.name for t in (await session.list_tools()).tools}
                result=await session.call_tool('create_experiment',{'project':'demo','run_id':'detached','files':{'input.py':'import time; time.sleep(2); print("done")'},'stages':[{'tool':'demo','input_file':'input.py'}]})
                assert not result.isError
                result=await session.call_tool('submit_experiment',{'run_id':'detached'})
                assert not result.isError
    try:
        asyncio.run(run())
        end=time.monotonic()+15
        while time.monotonic()<end and s.get('detached')['state'] not in ('completed','failed'):time.sleep(.1)
        assert s.get('detached')['state']=='completed'
    finally:worker.terminate();worker.wait(timeout=5)

def test_actions_disabled(monkeypatch):
    from sentaurus_mcp.server import create_experiment
    import pytest
    monkeypatch.delenv('SENTAURUS_ENABLE_ACTIONS',raising=False)
    with pytest.raises(ValueError,match='disabled'):create_experiment('p','r',{},[])
