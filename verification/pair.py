#!/usr/bin/env python3
"""Fail closed when a native architecture's required verification is absent."""
import hashlib
import json
from pathlib import Path
import sys
from archive import audit, require
from waiver import evaluate,utc

# One release policy shared by the native runner and pair validation.
# Advanced diagnostics are retained, but are never release prerequisites.
REQUIRED = {
    'platform-namespace-smoke', 'archive-integrity-provenance-safety',
    'archive-negative-tests', 'prepare-sdk', 'fixture-codecs', 'elf-static',
    'runtime-path-source-evidence', 'temporary-runtime-data-paths',
    'qt-private-abi', 'platform-symbol-resolution',
    'platform-executable-dependencies', 'startup-version',
    'version-matches-inputs', 'plugin-enumeration', 'decode-h264-aac.mp4',
}


def verify(directory):
    directory=Path(directory).resolve()
    lock=json.loads((directory/'inputs.json').read_text())
    # A failed re-evaluation must not leave an older WAIVED summary active.
    (directory/'verification-pair.json').write_text(json.dumps(dict(automated_status='FAIL',known_issues=[],release_ready=False))+'\n')
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
        decision=evaluate(report,REQUIRED,directory)
        require(decision['outcome'] in ('PASS','WAIVED'),'required verification failed: '+decision['reason'])
        require(report['automated_status']==decision['outcome'].lower(),'native automated decision mismatch')
        if decision['outcome']=='WAIVED':
            require(report.get('automated_decision',{}).get('outcome')=='WAIVED','missing recorded waiver decision')
            stored=report.get('automated_decision',{}).get('waiver',{})
            current=decision['waiver']
            require(all(stored.get(k)==v for k,v in current.items() if k!='evaluated_at'),
                    'waiver evidence or policy mismatch')
            require('evaluated_at' in stored and utc(current['effective_from'])<=utc(stored['evaluated_at'])
                    <=utc(current['evaluated_at'])<utc(current['expires_at']), 'invalid waiver evaluation time')
        reports.append(report);sizes[path.name]=actual['size'];sums.append(f'{actual["sha256"]}  {path.name}\n')
    require(reports[0]['verification_sha256']==reports[1]['verification_sha256'],'different verification recipes')
    require(set(p.name for p in directory.glob('*.tar.zst'))==set(sizes),'unexpected or partial archive pair')
    waived=[r['automated_decision']['waiver'] for r in reports if r['automated_status']=='waived']
    summary=dict(automated_status='WAIVED' if waived else 'PASS',known_issues=waived,release_ready=False)
    (directory/'verification-pair.json').write_text(json.dumps(summary,indent=2)+'\n')
    (directory/'sizes.json').write_text(json.dumps(sizes,indent=2)+'\n')
    (directory/'SHA256SUMS').write_text(''.join(sums))
    return reports

if __name__=='__main__':
    try:
        verify(sys.argv[1]);summary=json.loads((Path(sys.argv[1])/'verification-pair.json').read_text());print(summary['automated_status']+': both native artifacts evaluated; publication authorization remains separate')
    except Exception as e:
        print('FAIL: '+str(e),file=sys.stderr);raise SystemExit(1)
