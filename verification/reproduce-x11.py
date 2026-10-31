#!/usr/bin/env python3
"""Minimal replay of OpenUri followed by Quit, including bypassing all wrappers."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
from gui import names,call

p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True)
p.add_argument('--raw-elf',action='store_true');p.add_argument('--settle',type=float,default=0)
p.add_argument('--iterations',type=int,default=3);a=p.parse_args()
assert 1<=a.iterations<=10 and 0<=a.settle<=5
work=a.work.resolve();app=work/'verification'/('app-'+os.uname().machine);assert os.uname().machine in ('x86_64','aarch64')
os.environ['XDG_DATA_HOME']=str(work/'flatpak-data')
out=work/'verification'/('openuri-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()));out.mkdir()
rows=[]
for iteration in range(a.iterations):
    before=names();bus=None
    media=['--ignore-config','--no-one-instance','--no-qt-privacy-ask','--no-metadata-network-access',
           '--run-time=8','-I','qt','-vvv','/app/verify/fixtures/h264-aac.mp4','/app/verify/fixtures/vp8-vorbis.webm']
    if a.raw_elf:
        text='export LD_LIBRARY_PATH=/app/extra/lib:/app/extra/lib/vlc${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}; '
        text+='export VLC_PLUGIN_PATH=/app/extra/lib/vlc/plugins VLC_DATA_PATH=/app/extra/share/vlc '
        text+='VLC_LIB_PATH=/app/extra/lib/vlc VLC_LIBEXEC_PATH=/app/extra/lib/vlc GNUTLS_SYSTEM_PRIORITY_FILE=/etc/gnutls/config; '
        text+='exec -a /app/extra/bin/vlc '+shlex.join(['/app/extra/bin/vlc.bin',*media])
        command=['/bin/bash','-c',text]
    else:command=['/app/extra/bin/vlc',*media]
    argv=['flatpak','build','--runtime','--readonly','--die-with-parent','--socket=x11',
          '--share=ipc','--device=dri','--socket=session-bus','--socket=pulseaudio',
          '--env=QT_QPA_PLATFORM=xcb','--env=XDG_CONFIG_HOME=/tmp/vlc-repro-config',
          '--env=XDG_CACHE_HOME=/tmp/vlc-repro-cache',str(app),*command]
    with (out/f'{iteration}.log').open('w') as log:
        log.write('$ '+shlex.join(argv)+'\n');log.flush();process=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT)
        started=time.monotonic()
        try:
            while time.monotonic()-started<12 and process.poll() is None:
                current=names()-before
                if current:bus=sorted(current)[0]
                time.sleep(.2)
            opened=None;quit_code=None
            if bus and process.poll() is None:
                opened=call(bus,'org.mpris.MediaPlayer2.Player.OpenUri','file:///app/verify/fixtures/vp8-vorbis.webm').returncode
                if a.settle:time.sleep(a.settle)
                quit_code=call(bus,'org.mpris.MediaPlayer2.Quit').returncode
            try:rc=process.wait(timeout=8)
            except subprocess.TimeoutExpired:process.terminate();rc=process.wait(timeout=5)
        finally:
            if process.poll() is None:process.kill();process.wait()
    text=(out/f'{iteration}.log').read_text(errors='replace')
    rows.append(dict(iteration=iteration,bus=bus,open_uri=opened,quit=quit_code,exit_code=rc,
                     assertion='Assertion `m_qmlView\' failed' in text))
report=dict(raw_elf=a.raw_elf,settle_seconds=a.settle,results=rows)
(out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report));print(out)
