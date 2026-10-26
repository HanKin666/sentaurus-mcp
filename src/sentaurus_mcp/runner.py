"""Detached runner; survives normal MCP client shutdown without a solver timeout."""

import json
import os
import platform
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .service import Service, psutil, sha256_file


def _process_create_time(pid):
    if psutil is None:
        return None
    try:
        return psutil.Process(pid).create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def _memory_snapshot():
    if psutil is None:
        return {'total_bytes': None, 'available_bytes': None, 'method': 'unavailable'}
    try:
        memory = psutil.virtual_memory()
        return {'total_bytes': memory.total, 'available_bytes': memory.available, 'method': 'psutil'}
    except (OSError, psutil.Error) as exc:
        return {'total_bytes': None, 'available_bytes': None, 'method': type(exc).__name__}


def _sample_process_tree(pid, observed_cpu_by_process):
    """Sample the solver and visible descendants; this is not an OS peak counter."""
    if psutil is None:
        return None
    try:
        root_process = psutil.Process(pid)
        processes = [root_process, *root_process.children(recursive=True)]
    except psutil.Error:
        return None

    rss_bytes = 0
    thread_count = 0
    observed_processes = 0
    for process in processes:
        try:
            identity = (process.pid, process.create_time())
            cpu = process.cpu_times()
            cpu_seconds = float(cpu.user + cpu.system)
            observed_cpu_by_process[identity] = max(
                observed_cpu_by_process.get(identity, 0.0), cpu_seconds
            )
            rss_bytes += process.memory_info().rss
            thread_count += process.num_threads()
            observed_processes += 1
        except psutil.Error:
            continue
    if not observed_processes:
        return None
    return {
        'rss_bytes': rss_bytes,
        'cpu_seconds': sum(observed_cpu_by_process.values()),
        'thread_count': thread_count,
        'process_count': observed_processes,
    }


def _update_resource_usage(usage, sample):
    if sample is None:
        return
    usage['sample_count'] += 1
    usage['peak_observed_rss_bytes'] = max(
        usage['peak_observed_rss_bytes'] or 0, sample['rss_bytes']
    )
    usage['observed_cpu_seconds'] = max(
        usage['observed_cpu_seconds'], sample['cpu_seconds']
    )
    usage['peak_observed_thread_count'] = max(
        usage['peak_observed_thread_count'] or 0, sample['thread_count']
    )
    usage['last_observed_process_count'] = sample['process_count']


def _execution_snapshot(service, manifest):
    fingerprint = manifest.get('execution_fingerprint', {})
    tools = []
    for stage in manifest['stages']:
        executable = stage['argv'][0]
        try:
            digest = sha256_file(executable)
        except OSError:
            digest = None
        tools.append({
            'tool': stage['tool'],
            'executable': executable,
            'sha256': digest,
            'prepared_sha256': fingerprint.get('tool_executables', {}).get(executable),
        })
    try:
        config_digest = sha256_file(service.config_path)
    except OSError:
        config_digest = None
    return {
        'captured_at': time.time(),
        'host': {
            'platform': platform.platform(),
            'cpu_count': os.cpu_count(),
            'memory': _memory_snapshot(),
            'python_executable': sys.executable,
            'python_version': sys.version,
        },
        'configuration': {
            'path': str(service.config_path),
            'sha256': config_digest,
            'prepared_sha256': fingerprint.get('config_sha256'),
        },
        'tool_executables': tools,
    }


def _output_result(root, stage):
    expected = stage.get('expected_outputs', [])
    if not expected:
        return {'status': 'not_requested', 'expected': [], 'present': [], 'missing': []}
    present, missing = [], []
    for name in expected:
        path = root / name
        try:
            resolved = path.resolve(strict=True)
            if root.resolve() not in resolved.parents or path.is_symlink() or not resolved.is_file():
                missing.append(name)
            else:
                present.append(name)
        except OSError:
            missing.append(name)
    return {
        'status': 'missing' if missing else 'present',
        'expected': list(expected),
        'present': present,
        'missing': missing,
        'notice': 'File presence only; artifact contents and physical validity are not reviewed',
    }


def _aggregate_output_validation(stages, manifest_stages):
    expected = [stage for stage in manifest_stages if stage.get('expected_outputs')]
    if not expected:
        return {'status': 'not_requested', 'stages': stages}
    checked = {stage['index']: stage.get('output_validation') for stage in stages}
    if any(result and result['status'] == 'missing' for result in checked.values()):
        state = 'missing'
    elif len(checked) < len(manifest_stages):
        state = 'incomplete'
    elif any(
        stage.get('expected_outputs') and not checked.get(index)
        for index, stage in enumerate(manifest_stages)
    ):
        state = 'incomplete'
    else:
        state = 'present'
    return {
        'status': state,
        'stages': stages,
        'notice': 'File presence only; artifact contents and physical validity are not reviewed',
    }


def _failure_hints(log_path):
    try:
        with log_path.open('rb') as stream:
            stream.seek(max(0, log_path.stat().st_size - 32_000))
            text = stream.read().decode('utf-8', 'replace').lower()
    except OSError:
        return []
    hints = []
    if re.search(r'license|licence|checkout', text):
        hints.append('License-related text appeared in the stage log; this is a hint, not a verified cause.')
    if re.search(r'converg|iteration limit', text):
        hints.append('Convergence-related text appeared in the stage log; this is a hint, not a verified cause.')
    return hints


