#!/usr/bin/env python3
"""Small provenance helpers. No dependency resolver or external Python packages."""
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shlex
import subprocess
import sys
import time


ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'verification'))
from source_patches import identity as patch_identity
from runtime_paths import collect_evidence, evidence_matches, hash_drift
from qt_identity import artifact_version, release_identity, validate_inputs

PACKAGING_REVISION = 4


def git(*args):
    return subprocess.check_output(['git', '-C', '/work/source', *args], text=True).strip()


def digest_recipe():
    h = hashlib.sha256()
    root = Path(__file__).resolve().parent.parent
    for p in sorted((root/'scripts').glob('*')):
        if p.is_file():
            h.update(p.name.encode() + b'\0' + p.read_bytes())
    for p in sorted((root/'patches').glob('*')):
        if p.is_file():h.update(p.name.encode()+b'\0'+p.read_bytes())
    h.update((root/'container/Containerfile').read_bytes())
    for name in ('runtime_paths.py','runtime-path-policy.json','qt_abi.py'):
        h.update(name.encode()+b'\0'+(root/'verification'/name).read_bytes())
    return h.hexdigest()


mode, filename, *args = sys.argv[1:]
p = Path(filename)
if mode == 'time':
    start = time.monotonic()
    result = subprocess.run(args)
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    p.write_text(json.dumps(dict(elapsed_seconds=time.monotonic() - start,
                                max_rss_kib=usage.ru_maxrss,
                                user_seconds=usage.ru_utime,
                                system_seconds=usage.ru_stime,
                                exit_code=result.returncode), indent=2) + '\n')
    sys.exit(result.returncode if result.returncode >= 0 else 128 - result.returncode)
elif mode == 'recipe':
    print(digest_recipe())
elif mode == 'repackage':
    d=json.loads(p.read_text())
    assert evidence_matches(d.get('runtime_path_evidence'),d['upstream_sha'],
                            collect_evidence('/work/source',d['upstream_sha'],ROOT)), 'Runtime-path evidence differs from pinned build inputs'
    assert d.get('source_patches')==patch_identity('/work/source',d['upstream_sha']), 'Rebuild VLC: historical binaries lack the current source patch provenance'
    d.update(artifact_version=artifact_version(d['version'],PACKAGING_REVISION,d['qt_abi']) if 'qt_abi' in d else d['version']+f'-r{PACKAGING_REVISION}',
             packaging_revision=PACKAGING_REVISION,recipe_sha256=digest_recipe())
    Path(args[0]).write_text(json.dumps(d,indent=2)+'\n')
elif mode == 'resolve':
    data = dict(upstream_sha=os.environ['VLC_SHA'], version=os.environ['VLC_VERSION'],
                packaging_revision=PACKAGING_REVISION,
                sdk='org.kde.Sdk//6.11', runtime='org.kde.Platform//6.11',
                source_url='https://code.videolan.org/videolan/vlc.git',
                source_epoch=int(git('show', '-s', '--format=%ct', 'HEAD')),
                deps_epoch=int(git('log', '-1', '--format=%ct', 'HEAD', '--', 'contrib', 'extras/tools')),
                recipe_sha256=digest_recipe(), recipe_commit=os.getenv('GITHUB_SHA', 'local'),
                contrib_recipe_sha256=hashlib.sha256(Path('/recipe/scripts/contrib.sh').read_bytes()).hexdigest(),
                contrib_tree=git('rev-parse', 'HEAD:contrib'),
                tools_tree=git('rev-parse', 'HEAD:extras/tools'), architectures={})
    for arch in ('x86_64', 'aarch64'):
        pins = {name.lower() + '_commit': Path(f'/work/{name}-{arch}.commit').read_text().strip()
                for name in ('Sdk', 'Platform')}
        assert all(re.fullmatch('[0-9a-f]{64}', value) for value in pins.values())
        data['architectures'][arch] = pins
    assert data['upstream_sha']==git('rev-parse','HEAD'), 'Source checkout differs from resolved SHA'
    data['source_patches']=patch_identity('/work/source',data['upstream_sha'])
    evidence=collect_evidence('/work/source',data['upstream_sha'],ROOT)
    assert evidence_matches(evidence,data['upstream_sha']), 'Invalid runtime-path input evidence'
    print('INFO: runtime-path hash drift: '+json.dumps(hash_drift(evidence),sort_keys=True),file=sys.stderr)
    data['runtime_path_evidence']=evidence
    data['qt_abi']={arch:json.loads(Path(f'/work/qt-{arch}.json').read_text()) for arch in data['architectures']}
    for arch in data['architectures']:validate_inputs(data['qt_abi'][arch],arch,data['architectures'][arch])
    data['qt_abi_identity']=release_identity(data['qt_abi'])
    data['artifact_version']=artifact_version(data['version'],PACKAGING_REVISION,data['qt_abi'])
    p.write_text(json.dumps(data, indent=2) + '\n')
