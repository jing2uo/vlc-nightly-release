"""Bounded GUI regression checks with logs, MPRIS observations and screenshots."""
import json
import hashlib
import os
from pathlib import Path
from mpris_control import pause_resume
import re
import shlex
import shutil
import signal
import subprocess
import time


def names():
    r=subprocess.run(['gdbus','call','--session','--dest','org.freedesktop.DBus',
        '--object-path','/org/freedesktop/DBus','--method','org.freedesktop.DBus.ListNames'],
        capture_output=True,text=True,timeout=5)
    return set(re.findall(r'org\.mpris\.MediaPlayer2\.vlc[^\x27,\s\]]*',r.stdout))


def call(bus,method,*args):
    return subprocess.run(['gdbus','call','--session','--dest',bus,'--object-path',
        '/org/mpris/MediaPlayer2','--method',method,*args],capture_output=True,text=True,timeout=5)


def snapshot(out,name):
    """Only capture the test VLC window; never screenshot the whole desktop."""
    script='''window=
for candidate in $(xdotool search --onlyvisible --class '^vlc$'); do
  title=$(xdotool getwindowname "$candidate")
  case $title in *VLC*) window=$candidate; break;; esac
done
[ -n "$window" ] || exit 1
xprop -id "$window" WM_CLASS WM_NAME > /out/window.txt
xwd -silent -id "$window" -out /out/window.xwd
magick /out/window.xwd /out/window.png
'''
    folder=out/name;folder.mkdir(exist_ok=True)
    if shutil.which('xdotool') and shutil.which('xwd') and shutil.which('magick'):
        script=script.replace('/out',str(folder))
        r=subprocess.run(['/bin/bash','-ec',script],capture_output=True,text=True,timeout=15)
    elif shutil.which('podman') and os.getenv('XAUTHORITY'):
        argv=['podman','run','--pull=never','--rm','--userns=keep-id','--cap-drop=ALL','--security-opt','label=disable',
              '--volume','/tmp/.X11-unix:/tmp/.X11-unix:ro',
              '--volume',os.environ['XAUTHORITY']+':/tmp/auth:ro',
              '--volume',str(folder)+':/out','--env','DISPLAY='+os.environ['DISPLAY'],
              '--env','XAUTHORITY=/tmp/auth','localhost/vlc-nightly-verifier','-ec',script]
        environment=os.environ.copy();environment['XDG_DATA_HOME']=os.environ['VLC_VERIFY_PODMAN_DATA_HOME']
        r=subprocess.run(argv,capture_output=True,text=True,timeout=20,env=environment)
    else:return False
    (folder/'capture.log').write_text(r.stdout+r.stderr)
    return r.returncode==0 and (folder/'window.png').exists()


