"""Exercise the actual runner callbacks without installing an SDK or running VLC."""
import ast
import contextlib
import io
from pathlib import Path
import unittest
from pair import REQUIRED
from waiver import evaluate


class CorePolicy(unittest.TestCase):
    def setUp(self):
        self.checks=[]
        tree=ast.parse(Path(__file__).with_name('run.py').read_text())
        functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='result']
        self.env=dict(checks=self.checks,REQUIRED=REQUIRED)
        exec(compile(ast.Module(body=functions,type_ignores=[]),'run.py','exec'),self.env)

    def record(self,*args,**kwargs):
        with contextlib.redirect_stdout(io.StringIO()):self.env['result'](*args,**kwargs)

    def test_gui_explicit_mandatory_flag_cannot_block(self):
        for name in REQUIRED:self.record(name,'pass')
        for name in ('xcb-gui-openuri-quit-rapid','http-decode-hls-index.m3u8',
                     'pulse-audio-output','diagnostic-driver'):
            self.record(name,'fail','original diagnostic error',True)
            self.assertFalse(self.checks[-1]['mandatory'])
            self.assertEqual(self.checks[-1]['status'],'fail')
        self.assertEqual(evaluate(dict(checks=self.checks,architecture='x86_64'),REQUIRED,'.')['outcome'],'PASS')

    def test_required_failure_and_driver_exception_block(self):
        for name in REQUIRED:self.record(name,'pass')
        self.record('verification-driver','fail','core exception')
        self.assertEqual(evaluate(dict(checks=self.checks,architecture='x86_64'),REQUIRED,'.')['outcome'],'FAIL')

    def test_core_does_not_require_graphics_audio_or_optional_fixtures(self):
        self.assertNotIn('xcb-gui-openuri-quit-rapid',REQUIRED)
        self.assertNotIn('http-fixture-reachability',REQUIRED)
        self.assertIn('decode-h264-aac.mp4',REQUIRED)
        self.assertIn('qt-private-abi',REQUIRED)
        self.assertIn('runtime-path-source-evidence',REQUIRED)

    def test_headless_core_does_not_start_optional_services(self):
        import os
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            directory=Path(directory)
            python=directory/'python3'
            python.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGUMENTS"\nexit "$CORE_EXIT"\n')
            python.chmod(0o755)
            # Any accidental optional setup command fails this test immediately.
            for name in ('flatpak','Xvfb','pulseaudio','dbus-run-session'):
                stub=directory/name
                stub.write_text('#!/bin/sh\necho unexpected-optional-setup >&2\nexit 97\n')
                stub.chmod(0o755)
            script=Path(__file__).with_name('headless.sh')
            for status in (0,19):
                env=dict(os.environ,PATH=str(directory)+':'+os.environ['PATH'],
                         ARGUMENTS=str(directory/'arguments'),CORE_EXIT=str(status))
                result=__import__('subprocess').run(['bash',str(script),'x86_64'],
                    env=env,capture_output=True,text=True,timeout=5)
                self.assertEqual(result.returncode,status,result.stderr)
                self.assertNotIn('unexpected-optional-setup',result.stderr)
                self.assertEqual((directory/'arguments').read_text().splitlines(),
                    ['/recipe/verification/run.py','--work','/work','--arch','x86_64'])
