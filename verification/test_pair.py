"""Release gates must reject absent, skipped, or mismatched native evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from archive import InvalidArtifact
from pair import REQUIRED, verify

class PairGate(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)
        self.lock=dict(upstream_sha='a'*40,version='4.0.0-dev-1-gaaaaaaaaaa',architectures={
            a:dict(sdk_commit='b'*64,platform_commit='c'*64) for a in ('x86_64','aarch64')})
        self.lock['runtime_path_evidence']=dict(schema=1,source_sha=self.lock['upstream_sha'],sources={},recipes={})
        (self.directory/'inputs.json').write_text(json.dumps(self.lock))
        self.reports={}
        for arch in ('x86_64','aarch64'):
            (self.directory/f'vlc-{self.lock["version"]}-{arch}.tar.zst').touch()
            (self.directory/f'build-{arch}.json').write_text('{}')
            self.reports[arch]=dict(schema=2,architecture=arch,upstream_sha=self.lock['upstream_sha'],
                version=self.lock['version'],sdk_commit='b'*64,runtime_commit='c'*64,
                sha256='d'*64,size=123,verification_sha256='e'*64,automated_status='pass',
                runtime_path_evidence=copy.deepcopy(self.lock['runtime_path_evidence']),
                checks=[dict(name=n,status='pass',mandatory=True) for n in REQUIRED])
    def run_pair(self):
        for arch,report in self.reports.items():
            (self.directory/f'verification-{arch}.json').write_text(json.dumps(report))
        def audited(path,arch,lock,metadata):
            return dict(upstream_sha=self.lock['upstream_sha'],sha256='d'*64,size=123)
        with patch('pair.audit',side_effect=audited):return verify(self.directory)
    def test_complete_pair(self): self.run_pair()
    def test_missing_check(self):
        self.reports['aarch64']['checks'].pop()
        with self.assertRaises(InvalidArtifact):self.run_pair()
    def test_skip_cannot_be_pass(self):
        self.reports['x86_64']['checks'][0]['status']='skipped'
        with self.assertRaises(InvalidArtifact):self.run_pair()
    def test_optional_cannot_replace_mandatory(self):
        self.reports['x86_64']['checks'][0]['mandatory']=False
        with self.assertRaises(InvalidArtifact):self.run_pair()
    def test_wrong_source_or_asset(self):
        for field in ('sha256','upstream_sha','runtime_commit'):
            saved=self.reports['aarch64'][field];self.reports['aarch64'][field]='0'*64
            with self.assertRaises(InvalidArtifact):self.run_pair()
            self.reports['aarch64'][field]=saved
    def test_tampered_runtime_path_evidence(self):
        self.reports['aarch64']['runtime_path_evidence']['source_sha']='f'*40
        with self.assertRaises(InvalidArtifact):self.run_pair()
    def test_invalid_lock_evidence_invalidates_old_pair_summary(self):
        (self.directory/'verification-pair.json').write_text('{"automated_status":"PASS"}')
        lock=copy.deepcopy(self.lock);lock['runtime_path_evidence']['source_sha']='0'*40
        (self.directory/'inputs.json').write_text(json.dumps(lock))
        with self.assertRaises(InvalidArtifact):self.run_pair()
        self.assertEqual(json.loads((self.directory/'verification-pair.json').read_text())['automated_status'],'FAIL')
    def test_missing_runtime_path_evidence(self):
        del self.reports['aarch64']['runtime_path_evidence']
        with self.assertRaises(InvalidArtifact):self.run_pair()
    def test_different_verification_recipe(self):
        self.reports['aarch64']['verification_sha256']='f'*64
        with self.assertRaises(InvalidArtifact):self.run_pair()
    def test_unexpected_payload(self):
        (self.directory/'extra.tar.zst').touch()
        with self.assertRaises(InvalidArtifact):self.run_pair()

    def test_optional_results_never_block_pair(self):
        for status in ('fail','skipped','unavailable','untested'):
            for report in self.reports.values():
                report['checks']=[c for c in report['checks'] if c['name']!='xcb-gui-openuri-quit-rapid']
                # Also reject accidental dependence on historical mandatory flags.
                report['checks'].append(dict(name='xcb-gui-openuri-quit-rapid',status=status,mandatory=True))
            self.run_pair()
            summary=json.loads((self.directory/'verification-pair.json').read_text())
            self.assertEqual(summary['automated_status'],'PASS')
            self.assertFalse(summary['release_ready'])

    def test_each_core_check_fails_closed(self):
        for name in REQUIRED:
            for mode in ('fail','skipped','missing','optional'):
                original=copy.deepcopy(self.reports)
                checks=self.reports['aarch64']['checks']
                check=next(c for c in checks if c['name']==name)
                if mode=='missing':checks.remove(check)
                elif mode=='optional':check['mandatory']=False
                else:check['status']=mode
                with self.assertRaises(InvalidArtifact,msg=(name,mode)):self.run_pair()
                self.reports=original

    def test_driver_failure_blocks_pair(self):
        self.reports['x86_64']['checks'].append(dict(name='verification-driver',status='fail',mandatory=True))
        with self.assertRaises(InvalidArtifact):self.run_pair()


class WaivedPairGate(PairGate):
    # Historical-policy coverage below retains the old waiver semantics.
    test_optional_results_never_block_pair = None
    def setUp(self):
        super().setUp()
        from test_waiver import fixture,NOW,TEST_POLICY,REQUIRED as LEGACY_REQUIRED
        from waiver import evaluate
        self.now=NOW
        policy=self.directory/'policy.json';policy.write_text(json.dumps(TEST_POLICY))
        mock=patch('waiver.POLICY',policy);mock.start();self.addCleanup(mock.stop)
        self.reports['x86_64']['checks'].append(dict(name='xcb-gui-openuri-quit-rapid',status='pass',mandatory=True))
        report=self.reports['aarch64']
        report.update(fixture(self.directory,self.lock['upstream_sha']))
        decision=evaluate(report,LEGACY_REQUIRED,self.directory,self.now)
        self.assertEqual(decision['outcome'],'WAIVED')
        report.update(automated_status='waived',automated_decision=decision)
    def run_pair(self):
        from waiver import evaluate
        from test_waiver import REQUIRED as LEGACY_REQUIRED
        with patch('pair.REQUIRED',LEGACY_REQUIRED), patch('pair.evaluate',side_effect=lambda *args:evaluate(*args,now=self.now)):
            return super().run_pair()
    def test_pair_summary_labels_known_issue_without_unlocking(self):
        self.run_pair()
        summary=json.loads((self.directory/'verification-pair.json').read_text())
        self.assertEqual(summary['automated_status'],'WAIVED')
        self.assertFalse(summary['release_ready'])
        self.assertEqual(summary['known_issues'][0]['source_commit'],self.lock['upstream_sha'])
        self.assertEqual(next(c for c in self.reports['aarch64']['checks'] if c['name']=='xcb-gui-openuri-quit-rapid')['status'],'fail')
    def test_pair_rechecks_expiry(self):
        from waiver import utc
        self.now=utc('2026-11-16T00:00:00Z')
        with self.assertRaises(InvalidArtifact):self.run_pair()
    def test_x86_failure_blocks_waived_pair(self):
        self.reports['x86_64']['checks'][0]['status']='fail'
        with self.assertRaises(InvalidArtifact):self.run_pair()
    def test_missing_waiver_log_blocks_pair(self):
        (self.directory/self.reports['aarch64']['rapid_quit_evidence']['log_name']).unlink()
        with self.assertRaises(InvalidArtifact):self.run_pair()
    def test_provenance_mismatch_blocks_waived_pair(self):
        self.reports['aarch64']['sdk_commit']='f'*64
        with self.assertRaises(InvalidArtifact):self.run_pair()
    def test_missing_recorded_waiver_blocks_pair(self):
        del self.reports['aarch64']['automated_decision']
        with self.assertRaises(InvalidArtifact):self.run_pair()
