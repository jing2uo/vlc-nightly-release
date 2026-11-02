#!/usr/bin/env python3
"""Exact, auditable downstream patch identities; no arbitrary dirty source accepted."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parent.parent


def digest(data):return hashlib.sha256(data).hexdigest()


def identity(source,sha,root=ROOT):
    source=Path(source);root=Path(root)
    manifest=json.loads((root/'patches/manifest.json').read_text())
    if manifest['schema']!=1:raise ValueError('Unknown source patch schema')
    seen=set()
    for patch in manifest['patches']:
        name=patch['source']
        if Path(name).is_absolute() or '..' in Path(name).parts or name in seen:
            raise ValueError('Unsafe/duplicate patched source path')
        seen.add(name)
        path=root/patch['path']
        if not path.resolve().is_relative_to((root/'patches').resolve()):
            raise ValueError('Patch path outside patches directory')
        if digest(path.read_bytes())!=patch['sha256']:raise ValueError('Patch checksum mismatch')
        before=subprocess.check_output(['git','-C',str(source),'show',sha+':'+name])
        if digest(before)!=patch['before_sha256']:raise ValueError('Upstream patched source changed; review required')
        # Validate the whole diff and postimage in a disposable directory, never
        # modify the actual upstream checkout while resolving inputs.
        with tempfile.TemporaryDirectory() as directory:
            dest=Path(directory)/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(before)
            subprocess.run(['git','apply','--check',str(path.resolve())],cwd=directory,check=True,capture_output=True)
            subprocess.run(['git','apply',str(path.resolve())],cwd=directory,check=True,capture_output=True)
            files=[p.relative_to(directory).as_posix() for p in Path(directory).rglob('*') if p.is_file()]
            if files!=[name] or digest(dest.read_bytes())!=patch['after_sha256']:
                raise ValueError('Unexpected patch postimage/files')
    return dict(schema=1,base_sha=sha,patches=manifest['patches'])


def verify(source,expected):
    # Exact expected changes plus only the generated gettext catalogs handled
    # separately by build.sh. Never accept arbitrary edits in a patched file.
    allowed={p['source']:p['after_sha256'] for p in expected['patches']}
    names=subprocess.check_output(['git','-C',str(source),'diff','--name-only','HEAD','--'],text=True).splitlines()
    if set(names)!=set(allowed):raise ValueError('Unexpected or missing tracked source patch')
    for name,checksum in allowed.items():
        if digest((Path(source)/name).read_bytes())!=checksum:raise ValueError('Patched source modified: '+name)


def apply(source,sha,expected,root=ROOT):
    if identity(source,sha,root)!=expected:raise ValueError('Source patch inputs mismatch')
    subprocess.run(['git','-C',str(source),'diff','--exit-code','HEAD','--'],check=True,capture_output=True)
    # Validate the complete series before modifying the source checkout.
    paths=[str(Path(root)/p['path']) for p in expected['patches']]
    subprocess.run(['git','-C',str(source),'apply','--check',*paths],check=True)
    subprocess.run(['git','-C',str(source),'apply',*paths],check=True)
    verify(source,expected)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['apply','restore'])
    parser.add_argument('source',type=Path);parser.add_argument('inputs',type=Path)
    a=parser.parse_args();lock=json.loads(a.inputs.read_text())
    expected=lock['source_patches'];sha=lock['upstream_sha']
    if a.mode=='apply':apply(a.source,sha,expected)
    else:
        if identity(a.source,sha)!=expected:raise ValueError('Source patch inputs mismatch')
        verify(a.source,expected)
        subprocess.run(['git','-C',str(a.source),'restore','--source='+sha,'--worktree','--',
                        *[p['source'] for p in expected['patches']]],check=True)
