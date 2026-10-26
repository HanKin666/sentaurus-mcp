"""Read-only native evidence shared by MCP clients and private applications.

No dashboard, credentials, vendor libraries or solver processes are imported.
Only ASCII DF-ISE xyplot is supported; TDR remains an opaque native artifact.
"""
import hashlib
import json
import math
import os
import re
from pathlib import Path

MAX_BYTES = 32 * 1024 * 1024
NUMBER = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?\Z')


def parse_plt(raw):
    """Parse complete rows without assuming electrode order or physical units.

    An unterminated final token in an open file is withheld: even a valid float
    prefix could still be in the process of being written. Closed corrupt files
    fail explicitly instead of shifting columns or dropping invalid rows.
    """
    if len(raw) > MAX_BYTES:
        raise ValueError('PLT exceeds 32 MiB read limit')
    text = raw.decode('utf-8-sig')
    if not text.lstrip().startswith('DF-ISE text'):
        raise ValueError('Only ASCII DF-ISE text PLT is supported')
    match = re.search(r'\bData\s*\{', text)
    if not match:
        raise ValueError('Missing Data block')
    header = text[:match.start()]
    declared = re.search(r'\bdatasets\s*=\s*\[(.*?)\]', header, re.S)
    if not declared:
        raise ValueError('Missing datasets header')
    columns = re.findall(r'"([^"\r\n]+)"', declared.group(1))
    remainder = re.sub(r'"[^"\r\n]+"', '', declared.group(1)).strip()
    if remainder or not columns or len(columns) > 4096 or len(set(columns)) != len(columns):
        raise ValueError('Invalid or duplicate dataset names')
    body = text[match.end():]
    closed = '}' in body
    if closed:
        body, suffix = body.split('}', 1)
        if suffix.strip():
            raise ValueError('Unexpected content after Data block')
    tokens = body.split()
    withheld = 0
    if not closed and body and not body[-1].isspace() and tokens:
        tokens.pop()
        withheld = 1
    values = []
    for token in tokens:
        if not NUMBER.fullmatch(token):
            raise ValueError('Invalid numeric token in Data block')
        value = float(token.replace('D', 'E').replace('d', 'e'))
        if not math.isfinite(value):
            raise ValueError('Non-finite PLT value')
        values.append(value)
    trailing = len(values) % len(columns)
    if closed and trailing:
        raise ValueError('Closed PLT contains an incomplete row')
    count = len(values) // len(columns)
    rows = [values[i*len(columns):(i+1)*len(columns)] for i in range(count)]
    return {'columns': columns, 'rows': rows, 'total_rows': count,
            'file_closed': closed, 'withheld_tokens': withheld + trailing,
            'sha256': hashlib.sha256(raw).hexdigest(), 'units': None,
            'quality': 'parsed_records_only_not_physics_acceptance'}


def figure_spec(run_id, source_sha256, image_sha256, recipe, source_path=''):
    """Content-addressed provenance, not a numerical/physical acceptance label."""
    if not run_id or not all(re.fullmatch(r'[a-fA-F0-9]{64}', h) for h in (source_sha256, image_sha256)):
        raise ValueError('A run identity and SHA-256 fingerprints are required')
    payload = {'schema': 'sentaurus-figure-v1', 'run_id': run_id,
               'source_sha256': source_sha256, 'image_sha256': image_sha256,
               'source_path': source_path, 'recipe': recipe,
               'quality': 'unreviewed'}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > 128_000:
        raise ValueError('Figure recipe too large')
    return dict(payload, figure_id=hashlib.sha256(encoded).hexdigest())


class EvidenceService:
    """Operator-selected native roots; independent from the batch run database."""
    def __init__(self, roots):
        self.roots = []
        for root in roots:
            path = Path(root)
            if not path.is_absolute():
                raise ValueError('Native roots must be absolute')
            self.roots.append(path.resolve())

    @classmethod
    def configured(cls):
        path = os.getenv('SENTAURUS_MCP_CONFIG')
        if not path:
            raise ValueError('Set SENTAURUS_MCP_CONFIG with native_roots')
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        return cls(data.get('native_roots', []))

    def resolve(self, root_index, relative_path):
        if not 0 <= root_index < len(self.roots):
            raise ValueError('Unknown native root')
        relative = Path(relative_path)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Use a path relative to the native root')
        root = self.roots[root_index]
        path = (root / relative).resolve()
        if path != root and root not in path.parents:
            raise ValueError('Path escapes native root')
        return path

    def projects(self, root_index=0, relative_path='.', max_depth=2):
        if not 0 <= max_depth <= 4:
            raise ValueError('Depth must be 0..4')
        start = self.resolve(root_index, relative_path)
        queue, items, visited = [(start, 0)], [], 0
        while queue and visited < 2000:
            folder, depth = queue.pop(0)
            visited += 1
            root = self.roots[root_index]
            resolved = folder.resolve()
            if (not folder.is_dir() or folder.is_symlink() or resolved != folder
                    or (resolved != root and root not in resolved.parents)):
                continue
            tree = folder / 'gtree.dat'
            tree_resolved = tree.resolve()
            if tree.is_file() and not tree.is_symlink() and tree_resolved == tree:
                items.append({'relative_path': str(folder.relative_to(self.roots[root_index])),
                              'root_index': root_index, 'kind': 'swb_project_candidate'})
            if depth < max_depth:
                queue.extend((p, depth+1) for p in sorted(folder.iterdir())
                             if p.is_dir() and not p.is_symlink() and p.resolve() == p)
        return {'items': items, 'truncated': bool(queue), 'notice': 'Presence of gtree.dat is not SWB validation'}

    def project(self, root_index, relative_path):
        folder = self.resolve(root_index, relative_path)
        tree = self.resolve(root_index, str((folder / 'gtree.dat').relative_to(self.roots[root_index])))
        if not tree.is_file() or tree.stat().st_size > MAX_BYTES:
            raise ValueError('Missing or oversized gtree.dat')
        raw = tree.read_bytes()
        names = [p.name for p in sorted(folder.iterdir()) if p.is_file() and not p.is_symlink()]
        return {'relative_path': relative_path, 'root_index': root_index,
                'tree_sha256': hashlib.sha256(raw).hexdigest(), 'files': names[:1000],
                'truncated': len(names) > 1000,
                'organization_hint': 'hierarchical_candidate' if (folder/'results').is_dir() else 'unverified',
                'validation': 'not_preprocessed',
                'notice': 'Node numbers are version-local; no tree mutation or solver execution'}

    def plt(self, root_index, relative_path, offset=0, limit=1000):
        if offset < 0 or not 1 <= limit <= 2000:
            raise ValueError('Invalid row pagination')
        path = self.resolve(root_index, relative_path)
        if path.suffix.lower() != '.plt':
            raise ValueError('Expected a .plt file')
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        parsed = parse_plt(raw)
        parsed['rows'] = parsed['rows'][offset:offset+limit]
        parsed.update(offset=offset, next_offset=offset+len(parsed['rows']), source=relative_path)
        return parsed
