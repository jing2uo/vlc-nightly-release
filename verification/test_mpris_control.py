import unittest
from types import SimpleNamespace
from mpris_control import pause_resume

class ControlTests(unittest.TestCase):
    def exercise(self,resume=True,denied=False):
        now=[0];paused=[False];pos=[600000];events=[]
        def clock():return now[0]
        def sleep(seconds):now[0]+=seconds
        def call(bus,method,*args):
            if method.endswith('.Pause'):paused[0]=True
            if method.endswith('.Play') and resume:paused[0]=False
            output='()'
            if args and args[-1]=='PlaybackStatus':output="(<'Paused'>,)" if paused[0] else "(<'Playing'>,)"
            if args and args[-1]=='Position':
                if not paused[0]:pos[0]+=150000
                output=f'(<int64 {pos[0]}>,)'
            return SimpleNamespace(returncode=1 if denied else 0,stdout=output,stderr='denied' if denied else '')
        return pause_resume('bus',call,events,clock,sleep),events,now[0]
    def test_confirmed_resume_and_position_progress(self):
        ok,events,_=self.exercise();self.assertTrue(ok);self.assertTrue(events)
    def test_accepting_play_without_resuming_fails(self):
        ok,_,elapsed=self.exercise(resume=False);self.assertFalse(ok);self.assertLess(elapsed,3)
    def test_dbus_failure_fails(self):
        ok,events,_=self.exercise(denied=True);self.assertFalse(ok);self.assertEqual(events[0]['returncode'],1)

if __name__=='__main__':unittest.main()
