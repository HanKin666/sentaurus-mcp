"""Persistent batch experiments, independent of dashboards and model providers."""

import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is a declared runtime dependency
    psutil = None


OBSERVATION_STALE_SECONDS = 10.0


def identifier(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', value):
        raise ValueError('Invalid identifier')
    return value


def sha256_file(path):
    """Hash a file without loading large native executables into memory."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def process_liveness(pid, expected_create_time=None):
    """Return non-mutating evidence about a process and its PID identity."""
    if not isinstance(pid, int) or pid <= 0:
        return {'pid': pid, 'alive': None, 'evidence': {'method': 'unavailable', 'reason': 'pid_not_recorded'}}

    if psutil is not None:
        try:
            process = psutil.Process(pid)
            create_time = process.create_time()
            process_status = process.status()
            is_running = process.is_running() and process_status != psutil.STATUS_ZOMBIE
            if expected_create_time is not None:
                identity_matches = math.isclose(
                    create_time, float(expected_create_time), rel_tol=0.0, abs_tol=0.01
                )
                reason = (
                    'pid_reused' if not identity_matches
                    else 'process_zombie' if process_status == psutil.STATUS_ZOMBIE
                    else 'pid_and_create_time_match' if is_running
                    else 'process_not_running'
                )
                return {
                    'pid': pid,
                    'alive': bool(is_running and identity_matches),
                    'evidence': {
                        'method': 'psutil',
                        'identity_verified': identity_matches,
                        'observed_create_time': create_time,
                        'reason': reason,
                    },
                }
            return {
                'pid': pid,
                'alive': bool(is_running),
                'evidence': {
                    'method': 'psutil',
                    'identity_verified': False,
                    'observed_create_time': create_time,
                    'reason': 'process_zombie' if process_status == psutil.STATUS_ZOMBIE else 'pid_exists_identity_unverified',
                },
            }
        except psutil.NoSuchProcess:
            return {
                'pid': pid,
                'alive': False,
                'evidence': {'method': 'psutil', 'identity_verified': True, 'reason': 'process_not_found'},
            }
        except (psutil.AccessDenied, psutil.ZombieProcess) as exc:
            return {
                'pid': pid,
                'alive': None,
                'evidence': {'method': 'psutil', 'identity_verified': False, 'reason': type(exc).__name__},
            }

    # Windows does not support os.kill(pid, 0) as a process-existence query.
    if os.name == 'nt':
        return {
            'pid': pid,
            'alive': None,
            'evidence': {'method': 'unavailable', 'identity_verified': False, 'reason': 'psutil_unavailable_on_windows'},
        }

    # Keep status useful if psutil is unavailable in an older POSIX installation.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        alive, reason = False, 'process_not_found'
    except PermissionError:
        alive, reason = True, 'permission_denied_but_process_exists'
    except OSError as exc:
        alive, reason = None, type(exc).__name__
    else:
        alive, reason = True, 'pid_exists_identity_unverified'
    return {
        'pid': pid,
        'alive': alive,
        'evidence': {'method': 'os.kill(pid, 0)', 'identity_verified': False, 'reason': reason},
    }


def _age(timestamp, now):
    try:
        value = float(timestamp)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0 or value > now:
        return None
    return round(now - value, 3)


def _freshness(age):
    if age is None:
        return 'unknown'
    return 'fresh' if age <= OBSERVATION_STALE_SECONDS else 'stale'


class Service:
    def __init__(self, config_path=None):
        value = config_path or os.getenv('SENTAURUS_MCP_CONFIG')
        if not value:
            raise ValueError('Set SENTAURUS_MCP_CONFIG')
        self.config_path = Path(value).resolve()
        config_bytes = self.config_path.read_bytes()
        self.config_sha256 = hashlib.sha256(config_bytes).hexdigest()
        self.config = json.loads(config_bytes.decode('utf-8'))
        root = Path(self.config['root'])
        if not root.is_absolute():
            raise ValueError('root must be absolute')
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,project TEXT,state TEXT,manifest TEXT,status TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS worker (id INTEGER PRIMARY KEY,token TEXT,heartbeat REAL)')

    def connect(self):
        db = sqlite3.connect(str(self.root / 'experiments.sqlite3'), timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def directory(self, project, rid):
        path = (self.root / identifier(project) / identifier(rid)).resolve()
        if self.root not in path.parents:
            raise ValueError('Path escapes root')
        return path

    def _observation(self, row, worker_heartbeat, collected_at=None):
        now = time.time() if collected_at is None else collected_at
        status = json.loads(row['status'])
        worker_age = _age(worker_heartbeat, now)
        run_heartbeat = status.get('heartbeat_at', status.get('updated_at'))
        if run_heartbeat is None:
            run_heartbeat = status.get('started_at', status.get('submitted_at', status.get('queued_at')))
        run_age = _age(run_heartbeat, now)
        runner = process_liveness(status.get('runner_pid'), status.get('runner_create_time'))
        solver = process_liveness(status.get('solver_pid'), status.get('solver_create_time'))

        state = row['state']
        if state in ('completed', 'failed'):
            classification = state
        elif state == 'running':
            if runner['alive'] is False:
                classification = 'runner_lost'
            elif _freshness(run_age) == 'stale':
                classification = 'stale'
            elif runner['alive'] is True:
                classification = 'running'
            else:
                classification = 'unknown'
        elif state == 'starting':
            if runner['alive'] is False:
                classification = 'runner_lost'
            elif _freshness(run_age) == 'stale':
                classification = 'stale'
            elif runner['alive'] is True:
                classification = 'starting'
            else:
                classification = 'unknown'
        elif state in ('prepared', 'queued'):
            classification = state
        else:
            classification = 'unknown'

        return {
            'collected_at': now,
            'worker_lease': {
                'heartbeat_at': worker_heartbeat,
                'age_seconds': worker_age,
                'freshness': _freshness(worker_age),
                'stale_after_seconds': OBSERVATION_STALE_SECONDS,
            },
            'run_heartbeat': {
                'heartbeat_at': run_heartbeat,
                'age_seconds': run_age,
                'freshness': _freshness(run_age),
                'stale_after_seconds': OBSERVATION_STALE_SECONDS,
            },
            'process_liveness': {'runner': runner, 'solver': solver},
            'execution_classification': classification,
        }

    def get(self, rid):
        with self.connect() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?', (identifier(rid),)).fetchone()
            worker = db.execute('SELECT heartbeat FROM worker WHERE id=1').fetchone()
        if row is None:
            raise ValueError('Unknown experiment')
        heartbeat = None if worker is None else worker['heartbeat']
        return {
            'run_id': row['id'],
            'project': row['project'],
            'state': row['state'],
            'manifest': json.loads(row['manifest']),
            'status': json.loads(row['status']),
            'directory': str(self.directory(row['project'], row['id'])),
            'observation': self._observation(row, heartbeat),
        }

    def list(self, offset=0, limit=20):
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError('Invalid pagination')
        with self.connect() as db:
            total = db.execute('SELECT count(*) FROM runs').fetchone()[0]
            worker = db.execute('SELECT heartbeat FROM worker WHERE id=1').fetchone()
            rows = db.execute(
                'SELECT id,project,state,status FROM runs ORDER BY rowid DESC LIMIT ? OFFSET ?',
                (limit, offset),
            ).fetchall()
        heartbeat = None if worker is None else worker['heartbeat']
        items = []
        for row in rows:
            item = dict(row)
            item['status'] = json.loads(item['status'])
            item['observation'] = self._observation(row, heartbeat)
            items.append(item)
        return {'total': total, 'items': items}

    def create(self, project, rid, files, stages):
        folder = self.directory(project, rid)
        if not files or sum(len(v.encode()) for v in files.values()) > 2_000_000:
            raise ValueError('Inputs must be nonempty and <=2MB')
        for name in files:
            if (
                not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,119}', name)
                or name.lower() in ('manifest.json', 'runner.log', 'state.json')
                or name.startswith('stage-')
            ):
                raise ValueError('Invalid or reserved file name')
        if not 1 <= len(stages) <= 16:
            raise ValueError('Provide 1..16 stages')
        commands = []
        executable_hashes = {}
        for stage in stages:
            tool = stage['tool']
            name = stage['input_file']
            expected_outputs = stage.get('expected_outputs', [])
            argv = self.config.get('tools', {}).get(tool)
            if (
                name not in files
                or not isinstance(argv, list)
                or not argv
                or not all(isinstance(v, str) for v in argv)
            ):
                raise ValueError('Invalid input or tool profile')
            if (
                not isinstance(expected_outputs, list)
                or len(expected_outputs) > 64
                or any(
                    not isinstance(output, str)
                    or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,119}', output)
                    or output.lower() in ('manifest.json', 'runner.log', 'state.json')
                    or output.startswith('stage-')
                    or output in files
                    for output in expected_outputs
                )
            ):
                raise ValueError('Invalid expected output name')
            executable = Path(argv[0])
            if not executable.is_absolute() or not executable.is_file():
                raise ValueError('Configured executable must exist at absolute path')
            executable_hashes[str(executable)] = sha256_file(executable)
            commands.append({
                'tool': tool,
                'input_file': name,
                'argv': [v.replace('{input}', name) for v in argv],
                'expected_outputs': list(expected_outputs),
            })
        manifest = {
            'run_id': rid,
            'project': project,
            'created_at': time.time(),
            'stages': commands,
            'input_sha256': {k: hashlib.sha256(v.encode()).hexdigest() for k, v in files.items()},
            'execution_fingerprint': {
                'config_sha256': self.config_sha256,
                'tool_executables': executable_hashes,
            },
            'scope': 'Native batch folder, not a generated SWB project',
            'time_policy': 'no_wall_clock_kill',
        }
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM runs WHERE id=?', (rid,)).fetchone():
                raise ValueError('ID already exists')
            folder.mkdir(parents=True, exist_ok=False)
            for name, content in files.items():
                (folder / name).write_bytes(content.encode())
            (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
            db.execute(
                'INSERT INTO runs VALUES (?,?,?,?,?)',
                (rid, project, 'prepared', json.dumps(manifest), '{}'),
            )
        return self.get(rid)

    def verify_immutable_inputs(self, run):
        """Recheck prepared files, config and executables at each launch boundary."""
        folder = Path(run['directory'])
        for name, digest in run['manifest'].get('input_sha256', {}).items():
            try:
                actual = sha256_file(folder / name)
            except OSError as exc:
                raise ValueError(f'Input unavailable after preparation: {name}') from exc
            if actual != digest:
                raise ValueError(f'Input changed after preparation: {name}')

        fingerprint = run['manifest'].get('execution_fingerprint')
        if not fingerprint:
            return  # Older persisted runs predate execution fingerprints.
        try:
            config_hash = sha256_file(self.config_path)
        except OSError as exc:
            raise ValueError('Prepared configuration is unavailable') from exc
        if config_hash != fingerprint.get('config_sha256'):
            raise ValueError('Configuration changed after preparation')
        for path, digest in fingerprint.get('tool_executables', {}).items():
            try:
                actual = sha256_file(path)
            except OSError as exc:
                raise ValueError(f'Configured executable is unavailable: {path}') from exc
            if actual != digest:
                raise ValueError(f'Configured executable changed after preparation: {path}')

    def update(self, rid, state, status):
        with self.connect() as db:
            db.execute('UPDATE runs SET state=?,status=? WHERE id=?', (state, json.dumps(status), rid))

    def merge_status(self, rid, values, allowed_states=('starting', 'running')):
        """Merge launch metadata without overwriting a runner's newer status."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state,status FROM runs WHERE id=?', (rid,)).fetchone()
            if row is None or row['state'] not in allowed_states:
                return False
            status = json.loads(row['status'])
            status.update(values)
            db.execute('UPDATE runs SET status=? WHERE id=?', (json.dumps(status), rid))
            return True

    def submit(self, rid):
        run = self.get(rid)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM runs WHERE id=?', (rid,)).fetchone()
            if row[0] != 'prepared':
                return {'run_id': rid, 'state': row[0], 'submitted': False}
            worker = db.execute('SELECT heartbeat FROM worker WHERE id=1').fetchone()
            if not worker or time.time() - worker[0] > OBSERVATION_STALE_SECONDS:
                raise ValueError('Independent sentaurus-worker is not online')
            self.verify_immutable_inputs(run)
            queued_at = time.time()
            db.execute(
                'UPDATE runs SET state=?,status=? WHERE id=?',
                ('queued', json.dumps({'queued_at': queued_at, 'heartbeat_at': queued_at, 'validation': 'not_reviewed'}), rid),
            )
        return {'run_id': rid, 'state': 'queued', 'submitted': True}

    def launch_queued(self, rid):
        """Worker-only launch path; MCP never creates solver child processes."""
        run = self.get(rid)
        self.verify_immutable_inputs(run)
        token = uuid.uuid4().hex
        submitted_at = time.time()
        status = {
            'launch_token': token,
            'submitted_at': submitted_at,
            'heartbeat_at': submitted_at,
            'launch_worker_pid': os.getpid(),
            'validation': 'not_reviewed',
        }
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT state FROM runs WHERE id=?', (rid,)).fetchone()[0]
            if current != 'queued':
                return {'run_id': rid, 'state': current, 'submitted': False}
            count = db.execute("SELECT count(*) FROM runs WHERE state IN ('starting','running')").fetchone()[0]
            if count >= int(self.config.get('max_parallel', 1)):
                return {'run_id': rid, 'state': 'queued', 'submitted': False, 'reason': 'parallel_limit'}
            db.execute('UPDATE runs SET state=?,status=? WHERE id=?', ('starting', json.dumps(status), rid))
        options = {'start_new_session': True} if os.name != 'nt' else {
            'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        }
        try:
            with (Path(run['directory']) / 'runner.log').open('ab') as log:
                process = subprocess.Popen(
                    [sys.executable, '-m', 'sentaurus_mcp.runner', str(self.config_path), rid, token],
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    close_fds=True,
                    **options,
                )
            self.merge_status(rid, {'runner_pid': process.pid})
        except OSError as exc:
            status.update(error=str(exc), finished_at=time.time())
            self.update(rid, 'failed', status)
            raise
        return {'run_id': rid, 'state': 'starting', 'submitted': True}

    def log(self, rid, stage_index=0, offset=0, limit=8000):
        run = self.get(rid)
        if not 0 <= stage_index < len(run['manifest']['stages']) or offset < 0 or not 1 <= limit <= 16000:
            raise ValueError('Invalid cursor')
        path = Path(run['directory']) / f'stage-{stage_index}.log'
        if not path.exists():
            return {'text': '', 'next_offset': offset, 'available': False}
        with path.open('rb') as stream:
            stream.seek(offset)
            raw = stream.read(limit)
        return {'text': raw.decode('utf-8', 'replace'), 'next_offset': offset + len(raw), 'available': True, 'cursor_unit': 'bytes'}

    def artifacts(self, rid):
        root = Path(self.get(rid)['directory'])
        items = []
        for path in sorted(root.rglob('*')):
            if path.is_symlink() or not path.is_file() or root not in path.resolve().parents:
                continue
            items.append({'name': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size, 'path': str(path)})
            if len(items) >= 1000:
                break
        return {'run_id': rid, 'items': items, 'limit': 1000, 'scope': 'Current files; ongoing writes may be incomplete'}
