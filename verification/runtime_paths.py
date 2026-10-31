"""Narrow, content-reviewed disposition of the nine Phase 2 findings.

Unknown paths/consumers and changes to relevant source/configuration fail closed. Runtime probes
and file traces are separate mandatory checks: string classification alone is
not proof that the launcher applies a policy or that data opens successfully.
"""
import re
import hashlib
import json
from pathlib import Path
import subprocess

# Hash only source/configuration that supports the reviewed path arguments.
SOURCE_PATHS=(
 'contrib/bootstrap','contrib/src/main.mak',
 'contrib/src/gnutls','contrib/src/gpg-error','contrib/src/gcrypt',
 'contrib/src/mysofa','contrib/src/spatialaudio',
 'modules/audio_filter/channel_mixer/spatialaudio.cpp','include/vlc_gcrypt.h',
 'modules/access/dcp','modules/demux/adaptive/encryption',
 'modules/access/srt.c','modules/access/rist.c','modules/access/rist.h','modules/access/nfs.c',
 'modules/access_output/srt.c','modules/access_output/rist.c','modules/misc/gnutls.c',
 'src/config/dirs.c','src/posix/dirs.c','src/linux/dirs.c',
 'share/hrtfs/dodeca_and_7channel_3DSL_HRTF.sofa')
RECIPE_PATHS=('scripts/contrib.sh','scripts/build.sh','scripts/vlc-nightly','scripts/prepare-payload.py')

def collect_evidence(source,sha,recipe):
    names=subprocess.check_output(['git','-C',str(source),'ls-tree','-r','--name-only',sha,'--',*SOURCE_PATHS],text=True).splitlines()
    if not all(any(n==p or n.startswith(p+'/') for n in names) for p in SOURCE_PATHS):
        raise ValueError('reviewed runtime-path source was removed or renamed')
    sources={name:hashlib.sha256(subprocess.check_output(['git','-C',str(source),'show',sha+':'+name])).hexdigest() for name in names}
    recipes={name:hashlib.sha256((Path(recipe)/name).read_bytes()).hexdigest() for name in RECIPE_PATHS}
    return dict(schema=1,source_sha=sha,sources=sources,recipes=recipes)

def evidence_matches(evidence,sha):
    reviewed=json.loads((Path(__file__).with_name('runtime-path-policy.json')).read_text())
    return (isinstance(evidence,dict) and evidence.get('schema')==1 and evidence.get('source_sha')==sha
            and evidence.get('sources')==reviewed['sources'] and evidence.get('recipes')==reviewed['recipes'])
GNUTLS={
 'lib/vlc/plugins/access/libaccess_srt_plugin.so',
 'lib/vlc/plugins/access/libnfs_plugin.so',
 'lib/vlc/plugins/access/librist_plugin.so',
 'lib/vlc/plugins/access_output/libaccess_output_rist_plugin.so',
 'lib/vlc/plugins/access_output/libaccess_output_srt_plugin.so',
 'lib/vlc/plugins/misc/libgnutls_plugin.so',
}
GPG_ERROR={'lib/vlc/plugins/access/libdcp_plugin.so','lib/vlc/plugins/demux/libadaptive_plugin.so'}
SOFA='lib/vlc/plugins/audio_filter/libspatialaudio_plugin.so'


def classify(findings,sha,revision,evidence=None):
    dispositions=[]
    for finding in findings:
        for line in finding['strings']:
            value=re.sub(r'^\[.*?\]\s*','',line)
            if not (re.fullmatch(r"/(?:work|home/runner|snap)/[^\s'\"]*",value)
                    and re.search(r'/(?:share|etc)(?:/|$)',value)):
                continue # source assertions/configuration text remain in ELF diagnostics
            row=dict(path=finding['path'],reference=value,status='fail',category='unreviewed')
            if revision>=2 and evidence_matches(evidence,sha):
                prefix=r'/work/deps/[0-9a-f]{64}/contrib/(?:x86_64|aarch64)-[^/]+/'
                suffix=value.removeprefix(re.match(prefix,value)[0]) if re.match(prefix,value) else None
                if row['path'] in GNUTLS and suffix=='etc/gnutls/config':
                    row.update(status='pass',category='incorrect-default-overridden',
                        reason='GnuTLS secure_getenv override from every packaged app entry point; API/trace gates required')
                elif row['path'] in GPG_ERROR and suffix=='etc':
                    row.update(status='pass',category='dormant-library-default',
                        reason='libgpg-error fnameconcat SYSCONF branch; pinned VLC/asdcplib/gcrypt consumers do not request that flag')
                elif row['path']==SOFA and suffix=='share/libmysofa/default.sofa':
                    row.update(status='pass',category='dormant-library-default',
                        reason='mysofa_load NULL fallback; VLC/spatialaudio always passes non-NULL std::string::c_str() from VLC data path')
            dispositions.append(row)
    return dispositions

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('sha');p.add_argument('recipe',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();a.output.write_text(json.dumps(collect_evidence(a.source,a.sha,a.recipe),indent=2)+'\n')
