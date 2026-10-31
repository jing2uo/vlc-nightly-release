import copy
import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'scripts'))
from qt_identity import identity,artifact_version,validate_snapshot,validate_inputs
from qt_abi import qt_symbols,validate
from release import completed

class QtAbi(unittest.TestCase):
    def snapshots(self):
        result={}
        for arch in ('x86_64','aarch64'):
            libraries={f'libQt6{x}.so.6':dict(version='6.11.3',object=x+'1') for x in ('Core','Gui','Quick','Qml')}
            result[arch]=dict(architecture=arch,deployments=dict(sdk_commit='sdk1',platform_commit='platform1'),
                 sdk=dict(qt_version='6.11.3',libraries=libraries,private_headers={x:x+'-headers' for x in ('Core','Gui','Quick','Qml')}),
                 platform=dict(qt_version='6.11.3',libraries=copy.deepcopy(libraries),private_headers={}))
        return result
    def test_real_symbol_format(self):
        text='00000000 DF *UND* 00000000 (Qt_6_PRIVATE_API) _ZN19QRhiGles2InitParamsC1Ev\n00000001 g DF .text 00000012 Qt_6_PRIVATE_API _ZN19QRhiGles2InitParamsC1Ev'
        imports=qt_symbols(text,True);exports=qt_symbols(text,False)
        private,failures=validate(imports,exports,'6.11.3','6.11.3')
        self.assertEqual(len(private),1);self.assertFalse(failures)
    def test_generic_private_tag_does_not_allow_patch_mismatch(self):
        symbols={('Qt_6_PRIVATE_API','private_symbol')}
        self.assertTrue(validate(symbols,symbols,'6.11.3','6.11.4')[1])
    def test_missing_private_export(self):
        self.assertTrue(validate({('Qt_6_PRIVATE_API','missing')},set(),'6.11.3','6.11.3')[1])
    def test_unrelated_deployment_metadata_does_not_rebuild(self):
        a=self.snapshots();b=copy.deepcopy(a)
        b['x86_64']['deployments']['platform_commit']='different-runtime-metadata'
        b['aarch64']['deployments']['sdk_commit']='different-sdk-metadata'
        self.assertEqual(artifact_version('4.0.0-dev-1-gabc',2,a),artifact_version('4.0.0-dev-1-gabc',2,b))
    def test_qt_binary_or_private_header_change_gets_new_asset_name(self):
        a=self.snapshots()
        for kind in ('library','header'):
            b=copy.deepcopy(a)
            if kind=='library':
                for section in ('sdk','platform'):b['x86_64'][section]['libraries']['libQt6Gui.so.6']['object']='changed'
            else:b['x86_64']['sdk']['private_headers']['Gui']='changed'
            validate_snapshot(b['x86_64'])
            self.assertNotEqual(artifact_version('same-vlc',2,a),artifact_version('same-vlc',2,b))
    def test_mismatched_sdk_runtime_blocks_before_compilation(self):
        snapshot=self.snapshots()['x86_64'];snapshot['platform']['libraries']['libQt6Gui.so.6']['object']='different'
        with self.assertRaises(ValueError):validate_snapshot(snapshot)
    def test_stale_snapshot_cannot_describe_new_pins(self):
        snapshot=self.snapshots()['x86_64'];snapshot['identity']=identity(snapshot)
        with self.assertRaises(ValueError):validate_inputs(snapshot,'x86_64',dict(sdk_commit='different',platform_commit='platform1'))
    def test_snapshot_identity_is_verified(self):
        snapshot=self.snapshots()['x86_64'];snapshot['identity']='incorrect'
        with self.assertRaises(ValueError):validate_inputs(snapshot,'x86_64',snapshot['deployments'])
    def test_current_snapshots(self):
        for snapshot in self.snapshots().values():validate_snapshot(snapshot)

class ReleaseSelection(unittest.TestCase):
    def fixture(self):
        version='4.0.0-dev-1-gabc-r2-qt1234';sha='a'*40
        names={f'vlc-{version}-{arch}.tar.zst' for arch in ('x86_64','aarch64')}
        names|={'SHA256SUMS','sizes.json','inputs.json','build-x86_64.json','build-aarch64.json','verification-x86_64.json','verification-aarch64.json'}
        release=dict(tag_name=version,draft=False,body=sha,assets=[dict(name=n,size=1,id=i) for i,n in enumerate(sorted(names))])
        lock=dict(upstream_sha=sha,artifact_version=version,qt_abi_identity='qt1',recipe_sha256='recipe1')
        return release,lock
    def test_completed_qt_compatible_release_skips_metadata_noise(self):
        release,lock=self.fixture();previous=dict(lock,architectures={'old':'deployment'})
        self.assertTrue(completed([release],lock['artifact_version'],lock['upstream_sha'],dict(lock,architectures={'new':'metadata'}),lambda _:previous))
    def test_new_qt_asset_identity_requires_build(self):
        release,lock=self.fixture();lock['artifact_version']+='new-qt';lock['qt_abi_identity']='qt2'
        self.assertFalse(completed([release],lock['artifact_version'],lock['upstream_sha'],lock,lambda _:None))
    def test_same_asset_with_changed_abi_cannot_be_replaced(self):
        release,lock=self.fixture();previous=dict(lock,qt_abi_identity='different')
        with self.assertRaises(ValueError):completed([release],lock['artifact_version'],lock['upstream_sha'],lock,lambda _:previous)
    def test_draft_or_partial_release_is_not_rebuilt_over(self):
        for which in ('draft','partial'):
            release,lock=self.fixture()
            if which=='draft':release['draft']=True
            else:release['assets'].pop()
            with self.assertRaises(ValueError):completed([release],lock['artifact_version'],lock['upstream_sha'],lock,lambda _:lock)
    def test_personal_repository_cli_uses_context(self):
        with tempfile.TemporaryDirectory() as directory:
            directory=Path(directory);gh=directory/'gh';log=directory/'api.json'
            gh.write_text('#!'+sys.executable+'\nimport json,os,sys\nopen(os.environ["API_LOG"],"w").write(json.dumps(sys.argv[1:]))\nprint("[]")\n');gh.chmod(0o755)
            _,lock=self.fixture();file=directory/'inputs.json';file.write_text(json.dumps(lock))
            env=dict(os.environ,PATH=str(directory)+':'+os.environ['PATH'],GITHUB_REPOSITORY='test-personal-owner/test-nightlies',API_LOG=str(log))
            p=subprocess.run([sys.executable,str(Path(__file__).resolve().parent.parent/'scripts/release.py'),lock['artifact_version'],lock['upstream_sha'],str(file)],env=env,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout.strip(),'true')
            self.assertIn('repos/test-personal-owner/test-nightlies/releases?per_page=100',json.loads(log.read_text()))