def exercise(a,app,out,fp,wrapped,cmd,result,base,record):
    modes=[]
    if os.getenv('DISPLAY'):modes.append('xcb')
    if a.desktop and os.getenv('WAYLAND_DISPLAY'):modes.append('wayland')
    if not modes:
        result('gui-default-rendering','unavailable','no X11/Wayland display',True)
        return
    record['display_environment']={k:os.getenv(k) for k in ('DISPLAY','WAYLAND_DISPLAY','XDG_SESSION_TYPE')}
    external=[('https-mp4','https://media.w3.org/2010/05/sintel/trailer.mp4'),
              ('https-hls','https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8')]
    endpoints=[]
    if a.external:
        for label,url in external:
            file=out/(label+'-reachability.log')
            r=subprocess.run(['curl','--head','--fail','--location','--connect-timeout','10','--max-time','25',
                              '--no-progress-meter',url],capture_output=True,text=True)
            file.write_text(r.stdout+r.stderr)
            if r.returncode:
                result(label+'-reachability','unavailable',f'curl exit {r.returncode}; server/network unavailable',False)
            else:
                result(label+'-reachability','pass',url,False);endpoints.append((label,url))
    else:
        for label,_ in external:result(label,'skipped','external networking is an environment-dependent test; not requested',False)
    # Test-only privacy/profile flags avoid modal first-run prompts; no renderer
    # workaround or production configuration is applied.
    for mode in modes:
        cmd(mode+'-qml-window',fp(wrapped(['/app/verify/qml-probe','--window']),gui=mode,
            extra_env={'QT_QPA_PLATFORM':mode,'QSG_INFO':'1'}),timeout=15)
        cases=[('gui-local-h264','/app/verify/fixtures/h264-aac.mp4'),
               ('gui-local-webm','/app/verify/fixtures/vp8-vorbis.webm'),
               ('gui-local-hls',base+'/hls/index.m3u8'),
               ('gui-openuri-quit-rapid','/app/verify/fixtures/h264-aac.mp4')]+endpoints
        for label,media in cases:
            name=mode+'-'+label;file=out/(name+'.log')
            before=names();bus=None;positions=[];state=[];metadata=[];control_events=[]
            args=['/app/extra/bin/vlc-nightly','--ignore-config','--no-one-instance',
                  '--no-qt-privacy-ask','--no-metadata-network-access','--no-video-title-show',
                  '--run-time=8','-I','qt','-vvv',media]
            if label in ('gui-local-h264','gui-openuri-quit-rapid'):args.append('/app/verify/fixtures/vp8-vorbis.webm')
            # In CI the private PulseAudio null sink is used. Desktop tests use
            # the real session's PulseAudio-compatible server when available.
            env={'QT_QPA_PLATFORM':mode,'QSG_INFO':'1','QML_IMPORT_TRACE':'1'}
            if mode=='wayland':env['WAYLAND_DEBUG']='1'
            argv=fp(wrapped(args),gui=mode,pulse=True,extra_env=env)
            with file.open('w') as log:
                log.write('$ '+shlex.join(argv)+'\n');log.flush()
                process=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT)
                start=time.monotonic();capture=False;capture_attempted=False;pause_ok=False;pause_attempted=False;open_ok=False
                try:
                    while time.monotonic()-start<12 and process.poll() is None:
                        time.sleep(.4)
                        current=names()-before
                        if current:bus=sorted(current)[0]
                        if bus:
                            s=call(bus,'org.freedesktop.DBus.Properties.Get','org.mpris.MediaPlayer2.Player','PlaybackStatus')
                            t=call(bus,'org.freedesktop.DBus.Properties.Get','org.mpris.MediaPlayer2.Player','Position')
                            state.append(s.stdout.strip());positions.append(t.stdout.strip())
                            md=call(bus,'org.freedesktop.DBus.Properties.Get','org.mpris.MediaPlayer2.Player','Metadata')
                            metadata.append(md.stdout.strip())
                            progress=[int(n) for n in re.findall(r'int64 (\d+)',t.stdout)]
                            if (label=='gui-local-h264' and not pause_attempted and 'Playing' in s.stdout
                                    and progress and max(progress)>500000):
                                # Ordinary control checks require established playback,
                                # not a first Playing notification during output startup.
                                pause_attempted=True
                                pause_ok=pause_resume(bus,call,control_events)
                        if time.monotonic()-start>4 and not capture_attempted and mode=='xcb':
                            capture_attempted=True
                            capture=snapshot(out,name+'-window')
                    if bus and process.poll() is None:
                        if label in ('gui-local-h264','gui-openuri-quit-rapid'):
                            other='file:///app/verify/fixtures/vp8-vorbis.webm'
                            accepted=call(bus,'org.mpris.MediaPlayer2.Player.OpenUri',other).returncode==0
                            open_ok=accepted
                            if label=='gui-local-h264':
                                # Ordinary OpenUri must actually open/play, rather than merely accept D-Bus.
                                open_ok=False;deadline=time.monotonic()+4
                                while accepted and time.monotonic()<deadline and process.poll() is None:
                                    md=call(bus,'org.freedesktop.DBus.Properties.Get','org.mpris.MediaPlayer2.Player','Metadata')
                                    st=call(bus,'org.freedesktop.DBus.Properties.Get','org.mpris.MediaPlayer2.Player','PlaybackStatus')
                                    pos=call(bus,'org.freedesktop.DBus.Properties.Get','org.mpris.MediaPlayer2.Player','Position')
                                    values=[int(n) for n in re.findall(r'int64 (\d+)',pos.stdout)]
                                    if 'vp8-vorbis.webm' in md.stdout and 'Playing' in st.stdout and values and max(values)>500000:
                                        open_ok=True;break
                                    time.sleep(.1)
                        call(bus,'org.mpris.MediaPlayer2.Quit')
                    if process.poll() is None:
                        try:process.wait(timeout=5)
                        except subprocess.TimeoutExpired:process.terminate()
                    try:rc=process.wait(timeout=8)
                    except subprocess.TimeoutExpired:process.kill();rc=process.wait()
                finally:
                    if process.poll() is None:process.kill();process.wait()
            text=file.read_text(errors='replace')
            (out/(name+'-mpris.json')).write_text(json.dumps(dict(bus=bus,states=state,positions=positions,
                pause_resume=pause_ok,control_events=control_events,open_uri=open_ok,metadata=metadata,exit_code=rc,screenshot=capture),indent=2)+'\n')
            fatal=bool(re.search(r'Segmentation fault|SIGSEGV|QQmlApplicationEngine failed|module ".*" is not installed|Failed to create.*(?:OpenGL|RHI)',text))
            numbers=[int(n) for s in positions for n in re.findall(r'int64 (\d+)',s)]
            playing=any('Playing' in s for s in state) and numbers and max(numbers)>500000
            rendering=bool(re.search(r'using video output module|using vout display module',text))
            surface=capture if mode=='xcb' else bool(re.search(r'wl_surface.*commit\(',text))
            mandatory=not label.startswith('https-')
            ok=rc in (0,-signal.SIGTERM,143) and not fatal and playing and rendering and surface and (open_ok if label=='gui-openuri-quit-rapid' else True)
            if name=='xcb-gui-openuri-quit-rapid':
                record['rapid_quit_evidence']=dict(ran=True,test=name,exit_code=rc,
                    playing=bool(playing),rendering=rendering,surface=surface,open_uri=open_ok,no_other_fatal=not fatal,
                    log_name=name+'-'+record['architecture']+'.log',
                    log_sha256=hashlib.sha256(file.read_bytes()).hexdigest())
            result(name,'pass' if ok else 'fail',
                   f'exit={rc}; MPRIS playing={bool(playing)}; video output={rendering}; surface={surface}; log={file.name}',mandatory)
            if label=='gui-local-h264':
                result(mode+'-mpris-controls','pass' if bus and pause_ok and open_ok else 'fail',
                       f'bus={bus}; pause/play={pause_ok}; OpenUri={open_ok}',mandatory)
                seen='\n'.join(metadata)
                result(mode+'-multiple-file-invocation','pass' if 'h264-aac.mp4' in seen and 'vp8-vorbis.webm' in seen else 'fail',
                       'two files supplied in one real GUI invocation; MPRIS metadata observations saved',mandatory)
            # Do not silently retry a failure with software rendering. The user
            # may request a separately labeled diagnostic experiment afterward.
        result(mode+'-manual-visual-quality','untested','screenshots/protocol evidence are not human playback-quality review',False)
    if 'wayland' not in modes:result('wayland-desktop','unavailable','no Wayland session exposed',False)
    result('desktop-launcher-and-portal-integration','untested','requires Phase 3 manifest/permissions; no FlatPark changes made',False)
