"""Diagnostic instrumentation must preserve argv, payload privacy and gate failures."""
import ast
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock,patch
from network_trace import BUFFER_CALLS,capture


class NetworkTraceTests(unittest.TestCase):
    def test_original_failure_survives_successful_replay(self):
        argv=['flatpak','build','--runtime','--readonly','--share=network','app',
              '/app/verify/probe','decode','http://127.0.0.1:1234/hls/index.m3u8']
        original=dict(name='http-decode-hls-index.m3u8',status='fail',mandatory=True)
        process=MagicMock();process.wait.return_value=0
        process.__enter__.return_value=process
        with tempfile.TemporaryDirectory() as directory,patch('network_trace.subprocess.Popen',return_value=process) as popen:
            evidence=capture('/existing/strace',argv,directory,'hls',original)
        call=popen.call_args.args[0]
        self.assertEqual(call[call.index('--')+1:],argv)
        self.assertNotIn('--allow=devel',call)
        self.assertNotIn('env',popen.call_args.kwargs)
        self.assertIn('raw='+BUFFER_CALLS,call)
        self.assertIn('-f',call)
        self.assertEqual(call[call.index('-s')+1],'0')
        self.assertEqual(evidence['untraced']['status'],'fail')
        self.assertTrue(evidence['untraced']['mandatory'])
        self.assertEqual(evidence['traced_returncode'],0)
        self.assertFalse(evidence['trace_nonempty'])
        self.assertEqual(original['status'],'fail')

    def test_tracer_denial_is_retained(self):
        process=MagicMock();process.wait.return_value=1;process.__enter__.return_value=process
        with tempfile.TemporaryDirectory() as directory,patch('network_trace.subprocess.Popen',return_value=process):
            evidence=capture('/strace',['flatpak'],directory,'denied',{'status':'fail'})
        self.assertEqual(evidence['traced_returncode'],1)
        self.assertEqual(evidence['untraced']['status'],'fail')

    def test_missing_tracer_is_not_success(self):
        with tempfile.TemporaryDirectory() as directory,patch('network_trace.subprocess.Popen',side_effect=FileNotFoundError('missing tracer')):
            evidence=capture('/missing',['flatpak'],directory,'missing',{'status':'pass'})
        self.assertIsNone(evidence['traced_returncode'])
        self.assertIn('missing tracer',evidence['launch_error'])
        self.assertFalse(evidence['trace_nonempty'])

    def test_timeout_kills_only_replay_process_group(self):
        process=MagicMock(pid=1234,returncode=-9)
        process.wait.side_effect=[subprocess.TimeoutExpired('strace',1),-9]
        process.__enter__.return_value=process
        with tempfile.TemporaryDirectory() as directory,patch('network_trace.subprocess.Popen',return_value=process),patch('network_trace.os.killpg') as kill:
            evidence=capture('/strace',['flatpak'],directory,'timeout',{'status':'fail'},timeout=1)
        kill.assert_called_once()
        self.assertEqual(kill.call_args.args[0],1234)
        self.assertTrue(evidence['timed_out'])
        self.assertEqual(evidence['traced_returncode'],-9)

    def test_replays_cannot_write_gate_results(self):
        tree=ast.parse(Path(__file__).with_name('run.py').read_text())
        diagnostic=next(n for n in ast.walk(tree) if isinstance(n,ast.If)
                        and ast.unparse(n.test)=='a.trace_http')
        calls=[ast.unparse(n.func) for n in ast.walk(diagnostic) if isinstance(n,ast.Call)]
        self.assertIn('capture',calls)
        self.assertNotIn('result',calls)
        self.assertNotIn('cmd',calls)


if __name__=='__main__':unittest.main()