def _atomic_state(root, state, status):
    destination = root / 'state.json'
    temporary = root / f'.state-{os.getpid()}-{uuid.uuid4().hex}.tmp'
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump({'state': state, 'status': status}, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _finish(service, root, rid, state, status, started_monotonic):
    finished = time.time()
    status.update(
        finished_at=finished,
        heartbeat_at=finished,
        updated_at=finished,
        elapsed_seconds=time.monotonic() - started_monotonic,
        validation='not_reviewed',
    )
    manifest = service.get(rid)['manifest']
    status['output_validation'] = _aggregate_output_validation(status['stages'], manifest['stages'])
    service.update(rid, state, status)
    _atomic_state(root, state, status)


def run(config, rid, token):
    service = Service(config)
    record = service.get(rid)
    status = record['status']
    if record['state'] != 'starting' or status.get('launch_token') != token:
        return

    root = Path(record['directory'])
    started_monotonic = time.monotonic()
    now = time.time()
    status.update(
        runner_pid=os.getpid(),
        runner_create_time=_process_create_time(os.getpid()),
        started_at=now,
        heartbeat_at=now,
        stages=[],
        execution_snapshot=_execution_snapshot(service, record['manifest']),
    )
    service.update(rid, 'running', status)

    try:
        for index, stage in enumerate(record['manifest']['stages']):
            stage_started = time.time()
            stage_monotonic = time.monotonic()
            stage_status = {
                'index': index,
                'tool': stage['tool'],
                'started_at': stage_started,
                'ended_at': None,
                'wall_seconds': None,
                'returncode': None,
            }
            status['stages'].append(stage_status)
            status.update(
                stage_index=index,
                tool=stage['tool'],
                solver_pid=None,
                solver_create_time=None,
                heartbeat_at=stage_started,
                updated_at=stage_started,
            )
            service.update(rid, 'running', status)

            # Recheck immutable inputs and executable/configuration fingerprints
            # immediately before starting each configured tool.
            try:
                service.verify_immutable_inputs(record)
            except ValueError as exc:
                ended = time.time()
                stage_status.update(ended_at=ended, wall_seconds=time.monotonic() - stage_monotonic)
                status['failure'] = {
                    'stage_index': index,
                    'tool': stage['tool'],
                    'reason': 'immutable_input_changed',
                    'verified': True,
                    'detail': str(exc),
                }
                status['error'] = str(exc)
                _finish(service, root, rid, 'failed', status, started_monotonic)
                return

            log_path = root / f'stage-{index}.log'
            observed_cpu_by_process = {}
            stage_status['resource_usage'] = {
                'scope': 'solver_process_tree_sampled_during_polling',
                'sample_interval_seconds': 0.5,
                'sample_count': 0,
                'peak_observed_rss_bytes': None,
                'observed_cpu_seconds': 0.0,
                'peak_observed_thread_count': None,
                'last_observed_process_count': 0,
            }
            try:
                with log_path.open('wb') as log:
                    process = subprocess.Popen(
                        stage['argv'],
                        cwd=root,
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        shell=False,
                    )
                    solver_create_time = _process_create_time(process.pid)
                    stage_status.update(solver_pid=process.pid, solver_create_time=solver_create_time)
                    status.update(solver_pid=process.pid, solver_create_time=solver_create_time)
                    _update_resource_usage(
                        stage_status['resource_usage'],
                        _sample_process_tree(process.pid, observed_cpu_by_process),
                    )
                    service.update(rid, 'running', status)
                    while process.poll() is None:
                        _update_resource_usage(
                            stage_status['resource_usage'],
                            _sample_process_tree(process.pid, observed_cpu_by_process),
                        )
                        heartbeat = time.time()
                        status.update(
                            elapsed_seconds=time.monotonic() - started_monotonic,
                            heartbeat_at=heartbeat,
                            updated_at=heartbeat,
                        )
                        service.update(rid, 'running', status)
                        time.sleep(0.5)
            except OSError as exc:
                ended = time.time()
                stage_status.update(ended_at=ended, wall_seconds=time.monotonic() - stage_monotonic)
                status['failure'] = {
                    'stage_index': index,
                    'tool': stage['tool'],
                    'reason': 'process_start_error',
                    'verified': False,
                    'detail': str(exc),
                }
                status['error'] = str(exc)
                _finish(service, root, rid, 'failed', status, started_monotonic)
                return

            ended = time.time()
            _update_resource_usage(
                stage_status['resource_usage'],
                _sample_process_tree(process.pid, observed_cpu_by_process),
            )
            stage_status.update(
                ended_at=ended,
                wall_seconds=time.monotonic() - stage_monotonic,
                returncode=process.returncode,
                output_validation=_output_result(root, stage),
            )
            status.update(heartbeat_at=ended, updated_at=ended)
            service.update(rid, 'running', status)
            if process.returncode:
                status['failure'] = {
                    'stage_index': index,
                    'tool': stage['tool'],
                    'reason': 'nonzero_exit',
                    'verified': True,
                    'returncode': process.returncode,
                    'hints': _failure_hints(log_path),
                }
                status['error'] = f"Stage {index} exited with {process.returncode}"
                _finish(service, root, rid, 'failed', status, started_monotonic)
                return

        _finish(service, root, rid, 'completed', status, started_monotonic)
    except Exception as exc:
        status['failure'] = {
            'stage_index': status.get('stage_index'),
            'tool': status.get('tool'),
            'reason': 'runner_error',
            'verified': False,
            'detail': str(exc),
        }
        status['error'] = str(exc)
        _finish(service, root, rid, 'failed', status, started_monotonic)


if __name__ == '__main__':
    run(*sys.argv[1:])
