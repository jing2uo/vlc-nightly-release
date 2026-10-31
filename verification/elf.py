#!/usr/bin/env python3
"""SDK readelf inspection; actual symbol resolution is done in Platform by probe."""
import json
from pathlib import Path
import re
import subprocess
import sys

prefix=Path(sys.argv[1]);report=Path(sys.argv[2]);objects=[];failures=[];references=[]
for p in sorted(prefix.rglob('*')):
    if p.is_symlink() or not p.is_file(): continue
    with p.open('rb') as f: magic=f.read(4)
    if magic!=b'\x7fELF': continue
    dynamic=subprocess.check_output(['readelf','-dW',str(p)],text=True)
    needed=re.findall(r'\(NEEDED\).*?\[(.*?)\]',dynamic)
    paths=re.findall(r'\((?:RPATH|RUNPATH)\).*?\[(.*?)\]',dynamic)
    for value in needed:
        if '/' in value: failures.append(f'{p}: absolute/non-basename NEEDED {value}')
    for value in paths:
        for directory in value.split(':'):
            if not directory or not (directory.startswith(('$ORIGIN/','${ORIGIN}/','/app/extra/','/usr/lib/'))):
                failures.append(f'{p}: unexpected loader path {directory}')
            if any(s in directory for s in ('/work/','/home/runner/','/tmp/','/snap/','ubuntu')):
                failures.append(f'{p}: temporary/host loader path {directory}')
    header=subprocess.check_output(['readelf','-hW',str(p)],text=True)
    # PIE executables also have type DYN; PT_INTERP distinguishes executables.
    phdr=subprocess.check_output(['readelf','-lW',str(p)],text=True)
    shared='DYN ' in header and ' INTERP ' not in phdr
    objects.append(dict(path=str(p.relative_to(prefix)),needed=needed,loader_paths=paths,shared=shared,
                        interpreter=(re.findall(r'Requesting program interpreter: ([^\]]+)',phdr) or [None])[0]))
    # Allocated string sections exclude DWARF. Build configuration/__FILE__ strings
    # are retained as diagnostics; they are not automatically runtime searches.
    for section in ('.rodata','.dynstr'):
        r=subprocess.run(['readelf','-p',section,str(p)],capture_output=True,text=True,errors="replace")
        hits=[line.strip() for line in r.stdout.splitlines() if re.search(r'/(?:work|tmp|home/runner|snap)/',line)]
        if hits: references.append(dict(path=str(p.relative_to(prefix)),section=section,strings=hits))
result=dict(status='fail' if failures else 'pass',objects=objects,failures=failures,
            temporary_strings=references,temporary_strings_note='configuration/assertion strings require review; loader paths fail above')
report.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(dict(status=result['status'],objects=len(objects),failures=failures,
                      objects_with_temporary_strings=len({r['path'] for r in references}))))
raise SystemExit(bool(failures))
