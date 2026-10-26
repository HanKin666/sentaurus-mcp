"""One-time publisher for the independently reviewed alpha.3 artifacts."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = 'HanKin666/sentaurus-mcp'
TAG = 'v0.1.0-alpha.3'
ALLOWED_ASSETS = {'sentaurus-mcp-0.1.0-alpha.3-source.zip',
                  'sentaurus_batch_mcp-0.1.0a3-py3-none-any.whl',
                  'sentaurus_batch_mcp-0.1.0a3.tar.gz', 'SHA256SUMS.txt'}

def prepare():
    data = json.loads((ROOT / '.release/alpha3-assets.json').read_text(encoding='utf-8-sig'))
    assert data['tag'] == TAG
    for item in data['product_files']:
        path = ROOT / item['path']
        assert path.resolve().is_relative_to(ROOT) and not path.is_symlink()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'], item['path']
    assert {item['name'] for item in data['assets']} == ALLOWED_ASSETS
    destination = ROOT / '_release_assets'
    destination.mkdir(exist_ok=True)
    for item in data['assets']:
        raw = base64.b64decode(item['base64'], validate=True)
        assert len(raw) == item['bytes']
        assert hashlib.sha256(raw).hexdigest() == item['sha256']
        path = destination / item['name']
        path.write_bytes(raw)
    print('Reviewed product and four release assets verified.')
    return data

def request(method, url, payload=None, raw=None):
    assert url.startswith(('https://api.github.com/repos/' + REPOSITORY + '/',
                           'https://uploads.github.com/repos/' + REPOSITORY + '/'))
    body = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
    headers = {'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
               'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
               'User-Agent': 'reviewed-sentaurus-release',
               'Content-Type': 'application/octet-stream' if raw is not None else 'application/json'}
    with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers, method=method), timeout=60) as response:
        return json.load(response)

def publish():
    assert os.environ['GITHUB_REPOSITORY'] == REPOSITORY
    data = prepare()
    api = 'https://api.github.com/repos/' + REPOSITORY
    try:
        existing = request('GET', api + '/releases/tags/' + TAG)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    else:
        if not existing['draft']:
            print('Release already exists; refusing to replace or retag it.')
            return
        raise RuntimeError('Existing draft requires inspection; not overwriting it automatically')
    try:
        ref = request('GET', api + '/git/ref/tags/' + TAG)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    else:
        assert ref['object']['type'] == 'commit' and ref['object']['sha'] == os.environ['GITHUB_SHA'], 'Existing tag targets another commit'
    chinese = (ROOT / 'docs/release-alpha3.md').read_text(encoding='utf-8-sig')
    english = (ROOT / 'docs/release-alpha3.en.md').read_text(encoding='utf-8-sig')
    release = request('POST', api + '/releases', {'tag_name': TAG,
        'target_commitish': os.environ['GITHUB_SHA'],
        'name': 'v0.1.0-alpha.3 · 运行可靠性与实验归档',
        'body': chinese + '\n\n---\n\n' + english,
        'draft': True, 'prerelease': True, 'make_latest': 'false'})
    upload = release['upload_url'].split('{', 1)[0]
    uploaded = []
    for item in data['assets']:
        raw = (ROOT / '_release_assets' / item['name']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item['sha256']
        asset = request('POST', upload + '?name=' + urllib.parse.quote(item['name']), raw=raw)
        assert asset['size'] == len(raw)
        digest = asset.get('digest')
        if digest:
            assert digest == 'sha256:' + item['sha256']
        uploaded.append(asset['name'])
    assert set(uploaded) == ALLOWED_ASSETS
    final = request('PATCH', api + '/releases/' + str(release['id']), {'draft': False, 'prerelease': True})
    print('Published ' + final['html_url'])

if __name__ == '__main__':
    args = argparse.ArgumentParser()
    args.add_argument('--prepare', action='store_true')
    args.add_argument('--publish', action='store_true')
    options = args.parse_args()
    if options.publish:
        publish()
    elif options.prepare:
        prepare()
    else:
        args.error('Choose --prepare or --publish')
