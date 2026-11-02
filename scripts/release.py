#!/usr/bin/env python3
"""Skip only a completed, matching release; every URL uses the caller's repository."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from qt_identity import release_identity, validate_inputs


def build_recipe_equal(previous,current):
    # Publication/docs-only commits must not invalidate an already immutable
    # build. Compare actual tracked build inputs, never ignore a recipe change.
    old=previous.get('recipe_commit','');new=current.get('recipe_commit','')
    import re
    if not all(re.fullmatch('[0-9a-f]{40}',v) for v in [old,new]):return False
    if subprocess.run(['git','merge-base','--is-ancestor',old,new],capture_output=True).returncode:return False
    paths=['scripts','container/Containerfile','patches','verification/runtime_paths.py',
           'verification/runtime-path-policy.json','verification/qt_abi.py',
           ':(exclude)scripts/release.py',':(exclude)scripts/publish.sh',':(exclude)scripts/production.py',':(exclude)scripts/check-runtime.sh']
    return subprocess.run(['git','diff','--quiet',old,new,'--',*paths],capture_output=True).returncode==0


def completed(releases,version,sha,inputs,load_inputs):
    for release in releases:
        if release['tag_name']!=version:continue
        expected={f'vlc-{version}-{arch}.tar.zst' for arch in ('x86_64','aarch64')}
        expected|={'SHA256SUMS','sizes.json','inputs.json','build-x86_64.json','build-aarch64.json',
                   'verification-x86_64.json','verification-aarch64.json'}
        assets={a['name']:a for a in release['assets'] if a['size']>0}
        if release['draft'] or not expected<=assets.keys() or sha not in (release['body'] or ''):
            raise ValueError('Existing incomplete or conflicting release; inspect manually, never overwrite')
        previous=load_inputs(assets['inputs.json']['id'])
        if 'qt_abi' in inputs:
            if (release_identity(inputs['qt_abi'])!=inputs['qt_abi_identity']
                    or release_identity(previous.get('qt_abi',{}))!=previous.get('qt_abi_identity')):
                raise ValueError('Invalid release Qt ABI identity')
        for key in ('upstream_sha','artifact_version','qt_abi_identity','source_patches','recipe_sha256'):
            if previous.get(key)!=inputs.get(key):
                if key=='recipe_sha256' and build_recipe_equal(previous,inputs):continue
                raise ValueError('Existing release input conflict: '+key+'; bump packaging revision, never replace assets')
        return True
    return False

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version',help='resolved artifact_version')
    parser.add_argument('sha',help='resolved upstream_sha')
    parser.add_argument('input_path',type=Path,help='the resolved inputs.json file')
    args=parser.parse_args()
    version,sha=args.version,args.sha
    try:
        inputs=json.loads(args.input_path.read_text())
        if inputs['artifact_version']!=version or inputs['upstream_sha']!=sha:
            raise ValueError('artifact version or upstream SHA differs from the resolved input lock')
        if 'qt_abi' in inputs:
            if release_identity(inputs['qt_abi'])!=inputs['qt_abi_identity']:
                raise ValueError('invalid input-lock Qt ABI identity')
            for arch,snapshot in inputs['qt_abi'].items():
                validate_inputs(snapshot,arch,inputs['architectures'][arch])
    except (OSError,ValueError,KeyError,TypeError) as error:
        parser.error(f'invalid input lock {args.input_path}: {error}')
    repository=os.environ.get('GITHUB_REPOSITORY')
    if not repository:parser.error('GITHUB_REPOSITORY is required')
    result=subprocess.check_output(['gh','api','--paginate','--slurp',f'repos/{repository}/releases?per_page=100'])
    releases=[item for page in json.loads(result) for item in page]
    def load(asset):
        return json.loads(subprocess.check_output(['gh','api','-H','Accept: application/octet-stream',
                                                  f'repos/{repository}/releases/assets/{asset}']))
    try:
        build=not completed(releases,version,sha,inputs,load)
    except (ValueError,KeyError,TypeError) as error:
        parser.error(f'release selection failed: {error}')
    print(str(build).lower())
