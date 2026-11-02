"""A single signed-off policy window never changes raw checks or publication locks."""
import copy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pair import REQUIRED
from waiver import evaluate,POLICY,utc

NOW=utc('2026-11-03T12:00:00Z')
# Fixed historical policy fixture: disabling the real waiver must not break the
# negative tests or prevent a genuinely passing build after the upstream fix.
TEST_POLICY=dict(id='VLC-X11-RAPID-QUIT-AARCH64-2026-11',enabled=True,
                 effective_from='2026-11-02T00:00:00Z',expires_at='2026-11-16T00:00:00Z',
                 architecture='aarch64',test='xcb-gui-openuri-quit-rapid',exit_code=134)
SIGNATURE="vlc: /work/source/modules/gui/qt/maininterface/compositor_x11.cpp:296: virtual QQuickWindow* vlc::CompositorX11::quickWindow() const: Assertion `m_qmlView' failed.\n"


def fixture(directory,sha='8a47770f6333df6b60181329db5fdaad318bdb44'):
    report=dict(architecture='aarch64',upstream_sha=sha,release_ready=False,
                checks=[dict(name=n,status='pass',mandatory=True) for n in sorted(REQUIRED)])
    raw=next(c for c in report['checks'] if c['name']=='xcb-gui-openuri-quit-rapid')
    raw.update(status='fail',detail='exit=134; MPRIS playing=True; video output=True; surface=True')
    evidence=dict(ran=True,test='xcb-gui-openuri-quit-rapid',exit_code=134,playing=True,
                  rendering=True,surface=True,open_uri=True,no_other_fatal=True,
                  log_name='xcb-gui-openuri-quit-rapid-aarch64.log',
                  log_sha256=hashlib.sha256(SIGNATURE.encode()).hexdigest())
    report['rapid_quit_evidence']=evidence
    (Path(directory)/evidence['log_name']).write_text(SIGNATURE)
    return report


class WaiverTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name);self.report=fixture(self.directory)
        policy=self.directory/'policy.json';policy.write_text(json.dumps(TEST_POLICY))
        mock=patch('waiver.POLICY',policy);mock.start();self.addCleanup(mock.stop)
    def decide(self,now=NOW):return evaluate(self.report,REQUIRED,self.directory,now)
    def fail(self,name):next(c for c in self.report['checks'] if c['name']==name)['status']='fail'
    def replace_log(self,text):
        e=self.report['rapid_quit_evidence'];(self.directory/e['log_name']).write_text(text)
        e['log_sha256']=hashlib.sha256(text.encode()).hexdigest()
    def test_all_pass_never_uses_waiver(self):
        for c in self.report['checks']:c['status']='pass'
        d=self.decide();self.assertEqual(d['outcome'],'PASS');self.assertIsNone(d['waiver'])
    def test_exact_assertion_waived_raw_fail_unchanged(self):
        before=copy.deepcopy(self.report);d=self.decide()
        self.assertEqual(d['outcome'],'WAIVED');self.assertEqual(self.report,before)
        self.assertEqual(d['waiver']['id'],'VLC-X11-RAPID-QUIT-AARCH64-2026-11')
        self.assertEqual(d['waiver']['assertion_lines'],[SIGNATURE.strip()])
        self.assertFalse(self.report['release_ready'])
    def test_different_verified_source_commit_supported(self):
        self.report['upstream_sha']='a'*40;d=self.decide()
        self.assertEqual(d['outcome'],'WAIVED');self.assertEqual(d['waiver']['source_commit'],'a'*40)
    def test_expiry_is_exclusive_and_before_start_denied(self):
        for moment in ['2026-11-01T23:59:59Z','2026-11-16T00:00:00Z','2026-11-17T00:00:00Z']:
            self.assertEqual(self.decide(utc(moment))['outcome'],'FAIL')
        self.assertEqual(self.decide(utc('2026-11-02T00:00:00Z'))['outcome'],'WAIVED')
        self.assertEqual(self.decide(utc('2026-11-15T23:59:59Z'))['outcome'],'WAIVED')
    def test_different_or_additional_assertion_fails(self):
        for text in [SIGNATURE.replace('m_qmlView','another_field'),SIGNATURE+"Assertion `other' failed.\n"]:
            self.replace_log(text);self.assertEqual(self.decide()['outcome'],'FAIL')
    def test_raw_exit_must_agree_with_evidence(self):
        next(c for c in self.report['checks'] if c['name']=='xcb-gui-openuri-quit-rapid')['detail']='exit=139; crash'
        self.assertEqual(self.decide()['outcome'],'FAIL')
    def test_different_exit_code(self):
        self.report['rapid_quit_evidence']['exit_code']=139;self.assertEqual(self.decide()['outcome'],'FAIL')
    def test_missing_or_incomplete_evidence(self):
        for key in self.report['rapid_quit_evidence'].copy():
            r=copy.deepcopy(self.report);del self.report['rapid_quit_evidence'][key]
            self.assertEqual(self.decide()['outcome'],'FAIL',key);self.report=r
        e=self.report['rapid_quit_evidence'];(self.directory/e['log_name']).unlink()
        self.assertEqual(self.decide()['outcome'],'FAIL')
    def test_wrong_hash_incomplete_signature_and_path(self):
        self.replace_log('CompositorX11::quickWindow()\n');self.assertEqual(self.decide()['outcome'],'FAIL')
        self.replace_log(SIGNATURE);self.report['rapid_quit_evidence']['log_sha256']='0'*64
        self.assertEqual(self.decide()['outcome'],'FAIL')
        self.report['rapid_quit_evidence']['log_name']='../escape';self.assertEqual(self.decide()['outcome'],'FAIL')
    def test_other_mandatory_failures_and_missing_checks(self):
        for name in REQUIRED-{'xcb-gui-openuri-quit-rapid'}:
            r=copy.deepcopy(self.report);self.fail(name);self.assertEqual(self.decide()['outcome'],'FAIL',name);self.report=r
        self.report['checks'].pop();self.assertEqual(self.decide()['outcome'],'FAIL')
    def test_x86_cannot_be_waived(self):
        self.report['architecture']='x86_64';self.assertEqual(self.decide()['outcome'],'FAIL')
    def test_disabled(self):
        policy=json.loads(POLICY.read_text());policy['enabled']=False
        with patch('waiver.POLICY') as file:
            file.read_bytes.return_value=json.dumps(policy).encode()
            self.assertEqual(self.decide()['outcome'],'FAIL')
    def test_bad_source_and_failed_provenance_or_qt(self):
        self.report['upstream_sha']='not pinned';self.assertEqual(self.decide()['outcome'],'FAIL')
        self.report=fixture(self.directory)
        for name in ['archive-integrity-provenance-safety','runtime-path-source-evidence','qt-private-abi']:
            r=copy.deepcopy(self.report);self.fail(name);self.assertEqual(self.decide()['outcome'],'FAIL');self.report=r
    def test_execution_and_playback_prerequisites_required(self):
        for name in ['ran','playing','rendering','surface','open_uri','no_other_fatal']:
            self.report['rapid_quit_evidence'][name]=False;self.assertEqual(self.decide()['outcome'],'FAIL')
            self.report['rapid_quit_evidence'][name]=True
    def test_publication_script_still_refuses_without_manual_approval(self):
        import os,shutil,subprocess
        root=Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as directory:
            directory=Path(directory);scripts=directory/'scripts';scripts.mkdir()
            shutil.copy2(root/'scripts/publish.sh',scripts/'publish.sh')
            stub=scripts/'verify-artifacts.sh';stub.write_text('#!/bin/sh\nexit 0\n');stub.chmod(0o755)
            artifacts=directory/'artifacts';artifacts.mkdir()
            result=subprocess.run(['bash',str(scripts/'publish.sh'),str(artifacts)],
                env={'PATH':os.environ['PATH']},capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,1)
            self.assertIn('Publication locked',result.stderr)
            self.assertFalse((artifacts/'notes.md').exists())

    def test_no_publication_unlock(self):
        root=Path(__file__).resolve().parent.parent
        workflow=(root/'.github/workflows/build.yml').read_text()
        self.assertIn('if: ${{ false }}',workflow)
        self.assertIn('VLC_PUBLICATION_APPROVED', (root/'scripts/publish.sh').read_text())
        self.assertFalse(self.report['release_ready'])


if __name__=='__main__':unittest.main()
