"""Verify real PulseAudio output into a private CI null sink (no host sink changes)."""
import array
import json
import math
import os
import shutil
import subprocess
import time


def exercise(out,fp,wrapped,cmd,result):
    if os.getenv('VLC_PRIVATE_PULSE')!='1':
        result('pulse-audio-output','unavailable','private monitor not provisioned; decoded PCM is checked separately',False)
        return
    pcm=out/'pulse-monitor.s16le'
    with pcm.open('wb') as f:
        recorder=subprocess.Popen(['parec','--device=vlc_verify.monitor','--format=s16le',
                                   '--rate=48000','--channels=1'],stdout=f,stderr=subprocess.PIPE)
        try:
            time.sleep(.3)
            played=cmd('pulse-playback',fp(wrapped(['/app/extra/bin/vlc-nightly',
                '--ignore-config','-I','dummy','--no-one-instance','--aout=pulse','--vout=dummy',
                '--play-and-exit','-vvv','/app/verify/fixtures/h264-aac.mp4']),pulse=True),timeout=25)
            time.sleep(.3)
        finally:
            recorder.terminate();_,err=recorder.communicate(timeout=5)
    data=array.array('h');data.frombytes(pcm.read_bytes())
    # Analyze the loudest one-second interval to exclude startup/trailing silence.
    chunks=[data[i:i+48000] for i in range(0,len(data)-48000+1,48000)]
    block=max(chunks,key=lambda c:sum(x*x for x in c),default=[])
    rms=math.sqrt(sum(x*x for x in block)/len(block)) if block else 0
    real=sum(x*math.cos(2*math.pi*997*i/48000) for i,x in enumerate(block))
    imag=sum(x*math.sin(2*math.pi*997*i/48000) for i,x in enumerate(block))
    amplitude=2*math.hypot(real,imag)/len(block) if block else 0
    evidence=dict(samples=len(data),rms=rms,amplitude_997_hz=amplitude,recorder_stderr=err.decode(errors='replace'))
    (out/'pulse-monitor.json').write_text(json.dumps(evidence,indent=2)+'\n')
    # Audio files are transient diagnostics; numeric evidence is sufficient.
    pcm.unlink()
    result('pulse-audio-output','pass' if played and rms>50 and amplitude>50 else 'fail',
           f'private null sink: samples={len(data)}, RMS={rms:.1f}, 997 Hz amplitude={amplitude:.1f}',True)
