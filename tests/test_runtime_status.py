import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from sentaurus_mcp import runner
import sentaurus_mcp.service as service_module
from sentaurus_mcp.service import OBSERVATION_STALE_SECONDS, Service, process_liveness


@pytest.fixture
def service(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(
        json.dumps({
            'root': str(tmp_path / 'data'),
            'max_parallel': 1,
            'tools': {'demo': [sys.executable, '{input}']},
        }),
        encoding='utf-8',
    )
    return Service(config)


def prepare_starting(service, rid, script, expected_outputs=None):
    stage = {'tool': 'demo', 'input_file': 'input.py'}
    if expected_outputs is not None:
        stage['expected_outputs'] = expected_outputs
    record = service.create('project', rid, {'input.py': script}, [stage])
    token = f'token-{rid}'
    now = time.time()
    service.update(rid, 'starting', {
        'launch_token': token,
        'submitted_at': now,
        'heartbeat_at': now,
        'validation': 'not_reviewed',
    })
    return token, record


def test_observation_reports_stale_and_runner_lost_without_mutating(service):
    now = time.time()
    prepare_starting(service, 'stale', 'pass')
    service.update('stale', 'running', {
        'heartbeat_at': now - OBSERVATION_STALE_SECONDS - 1,
        'runner_pid': os.getpid(),
        'runner_create_time': psutil.Process(os.getpid()).create_time(),
    })
    prepare_starting(service, 'lost', 'pass')
    dead_pid = 2_000_000_000
    service.update('lost', 'running', {
        'heartbeat_at': now - OBSERVATION_STALE_SECONDS - 1,
        'runner_pid': dead_pid,
        'runner_create_time': now - 100,
    })
    with service.connect() as db:
        db.execute('INSERT OR REPLACE INTO worker VALUES (1,?,?)', ('worker-token', now - 30))

    stale_before = service.get('stale')['status']
    stale = service.get('stale')
    lost = service.get('lost')
    items = {item['id']: item for item in service.list()['items']}

    assert stale['state'] == 'running'
    assert stale['observation']['execution_classification'] == 'stale'
    assert stale['observation']['run_heartbeat']['freshness'] == 'stale'
    assert stale['observation']['process_liveness']['runner']['alive'] is True
    assert lost['state'] == 'running'
    assert lost['observation']['execution_classification'] == 'runner_lost'
    assert lost['observation']['process_liveness']['runner']['alive'] is False
    assert stale['observation']['worker_lease']['age_seconds'] >= 30
    assert stale['observation']['worker_lease']['freshness'] == 'stale'
    assert isinstance(stale['observation']['collected_at'], float)
    assert items['lost']['observation']['execution_classification'] == 'runner_lost'
    assert service.get('stale')['status'] == stale_before


def test_future_heartbeat_is_unknown_not_fresh(service):
    token, _ = prepare_starting(service, 'future', 'pass')
    service.update('future', 'running', {
        'launch_token': token,
        'heartbeat_at': time.time() + 60,
        'runner_pid': None,
    })
    with service.connect() as db:
        db.execute('INSERT OR REPLACE INTO worker VALUES (1,?,?)', ('worker-token', time.time() + 60))

    observation = service.get('future')['observation']

    assert observation['run_heartbeat']['age_seconds'] is None
    assert observation['run_heartbeat']['freshness'] == 'unknown'
    assert observation['worker_lease']['freshness'] == 'unknown'
    assert observation['execution_classification'] == 'unknown'


def test_windows_liveness_fallback_does_not_call_os_kill(monkeypatch):
    def forbidden_kill(*args, **kwargs):
        raise AssertionError('Windows fallback must not call os.kill')

    monkeypatch.setattr(service_module, 'psutil', None)
    monkeypatch.setattr(service_module.os, 'name', 'nt')
    monkeypatch.setattr(service_module.os, 'kill', forbidden_kill)

    result = process_liveness(os.getpid())

    assert result['alive'] is None
    assert result['evidence']['reason'] == 'psutil_unavailable_on_windows'


def test_zombie_pid_is_not_reported_as_running(monkeypatch):
    class ZombieProcess:
        def create_time(self):
            return 123.0

        def status(self):
            return 'zombie'

        def is_running(self):
            return True

    class FakePsutil:
        STATUS_ZOMBIE = 'zombie'

        @staticmethod
        def Process(_pid):
            return ZombieProcess()

    monkeypatch.setattr(service_module, 'psutil', FakePsutil)

    result = process_liveness(123, expected_create_time=123.0)

    assert result['alive'] is False
    assert result['evidence']['reason'] == 'process_zombie'


def test_killed_runner_is_observed_as_lost_without_rewriting_state(service):
    token, record = prepare_starting(service, 'killed', 'import time; time.sleep(60)')
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join(filter(None, [
        str(Path(__file__).resolve().parents[1] / 'src'),
        os.environ.get('PYTHONPATH', ''),
    ]))}
    process = subprocess.Popen(
        [sys.executable, '-m', 'sentaurus_mcp.runner', str(service.config_path), 'killed', token],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    solver_pid = None
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            current = service.get('killed')
            solver_pid = current['status'].get('solver_pid')
            if current['state'] == 'running' and solver_pid:
                break
            if process.poll() is not None:
                pytest.fail(f'Runner exited early with {process.returncode}')
            time.sleep(0.05)
        else:
            pytest.fail('Synthetic runner did not start its stage')

        process.terminate()
        process.wait(timeout=5)
        try:
            solver = psutil.Process(solver_pid)
            solver.terminate()
            solver.wait(timeout=5)
        except (psutil.NoSuchProcess, psutil.TimeoutExpired):
            pass

        before = service.get('killed')
        after = service.get('killed')
        assert before['state'] == 'running'
        assert before['observation']['execution_classification'] == 'runner_lost'
        assert before['observation']['process_liveness']['runner']['alive'] is False
        assert after['state'] == 'running'
        assert after['status'] == before['status']
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if solver_pid:
            try:
                solver = psutil.Process(solver_pid)
                solver.kill()
                solver.wait(timeout=5)
            except (psutil.NoSuchProcess, psutil.TimeoutExpired):
                pass


def test_nonzero_exit_has_stage_times_and_generic_diagnostics(service):
    token, _ = prepare_starting(
        service,
        'failed-stage',
        "import time; time.sleep(1); print('convergence failed'); raise SystemExit(3)",
        expected_outputs=['result.dat'],
    )

    runner.run(str(service.config_path), 'failed-stage', token)
    result = service.get('failed-stage')
    stage = result['status']['stages'][0]

    assert result['state'] == 'failed'
    assert stage['started_at'] <= stage['ended_at']
    assert stage['wall_seconds'] >= 0
    assert stage['returncode'] == 3
    assert stage['resource_usage']['scope'] == 'solver_process_tree_sampled_during_polling'
    assert stage['resource_usage']['sample_count'] >= 1
    assert 'observed_cpu_seconds' in stage['resource_usage']
    assert 'python_version' in result['status']['execution_snapshot']['host']
    assert result['status']['failure']['reason'] == 'nonzero_exit'
    assert result['status']['failure']['verified'] is True
    assert any('hint, not a verified cause' in hint for hint in result['status']['failure']['hints'])
    assert result['status']['output_validation']['status'] == 'missing'
    state_file = Path(result['directory']) / 'state.json'
    assert json.loads(state_file.read_text(encoding='utf-8'))['status']['failure']['returncode'] == 3


def test_runner_rechecks_immutable_input_before_tool_start(service):
    token, record = prepare_starting(service, 'changed-input', 'print("prepared")')
    input_path = Path(record['directory']) / 'input.py'
    input_path.write_text('print("changed")', encoding='utf-8')

    runner.run(str(service.config_path), 'changed-input', token)
    result = service.get('changed-input')

    assert result['state'] == 'failed'
    assert result['status']['failure']['reason'] == 'immutable_input_changed'
    assert result['status']['failure']['verified'] is True
    assert result['status']['stages'][0]['returncode'] is None
    assert not (Path(result['directory']) / 'stage-0.log').exists()


def test_expected_output_presence_is_not_physics_validation(service):
    token, record = prepare_starting(
        service,
        'artifact-check',
        "from pathlib import Path; Path('result.dat').write_text('synthetic')",
        expected_outputs=['result.dat'],
    )

    runner.run(str(service.config_path), 'artifact-check', token)
    result = service.get('artifact-check')

    assert result['state'] == 'completed'
    assert result['status']['output_validation']['status'] == 'present'
    assert result['status']['output_validation']['stages'][0]['output_validation']['present'] == ['result.dat']
    assert 'physical validity are not reviewed' in result['status']['output_validation']['notice']