elif mode == 'check':
    d = json.loads(p.read_text())
    assert d['recipe_sha256'] == digest_recipe(), 'Recipe differs from resolved inputs; resolve again'
    assert d['upstream_sha'] == git('rev-parse', 'HEAD')
    assert d['source_patches']==patch_identity('/work/source',d['upstream_sha']), 'Source patch identity mismatch'
    assert evidence_matches(d.get('runtime_path_evidence'),d['upstream_sha'],
                            collect_evidence('/work/source',d['upstream_sha'],ROOT)), 'Runtime-path evidence differs from pinned build inputs'
    assert d['qt_abi_identity']==release_identity(d['qt_abi'])
    for arch in d['architectures']:validate_inputs(d['qt_abi'][arch],arch,d['architectures'][arch])
    assert d['contrib_tree'] == git('rev-parse', 'HEAD:contrib')
    assert d['tools_tree'] == git('rev-parse', 'HEAD:extras/tools')
    assert d['contrib_recipe_sha256'] == hashlib.sha256(Path('/recipe/scripts/contrib.sh').read_bytes()).hexdigest()
elif mode == 'env':
    d = json.loads(p.read_text())
    arch = args[0]
    pins = d['architectures'][arch]
    key = hashlib.sha256(json.dumps([arch, d['sdk'], pins, d['contrib_tree'],
                                   d['tools_tree'], d['deps_epoch'], d['contrib_recipe_sha256']], sort_keys=True).encode()).hexdigest()
    for name, value in dict(VLC_SHA=d['upstream_sha'], VERSION=d['version'],
                            ARTIFACT_VERSION=d.get('artifact_version',d['version']), SDK_COMMIT=pins['sdk_commit'], RUNTIME_COMMIT=pins['platform_commit'],
                            SOURCE_DATE_EPOCH=d['source_epoch'], DEPS_SOURCE_DATE_EPOCH=d['deps_epoch'], CACHE_KEY=key).items():
        print(f'{name}={shlex.quote(str(value))}')
elif mode == 'build':
    d = json.loads(p.read_text())
    arch, cache_key, cache_hit, destination = args
    assert evidence_matches(d.get('runtime_path_evidence'),d['upstream_sha'],
                            collect_evidence('/work/source',d['upstream_sha'],ROOT)), 'Runtime-path evidence differs from pinned build inputs'
    d.update(architecture=arch, cache_key=cache_key, cache_reused=cache_hit == 'true',
             workflow_run=os.getenv('GITHUB_RUN_ID', 'local'),
             repository=os.getenv('GITHUB_REPOSITORY', 'local'))
    d['qt_gui']=json.loads(Path('/work/logs/qt-abi.json').read_text())
    assert d['qt_gui']['status']=='pass', 'Qt ABI verification failed'
    Path(destination).write_text(json.dumps(d, indent=2) + '\n')
else:
    raise SystemExit(f'Unknown operation: {mode}')
