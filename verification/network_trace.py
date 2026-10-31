"""Opt-in diagnostic replays; never substitute for mandatory untraced results."""
import os
from pathlib import Path
import signal
import subprocess
import time

# Raw buffer syscalls retain fd, flags, lengths and errno without disclosing data.
# In raw output MSG_FASTOPEN is bit 0x20000000 (MSG_NOSIGNAL is 0x4000).
BUFFER_CALLS='sendmsg,recvmsg,sendto,recvfrom,sendmmsg,recvmmsg,read,write,readv,writev'
TRACE_CALLS=('socket,socketpair,connect,getsockopt,setsockopt,shutdown,close,dup,dup2,dup3,'
             'fcntl,poll,ppoll,'+BUFFER_CALLS)


def capture(tracer,argv,out,name,untraced,timeout=30):
    """Trace outside Flatpak: the replay receives exactly the original argv/env.

    ptrace can affect timing and security mediation, even with unchanged flags.
    A successful replay therefore cannot clear an original verification failure.
    """
    out=Path(out)
    trace=out/(name+'.network.trace')
    log=out/(name+'.traced.log')
    evidence=dict(untraced=dict(untraced),traced_returncode=None,
                  trace=trace.name,log=log.name,timeout_seconds=timeout,
                  sandbox_arguments_changed=False,
                  limitation='ptrace may change timing or security mediation; replay is diagnostic only')
    call=[str(tracer),'-f','-ttt','-T','-s','0','-e','trace='+TRACE_CALLS,
          '-e','raw='+BUFFER_CALLS,'-o',str(trace),'--',*map(str,argv)]
    start=time.monotonic()
    with log.open('w') as output:
        try:
            with subprocess.Popen(call,stdout=output,stderr=subprocess.STDOUT,
                                  start_new_session=True) as process:
                try:evidence['traced_returncode']=process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL)
                    process.wait()
                    evidence['timed_out']=True
                    evidence['traced_returncode']=process.returncode
        except OSError as error:
            evidence['launch_error']=str(error)
        evidence['trace_nonempty']=trace.is_file() and trace.stat().st_size>0
    evidence['duration_seconds']=round(time.monotonic()-start,3)
    return evidence
