#!/usr/bin/env python3
"""Repackage an audited historical build; strip only the staged ELF copies."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
root=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root/'verification'))
from archive import audit,require
p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('destination',type=Path)
p.add_argument('--arch',choices=['x86_64','aarch64'],default=os.uname().machine)
a=p.parse_args();src=a.source.resolve();dest=a.destination.resolve();arch=a.arch
require(not dest.exists(),'candidate destination already exists; refusing replacement')
old=json.loads((src/'inputs.json').read_text());metadata=json.loads((src/f'build-{arch}.json').read_text())
asset=src/f'vlc-{old.get("artifact_version",old["version"])}-{arch}.tar.zst'
stage=dest.parent/(dest.name+'-stage');require(not stage.exists(),'staging directory already exists')
start=time.monotonic();original=audit(asset,arch,old,metadata,destination=stage)
dest.mkdir(parents=True);payload=stage/'extra'
# Preserve the original binary build inputs; the new lock describes packaging.
def elf_inventory():
 result={}
 for path in payload.rglob('*'):
  if not path.is_file() or path.is_symlink():continue
  with path.open('rb') as f:
   if f.read(4)!=b'\x7fELF':continue
  with path.open('rb') as f:result[str(path.relative_to(payload))]=hashlib.file_digest(f,'sha256').hexdigest()
 return result
original_elfs=elf_inventory()
shutil.copy2(payload/'share/vlc/build/inputs.json',payload/'share/vlc/build/binary-inputs.json')
subprocess.run([sys.executable,root/'scripts/prepare-payload.py',payload,src.parent/'source',old['upstream_sha']],check=True)
subprocess.run([sys.executable,root/'scripts/metadata.py','repackage',src/'inputs.json',dest/'inputs.json'],check=True)
lock=json.loads((dest/'inputs.json').read_text())
(payload/'share/vlc/build/inputs.json').write_text(json.dumps(lock,indent=2)+'\n')
updated=dict(metadata,**lock,binary_build=metadata,repackaged_from=dict(sha256=original['sha256'],size=original['size'],filename=asset.name),
             packaging_run='local-task-2.1',cache_reused=True)
(dest/f'build-{arch}.json').write_text(json.dumps(updated,indent=2)+'\n')
# Prove launcher adaptation preserved every ELF before package.sh strips staged copies.
elf_hashes=elf_inventory()
expected={('bin/vlc.bin' if name=='bin/vlc' else name):digest for name,digest in original_elfs.items()}
require(elf_hashes==expected,'packaging changed an ELF binary')
env=os.environ.copy();env.update(SOURCE_DATE_EPOCH=str(lock['source_epoch']),DIST_DIR=str(dest),EXTRACT_TMPDIR=str(dest.parent))
subprocess.run([root/'scripts/package.sh',payload,arch,lock['artifact_version']],env=env,check=True)
# package.sh strips staged copies; record the hashes of the actual shipped ELFs.
(dest/f'elf-sha256-{arch}.json').write_text(json.dumps(elf_inventory(),indent=2)+'\n')
newasset=dest/f'vlc-{lock["artifact_version"]}-{arch}.tar.zst'
result=audit(newasset,arch,lock,updated)
result.update(elapsed_seconds=round(time.monotonic()-start,2),elfs_recompiled=False,original_sha256=original['sha256'])
(dest/'repackage.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
shutil.rmtree(stage)
