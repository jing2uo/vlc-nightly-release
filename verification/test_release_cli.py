"""Exercise the workflow's actual resolve shell block without network or SDKs."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from qt_identity import artifact_version, identity, release_identity


class ReleaseCLI(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'scripts').mkdir()
        (self.root/'work').mkdir()
        for name in ['release.py','qt_identity.py']:
            shutil.copyfile(ROOT/'scripts'/name,self.root/'scripts'/name)
        self.lock=self.fixture()
        self.input=self.root/'work/inputs.json'
        self.input.write_text(json.dumps(self.lock))
        gh=self.root/'gh'
        gh.write_text('#!'+sys.executable+'''\nimport json,os,sys
with open(os.environ['API_LOG'],'a') as log: log.write(json.dumps(sys.argv[1:])+'\\n')
data=json.load(open(os.environ['GH_RESPONSES']))
print(json.dumps(data['asset'] if '/releases/assets/' in sys.argv[-1] else data['releases']))
''')
        gh.chmod(0o755)
        self.env=dict(os.environ,PATH=str(self.root)+':'+os.environ['PATH'],
                      GITHUB_REPOSITORY='personal-owner/vlc-nightly-release',
                      API_LOG=str(self.root/'api.log'),GH_RESPONSES=str(self.root/'responses.json'),
                      GITHUB_OUTPUT=str(self.root/'outputs'),PIN=self.lock['upstream_sha'])
        self.responses([])

    def fixture(self):
        snapshots={}
        for arch in ('x86_64','aarch64'):
            libraries={f'libQt6{x}.so.6':dict(version='6.11.3',object=x+'-content') for x in ('Core','Gui','Quick','Qml')}
            snapshot=dict(architecture=arch,deployments=dict(sdk_commit='a'*64,platform_commit='b'*64),
                sdk=dict(qt_version='6.11.3',libraries=libraries,private_headers={x:x+'-headers' for x in ('Core','Gui','Quick','Qml')}),
                platform=dict(qt_version='6.11.3',libraries=copy.deepcopy(libraries),private_headers={}))
            snapshot['identity']=identity(snapshot);snapshots[arch]=snapshot
        return dict(version='4.0.0-dev-1-gabcdef',upstream_sha='c'*40,packaging_revision=2,
                    artifact_version=artifact_version('4.0.0-dev-1-gabcdef',2,snapshots),
                    architectures={a:copy.deepcopy(s['deployments']) for a,s in snapshots.items()},
                    qt_abi=snapshots,qt_abi_identity=release_identity(snapshots),recipe_sha256='d'*64)

    def responses(self,releases,asset=None):
        (self.root/'responses.json').write_text(json.dumps(dict(releases=[releases],asset=asset or self.lock)))

    def completed_release(self):
        version=self.lock['artifact_version']
        names={f'vlc-{version}-{a}.tar.zst' for a in ('x86_64','aarch64')}
        names|={'SHA256SUMS','sizes.json','inputs.json','build-x86_64.json','build-aarch64.json',
                'verification-x86_64.json','verification-aarch64.json'}
        return dict(tag_name=version,draft=False,body=self.lock['upstream_sha'],
                    assets=[dict(name=n,size=1,id=i) for i,n in enumerate(sorted(names))])

    def cli(self,*args):
        return subprocess.run([sys.executable,'scripts/release.py',*map(str,args)],
                              cwd=self.root,env=self.env,capture_output=True,text=True)

    def test_original_two_argument_invocation_is_clear_usage_error(self):
        result=self.cli(self.lock['artifact_version'],self.lock['upstream_sha'])
        self.assertEqual(result.returncode,2)
        self.assertIn('input_path',result.stderr)
        self.assertNotIn('Traceback',result.stderr)
        self.assertFalse((self.root/'api.log').exists())

    def test_invalid_inputs_fail_before_github(self):
        for kind in ['missing-file','bad-json','wrong-type','missing-field','wrong-version','wrong-sha',
                     'wrong-qt-identity','wrong-deployment-pin']:
            with self.subTest(kind=kind):
                lock=copy.deepcopy(self.lock)
                if kind=='missing-field':del lock['upstream_sha']
                if kind=='wrong-version':lock['artifact_version']='unrelated-artifact'
                if kind=='wrong-sha':lock['upstream_sha']='e'*40
                if kind=='wrong-qt-identity':lock['qt_abi_identity']='incorrect'
                if kind=='wrong-deployment-pin':lock['architectures']['x86_64']['sdk_commit']='e'*64
                self.input.write_text('{' if kind=='bad-json' else json.dumps([] if kind=='wrong-type' else lock))
                path=self.root/'absent.json' if kind=='missing-file' else self.input
                result=self.cli(self.lock['artifact_version'],self.lock['upstream_sha'],path)
                self.assertEqual(result.returncode,2,result.stderr)
                self.assertIn('invalid input lock',result.stderr)
                self.assertNotIn('Traceback',result.stderr)
                self.assertFalse((self.root/'api.log').exists())

    def workflow(self):
        # Execute the actual YAML run block, not a duplicated shell invocation.
        workflow=(ROOT/'.github/workflows/build.yml').read_text()
        lines=workflow.split('id: resolve',1)[1].split('run: |\n',1)[1].splitlines()
        block=[]
        for line in lines:
            if line.strip() and not line.startswith('          '):break
            block.append(line)
        script=textwrap.dedent('\n'.join(block))
        wrapper=self.root/'scripts/run-container.sh'
        wrapper.write_text('#!/usr/bin/env bash\nset -euo pipefail\n'
                           '[[ $1 == resolve && $2 == "$PIN" ]]\n'
                           'cp seed-inputs.json work/inputs.json\n')
        wrapper.chmod(0o755)
        (self.root/'seed-inputs.json').write_text(json.dumps(self.lock))
        # An unrelated adjacent lock must never be used as an implicit fallback.
        (self.root/'inputs.json').write_text('{}')
        return subprocess.run(['bash','-euo','pipefail','-c',script],cwd=self.root,
                              env=self.env,capture_output=True,text=True)

    def test_workflow_requests_build_when_no_completed_release(self):
        result=self.workflow()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual((self.root/'outputs').read_text(),f'version={self.lock["artifact_version"]}\nbuild=true\n')
        self.assertEqual(json.loads(self.input.read_text()),self.lock)

    def test_workflow_skips_completed_matching_release(self):
        self.responses([self.completed_release()])
        result=self.workflow()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual((self.root/'outputs').read_text(),f'version={self.lock["artifact_version"]}\nbuild=false\n')
        calls=[json.loads(line) for line in (self.root/'api.log').read_text().splitlines()]
        self.assertEqual(len(calls),2)
        self.assertTrue(all('repos/personal-owner/vlc-nightly-release/releases' in c[-1] for c in calls))
        self.assertIn('/releases/assets/',calls[1][-1])

    def test_workflow_blocks_conflicting_completed_release(self):
        previous=copy.deepcopy(self.lock);previous['qt_abi_identity']='conflicting'
        self.responses([self.completed_release()],previous)
        result=self.workflow()
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Invalid release Qt ABI identity',result.stderr)
        self.assertNotIn('Traceback',result.stderr)
        self.assertFalse((self.root/'outputs').exists())


if __name__=='__main__':unittest.main()
