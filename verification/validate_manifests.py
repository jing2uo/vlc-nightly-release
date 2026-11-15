"""Validate checked-in JSON and required manifest fields without dependencies."""
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {
    'patches/manifest.json': {'schema': int, 'patches': list},
    'verification/fixtures.json': {'url': str, 'sha256': str, 'size': int, 'attribution': str},
    'verification/runtime-path-policy.json': {'schema': int, 'source_sha': str, 'sources': dict, 'recipes': dict},
    'verification/x11-waiver.json': {'id': str, 'enabled': bool, 'effective_from': str,
                                  'expires_at': str, 'architecture': str, 'test': str, 'exit_code': int},
}
PATCH_FIELDS = {key: str for key in ('path', 'source', 'sha256', 'before_sha256',
                                    'after_sha256', 'origin', 'purpose')}


def require(data, fields):
    if not isinstance(data, dict):
        raise ValueError('expected a JSON object')
    for key, kind in fields.items():
        if key not in data or type(data[key]) is not kind:
            raise ValueError(f'{key}: required {kind.__name__}')
        if kind in (str, list, dict) and not data[key]:
            raise ValueError(f'{key}: must not be empty')


def checksum(value, length=64):
    if not isinstance(value, str) or not re.fullmatch(f'[0-9a-f]{{{length}}}', value):
        raise ValueError(f'expected a {length}-character hexadecimal checksum')


def relative_path(value):
    path = Path(value)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise ValueError(f'expected a relative repository path: {value}')


def validate(name, data):
    require(data, FIELDS[name])
    if 'schema' in FIELDS[name] and data['schema'] != 1:
        raise ValueError('unsupported schema')
    if name == 'patches/manifest.json':
        for patch in data['patches']:
            require(patch, PATCH_FIELDS)
            for key in ('path', 'source'):
                relative_path(patch[key])
            for key in ('sha256', 'before_sha256', 'after_sha256'):
                checksum(patch[key])
    elif name == 'verification/fixtures.json':
        checksum(data['sha256'])
        if not data['url'].startswith('https://') or data['size'] <= 0:
            raise ValueError('fixture requires an HTTPS URL and positive size')
    elif name == 'verification/runtime-path-policy.json':
        checksum(data['source_sha'], 40)
        for key in ('sources', 'recipes'):
            for path, sha in data[key].items():
                relative_path(path)
                checksum(sha)
    else:
        start, end = (datetime.fromisoformat(data[key].replace('Z', '+00:00'))
                      for key in ('effective_from', 'expires_at'))
        if start.utcoffset() is None or end.utcoffset() is None or start >= end:
            raise ValueError('waiver requires an ordered, timezone-aware validity window')
        if data['architecture'] not in ('x86_64', 'aarch64') or not 1 <= data['exit_code'] <= 255:
            raise ValueError('invalid waiver architecture or exit code')
        # Expiry is enforced at publication time, not when linting historical policy.


def main():
    tracked = subprocess.check_output(['git', 'ls-files', '-z', '--', '*.json'], cwd=ROOT)
    names = set(tracked.decode().rstrip('\0').split('\0')) - {''}
    if not FIELDS.keys() <= names:
        raise ValueError('missing required manifests: ' + ', '.join(FIELDS.keys() - names))
    for name in sorted(names):
        try:
            data = json.loads((ROOT / name).read_text())
            if name in FIELDS:
                validate(name, data)
        except (OSError, ValueError, TypeError) as error:
            raise ValueError(f'{name}: {error}') from error
        print(f'Validated {name}')


if __name__ == '__main__':
    main()
