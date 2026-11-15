#!/usr/bin/env python3
"""Small release/promotion helpers; artifact validation remains in pair.py."""
import argparse
from datetime import datetime,timezone,date,timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'verification'))
from pair import verify
sys.path.insert(0,str(Path(__file__).resolve().parent))
from qt_identity import release_identity,validate_inputs
from waiver import utc


def api(path):
    headers={'Accept':'application/vnd.github+json','User-Agent':'vlc-nightly-release'}
    if os.getenv('GH_TOKEN'):headers['Authorization']='Bearer '+os.environ['GH_TOKEN']
    with urllib.request.urlopen(urllib.request.Request('https://api.github.com/'+path,headers=headers),timeout=30) as response:
        return json.load(response)


def promotion(run,artifacts,jobs,repository):
    if (run['repository']['full_name']!=repository or run['head_repository']['full_name']!=repository
        or run['head_branch']!='main' or run['event'] not in ('schedule','workflow_dispatch')
        or run['path']!='.github/workflows/build.yml' or run['conclusion']!='success'):
        raise ValueError('Promotion requires a successful trusted main build workflow')
    expected={'resolve','build (x86_64, ubuntu-26.04)','build (aarch64, ubuntu-26.04-arm)','verify'}
    passed={j['name'] for j in jobs if j['conclusion']=='success'}
    if not expected<=passed:raise ValueError('Both native builds and pair verification must have succeeded')
    selected=[a for a in artifacts if a['name']=='release-candidate' and not a['expired']]
    if len(selected)!=1:raise ValueError('Missing/ambiguous/expired release-candidate artifact')
    return selected[0]


def prepare(directory,repository,source_run):
    directory=Path(directory);reports=verify(directory) # Rechecks real UTC waiver expiry.
    lock=json.loads((directory/'inputs.json').read_text())
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):raise ValueError('Invalid repository')
    current=json.loads((directory/'current-runtime.json').read_text())
    if current['schema']!=1:raise ValueError('Invalid current runtime check')
    checked=utc(current['checked_at']);now=datetime.now(timezone.utc)
    if not now-timedelta(hours=2)<=checked<=now:raise ValueError('Current runtime check is stale or from the future')
    for arch in ('x86_64','aarch64'):
        snapshot=current['qt_abi'][arch];validate_inputs(snapshot,arch,snapshot['deployments'])
    if release_identity(current['qt_abi'])!=lock['qt_abi_identity']:raise ValueError('Current Qt identity changed: rebuild required')
    version=lock['artifact_version'];assets={}
    if not re.fullmatch(r'4\.0\.0-dev-\d+-g[0-9a-f]+-r\d+-qt[0-9a-f]{16}',version):raise ValueError('Invalid artifact version')
    for arch in ('x86_64','aarch64'):
        build=json.loads((directory/f'build-{arch}.json').read_text())
        if str(build['workflow_run'])!=str(source_run) or build['repository']!=repository:
            raise ValueError('Candidate does not belong to the approved source workflow/repository')
        if build['recipe_commit']!=lock['recipe_commit']:raise ValueError('Build recipe mismatch')
        name=f'vlc-{version}-{arch}.tar.zst'
        report=next(r for r in reports if r['architecture']==arch)
        assets[arch]=dict(name=name,sha256=report['sha256'],size=report['size'],
                         url=f'https://github.com/{repository}/releases/download/{version}/{name}',
                         verification=report['automated_status'].upper())
    summary=json.loads((directory/'verification-pair.json').read_text())
    result=dict(schema=1,channel='production',version=version,repository=repository,
                upstream_sha=lock['upstream_sha'],qt_abi_identity=lock['qt_abi_identity'],
                source_recipe_commit=lock['recipe_commit'],source_run_id=str(source_run),
                publication_run_id=os.getenv('GITHUB_RUN_ID','local'),
                runtime='org.kde.Platform//6.11',sdk='org.kde.Sdk//6.11',
                automated_status=summary['automated_status'],known_issues=summary['known_issues'],
                current_runtime=current,attestation_required=True,assets=assets)
    (directory/'release.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def latest_production(releases,repository,load):
    for rel in sorted(releases,key=lambda r:r.get('published_at') or '',reverse=True):
        version=rel.get('tag_name','')
        if rel.get('draft') or not re.fullmatch(r'4\.0\.0-dev-\d+-g[0-9a-f]+-r\d+-qt[0-9a-f]{16}',version):continue
        expected=f'https://github.com/{repository}/releases/download/{version}/release.json'
        asset=[a for a in rel['assets'] if a['name']=='release.json' and a['browser_download_url']==expected]
        if len(asset)!=1:continue
        data=load(expected)
        if (data.get('channel')=='production' and data.get('repository')==repository and data.get('version')==version
                and data.get('automated_status') in ('PASS','WAIVED') and re.fullmatch('[0-9a-f]{40}',data.get('upstream_sha',''))):
            return data
    return None


def scheduled_pin(releases,repository,today,load):
    if ((today-date(2026,11,2)).days//7)%2==0:return ''
    data=latest_production(releases,repository,load)
    return data['upstream_sha'] if data else '' # Initialize on the weekly schedule.


def runtime_baseline(releases,repository,load,directory):
    data=latest_production(releases,repository,load)
    if data is None:raise ValueError('No production baseline; initialize with the normal build workflow')
    if not re.fullmatch('[0-9a-f]{64}',data.get('qt_abi_identity','')):
        raise ValueError('Production release lacks a Qt content identity')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    (directory/'inputs.json').write_text(json.dumps(data,indent=2)+'\n')
    print('Runtime watcher baseline: '+data['version']+'; source: '+data['upstream_sha'],file=sys.stderr)
    return data['upstream_sha']


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['promotion','prepare','schedule','runtime-baseline']);p.add_argument('value',nargs='?')
    p.add_argument('--repository',default=os.getenv('GITHUB_REPOSITORY'));p.add_argument('--source-run',default=os.getenv('SOURCE_RUN_ID'))
    a=p.parse_args()
    try:
        if a.mode=='promotion':
            if not a.value or not a.value.isdecimal():raise ValueError('Positive workflow run ID required')
            base=f'repos/{a.repository}/actions/runs/{a.value}'
            run=api(base);artifact=promotion(run,api(base+'/artifacts')['artifacts'],api(base+'/jobs?per_page=100')['jobs'],a.repository)
            subprocess.run(['git','merge-base','--is-ancestor',run['head_sha'],'HEAD'],check=True)
            print(artifact['id'])
        elif a.mode=='prepare':print(prepare(a.value,a.repository,a.source_run)['version'])
        else:
            # Weekly polling; every second Monday selects a new VLC snapshot.
            # Off-weeks retain the latest production source but resolve current
            # SDK/Qt identities so an ABI change can trigger an urgent rebuild.
            releases=api(f'repos/{a.repository}/releases?per_page=100')
            def load(url):
                with urllib.request.urlopen(url,timeout=30) as response:return json.load(response)
            if a.mode=='runtime-baseline':print(runtime_baseline(releases,a.repository,load,a.value))
            else:print(scheduled_pin(releases,a.repository,datetime.now(timezone.utc).date(),load))
    except Exception as error:p.exit(1,'Release eligibility failed: '+str(error)+'\n')
