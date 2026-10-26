import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

from sentaurus_mcp.reporting import diagnose_run, export_runs
from sentaurus_mcp.service import Service


@pytest.fixture
def archive_service(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'root': str(tmp_path / 'runs'),
                                 'tools': {'demo': [sys.executable, '{input}']}}))
    return Service(config)


def terminal(service, rid='example'):
    run = service.create('project', rid, {'input.py': 'print(1)'},
                         [{'tool': 'demo', 'input_file': 'input.py'}])
    service.update(rid, 'completed', {'stages': [{'index': 0, 'returncode': 0}],
                                      'validation': 'not_reviewed'})
    Path(run['directory'], 'result.plt').write_bytes(b'opaque native result')
    return run


def test_archive_preserves_exact_inputs_and_combines_runs(archive_service):
    terminal(archive_service, 'first')
    terminal(archive_service, 'second')
    result = export_runs(archive_service, ['first', 'second'])
    with zipfile.ZipFile(result['path']) as archive:
        receipt = json.loads(archive.read('export.json'))
        assert len(receipt['runs']) == 2
        for item in receipt['files']:
            assert hashlib.sha256(archive.read(item['name'])).hexdigest() == item['sha256']
        assert archive.read('runs/first/input.py') == b'print(1)'
        assert 'not_numerical_or_physical_acceptance' in receipt['validation']
    assert hashlib.sha256(Path(result['path']).read_bytes()).hexdigest() == result['sha256']


def test_active_and_changed_inputs_cannot_be_exported(archive_service):
    run = terminal(archive_service)
    archive_service.update('example', 'running', {})
    with pytest.raises(ValueError, match='terminal'):
        export_runs(archive_service, ['example'])
    archive_service.update('example', 'completed', {})
    Path(run['directory'], 'input.py').write_text('changed')
    with pytest.raises(ValueError, match='changed'):
        export_runs(archive_service, ['example'])


def test_export_bounds_and_symlinks(archive_service, tmp_path):
    run = terminal(archive_service)
    outside = tmp_path / 'outside.txt'
    outside.write_text('must not enter archive')
    link = Path(run['directory']) / 'outside.txt'
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip('Symlink creation not permitted on this host')
    result = export_runs(archive_service, ['example'])
    assert result['skipped_links_or_nonfiles'] == ['example/outside.txt']
    with zipfile.ZipFile(result['path']) as archive:
        assert 'runs/example/outside.txt' not in archive.namelist()
    with pytest.raises(ValueError, match='exceeds'):
        export_runs(archive_service, ['example'], max_bytes=1)


def test_failed_diagnostics_keep_hints_separate(archive_service):
    run = terminal(archive_service)
    archive_service.update('example', 'failed', {
        'stage_index': 0, 'stages': [{'index': 0, 'returncode': 2}],
        'error': 'Stage 0 exited with 2'})
    Path(run['directory'], 'stage-0.log').write_text('License checkout failed')
    result = diagnose_run(archive_service, 'example')
    assert result['failed_stage']['returncode'] == 2
    assert result['hints'][0]['category'] == 'license'
    assert result['hints'][0]['certainty'] == 'log_hint_only'
    assert result['physical_acceptance'] == 'unverified'
