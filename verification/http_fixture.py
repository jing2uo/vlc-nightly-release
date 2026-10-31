"""Loopback-only fixtures with concurrent clients and persistent request evidence."""
from contextlib import contextmanager
import http.server
import json
import os
from pathlib import Path
import threading
import time


@contextmanager
def fixture_server(directory,log_path):
    directory=Path(directory).resolve()
    if not directory.is_dir():raise ValueError('HTTP fixture directory is missing: '+str(directory))
    lock=threading.Lock()
    with Path(log_path).open('w') as log:
        def record(**event):
            with lock:
                log.write(json.dumps(dict(time=time.time(),**event))+'\n');log.flush()
        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(directory),**kwargs)
            def log_message(self,*args):pass
            def log_request(self,code='-',size='-'):
                record(event='request',peer=self.client_address,request=self.requestline,
                       status=code,range=self.headers.get('Range'))
            def copyfile(self,source,outputfile):
                try:super().copyfile(source,outputfile)
                except (BrokenPipeError,ConnectionResetError):pass # bounded VLC probes intentionally stop
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        base=f'http://127.0.0.1:{server.server_address[1]}'
        record(event='start',base=base,directory=str(directory),
               controller_network_namespace=os.readlink('/proc/self/ns/net'),server_alive=thread.is_alive())
        try:yield base
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)
            record(event='stop',server_alive=thread.is_alive())
