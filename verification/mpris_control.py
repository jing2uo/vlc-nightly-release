"""Bounded ordinary MPRIS state transitions; never used by the rapid stress case."""
import re
import time


def pause_resume(bus,call,events,clock=time.monotonic,sleep=time.sleep):
    def invoke(method,*args):
        response=call(bus,method,*args)
        events.append(dict(time=clock(),method=method,returncode=response.returncode,
                           stdout=response.stdout,stderr=response.stderr))
        return response
    def state():
        r=invoke('org.freedesktop.DBus.Properties.Get','org.mpris.MediaPlayer2.Player','PlaybackStatus')
        return r.stdout if r.returncode==0 else ''
    def position():
        r=invoke('org.freedesktop.DBus.Properties.Get','org.mpris.MediaPlayer2.Player','Position')
        values=re.findall(r'int64 (\d+)',r.stdout) if r.returncode==0 else []
        return int(values[0]) if values else None
    if invoke('org.mpris.MediaPlayer2.Player.Pause').returncode:return False
    paused=False;deadline=clock()+2
    while clock()<deadline:
        if 'Paused' in state():paused=True;break
        sleep(.1)
    before=position()
    # Send one Play even when Pause confirmation failed, so diagnostics do not
    # leave the remaining ordinary playback test intentionally paused.
    if invoke('org.mpris.MediaPlayer2.Player.Play').returncode:return False
    deadline=clock()+2
    while clock()<deadline:
        playing='Playing' in state();after=position()
        if paused and playing and before is not None and after is not None and after>before+100000:
            return True
        sleep(.1)
    return False
