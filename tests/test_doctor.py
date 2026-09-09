import json
import sqlite3
import sys
import time
import shlex
import pytest
from sentaurus_mcp.doctor import diagnose, connection_guide


def test_unconfigured_and_vnc(monkeypatch):
    monkeypatch.delenv('SENTAURUS_MCP_CONFIG', raising=False)
    assert diagnose()['configuration']['state'] == 'missing'
    assert connection_guide('vnc')['state'] == 'unsupported_transport'


def test_readonly_and_worker(tmp_path):
    root = tmp_path/'data'
    config = tmp_path/'config.json'
    config.write_text(json.dumps({'root': str(root), 'tools': {'demo': [sys.executable]}}))
    assert diagnose(config)['worker']['state'] == 'offline'
    assert not root.exists()
    root.mkdir()
    with sqlite3.connect(root/'experiments.sqlite3') as db:
        db.execute('CREATE TABLE worker (id INTEGER,heartbeat REAL)')
        db.execute('INSERT INTO worker VALUES (1,?)',(time.time(),))
    r = diagnose(config)
    assert r['worker']['state'] == 'online'
    assert r['tools']['demo']['state'] == 'executable_found'
    assert r['license']['state'] == 'unverified'
    with sqlite3.connect(root/'experiments.sqlite3') as db:
        db.execute('UPDATE worker SET heartbeat=0')
    assert diagnose(config)['worker']['state'] == 'stale_or_offline'


def test_invalid_and_safe_remote(tmp_path):
    config = tmp_path/'bad.json'
    config.write_text('{}')
    assert diagnose(config)['configuration']['state'] == 'invalid'
    r = connection_guide('ssh','server.example.com','user',2222,'/path with space/python',"/tmp/a;echo nope")
    assert shlex.split(r['probe_argv'][-1])[-1] == '/tmp/a;echo nope'
    assert 'BatchMode=yes' in r['probe_argv']
    assert 'StrictHostKeyChecking=yes' in r['probe_argv']
    with pytest.raises(ValueError):
        connection_guide('ssh','-oProxyCommand=evil','user',22,'/python','/config')
