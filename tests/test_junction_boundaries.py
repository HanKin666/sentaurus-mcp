"""Windows junctions are available without the symbolic-link privilege."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sentaurus_mcp.evidence import EvidenceService
from sentaurus_mcp.reporting import export_runs
from sentaurus_mcp.service import Service


pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows junction regression')


def junction(link, target):
    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                            capture_output=True, text=True)
    if result.returncode:
        pytest.skip('Filesystem does not support junction creation')


def test_discovery_never_enters_junction(tmp_path):
    root = tmp_path / 'native'
    outside = tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    (outside / 'gtree.dat').write_text('outside project')
    link = root / 'linked'
    junction(link, outside)
    try:
        assert EvidenceService([root]).projects()['items'] == []
    finally:
        os.rmdir(link)


def test_export_directory_rejects_junction_without_is_junction_api(tmp_path, monkeypatch):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'root': str(tmp_path / 'runs'),
                                 'tools': {'demo': [sys.executable, '{input}']}}))
    service = Service(config)
    service.create('p', 'r', {'input.py': 'pass'}, [{'tool': 'demo', 'input_file': 'input.py'}])
    service.update('r', 'completed', {})
    outside = tmp_path / 'outside'
    outside.mkdir()
    link = service.root / '_exports'
    junction(link, outside)
    # Simulate Python 3.10/3.11, where Path.is_junction is not available.
    monkeypatch.setattr(Path, 'is_junction', lambda self: False, raising=False)
    try:
        with pytest.raises(ValueError, match='must not be linked'):
            export_runs(service, ['r'])
        assert list(outside.iterdir()) == []
    finally:
        os.rmdir(link)
