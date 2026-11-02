#!/usr/bin/env python3
"""Compile the actual patched transport/write functions with deterministic I/O.
Run only inside the KDE SDK. No VLC library or contrib rebuild is performed.
"""
from pathlib import Path
import subprocess
import sys
import tempfile


def function(text,signature):
    start=text.index(signature);brace=text.index('{',start);depth=1;end=brace+1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]


source=(Path(sys.argv[1])/'src/network/stream.c').read_text()
connect=function(source,'static ssize_t vlc_tls_ConnectWrite(')
write=function(source,'ssize_t vlc_tls_Write(')
setup=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <sys/socket.h>
#include <sys/uio.h>
#include <poll.h>
#include <unistd.h>
typedef struct vlc_tls vlc_tls_t;
struct vlc_tls_operations { ssize_t (*writev)(vlc_tls_t *,const struct iovec *,unsigned); };
struct vlc_tls { const struct vlc_tls_operations *ops; };
typedef struct { vlc_tls_t tls; int fd; struct sockaddr *peer; socklen_t peerlen; } vlc_tls_socket_t;
static int fault,connect_fault,wait_fault,connects,waits,sends,fasts;
static bool partial;
static char received[256];static size_t received_len;
static void accept_bytes(const struct iovec *iov,unsigned count,size_t limit) {
 for(unsigned i=0;i<count && limit;i++) {
  size_t n=iov[i].iov_len<limit?iov[i].iov_len:limit;
  assert(received_len+n<=sizeof(received));memcpy(received+received_len,iov[i].iov_base,n);
  received_len+=n;limit-=n;
 }
}
static ssize_t vlc_tls_SocketWrite(vlc_tls_t *t,const struct iovec *iov,unsigned count) {
 (void)t;sends++;size_t n=0;for(unsigned i=0;i<count;i++)n+=iov[i].iov_len;
 accept_bytes(iov,count,n);return n;
}
static const struct vlc_tls_operations vlc_tls_socket_ops={vlc_tls_SocketWrite};
static ssize_t vlc_sendmsg(int fd,const struct msghdr *msg,int flags) {
 (void)fd;assert(flags==MSG_FASTOPEN);fasts++;
 if(fault){errno=fault;return -1;}
 size_t n=0;for(size_t i=0;i<msg->msg_iovlen;i++)n+=msg->msg_iov[i].iov_len;
 if(partial && n>2)n=2;accept_bytes(msg->msg_iov,msg->msg_iovlen,n);return n;
}
static int vlc_tls_WaitConnect(vlc_tls_t *t) {(void)t;waits++;if(wait_fault){errno=wait_fault;return -1;}return 0;}
static ssize_t vlc_tls_Connect(vlc_tls_t *t) {(void)t;connects++;if(connect_fault==EINPROGRESS)return vlc_tls_WaitConnect(t);if(connect_fault){errno=connect_fault;return -1;}return 0;}
static bool vlc_killed(void){return false;}
static int vlc_tls_GetPollFD(vlc_tls_t *t,short *events){(void)t;(void)events;return 1;}
static int vlc_poll_i11e(struct pollfd *p,unsigned n,int timeout){(void)p;(void)n;(void)timeout;return 1;}
'''
tests=r'''
static void run(int f,int c,int w,bool part,bool success) {
 fault=f;connect_fault=c;wait_fault=w;partial=part;
 connects=waits=sends=fasts=0;received_len=0;
 const struct vlc_tls_operations fastops={vlc_tls_ConnectWrite};
 vlc_tls_socket_t sock={.tls={&fastops},.fd=1};
 const char payload[]="GET /media HTTP/1.1\r\n\r\n";
 errno=0;ssize_t result=vlc_tls_Write(&sock.tls,payload,sizeof(payload)-1);int saved=errno;
 assert(fasts==1);
 if(success) {
  assert(result==(ssize_t)sizeof(payload)-1);
  assert(received_len==sizeof(payload)-1 && !memcmp(received,payload,received_len));
  assert(connects==(f!=0));assert(waits==(f==EINPROGRESS));
 } else {
  assert(result==-1 && received_len==0 && sends==0);
  assert(saved==(w?w:(c?c:f)));
 }
}
int main(void) {
 run(0,0,0,false,true);run(0,0,0,true,true);
 run(EINPROGRESS,0,0,false,true);
 run(EINPROGRESS,0,EACCES,false,false);
 run(EOPNOTSUPP,0,0,false,true);
 run(EACCES,0,0,false,true);
 run(EACCES,EACCES,0,false,false);
 run(EACCES,EINPROGRESS,EACCES,false,false);
 run(EPERM,0,0,false,false);
 /* Multiple iovecs accepted exactly once by the real first-write callback. */
 fault=0;partial=false;received_len=0;
 vlc_tls_socket_t sock={.fd=1};char a[]="abc",b[]="def";
 struct iovec iov[]={{a,3},{b,3}};
 assert(vlc_tls_ConnectWrite(&sock.tls,iov,2)==6);
 assert(received_len==6 && !memcmp(received,"abcdef",6));
 puts("PASS: actual VLC transport/write functions: success, partial, EINPROGRESS, unsupported, EACCES, denial, no duplicate payload, iovecs");
}
'''
with tempfile.TemporaryDirectory() as directory:
    file=Path(directory)/'transport.c';binary=Path(directory)/'transport'
    file.write_text(setup+'\n'+connect+'\n'+write+'\n'+tests)
    subprocess.run(['gcc','-std=c17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',str(file),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)
