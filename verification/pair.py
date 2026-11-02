#!/usr/bin/env python3
"""Fail closed when a native architecture's required verification is absent."""
import hashlib
import json
from pathlib import Path
import sys
from archive import audit, require

REQUIRED = {
    'gnutls-config-overrides', 'sofa-explicit-runtime-data', 'runtime-file-trace', 'runtime-file-paths',
    'relocated-vlc-direct', 'relocated-cvlc-playback', 'relocated-sofa-runtime-data',
    'runtime-path-source-evidence', 'qt-private-abi', 'http-fixture-reachability',
    'platform-namespace-smoke', 'archive-integrity-provenance-safety',
    'archive-negative-tests', 'prepare-sdk', 'fixture-codecs', 'elf-static',
    'temporary-runtime-data-paths', 'platform-symbol-resolution', 'platform-executable-dependencies', 'startup-version',
    'version-matches-inputs', 'plugin-enumeration', 'qml-runtime-imports',
    'decode-h264-aac.mp4', 'decode-vp8-vorbis.webm', 'relocated-startup',
    'relocated-symbol-resolution', 'relocated-playback', 'relocated-cli-alias',
    'http-decode-h264-aac.mp4', 'http-decode-hls-index.m3u8',
    'xcb-gui-openuri-quit-rapid',
    'xcb-qml-window', 'xcb-gui-local-h264', 'xcb-gui-local-webm', 'xcb-gui-local-hls',
    'pulse-playback', 'pulse-audio-output',
    'xcb-mpris-controls', 'xcb-multiple-file-invocation',
}

def verify(directory):
    directory=Path(directory).resolve()
    lock=json.loads((directory/'inputs.json').read_text())
    reports=[];sizes={};sums=[]
    for arch in ('x86_64','aarch64'):
        path=directory/f'vlc-{lock.get("artifact_version",lock["version"])}-{arch}.tar.zst'
        metadata=json.loads((directory/f'build-{arch}.json').read_text())
        actual=audit(path,arch,lock,metadata)
        report=json.loads((directory/f'verification-{arch}.json').read_text())
        require(report['schema']==2 and report['architecture']==arch,'wrong verification architecture/schema')
        for key in ('upstream_sha','version','sha256','size'):
            require(report[key]==(actual[key] if key in actual else lock[key]),f'verification mismatch: {key}')
        require(report['sdk_commit']==lock['architectures'][arch]['sdk_commit'],'SDK verification mismatch')
        require(report['runtime_commit']==lock['architectures'][arch]['platform_commit'],'runtime verification mismatch')
        require(report.get('artifact_version',report['version'])==lock.get('artifact_version',lock['version']),'artifact revision mismatch')
        if 'qt_abi_identity' in lock:
            require(report.get('qt_abi_identity')==lock['qt_abi_identity'],'Qt build identity mismatch')
            qt=report.get('qt_private_abi',{})
            require(qt.get('status')=='pass','missing or incompatible Qt ABI report')
            require(qt.get('compiled_qt_version')==lock['qt_abi'][arch]['sdk']['qt_version'],'wrong compiled Qt version')
            require(qt.get('runtime_qt_version')==lock['qt_abi'][arch]['platform']['qt_version'],'wrong target Qt version')
        if lock.get('packaging_revision',0)>=3:
            require(report.get('source_patches')==lock.get('source_patches') and bool(lock.get('source_patches')),
                    'source patch verification mismatch')
        checks={}
        for check in report['checks']:
            require(check['name'] not in checks,'duplicate verification check')
            checks[check['name']]=check
        require(REQUIRED<=checks.keys(),f'missing mandatory verification: {sorted(REQUIRED-checks.keys())}')
        require(all(checks[n]['mandatory'] and checks[n]['status']=='pass' for n in REQUIRED),'required verification failed')
        require(report['automated_status']=='pass' and all(c['status']=='pass' for c in checks.values() if c['mandatory']),
                'native automated checks incomplete')
        reports.append(report);sizes[path.name]=actual['size'];sums.append(f'{actual["sha256"]}  {path.name}\n')
    require(reports[0]['verification_sha256']==reports[1]['verification_sha256'],'different verification recipes')
    require(set(p.name for p in directory.glob('*.tar.zst'))==set(sizes),'unexpected or partial archive pair')
    (directory/'sizes.json').write_text(json.dumps(sizes,indent=2)+'\n')
    (directory/'SHA256SUMS').write_text(''.join(sums))
    return reports

if __name__=='__main__':
    try:
        verify(sys.argv[1]);print('PASS: both native artifact reports and safe archive namespaces match the shared input lock')
    except Exception as e:
        print('FAIL: '+str(e),file=sys.stderr);raise SystemExit(1)
