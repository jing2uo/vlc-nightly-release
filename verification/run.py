#!/usr/bin/env python3
"""Small stdlib controller: SDK inspection + actual Platform execution, never host VLC."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time
import urllib.request
from archive import audit, require

p=argparse.ArgumentParser()
p.add_argument('--work',type=Path,required=True)
p.add_argument('--dist',type=Path)
p.add_argument('--arch',choices=['x86_64','aarch64'],required=True)
p.add_argument('--desktop',action='store_true')
p.add_argument('--external',action='store_true')
p.add_argument('--smoke-only',action='store_true')
p.add_argument('--trace-http',action='store_true',help='Diagnostic network replays after unchanged mandatory tests')
a=p.parse_args();work=a.work.resolve();root=Path(__file__).resolve().parent
dist=(a.dist or work/'dist').resolve()
input_file=dist/'inputs.json' if a.dist else work/'inputs.json'
lock=json.loads(input_file.read_text());arch=a.arch
runtime_root=None
stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
out=work/'verification/results'/f'{stamp}-{arch}';out.mkdir(parents=True,exist_ok=True)
app=work/'verification'/f'app-{arch}'
os.environ['VLC_VERIFY_PODMAN_DATA_HOME']=os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share'))
os.environ['XDG_DATA_HOME']=str(work/'flatpak-data')
os.environ['XDG_CACHE_HOME']=str(work/'cache')
checks=[]
record=dict(schema=2,architecture=arch,upstream_sha=lock['upstream_sha'],version=lock['version'],artifact_version=lock.get('artifact_version',lock['version']),
            sdk_commit=lock['architectures'][arch]['sdk_commit'],
            runtime_commit=lock['architectures'][arch]['platform_commit'],
            backend=os.getenv('VLC_VERIFY_BACKEND','host'),checks=checks,
            qt_abi_identity=lock.get('qt_abi_identity'),
            verification_sha256=hashlib.sha256(b''.join(x.name.encode()+b'\0'+x.read_bytes()
                for x in sorted(root.iterdir()) if x.is_file())).hexdigest())

def result(name,status,detail='',mandatory=True):
    checks.append(dict(name=name,status=status,detail=detail,mandatory=mandatory))
    print(f'{status.upper()}: {name}: {detail}',flush=True)

def cmd(name,argv,mandatory=True,timeout=60,env=None):
    file=out/(name+'.log')
    with file.open('w') as f:
        f.write('$ '+shlex.join(map(str,argv))+'\n');f.flush()
        try:
            r=subprocess.run(list(map(str,argv)),stdout=f,stderr=subprocess.STDOUT,
                             timeout=timeout,env=env)
            status='pass' if r.returncode==0 else 'fail'
            detail=f'exit={r.returncode}; log={file.name}'
        except FileNotFoundError as e: status='unavailable';detail=str(e)
        except subprocess.TimeoutExpired: status='fail';detail=f'timeout after {timeout}s'
    result(name,status,detail,mandatory)
    return status=='pass'

def fp(argv,sdk=False,gui=None,pulse=False,extra_env=None):
    call=['flatpak','build','--die-with-parent']
    if not sdk: call+=['--runtime','--readonly']
    call+=['--share=network']
    if gui: call+=['--device=dri','--socket='+('wayland' if gui=='wayland' else 'x11'),'--share=ipc',
                  '--socket=session-bus']
    if pulse: call+=['--socket=pulseaudio']
    if sdk:
        call+=['--filesystem='+str(root)+':ro']
        if runtime_root:call+=['--filesystem='+str(runtime_root)+':ro']
        call+=['--filesystem='+str(input_file)+':ro']
    for k,v in (extra_env or {}).items():call+=['--env='+k+'='+str(v)]
    return call+[str(app)]+list(map(str,argv))

def wrapped(command,prefix='/app/extra'):
    env=dict(VLC_PLUGIN_PATH=prefix+'/lib/vlc/plugins',
             VLC_DATA_PATH=prefix+'/share/vlc',VLC_LIB_PATH=prefix+'/lib/vlc',VLC_LIBEXEC_PATH=prefix+'/lib/vlc',
             XDG_CONFIG_HOME='/tmp/vlc-config',XDG_DATA_HOME='/tmp/vlc-data',XDG_CACHE_HOME='/tmp/vlc-cache')
    text='export LD_LIBRARY_PATH='+shlex.quote(prefix+'/lib:'+prefix+'/lib/vlc')+'${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}; unset QT_QUICK_BACKEND QSG_RHI_BACKEND; '+shlex.join(['env']+[k+'='+v for k,v in env.items()]+list(map(str,command)))
    return ['/bin/bash','-c',text]

def write_report():
    from pair import REQUIRED
    from waiver import evaluate
    dist.mkdir(exist_ok=True)
    evidence=record.get('rapid_quit_evidence')
    if evidence:
        shutil.copy2(out/'xcb-gui-openuri-quit-rapid.log',dist/evidence['log_name'])
    decision=evaluate(record,{'platform-namespace-smoke'} if a.smoke_only else REQUIRED,dist)
    record['automated_status']=decision['outcome'].lower()
    record['automated_decision']=decision
    print(decision['outcome']+': automated verification: '+decision['reason'],flush=True)
    record['release_ready']=False
    record['release_blockers']=['native aarch64 and actual GitHub Actions execution require evidence',
                                'manual/environment-dependent coverage must be reviewed; workflow publication lock remains']
    path=out/('smoke.json' if a.smoke_only else f'verification-{arch}.json');path.write_text(json.dumps(record,indent=2)+'\n')
    dist.mkdir(exist_ok=True)
    if not a.smoke_only: shutil.copy2(path,dist/path.name)
    print('Report: '+str(path),flush=True)

# Startup may fail before an app directory exists; always retain a report.
try:
    require(os.uname().machine==arch,'native architecture required; no emulated validation')
    for name,key in [('Sdk','sdk_commit'),('Platform','platform_commit')]:
        got=subprocess.check_output(['flatpak','info','--user','--show-commit',f'org.kde.{name}/{arch}/6.11'],text=True).strip()
        require(got==lock['architectures'][arch][key],f'{name} installation differs from the artifact input lock')
    # No source fetch, SDK updates, or VLC compilation. Existing installation only.
    if not app.exists():
        subprocess.run(['flatpak','build-init','--arch='+arch,str(app),'org.flatpark.VLCVerify',
                        'org.kde.Sdk','org.kde.Platform','6.11'],check=True)
    if not cmd('platform-namespace-smoke',fp(['/bin/sh','-c',
        'test -f /.flatpak-info && test ! -x /usr/bin/gcc && '
        'grep -E "^(runtime|runtime-commit|runtime-extensions)=" /.flatpak-info && readlink /proc/self/ns/user'])):
        raise RuntimeError('real Platform sandbox failed; wrapper may select host-managed Flatpak fallback')
    if a.smoke_only:
        raise SystemExit(0)
    archive=dist/f'vlc-{record["artifact_version"]}-{arch}.tar.zst'
    metadata=json.loads((dist/f'build-{arch}.json').read_text())
    runtime_root=Path(subprocess.check_output(['flatpak','info','--user','--show-location',f'org.kde.Platform/{arch}/6.11'],text=True).strip())/'files'
    # Test the archive afresh; prior test payloads cannot mask missing dependencies.
    if (app/'files/extra').exists():shutil.rmtree(app/'files/extra')
    integrity=audit(archive,arch,lock,metadata,destination=app/'files') if not any((app/'files').iterdir()) else None
    if integrity is None:
        # Keep helper/fixture caches outside the extraction destination.
        extraction=app/'extract';shutil.rmtree(extraction,ignore_errors=True)
        integrity=audit(archive,arch,lock,metadata,destination=extraction)
        shutil.move(str(extraction/'extra'),app/'files/extra');extraction.rmdir()
    record['source_patches']=lock.get('source_patches')
    record.update({k:integrity[k] for k in ('sha256','size','unpacked_bytes')})
    result('archive-integrity-provenance-safety','pass',f'{integrity["members"]} entries; {integrity["size"]} bytes')
    cmd('archive-negative-tests',['python3','-m','unittest','discover','-s',str(root),'-p','test_*.py'])
    fixture=json.loads((root/'fixtures.json').read_text());cache=work/'verification/fixtures/reference.mp4'
    cache.parent.mkdir(parents=True,exist_ok=True)
    if not cache.exists():
        with urllib.request.urlopen(fixture['url'],timeout=30) as response,cache.open('wb') as dest:
            shutil.copyfileobj(response,dest)
    require(cache.stat().st_size==fixture['size'] and hashlib.sha256(cache.read_bytes()).hexdigest()==fixture['sha256'],
            'reference fixture checksum mismatch')
    target=app/'files/verify/fixtures';target.mkdir(parents=True,exist_ok=True)
    shutil.copy2(cache,target/'reference.mp4')
    if not cmd('prepare-sdk',fp(['/bin/bash',root/'prepare-sdk.sh',root],sdk=True),timeout=120):
        raise RuntimeError('SDK verification helper/fixture preparation failed')
    for filename,expected in [('h264-aac.mp4',['h264','aac']),('vp8-vorbis.webm',['vp8','vorbis'])]:
        actual=json.loads((target/(filename+'.streams.json')).read_text())
        require([s['codec_name'] for s in actual['streams']]==expected,'wrong generated fixture codecs')
    result('fixture-codecs','pass','independent H.264 + SDK AAC; SDK VP8/Vorbis')
    cmd('elf-static',fp(['/usr/bin/python3',root/'elf.py','/app/extra','/app/verify/elf.json'],sdk=True),timeout=120)
    elf=json.loads((app/'files/verify/elf.json').read_text());shutil.copy2(app/'files/verify/elf.json',out/'elf.json')
    from runtime_paths import classify, GNUTLS, evidence_matches
    result('runtime-path-source-evidence','pass' if evidence_matches(lock.get('runtime_path_evidence'),lock['upstream_sha']) else 'fail','relevant source and configuration content must match the reviewed policy')
    runtime_paths=classify(elf['temporary_strings'],lock['upstream_sha'],lock.get('packaging_revision',0),lock.get('runtime_path_evidence'))
    record['runtime_path_findings']=runtime_paths
    result('temporary-runtime-data-paths','fail' if any(x['status']!='pass' for x in runtime_paths) else 'pass',
           f'{len(runtime_paths)} source-reviewed occurrences; API and syscall trace gates remain required')
    # Contrib's static GnuTLS symbols are hidden; dlopen runs its actual
    # constructor. Trace each copy rather than assuming a callable public getter.
    commands='; '.join(shlex.join(['/app/verify/strace','-f','-e','trace=%file','-o','/tmp/gnutls.trace',
        '/app/verify/probe','load','/app/extra/lib/libvlccore.so.9','/app/extra/'+plugin])+
        '; grep -F \'"/etc/gnutls/config"\' /tmp/gnutls.trace; cat /tmp/gnutls.trace' for plugin in sorted(GNUTLS))
    gnuprobe=fp(wrapped(['/bin/bash','-ec',commands]),extra_env={'GNUTLS_SYSTEM_PRIORITY_FILE':'/etc/gnutls/config'})
    gnuprobe.insert(2,'--allow=devel')
    cmd('gnutls-config-overrides',gnuprobe,timeout=90)
    sofa='/app/extra/share/vlc/hrtfs/dodeca_and_7channel_3DSL_HRTF.sofa'
    cmd('sofa-explicit-runtime-data',fp(wrapped(['/app/verify/probe','sofa',
        '/app/extra/lib/vlc/plugins/audio_filter/libspatialaudio_plugin.so',sofa])))
    # Only the diagnostic sandbox gets ptrace permission; /usr remains Platform.
    trace=fp(['/bin/bash','-ec',
        '/app/verify/strace -f -e trace=%file -o /tmp/paths.trace /app/extra/bin/cvlc --ignore-config --list; cat /tmp/paths.trace'])
    trace.insert(2,'--allow=devel')
    traced=cmd('runtime-file-trace',trace,timeout=90)
    text=(out/'runtime-file-trace.log').read_text(errors='replace')
    bad=[line for line in text.splitlines() if re.search(r'"/(?:work|home/runner)/',line)]
    result('runtime-file-paths','pass' if traced and not bad and '"/etc/gnutls/config"' in text else 'fail',
           f'{len(bad)} temporary filesystem accesses; optional runtime GnuTLS policy must be observed')
    cmd('qt-private-abi',fp(['/usr/bin/python3',root/'qt_abi.py','--payload','/app/extra',
        '--runtime',runtime_root,'--arch',arch,'--inputs',input_file,'--output','/app/verify/qt-abi.json'],sdk=True),timeout=90)
    record['qt_private_abi']=json.loads((app/'files/verify/qt-abi.json').read_text())
    shutil.copy2(app/'files/verify/qt-abi.json',out/'qt-abi.json')
    shared=['/app/extra/'+x['path'] for x in elf['objects'] if x['shared']]
    cmd('platform-symbol-resolution',fp(wrapped(['/app/verify/probe','load','/app/extra/lib/libvlccore.so.9']+shared)),timeout=120)
    executables=[x for x in elf['objects'] if not x['shared']]
    loader_commands='; '.join(shlex.join([x['interpreter'],'--list','/app/extra/'+x['path']]) for x in executables)
    cmd('platform-executable-dependencies',fp(wrapped(['/bin/bash','-ec',loader_commands])))
    cmd('startup-version',fp(wrapped(['/app/extra/bin/vlc-nightly','--version'])))
    text=(out/'startup-version.log').read_text()
    result('version-matches-inputs','pass' if lock['version'] in text else 'fail',lock['version'])
    cmd('plugin-enumeration',fp(wrapped(['/app/extra/bin/vlc-nightly','-I','dummy','--ignore-config','--list'])))
    cmd('qml-runtime-imports',fp(wrapped(['/app/verify/qml-probe']),extra_env={'QT_QPA_PLATFORM':'offscreen'}))
    for file in ('h264-aac.mp4','vp8-vorbis.webm'):
        cmd('decode-'+file,fp(wrapped(['/app/verify/probe','decode','/app/verify/fixtures/'+file])),timeout=25)
    from audio import exercise as audio_exercise
    audio_exercise(out,fp,wrapped,cmd,result)
    # Move, do not copy: no canonical /app/extra and no work/deps/source grants.
    moved=app/'files/relocated/extra';moved.parent.mkdir(exist_ok=True)
    shutil.move(str(app/'files/extra'),moved)
    try:
        cmd('relocated-startup',fp(wrapped(['/app/relocated/extra/bin/vlc-nightly','--version'],'/app/relocated/extra')))
        cmd('relocated-symbol-resolution',fp(wrapped(['/app/verify/probe','load',
            '/app/relocated/extra/lib/libvlccore.so.9']+[x.replace('/app/extra/','/app/relocated/extra/') for x in shared],
            '/app/relocated/extra')),timeout=120)
        cmd('relocated-playback',fp(wrapped(['/app/verify/probe','decode','/app/verify/fixtures/h264-aac.mp4'],
                                          '/app/relocated/extra')),timeout=25)
        cmd('relocated-cli-alias',fp(['/app/relocated/extra/bin/cvlc','--version']))
        cmd('relocated-vlc-direct',fp(['/app/relocated/extra/bin/vlc','--version']))
        cmd('relocated-cvlc-playback',fp(['/app/relocated/extra/bin/cvlc','--ignore-config',
            '--aout=dummy','--vout=dummy','--play-and-exit','/app/verify/fixtures/h264-aac.mp4']),timeout=25)
        cmd('relocated-sofa-runtime-data',fp(wrapped(['/app/verify/probe','sofa',
            '/app/relocated/extra/lib/vlc/plugins/audio_filter/libspatialaudio_plugin.so',
            '/app/relocated/extra/share/vlc/hrtfs/dodeca_and_7channel_3DSL_HRTF.sofa'],'/app/relocated/extra')))
    finally:shutil.move(str(moved),app/'files/extra')
    # Local HTTP/HLS are deterministic; external reachability is reported separately.
    from http_fixture import fixture_server
    with fixture_server(target,out/'http-fixture.jsonl') as base:
        record['local_http_base']=base
        # Independent request from the same Platform sandbox used for VLC.
        # No proxy for this diagnostic loopback client; VLC's settings stay unchanged.
        cmd('http-fixture-reachability',fp(['/bin/bash','-ec',
            'readlink /proc/self/ns/net; for url in "$@"; do '
            'curl --noproxy "*" --fail --silent --show-error --connect-timeout 2 --max-time 5 '
            '--dump-header - --output /dev/null "$url"; done','test',
            base+'/h264-aac.mp4',base+'/hls/index.m3u8',base+'/hls/index0.ts']),timeout=25)
        for suffix in ('h264-aac.mp4','hls/index.m3u8'):
            cmd('http-decode-'+suffix.replace('/','-'),fp(wrapped(['/app/verify/probe','decode',base+'/'+suffix])),timeout=25)
        # GUI/MPRIS tests use the existing desktop or the private CI Xvfb session.
        from gui import exercise
        exercise(a,app,out,fp,wrapped,cmd,result,base,record)
        if a.trace_http:
            from network_trace import capture
            record['http_network_diagnostics']=[]
            for suffix in ('h264-aac.mp4','hls/index.m3u8'):
                name='http-decode-'+suffix.replace('/','-')
                original=next(x for x in checks if x['name']==name)
                evidence=capture(app/'files/verify/strace',
                    fp(wrapped(['/app/verify/probe','decode',base+'/'+suffix])),
                    out,name,original)
                record['http_network_diagnostics'].append(evidence)
            # No result() calls: traced replays cannot replace mandatory outcomes.

    result('hardware-acceleration','unavailable' if not list(Path('/dev/dri').glob('renderD*')) else 'untested',
           'no render device' if not list(Path('/dev/dri').glob('renderD*')) else 'requires real GPU playback review',False)
    result('physical-audio-quality','untested','PCM callbacks/device monitor do not establish audible quality',False)
    result('native-other-architecture','untested','requires its own native runner',False)
    result('github-actions-execution','untested','local tests do not establish hosted workflow success',False)
except SystemExit:
    raise
except Exception as e:
    result('verification-driver','fail',str(e))
finally:
    write_report()
raise SystemExit(0 if record['automated_status'] in ('pass','waived') else 1)
