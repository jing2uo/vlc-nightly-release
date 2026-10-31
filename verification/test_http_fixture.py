"""Real loopback requests and unchanged GUI assertions must reject false success."""
import ast
import json
from pathlib import Path
import signal
import socket
import tempfile
import unittest
import urllib.error
import urllib.request
from http_fixture import fixture_server


class HTTPFixtureTests(unittest.TestCase):
    def test_concurrent_idle_connection_does_not_block_media_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'hls').mkdir()
            (root/'h264-aac.mp4').write_bytes(b'fixture media')
            (root/'hls/index.m3u8').write_text('#EXTM3U\nindex0.ts\n')
            (root/'hls/index0.ts').write_bytes(b'fixture segment')
            log=root/'requests.jsonl'
            with fixture_server(root,log) as base:
                host=urllib.parse.urlsplit(base)
                with socket.create_connection((host.hostname,host.port),timeout=2):
                    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    for name in ['h264-aac.mp4','hls/index.m3u8','hls/index0.ts']:
                        request=urllib.request.Request(base+'/'+name,headers={'Range':'bytes=0-'})
                        with opener.open(request,timeout=2) as response:
                            self.assertEqual(response.status,200)
                            self.assertEqual(response.read(),(root/name).read_bytes())
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        opener.open(base+'/missing.ts',timeout=2)
                    self.assertEqual(error.exception.code,404)
                    error.exception.close()
            events=[json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(events[0]['event'],'start')
            self.assertTrue(events[0]['base'].startswith('http://127.0.0.1:'))
            self.assertEqual([e['status'] for e in events if e['event']=='request'],[200,200,200,404])
            self.assertFalse(events[-1]['server_alive'])
            with self.assertRaises(urllib.error.URLError):opener.open(base+'/h264-aac.mp4',timeout=2)

    def test_missing_fixture_directory_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'fixture directory is missing'):
                with fixture_server(Path(directory)/'missing',Path(directory)/'log'):pass

    def test_actual_gui_assertion_rejects_clean_exit_without_playback(self):
        # Inspect the real assertion, without changing or duplicating its logic.
        tree=ast.parse((Path(__file__).with_name('gui.py')).read_text())
        expression=next(n.value for n in ast.walk(tree) if isinstance(n,ast.Assign)
                        and any(isinstance(t,ast.Name) and t.id=='ok' for t in n.targets))
        code=compile(ast.Expression(expression),'<GUI playback assertion>','eval')
        scope=dict(rc=0,signal=signal,fatal=False,playing=True,rendering=True,surface=True,
                   label='gui-local-hls',open_ok=False)
        self.assertTrue(eval(code,scope))
        for flag in ['playing','rendering','surface']:
            self.assertFalse(eval(code,dict(scope,**{flag:False})))
        self.assertFalse(eval(code,dict(scope,rc=134)))
        self.assertFalse(eval(code,dict(scope,label='gui-openuri-quit-rapid')))


if __name__=='__main__':unittest.main()
