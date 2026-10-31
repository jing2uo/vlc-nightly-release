#!/usr/bin/env python3
"""Inspect real Qt imports/exports using SDK ELF tools; no GUI or compilation."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def qt_symbols(text,undefined):
    result=set()
    for line in text.splitlines():
        parts=line.split()
        if len(parts)<3 or ('*UND*' in parts)!=undefined:continue
        version=parts[-2].strip('()')
        if version.startswith('Qt_'):result.add((version,parts[-1]))
    return result


def validate(required,exports,compiled_version,runtime_version):
    missing=sorted(required-exports)
    private=sorted(x for x in required if 'PRIVATE_API' in x[0])
    failures=[f'unresolved Qt symbol {version}: {name}' for version,name in missing]
    if private and compiled_version!=runtime_version:
        failures.append(f'Qt private ABI build/runtime mismatch: {compiled_version} != {runtime_version}')
    return private,failures


def runtime_library(runtime,arch,name):
    if not runtime.is_dir():raise ValueError('target Platform root is not accessible: '+str(runtime))
    if Path(name).name!=name:raise ValueError('invalid Qt library name: '+name)
    library=runtime/'lib'/f'{arch}-linux-gnu'/name
    if not library.is_file():raise ValueError('target Platform lacks '+name+' at '+str(library))
    resolved=library.resolve(strict=True)
    if not resolved.is_relative_to(runtime.resolve()):
        raise ValueError('Qt library symlink escapes target Platform: '+str(library))
    return resolved


def inspect(payload,runtime,arch,inputs=None,snapshot=None):
    plugins=list(payload.rglob('libqt_plugin.so'))
    if len(plugins)!=1:raise ValueError('expected exactly one actual Qt GUI plugin')
    plugin=plugins[0]
    toolchain=(payload/'share/vlc/build/toolchain.log').read_text()
    versions=re.findall(r'^QT_VERSION:(\S+)$',toolchain,re.M)
    if len(set(versions))!=1:raise ValueError('exact compiled Qt version missing from toolchain provenance')
    compiled=versions[0]
    def output(*argv):return subprocess.check_output(argv,text=True,errors='replace')
    required=qt_symbols(output('objdump','-T',str(plugin)),True)
    needed=re.findall(r'\(NEEDED\).*?\[(libQt6[^\]]+)\]',output('readelf','-dW',str(plugin)))
    exports=set();libraries={};providers={}
    for name in needed:
        library=runtime_library(runtime,arch,name)
        target=library.resolve().name
        match=re.search(r'\.so\.(\d+\.\d+\.\d+)$',target)
        if not match:raise ValueError('cannot determine runtime Qt version: '+target)
        symbols=qt_symbols(output('objdump','-T',str(library)),False)
        exports|=symbols
        with library.open('rb') as stream:raw_sha=hashlib.file_digest(stream,'sha256').hexdigest()
        libraries[name]=dict(version=match[1],target=target,sha256=raw_sha)
        for symbol in required & symbols:providers.setdefault(symbol,[]).append(name)
    runtime_version=libraries['libQt6Core.so.6']['version']
    private,failures=validate(required,exports,compiled,runtime_version)
    expected=snapshot or ((inputs or {}).get('qt_abi',{}).get(arch))
    if expected:
        provenance=json.loads((payload/'share/vlc/build/inputs.json').read_text())
        compiled_context=provenance.get('qt_abi',{}).get(arch)
        if compiled_context:
            if compiled_context['sdk']!=expected['sdk']:failures.append('artifact was compiled with a different private Qt content/header context')
        elif provenance['architectures'][arch]['sdk_commit']!=expected['deployments']['sdk_commit']:
            failures.append('legacy artifact lacks Qt content attestation for this SDK revision')
        for name,definition in expected['platform']['libraries'].items():
            if name not in libraries or libraries[name]['sha256']!=definition.get('sha256'):
                failures.append('actual target Qt contents differ from the resolved identity: '+name)
        if compiled!=expected['sdk']['qt_version']:failures.append('compiled Qt differs from resolved SDK Qt')
        for symbol in private:
            for name in providers.get(symbol,[]):
                sdk=expected['sdk']['libraries'].get(name)
                target=expected['platform']['libraries'].get(name)
                tracked={f'libQt6{x}.so.6' for x in expected['sdk']['private_headers']}
                if name not in tracked or not sdk or not target:failures.append('untracked private Qt provider: '+name)
                elif sdk['version']!=libraries[name]['version'] or sdk['object']!=target['object']:
                    failures.append('private Qt SDK/runtime provider differs: '+name)
    return dict(status='fail' if failures else 'pass',plugin=str(plugin.relative_to(payload)),
                compiled_qt_version=compiled,runtime_qt_version=runtime_version,
                qt_import_count=len(required),private_symbols=[dict(version=v,symbol=n,providers=providers.get((v,n),[])) for v,n in private],
                runtime_libraries=libraries,failures=failures)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--payload',type=Path,required=True)
    p.add_argument('--runtime',type=Path,required=True);p.add_argument('--arch',required=True)
    p.add_argument('--inputs',type=Path);p.add_argument('--snapshot',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    try:result=inspect(a.payload,a.runtime,a.arch,json.loads(a.inputs.read_text()) if a.inputs else None,
                       json.loads(a.snapshot.read_text()) if a.snapshot else None)
    except Exception as e:result=dict(status='fail',failures=[str(e)])
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    raise SystemExit(result['status']!='pass')
