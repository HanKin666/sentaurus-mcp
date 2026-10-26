"""Bounded diagnostics and explicit, reproducible export of terminal batch runs."""
import hashlib
import json
import os
import tempfile
import time
import zipfile
from pathlib import Path


def diagnose_run(service, run_id):
    run = service.get(run_id)
    folder = Path(run['directory'])
    index = run['status'].get('stage_index', 0)
    log = folder / f'stage-{index}.log'
    excerpt = ''
    if log.is_file() and not log.is_symlink():
        with log.open('rb') as stream:
            stream.seek(max(0, log.stat().st_size - 12000))
            excerpt = stream.read(12000).decode('utf-8', 'replace')
    hints = []
    lower = excerpt.lower()
    for label, patterns in (
        ('license', ('license checkout failed', 'license denied', 'cannot obtain license')),
        ('numerical_convergence', ('convergence failure', 'failed to converge', 'step-size is too small')),
        ('input_or_path', ('no such file', 'cannot open file', 'syntax error')),
        ('memory', ('out of memory', 'cannot allocate memory')),
    ):
        matches = [pattern for pattern in patterns if pattern in lower]
        if matches:
            hints.append({'category': label, 'matched_text': matches, 'certainty': 'log_hint_only'})
    return {
        'run_id': run_id, 'collected_at': time.time(), 'stored_state': run['state'],
        'observation': run.get('observation', {}),
        'failed_stage': next((s for s in run['status'].get('stages', [])
                              if s.get('returncode') not in (None, 0)), None),
        'error': run['status'].get('error'), 'hints': hints,
        'failure': run['status'].get('failure'),
        'output_validation': run['status'].get('output_validation', {'status': 'unverified'}),
        'log': {'path': str(log), 'tail': excerpt, 'max_bytes': 12000},
        'next_action': ('Inspect observation and latest accepted state before preparing a new run; '
                        'never infer a physical breakdown voltage from the last solved point.'),
        'numerical_acceptance': 'unverified', 'physical_acceptance': 'unverified',
    }


def _signature(path):
    return _stat_signature(path.stat())


def _stat_signature(stat):
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino


def _opened_matches(stream, signature):
    # Windows path.stat and fstat expose different ctime semantics on some Python
    # versions. Compare the opened identity, size and mtime; keep path ctime in
    # the before/after path checks separately.
    stat = os.fstat(stream.fileno())
    return (stat.st_size, stat.st_mtime_ns, stat.st_ino) == (signature[0], signature[1], signature[3])


def export_runs(service, run_ids, max_bytes=512 * 1024 * 1024):
    """Only archive terminal runs. Stream files and reject changes during export.

    Exports live below root/_exports, never in a solver directory. This is a batch
    archive, not SWB project generation or scientific qualification.
    """
    if not run_ids or len(run_ids) > 20 or len(set(run_ids)) != len(run_ids):
        raise ValueError('Select 1..20 distinct run IDs')
    runs = [service.get(rid) for rid in run_ids]
    if any(run['state'] not in ('completed', 'failed') for run in runs):
        raise ValueError('Only terminal runs can be exported; active runs may change')
    files, skipped, total = [], [], 0
    for run in runs:
        folder = Path(run['directory'])
        manifest_path = folder / 'manifest.json'
        if manifest_path.is_symlink() or json.loads(manifest_path.read_text(encoding='utf-8')) != run['manifest']:
            raise ValueError('Manifest changed; cannot verify provenance')
        for name, expected in run['manifest']['input_sha256'].items():
            path = folder / name
            if path.is_symlink() or not path.is_file():
                raise ValueError('Input missing or linked; cannot verify provenance')
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('Input changed after preparation; cannot export as reproducible')
        for directory, dirs, names in os.walk(folder, followlinks=False):
            for name in list(dirs):
                path = Path(directory) / name
                if path.resolve() != path or path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
                    skipped.append(f"{run['run_id']}/{path.relative_to(folder).as_posix()}")
                    dirs.remove(name)
            for name in sorted(names):
                path = Path(directory) / name
                if path.is_symlink() or not path.is_file() or folder not in path.resolve().parents:
                    skipped.append(f"{run['run_id']}/{path.relative_to(folder).as_posix()}")
                    continue
                sig = _signature(path)
                total += sig[0]
                if total > max_bytes or len(files) >= 10000:
                    raise ValueError('Export exceeds 512 MiB or 10000 files; use a smaller selection')
                files.append((run, path, sig))
    destination = service.root / '_exports'
    destination.mkdir(exist_ok=True)
    if destination.resolve() != destination or destination.is_symlink() or getattr(destination, 'is_junction', lambda: False)():
        raise ValueError('Export directory must not be linked')
    handle, temporary = tempfile.mkstemp(prefix='batch-', suffix='.tmp', dir=destination)
    os.close(handle)
    archive = Path(temporary).with_suffix('.zip')
    records = []
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as output:
            for run, path, sig in files:
                if path.is_symlink() or _signature(path) != sig:
                    raise ValueError('File changed before export')
                digest = hashlib.sha256()
                name = f"runs/{run['run_id']}/{path.relative_to(run['directory']).as_posix()}"
                size = 0
                with path.open('rb') as source, output.open(name, 'w') as target:
                    if not _opened_matches(source, sig):
                        raise ValueError('Opened file identity changed during export')
                    while chunk := source.read(1024 * 1024):
                        size += len(chunk)
                        if size > sig[0]:
                            raise ValueError('File grew during export')
                        target.write(chunk)
                        digest.update(chunk)
                    if not _opened_matches(source, sig):
                        raise ValueError('Opened file changed during export')
                if size != sig[0] or _signature(path) != sig:
                    raise ValueError('File changed during export')
                relative = path.relative_to(run['directory']).as_posix()
                expected = run['manifest']['input_sha256'].get(relative)
                if expected and digest.hexdigest() != expected:
                    raise ValueError('Input changed during export')
                if relative == 'manifest.json':
                    # Archive bytes must describe the same frozen run as export.json.
                    with output.open(name) as manifest_stream:
                        if json.load(manifest_stream) != run['manifest']:
                            raise ValueError('Manifest changed during export')
                records.append({'name': name, 'bytes': size, 'sha256': digest.hexdigest()})
            receipt = {'schema': 'sentaurus-export-v1', 'created_at': time.time(),
                       'runs': runs, 'files': records, 'skipped_links_or_nonfiles': skipped,
                       'validation': 'archived_bytes_only_not_numerical_or_physical_acceptance'}
            output.writestr('export.json', json.dumps(receipt, indent=2, ensure_ascii=False))
            output.writestr('README.txt',
                'Native batch archive. See export.json for input hashes, commands, stage exit codes, '
                'timing and observation. Configure compatible Sentaurus tools and licenses on the '
                'target host before rerunning the recorded stage argv in its run folder. '
                'This archive does not create a Sentaurus Workbench project. Failed runs remain failed. '
                'Numerical and physical acceptance require independent review.\n')
        os.replace(temporary, archive)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
    digest = hashlib.sha256()
    with archive.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return {'path': str(archive), 'bytes': archive.stat().st_size,
            'sha256': digest.hexdigest(), 'run_ids': run_ids, 'files': len(records),
            'skipped_links_or_nonfiles': skipped, 'collected_at': time.time()}
