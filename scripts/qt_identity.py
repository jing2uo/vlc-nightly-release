#!/usr/bin/env python3
"""Qt content identities from signed Flatpak OSTree metadata, without SDK execution or deployment."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

LIBRARIES=('Core','Gui','Quick','Qml')
# gui-private/quick-private also inherit Core/Qml private headers.
PRIVATE_HEADERS=LIBRARIES

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def identity(snapshot):
    return digest({key:snapshot[key] for key in ('architecture','sdk','platform')})

def release_identity(snapshots):
    if set(snapshots)!={'x86_64','aarch64'}:raise ValueError('both native target Qt identities are required')
    return digest({arch:identity(value) for arch,value in snapshots.items()})

def artifact_version(version,revision,snapshots):
    return f'{version}-r{revision}-qt{release_identity(snapshots)[:16]}'

def validate_snapshot(snapshot):
    if set(snapshot['sdk']['private_headers'])!=set(PRIVATE_HEADERS):
        raise ValueError('incomplete Qt private-header identity')
    for name in snapshot['sdk']['libraries']:
        if snapshot['sdk']['libraries'][name]['version']!=snapshot['platform']['libraries'][name]['version']:
            raise ValueError('SDK/Platform Qt version mismatch: '+name)
    for component in PRIVATE_HEADERS:
        name=f'libQt6{component}.so.6'
        if snapshot['sdk']['libraries'][name]['object']!=snapshot['platform']['libraries'][name]['object']:
            raise ValueError('private Qt SDK/Platform build mismatch: '+name)


def validate_inputs(snapshot,arch,pins):
    validate_snapshot(snapshot)
    if snapshot['architecture']!=arch or snapshot['deployments']!=pins:
        raise ValueError('Qt identity does not describe the resolved SDK/Platform pins')
    if snapshot.get('identity')!=identity(snapshot):
        raise ValueError('Qt identity checksum mismatch')


def library_target(soname,row):
    # Accept only the SDK's adjacent, versioned library. Never follow an
    # absolute/escaping link, a link chain or a path in the host filesystem.
    if len(row)<8 or not row[0].startswith('l') or row[-2]!='->':
        raise ValueError('expected Qt SONAME symlink: '+soname)
    target=row[-1]
    match=re.fullmatch(re.escape(soname)+r'\.(\d+\.\d+)',target)
    if not match:raise ValueError('unrecognized or unsafe Qt library target: '+target)
    return target,'6.'+match[1]


def collect(repo,arch,sdk,platform,pull=False):
    def command(*args):
        argv=['ostree','--repo='+str(repo),*args]
        try:
            return subprocess.check_output(argv,text=True,stderr=subprocess.PIPE).strip()
        except subprocess.CalledProcessError as error:
            raise RuntimeError(f'OSTree command failed (exit {error.returncode}): {argv!r}\n{error.stderr}') from error
    def entry(commit,path):
        row=command('ls','-Cd',commit,path).split()
        if len(row)<6 or not re.fullmatch('[0-9a-f]{64}',row[4]):raise ValueError('invalid OSTree file identity')
        return row
    def anchor(commit,path):
        if pull:
            version=subprocess.check_output(['flatpak','--version'],text=True).split()[-1]
            command('pull','--disable-static-deltas','--subpath='+path,
                    '--http-header=User-Agent=flatpak/'+version,'flathub',commit)
    def component(commit,headers):
        # Directory metadata lists siblings, but does not fetch their symlink
        # content objects. Fetch each SONAME before asking OSTree for its target.
        # Only four Qt libraries and four config headers are fetched;
        # the shared OSTree store reuses these objects during native SDK install.
        libraries={}
        for name in LIBRARIES:
            soname=f'libQt6{name}.so.6';path=f'/files/lib/{arch}-linux-gnu/{soname}'
            anchor(commit,path)
            link=entry(commit,path)
            target,version=library_target(soname,link)
            target_path=str(Path(path).parent/target)
            anchor(commit,target_path)
            target_entry=entry(commit,target_path)
            if not target_entry[0].startswith('-'):raise ValueError('Qt library target must be a regular file: '+target_path)
            process=subprocess.Popen(['ostree','--repo='+str(repo),'cat',commit,target_path],stdout=subprocess.PIPE)
            with process.stdout as stream:raw_sha=hashlib.file_digest(stream,'sha256').hexdigest()
            if process.wait()!=0:raise ValueError('cannot hash Qt library contents')
            libraries[soname]=dict(target=target,version=version,object=target_entry[4],sha256=raw_sha)
        private_headers={}
        if headers:
            for name in PRIVATE_HEADERS:
                version=libraries[f'libQt6{name}.so.6']['version']
                directory=f'/files/include/Qt{name}/{version}/Qt{name}/private'
                anchor(commit,directory+f'/qt{name.lower()}-config_p.h')
                private_headers[name]=entry(commit,directory)[4]
        return dict(qt_version=libraries['libQt6Core.so.6']['version'],libraries=libraries,private_headers=private_headers)
    result=dict(schema=1,architecture=arch,deployments=dict(sdk_commit=sdk,platform_commit=platform),
                sdk=component(sdk,True),platform=component(platform,False))
    validate_snapshot(result)
    result['identity']=identity(result)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True)
    p.add_argument('--arch',choices=['x86_64','aarch64'],required=True)
    p.add_argument('--sdk',required=True);p.add_argument('--platform',required=True)
    p.add_argument('--check-inputs',type=Path);p.add_argument('--pull',action='store_true');p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=collect(a.repo,a.arch,a.sdk,a.platform,a.pull)
    if a.check_inputs:
        inputs=json.loads(a.check_inputs.read_text());validate_inputs(result,a.arch,inputs['architectures'][a.arch])
        if identity(result)!=identity(inputs['qt_abi'][a.arch]):raise ValueError('deployed Qt differs from resolved build inputs')
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(result['identity'])
