#!/usr/bin/env python3
"""Packaging adaptation only: every public entry point uses the same environment."""
from pathlib import Path
import shutil
import hashlib
import json
import subprocess
import sys

payload=Path(sys.argv[1]);root=Path(__file__).resolve().parent
binary=payload/'bin/vlc'
assert binary.read_bytes()[:4]==b'\x7fELF', 'expected upstream VLC ELF, not an already adapted payload'
assert not (payload/'bin/vlc.bin').exists(), 'refusing to replace a packaged binary'
binary.rename(payload/'bin/vlc.bin')
shutil.copy2(root/'vlc-nightly',payload/'bin/vlc-nightly')
(payload/'bin/vlc-nightly').chmod(0o755)
binary.symlink_to('vlc-nightly')
for name in ('cvlc','nvlc','qvlc','rvlc','svlc'):
    path=payload/'bin'/name
    if not path.exists():continue
    text=path.read_text()
    assert text.count('exec /app/extra/bin/vlc ')==1, f'unknown upstream alias: {name}'
    path.write_text(text.replace('exec /app/extra/bin/vlc ', 'exec "$(dirname "$0")/vlc" '))

# Upstream distributes this data but share/Makefile.am does not install it.
source=Path(sys.argv[2]);sha=sys.argv[3]
relative='share/hrtfs/dodeca_and_7channel_3DSL_HRTF.sofa'
data=subprocess.check_output(['git','-C',str(source),'show',sha+':'+relative])
target=payload/'share/vlc/hrtfs/dodeca_and_7channel_3DSL_HRTF.sofa'
target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);target.chmod(0o644)
provenance=payload/'share/vlc/build/packaging-data.json';provenance.parent.mkdir(parents=True,exist_ok=True)
provenance.write_text(json.dumps(dict(upstream_sha=sha,source_path=relative,sha256=hashlib.sha256(data).hexdigest()),indent=2)+'\n')
