#define _POSIX_C_SOURCE 200809L
#include <vlc/vlc.h>
#include <dlfcn.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static _Atomic unsigned frames, samples, nonzero;
static unsigned char pixels[160*96*4] __attribute__((aligned(64)));
static void *lock_frame(void *opaque, void **planes) { (void)opaque; *planes=pixels; return NULL; }
static void display_frame(void *opaque, void *picture) { (void)opaque;(void)picture;atomic_fetch_add(&frames,1); }
static void audio_play(void *opaque,const void *data,unsigned count,int64_t pts) {
    (void)opaque;(void)pts;const int16_t *s=data;
    atomic_fetch_add(&samples,count);
    for(unsigned i=0;i<count*2;i++) if(s[i]) { atomic_fetch_add(&nonzero,1);break; }
}
static int load_all(int argc,char **argv) {
    int failed=0;
    for(int i=3;i<argc;i++) {
        fflush(NULL);pid_t pid=fork();
        if(pid<0) return 2;
        if(!pid) {
            if(!dlopen(argv[2],RTLD_NOW|RTLD_GLOBAL)||!dlopen(argv[i],RTLD_NOW|RTLD_LOCAL)) {
                fprintf(stderr,"FAIL\t%s\t%s\n",argv[i],dlerror());exit(1);
            }
            printf("PASS\t%s\n",argv[i]);exit(0);
        }
        int status=0;waitpid(pid,&status,0);
        if(!WIFEXITED(status)||WEXITSTATUS(status)) {
            failed++;
            if(WIFSIGNALED(status)) fprintf(stderr,"SIGNAL\t%s\t%d\n",argv[i],WTERMSIG(status));
        }
    }
    return failed?1:0;
}
static int path_probe(int argc,char **argv) {
    if(argc!=4)return 2;
    void *library=dlopen(argv[2],RTLD_NOW|RTLD_LOCAL);
    if(!library){fprintf(stderr,"%s\n",dlerror());return 1;}
    void *(*open_sofa)(const char *,float,int *,int *)=(void *(*)(const char *,float,int *,int *))dlsym(library,"mysofa_open");
    void (*close_sofa)(void *)=(void (*)(void *))dlsym(library,"mysofa_close");
    if(!open_sofa||!close_sofa)return 1;
    int length=0,error=0;void *filter=open_sofa(argv[3],48000,&length,&error);
    printf("SOFA path: %s; filter_length=%d error=%d\n",argv[3],length,error);
    int ok=filter&&length>0&&!error;if(filter)close_sofa(filter);return ok?0:1;
}
int main(int argc,char **argv) {
    if(argc==4&&!strcmp(argv[1],"sofa"))return path_probe(argc,argv);
    if(argc>=3&&!strcmp(argv[1],"load")) return load_all(argc,argv);
    if(argc!=3) { fprintf(stderr,"usage: probe decode MEDIA | probe load CORE LIB...\n");return 2; }
    const char *args[]={"--ignore-config","--no-metadata-network-access","--verbose=2"};
    libvlc_instance_t *v=libvlc_new(3,args);if(!v)return 2;
    libvlc_media_t *m=strstr(argv[2],"://")?libvlc_media_new_location(argv[2]):libvlc_media_new_path(argv[2]);
    libvlc_media_player_t *mp=libvlc_media_player_new(v,NULL,NULL);if(!m||!mp)return 2;
    libvlc_video_set_callbacks(mp,lock_frame,NULL,display_frame,NULL);
    libvlc_video_set_format(mp,"RV32",160,96,160*4);
    libvlc_audio_set_callbacks(mp,audio_play,NULL,NULL,NULL,NULL,NULL);
    libvlc_audio_set_format(mp,"S16N",48000,2);
    libvlc_media_player_set_media(mp,m);libvlc_media_release(m);
    if(libvlc_media_player_play(mp))return 1;
    struct timespec nap={0,100000000};int error=0;
    for(int i=0;i<120;i++) {
        nanosleep(&nap,NULL);
        if(libvlc_media_player_get_state(mp)==libvlc_Error){error=1;break;}
        if(atomic_load(&frames)>=12&&atomic_load(&samples)>12000&&atomic_load(&nonzero)>0)break;
    }
    libvlc_media_player_stop_async(mp);
    for(int i=0;i<50&&libvlc_media_player_get_state(mp)!=libvlc_Stopped;i++)nanosleep(&nap,NULL);
    printf("{\"frames\":%u,\"audio_samples\":%u,\"nonzero_audio_blocks\":%u,\"error\":%d}\n",
           atomic_load(&frames),atomic_load(&samples),atomic_load(&nonzero),error);
    int ok=!error&&atomic_load(&frames)>=12&&atomic_load(&samples)>12000&&atomic_load(&nonzero)>0;
    libvlc_media_player_release(mp);libvlc_release(v);return ok?0:1;
}
