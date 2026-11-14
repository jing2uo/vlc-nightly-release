"""Promotion trust, candidate ownership and production controls fail closed."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

path=Path(__file__).resolve().parent.parent/'scripts/production.py'
spec=importlib.util.spec_from_file_location('production',path);p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.repo='rhgKc2yp/vlc-nightly-release'
        self.run=dict(repository=dict(full_name=self.repo),head_repository=dict(full_name=self.repo),
                      head_branch='main',event='workflow_dispatch',path='.github/workflows/build.yml',conclusion='success')
        self.jobs=[dict(name=name,conclusion='success') for name in ['resolve','build (x86_64, ubuntu-26.04)','build (aarch64, ubuntu-26.04-arm)','verify']]
        self.assets=[dict(id=123,name='release-candidate',expired=False)]
    def test_trusted_successful_native_pair(self):self.assertEqual(p.promotion(self.run,self.assets,self.jobs,self.repo)['id'],123)
    def test_fork_branch_failed_run_or_wrong_workflow_rejected(self):
        for key,value in [('head_branch','feature'),('event','pull_request'),('conclusion','failure'),('path','other.yml')]:
            run=copy.deepcopy(self.run);run[key]=value
            with self.assertRaises(ValueError):p.promotion(run,self.assets,self.jobs,self.repo)
        self.run['head_repository']['full_name']='attacker/fork'
        with self.assertRaises(ValueError):p.promotion(self.run,self.assets,self.jobs,self.repo)
    def test_missing_failed_or_expired_pair_rejected(self):
        with self.assertRaises(ValueError):p.promotion(self.run,[],self.jobs,self.repo)
        with self.assertRaises(ValueError):p.promotion(self.run,self.assets*2,self.jobs,self.repo)
        self.assets[0]['expired']=True
        with self.assertRaises(ValueError):p.promotion(self.run,self.assets,self.jobs,self.repo)
        self.assets[0]['expired']=False;self.jobs[-1]['conclusion']='failure'
        with self.assertRaises(ValueError):p.promotion(self.run,self.assets,self.jobs,self.repo)
    def test_prepare_never_bypasses_pair_gate(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(p,'verify',side_effect=ValueError('expired waiver')):
            with self.assertRaises(ValueError):p.prepare(directory,self.repo,'1')
            self.assertFalse((Path(directory)/'release.json').exists())
    def test_biweekly_source_and_offweek_runtime_selection(self):
        from datetime import date
        version='4.0.0-dev-1-gaaaaaaaaaa-r3-qt'+('b'*16)
        url=f'https://github.com/{self.repo}/releases/download/{version}/release.json'
        release=dict(tag_name=version,draft=False,published_at='2026-11-02T00:00:00Z',assets=[dict(name='release.json',browser_download_url=url)])
        data=dict(channel='production',repository=self.repo,version=version,automated_status='PASS',upstream_sha='a'*40)
        self.assertEqual(p.scheduled_pin([release],self.repo,date(2026,11,2),lambda u:data),'')
        self.assertEqual(p.scheduled_pin([release],self.repo,date(2026,11,9),lambda u:data),'a'*40)
        self.assertEqual(p.scheduled_pin([release],self.repo,date(2026,11,16),lambda u:data),'')
        data['channel']='internal'
        self.assertEqual(p.scheduled_pin([release],self.repo,date(2026,11,9),lambda u:data),'')

    def test_runtime_baseline_retains_latest_production_source_even_in_source_week(self):
        version='4.0.0-dev-1-gaaaaaaaaaa-r4-qt'+('b'*16)
        url=f'https://github.com/{self.repo}/releases/download/{version}/release.json'
        release=dict(tag_name=version,draft=False,published_at='2026-11-02T00:00:00Z',
                     assets=[dict(name='release.json',browser_download_url=url)])
        data=dict(channel='production',repository=self.repo,version=version,
                  automated_status='PASS',upstream_sha='a'*40,qt_abi_identity='b'*64)
        with tempfile.TemporaryDirectory() as directory:
            # An internal candidate and a newer draft must not become the baseline.
            draft=dict(release,draft=True,published_at='2026-11-16T00:00:00Z')
            self.assertEqual(p.runtime_baseline([draft,release],self.repo,lambda u:data,directory),'a'*40)
            self.assertEqual(json.loads((Path(directory)/'inputs.json').read_text()),data)
            data['channel']='internal'
            with self.assertRaises(ValueError):p.runtime_baseline([release],self.repo,lambda u:data,directory)
            with self.assertRaises(ValueError):p.runtime_baseline([],self.repo,lambda u:data,directory)

    def test_watcher_decisions_and_publication_gate(self):
        import subprocess,sys
        from test_release_cli import ReleaseCLI
        from qt_identity import identity
        script=(path.parent/'check-runtime.sh').read_text().split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0]
        for change in ('unchanged','metadata','qml','plugins','incompatible'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);(root/'logs').mkdir()
                lock=ReleaseCLI().fixture()
                snapshots=copy.deepcopy(lock['qt_abi'])
                if change=='metadata':snapshots['aarch64']['deployments']['sdk_commit']='metadata-only'
                elif change in ('qml','plugins'):snapshots['aarch64']['platform']['runtime_trees']={change:'changed'}
                elif change=='incompatible':snapshots['x86_64']['sdk']['libraries']['libQt6Core.so.6']['object']='mismatched'
                for arch,snapshot in snapshots.items():
                    snapshot['identity']=identity(snapshot)
                    (root/'logs'/f'current-{arch}.json').write_text(json.dumps(snapshot))
                (root/'inputs.json').write_text(json.dumps(lock))
                code=script.replace('/work/',str(root)+'/').replace('/recipe/scripts',str(path.parent))
                result=subprocess.run([sys.executable,'-','--watch'],input=code,text=True,capture_output=True)
                if change=='incompatible':
                    self.assertNotEqual(result.returncode,0)
                    self.assertFalse((root/'logs/current-runtime.json').exists())
                    continue
                self.assertEqual(result.returncode,0,result.stderr)
                report=json.loads((root/'logs/current-runtime.json').read_text())
                self.assertEqual(report['changed'],change in ('qml','plugins'))
                self.assertIn('Decision:',result.stdout)
                # The publication invocation still rejects changed identities.
                result=subprocess.run([sys.executable,'-',''],input=code,text=True,capture_output=True)
                self.assertEqual(result.returncode==0,change in ('unchanged','metadata'))

    def test_runtime_check_refuses_to_replace_unrelated_inputs(self):
        import os,subprocess
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);candidate=root/'candidate';candidate.mkdir();work=root/'work';work.mkdir()
            (candidate/'inputs.json').write_text('new inputs')
            (work/'inputs.json').write_text('preserved inputs')
            result=subprocess.run(['bash',str(path.parent/'check-runtime.sh'),str(candidate)],
                env=dict(os.environ,WORK_DIR=str(work)),capture_output=True,text=True,timeout=5)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual((work/'inputs.json').read_text(),'preserved inputs')
            self.assertIn('separate WORK_DIR',result.stderr)

    def test_prepared_metadata_and_source_run_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            from test_release_cli import ReleaseCLI
            from datetime import datetime,timezone
            root=Path(directory);lock=ReleaseCLI().fixture();lock.update(recipe_commit='c'*40)
            lock['artifact_version']=lock['artifact_version'].replace('-r2-','-r3-')
            (root/'current-runtime.json').write_text(json.dumps(dict(schema=1,checked_at=datetime.now(timezone.utc).isoformat(),qt_abi=lock['qt_abi'])))
            (root/'inputs.json').write_text(json.dumps(lock))
            (root/'verification-pair.json').write_text(json.dumps(dict(automated_status='PASS',known_issues=[])))
            for arch in ['x86_64','aarch64']:
                (root/f'build-{arch}.json').write_text(json.dumps(dict(workflow_run='1',repository=self.repo,recipe_commit='c'*40)))
            reports=[dict(architecture=a,sha256='d'*64,size=123,automated_status='pass') for a in ['x86_64','aarch64']]
            with patch.object(p,'verify',return_value=reports):
                result=p.prepare(root,self.repo,'1')
                self.assertEqual(result['channel'],'production')
                self.assertEqual(set(result['assets']),{'x86_64','aarch64'})
                self.assertEqual(result['source_recipe_commit'],'c'*40)
                self.assertTrue(result['attestation_required'])
                with self.assertRaises(ValueError):p.prepare(root,self.repo,'another-run')
                with self.assertRaises(ValueError):p.prepare(root,'other/repository','1')
                current=json.loads((root/'current-runtime.json').read_text())
                current['checked_at']='2000-01-01T00:00:00Z'
                (root/'current-runtime.json').write_text(json.dumps(current))
                with self.assertRaises(ValueError):p.prepare(root,self.repo,'1')
                current['checked_at']=datetime.now(timezone.utc).isoformat()
                current['qt_abi']['x86_64']['sdk']['libraries']['libQt6Core.so.6']['object']='different'
                (root/'current-runtime.json').write_text(json.dumps(current))
                with self.assertRaises(ValueError):p.prepare(root,self.repo,'1')
                from qt_identity import identity
                current['qt_abi']['x86_64']['platform']['libraries']['libQt6Core.so.6']['object']='different'
                current['qt_abi']['x86_64']['identity']=identity(current['qt_abi']['x86_64'])
                (root/'current-runtime.json').write_text(json.dumps(current))
                with self.assertRaises(ValueError):p.prepare(root,self.repo,'1')

    def test_production_permission_and_attestation_controls(self):
        root=path.parent.parent;text=(root/'.github/workflows/build.yml').read_text()
        self.assertIn('environment: production',text);self.assertIn('uses: actions/attest@v4',text)
        self.assertIn('needs: [verify, promote]',text)
        publish=(root/'scripts/publish.sh').read_text()
        self.assertIn('gh attestation verify',publish);self.assertNotIn('--clobber',publish)
        self.assertIn('cmp release.json',publish)
        self.assertLess(publish.rindex('verify-artifacts.sh'),publish.index('gh release edit'))

if __name__=='__main__':unittest.main()
