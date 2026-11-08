"""Known runtime-path classifications with build-bound, informational source drift.

The historical hashes are an audit baseline, not an upstream source allowlist.
Build-time evidence is checked against the pinned Git tree and current recipes;
unknown runtime references and consumers still fail closed.
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

def recipe_hashes(recipe):
    return {name:hashlib.sha256((Path(recipe)/name).read_bytes()).hexdigest()
            for name in RECIPE_PATHS if (Path(recipe)/name).is_file()}


def collect_evidence(source,sha,recipe):
    # ls-tree/show read the exact pinned Git objects, never a different HEAD.
    subprocess.check_call(['git','-C',str(source),'cat-file','-e',sha+'^{commit}'])
    names=subprocess.check_output(['git','-C',str(source),'ls-tree','-r','--name-only',sha,'--',*SOURCE_PATHS],text=True).splitlines()
    sources={name:hashlib.sha256(subprocess.check_output(['git','-C',str(source),'show',sha+':'+name])).hexdigest() for name in names}
    return dict(schema=1,source_sha=sha,sources=sources,recipes=recipe_hashes(recipe))


def evidence_matches(evidence,sha,expected=None):
    """Validate structure/source identity, and actual inputs when supplied.

    Build callers MUST supply freshly collected expected evidence. Archive and
    pair validation bind that evidence to the embedded lock and native reports.
    No comparison against the historical content allowlist is made here.
    """
    if (not isinstance(evidence,dict) or set(evidence)!={'schema','source_sha','sources','recipes'}
            or type(evidence.get('schema')) is not int or evidence['schema']!=1
            or not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{40}',sha)
            or evidence.get('source_sha')!=sha):return False
    for section,paths in (('sources',SOURCE_PATHS),('recipes',RECIPE_PATHS)):
        hashes=evidence.get(section)
        if not isinstance(hashes,dict):return False
        for name,digest in hashes.items():
            if (not isinstance(name,str) or any(part in ('','..','.') for part in name.split('/'))
                    or not any(name==p or (section=='sources' and name.startswith(p+'/')) for p in paths)
                    or not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest)):return False
    return expected is None or evidence==expected


def hash_drift(evidence):
    """Report added, removed and changed hashes without approving runtime paths."""
    baseline=json.loads(Path(__file__).with_name('runtime-path-policy.json').read_text())
    drift={}
    for section in ('sources','recipes'):
        old=baseline[section];new=evidence[section]
        drift[section]=dict(
            added={n:new[n] for n in sorted(new.keys()-old.keys())},
            removed={n:old[n] for n in sorted(old.keys()-new.keys())},
            changed={n:dict(before=old[n],after=new[n]) for n in sorted(old.keys()&new.keys()) if old[n]!=new[n]})
    return dict(baseline_source_sha=baseline['source_sha'],source_sha=evidence['source_sha'],**drift)

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
            if not (re.fullmatch(r"/(?:work|tmp|home/runner|snap)/[^\s'\"]*",value)
                    and re.search(r'/(?:share|etc)(?:/|$)',value)):
                continue # source assertions/configuration text remain in ELF diagnostics
            row=dict(path=finding['path'],reference=value,status='fail',category='unreviewed')
            if revision>=2 and evidence_matches(evidence,sha):
                prefix=r'/work/deps/[0-9a-f]{64}/contrib/(?:x86_64|aarch64)-[^/]+/'
                suffix=value.removeprefix(re.match(prefix,value)[0]) if re.match(prefix,value) else None
                if row['path'] in GNUTLS and suffix=='etc/gnutls/config':
                    row.update(status='pass',category='incorrect-default-overridden',
                        reason='Known GnuTLS default; launcher override retained, API/trace diagnostics available')
                elif row['path'] in GPG_ERROR and suffix=='etc':
                    row.update(status='pass',category='dormant-library-default',
                        reason='Known libgpg-error SYSCONF default; source/configuration drift is reported separately')
                elif row['path']==SOFA and suffix=='share/libmysofa/default.sofa':
                    row.update(status='pass',category='dormant-library-default',
                        reason='mysofa_load NULL fallback; VLC/spatialaudio always passes non-NULL std::string::c_str() from VLC data path')
            dispositions.append(row)
    return dispositions

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('sha');p.add_argument('recipe',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();a.output.write_text(json.dumps(collect_evidence(a.source,a.sha,a.recipe),indent=2)+'\n')
