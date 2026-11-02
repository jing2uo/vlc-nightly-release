"""Exercise the real publication shell against local GH/validator stubs only."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent.parent

class PublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);scripts=self.root/'scripts';scripts.mkdir();self.bin=self.root/'bin';self.bin.mkdir()
        shutil.copy2(ROOT/'scripts/publish.sh',scripts/'publish.sh')
        self.publish=scripts/'publish.sh';self.assets=self.root/'assets';self.assets.mkdir()
        self.version='4.0.0-dev-1-gaaaaaaaaaa-r3-qtbbbbbbbbbbbbbbbb'
        (scripts/'production.py').write_text('print('+repr(self.version)+')\n')
        check=scripts/'verify-artifacts.sh';check.write_text('''#!/bin/bash
set -eu
n=0
if [[ -f $COUNTER ]]; then n=$(cat "$COUNTER"); fi
n=$((n+1)); echo "$n" > "$COUNTER"
if [[ ${EXPIRE:-} == yes && $n == 2 ]]; then echo 'expired waiver' >&2; exit 1; fi
''');check.chmod(0o755)
        for name,value in [('inputs.json',dict(upstream_sha='a'*40)),('verification-pair.json',dict(automated_status='PASS',known_issues=[]))]:
            (self.assets/name).write_text(json.dumps(value))
        sizes={};sums=[];manifest={}
        for arch in ['x86_64','aarch64']:
            name=f'vlc-{self.version}-{arch}.tar.zst';data=arch.encode();(self.assets/name).write_bytes(data)
            sizes[name]=len(data);sums.append(hashlib.sha256(data).hexdigest()+'  '+name+'\n');manifest[arch]=dict(name=name,size=len(data))
        (self.assets/'release.json').write_text(json.dumps(dict(assets=manifest)))
        (self.assets/'sizes.json').write_text(json.dumps(sizes));(self.assets/'SHA256SUMS').write_text(''.join(sums))
        (self.assets/'provenance.intoto.jsonl').write_text('test fixture only')
        for name in ['build-x86_64.json','build-aarch64.json','verification-x86_64.json','verification-aarch64.json','current-runtime.json']:
            (self.assets/name).write_text('{}')
        gh=self.bin/'gh';gh.write_text('''#!/usr/bin/env python3
import os,sys,json,shutil
from pathlib import Path
a=sys.argv[1:]
with open(os.environ['GH_LOG'],'a') as f:f.write(json.dumps(a)+'\\n')
if a[:2]==['attestation','verify'] and os.getenv('BAD_SIGNATURE')=='yes':sys.exit(1)
if a[0]=='api':print('HTTP 404',file=sys.stderr);sys.exit(1)
if a[:2]==['release','create']:
 Path(os.environ['GH_ASSET_LIST']).write_text(json.dumps([x for x in a if Path(x).is_file() and x!='notes.md']))
if a[:2]==['release','download']:
 dest=Path(a[a.index('--dir')+1])
 for n in json.loads(Path(os.environ['GH_ASSET_LIST']).read_text()):
  p=Path(n);shutil.copy2(p,dest/p.name)
 if os.getenv('BAD_DOWNLOAD')=='yes':next(dest.glob('*.tar.zst')).write_bytes(b'tampered')
''');gh.chmod(0o755)
        self.env=dict(os.environ,PATH=str(self.bin)+':'+os.environ['PATH'],VLC_PUBLICATION_APPROVED='production-pair-reviewed',
                      GITHUB_ACTIONS='true',GITHUB_REF='refs/heads/main',GITHUB_REPOSITORY='owner/repository',
                      GITHUB_SHA='b'*40,GITHUB_SERVER_URL='https://github.com',GITHUB_RUN_ID='2',SOURCE_RUN_ID='1',
                      GH_LOG=str(self.root/'gh.log'),GH_ASSET_LIST=str(self.root/'asset-list.json'),COUNTER=str(self.root/'counter'))
    def run_publish(self,**env):
        result=subprocess.run(['bash',str(self.publish),str(self.assets)],env=dict(self.env,**env),capture_output=True,text=True,timeout=10)
        calls=[json.loads(line) for line in (self.root/'gh.log').read_text().splitlines()] if (self.root/'gh.log').exists() else []
        return result,calls
    def test_exact_signed_pair_reaches_publish(self):
        result,calls=self.run_publish();self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(any(c[:2]==['release','edit'] for c in calls))
        self.assertEqual((self.root/'counter').read_text().strip(),'2')
    def test_download_tampering_leaves_draft(self):
        result,calls=self.run_publish(BAD_DOWNLOAD='yes');self.assertNotEqual(result.returncode,0)
        self.assertTrue(any(c[:2]==['release','create'] for c in calls))
        self.assertFalse(any(c[:2]==['release','edit'] for c in calls))
    def test_signature_failure_stops_before_creation(self):
        result,calls=self.run_publish(BAD_SIGNATURE='yes');self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(c[:2]==['release','create'] for c in calls))
    def test_expiry_during_upload_leaves_draft(self):
        result,calls=self.run_publish(EXPIRE='yes');self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(c[:2]==['release','edit'] for c in calls))
    def test_nonmain_or_missing_authorization_never_calls_github(self):
        result,calls=self.run_publish(GITHUB_REF='refs/heads/feature');self.assertNotEqual(result.returncode,0);self.assertEqual(calls,[])

if __name__=='__main__':unittest.main()
