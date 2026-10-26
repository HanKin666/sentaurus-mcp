import hashlib
import pytest
from sentaurus_mcp.evidence import EvidenceService, parse_plt, figure_spec


def sample(body, close=True):
    return ('DF-ISE text\nInfo { datasets = ["Drain TotalCurrent" "Gate InnerVoltage"] }\nData {\n'
            + body + ('\n}' if close else '')).encode()


def test_names_signs_exponents_and_incremental_write():
    data = parse_plt(sample('-2D-9 3\n4e-6 -5'))
    assert data['columns'] == ['Drain TotalCurrent', 'Gate InnerVoltage']
    assert data['rows'] == [[-2e-9, 3], [4e-6, -5]]
    assert data['units'] is None
    assert parse_plt(sample('1 2\n3 4e', False))['rows'] == [[1, 2]]
    # Valid final prefix must also be withheld until it is delimited.
    assert parse_plt(sample('1 2\n3 4', False))['rows'] == [[1, 2]]
    assert parse_plt(sample('1 2\n3 4\n', False))['rows'] == [[1, 2], [3, 4]]


@pytest.mark.parametrize('body', ['1 2 3', '1 NaN', '1 2x', '1 1e999'])
def test_corrupt_closed_files_rejected(body):
    with pytest.raises(ValueError):
        parse_plt(sample(body))


def test_root_confinement_inventory_and_pagination(tmp_path):
    root = tmp_path / 'native'; root.mkdir()
    project = root / 'device'; project.mkdir()
    (project/'gtree.dat').write_text('native tree fixture')
    (project/'curve.plt').write_bytes(sample('1 2 3 4'))
    service = EvidenceService([root])
    assert service.projects()['items'][0]['relative_path'] == 'device'
    assert service.project(0, 'device')['validation'] == 'not_preprocessed'
    assert service.plt(0, 'device/curve.plt', 1, 1)['rows'] == [[3, 4]]
    with pytest.raises(ValueError): service.plt(0, '../outside.plt')
    with pytest.raises(ValueError): service.plt(0, str(tmp_path/'outside.plt'))
    with pytest.raises(ValueError): service.plt(0, 'device/gtree.dat')
    outside = tmp_path/'outside'; outside.mkdir()
    try: (root/'link').symlink_to(outside, target_is_directory=True)
    except OSError: return
    with pytest.raises(ValueError): service.resolve(0, 'link/curve.plt')


def test_figure_identity_changes_with_recipe():
    h = hashlib.sha256(b'example').hexdigest()
    a = figure_spec('run', h, h, {'cut': 1})
    assert a == figure_spec('run', h, h, {'cut': 1})
    assert a['figure_id'] != figure_spec('run', h, h, {'cut': 2})['figure_id']
    assert a['quality'] == 'unreviewed'
