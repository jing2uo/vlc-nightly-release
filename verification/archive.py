#!/usr/bin/env python3
"""Validate the complete archive namespace before any filesystem extraction."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import stat
import struct
import subprocess
import tarfile


class InvalidArtifact(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InvalidArtifact(message)


def canonical(name):
    require(isinstance(name, str) and name and '\\' not in name and '\x00' not in name,
            f'invalid path: {name!r}')
    name = name.rstrip('/')
    require(not name.startswith('/') and name == posixpath.normpath(name), f'noncanonical path: {name!r}')
    require(PurePosixPath(name).parts[0] == 'extra' and '..' not in PurePosixPath(name).parts,
            f'path outside extra/: {name!r}')
    return name


def namespace(members):
    entries = {}
    total = 0
    for m in members:
        name = canonical(m.name)
        require(name not in entries, f'duplicate entry: {name}')
        require(m.isfile() or m.isdir() or m.issym() or m.islnk(), f'special entry: {name}')
        require(not m.issparse() and not m.mode & 0o7000, f'unsafe mode/sparse file: {name}')
        require(m.uid == 0 and m.gid == 0, f'unnormalized ownership: {name}')
        require(m.size >= 0, 'negative member size')
        total += m.size
        require(total <= 8 * 2**30 and len(entries) < 100000, 'archive exceeds unpacking budget')
        entries[name] = m
    for name, m in entries.items():
        for parent in PurePosixPath(name).parents:
            p = str(parent)
            if p == '.':
                break
            require(p not in entries or entries[p].isdir(), f'non-directory ancestor: {name}')
        if not (m.issym() or m.islnk()):
            continue
        target = m.linkname
        require(target and not target.startswith('/') and '\\' not in target, f'unsafe link: {name}')
        target = canonical(posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
                           if m.issym() else target)
        seen = {name}
        while True:
            require(target in entries, f'dangling link: {name} -> {target}')
            require(target not in seen, f'cyclic link: {name}')
            seen.add(target)
            other = entries[target]
            if other.isfile():
                break
            require(other.issym() or other.islnk(), f'link must terminate at a regular file: {name}')
            target = canonical(posixpath.normpath(posixpath.join(posixpath.dirname(target), other.linkname))
                               if other.issym() else other.linkname)
    return entries, total


def stream(path):
    proc = subprocess.Popen(['zstd', '-dc', '--', str(path)], stdout=subprocess.PIPE)
    return proc, tarfile.open(fileobj=proc.stdout, mode='r|')


def drain_padding(tf):
    # Consume bounded trailing padding so a zstd pipe cannot block at tar EOF.
    count = 0
    while True:
        chunk = tf.fileobj.read(65536)
        if not chunk:
            break
        count += len(chunk)
        require(count <= 1024 * 1024 and not chunk.strip(b'\0'), 'unexpected trailing archive data/padding')


def inspect(path, expected_patches=()):
    proc, tf = stream(path)
    try:
        members = []
        total = 0
        embedded = None
        required_patches={'extra/share/vlc/build/'+p['path']:p['sha256'] for p in expected_patches}
        found_patches=set()
        for m in tf:
            # Check budgets before tarfile advances over the next member body.
            require(m.size >= 0, 'negative member size')
            total += m.size
            require(total <= 8 * 2**30 and len(members) < 100000, 'oversized archive member')
            members.append(m)
            if m.name.rstrip('/') == 'extra/share/vlc/build/inputs.json':
                require(m.isfile() and m.size < 131072, 'invalid embedded provenance')
                embedded = json.load(tf.extractfile(m))
            if m.name.rstrip('/') in required_patches:
                require(m.isfile() and m.size<1048576, 'invalid published source patch')
                name=m.name.rstrip('/')
                require(hashlib.sha256(tf.extractfile(m).read()).hexdigest()==required_patches[name], 'published source patch checksum mismatch')
                found_patches.add(name)
        require(found_patches==set(required_patches),'missing published source patches')
        drain_padding(tf)
        entries, size = namespace(members)
        require(proc.wait() == 0, 'zstd decompression failed')
        return entries, size, embedded
    finally:
        tf.close()
        proc.stdout.close()
        if proc.poll() is None:
            proc.terminate()
        proc.wait()


def extract(path, destination, entries):
    # An empty destination and two-pass extraction avoid symlink-parent attacks.
    destination.mkdir(parents=True, exist_ok=True)
    require(not any(destination.iterdir()), 'extraction destination must be empty')
    proc, tf = stream(path)
    links = []
    seen = set()
    try:
        for m in tf:
            name = canonical(m.name)
            require(name not in seen, 'duplicate member during extraction')
            seen.add(name)
            require(name in entries, 'archive changed between inspection and extraction')
            expected = entries[name]
            require((m.type,m.size,m.mode,m.linkname,m.uid,m.gid) ==
                    (expected.type,expected.size,expected.mode,expected.linkname,expected.uid,expected.gid),
                    'archive headers changed during extraction')
            out = destination / name
            if m.isdir():
                out.mkdir(parents=True, exist_ok=True)
                out.chmod(m.mode & 0o777)
            elif m.isfile():
                out.parent.mkdir(parents=True, exist_ok=True)
                with out.open('xb') as f:
                    shutil.copyfileobj(tf.extractfile(m), f)
                out.chmod(m.mode & 0o777)
            else:
                links.append((out, m))
        drain_padding(tf)
        require(seen == entries.keys(), 'missing members during extraction')
        require(proc.wait() == 0, 'zstd extraction failed')
        for out, m in links:
            if m.issym():
                out.symlink_to(m.linkname)
            else:
                target = destination / canonical(m.linkname)
                # Resolve the validated namespace, independent of link ordering.
                item = entries[canonical(m.linkname)]
                name = canonical(m.linkname)
                while not item.isfile():
                    name = canonical(posixpath.normpath(posixpath.join(posixpath.dirname(name), item.linkname))
                                     if item.issym() else item.linkname)
                    item = entries[name]
                resolved = (destination / name).resolve(strict=True)
                require(resolved.is_relative_to(destination.resolve()), 'hardlink escapes destination')
                os.link(resolved, out)
    finally:
        tf.close()
        proc.stdout.close()
        if proc.poll() is None:
            proc.terminate()
        proc.wait()


def audit(path, arch, lock, metadata, expected_sha=None, destination=None):
    with path.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    sidecar = Path(str(path) + '.sha256').read_text()
    require(sidecar == f'{digest}  {path.name}\n', 'checksum sidecar mismatch/unsafe filename')
    require(expected_sha is None or digest == expected_sha, 'trusted SHA-256 mismatch')
    size = path.stat().st_size
    require(0 < size < 2**31 and Path(str(path)+'.size').read_text() == f'{size}\n', 'asset size mismatch/limit')
    require(re.fullmatch('[0-9a-f]{40}', lock['upstream_sha']), 'invalid source SHA')
    require(metadata['architecture'] == arch, 'metadata architecture mismatch')
    require(lock['sdk'] == 'org.kde.Sdk//6.11' and lock['runtime'] == 'org.kde.Platform//6.11', 'wrong target')
    for key, value in lock.items():
        require(metadata.get(key) == value, f'build metadata mismatch: {key}')
    entries, unpacked, embedded = inspect(path,lock.get('source_patches',{}).get('patches',[]))
    require(embedded == lock, 'embedded input lock mismatch')
    for name in ('extra/bin/vlc', 'extra/bin/vlc-nightly', 'extra/lib/vlc/vlc-cache-gen'):
        require(name in entries and (entries[name].isfile() or entries[name].issym()) and entries[name].mode & 0o111,
                f'missing/nonexecutable: {name}')
    for name in ('extra/lib/libvlc.so.12', 'extra/lib/libvlccore.so.9',
                 'extra/share/vlc', 'extra/share/locale'):
        require(name in entries, f'missing payload component: {name}')
    for name in ('libqt_plugin.so', 'libavcodec_plugin.so'):
        require(any(n.endswith('/'+name) for n in entries), f'missing required plugin: {name}')
    if lock.get('packaging_revision',0)>=3:
        patches=lock.get('source_patches',{})
        require(patches.get('base_sha')==lock['upstream_sha'] and bool(patches.get('patches')), 'missing patch provenance')
        reviewed=json.loads((Path(__file__).resolve().parent.parent/'patches/manifest.json').read_text())
        require(patches.get('schema')==reviewed['schema'] and patches.get('patches')==reviewed['patches'],
                'unreviewed source patch provenance')
        for patch in patches['patches']:
            require('extra/share/vlc/build/'+patch['path'] in entries,'missing published source patch')
    if lock.get('packaging_revision',0)>=2:
        require('extra/share/vlc/hrtfs/dodeca_and_7channel_3DSL_HRTF.sofa' in entries,'missing upstream HRTF data')
    if destination:
        extract(path, destination, entries)
        machine = {'x86_64': 62, 'aarch64': 183}[arch]
        elfs = 0
        for p in (destination/'extra').rglob('*'):
            if not p.is_file() or p.is_symlink():
                continue
            with p.open('rb') as f:
                h = f.read(20)
            if h[:4] == b'\x7fELF':
                elfs += 1
                require(h[4:6] == b'\x02\x01' and struct.unpack('<H', h[18:20])[0] == machine,
                        f'wrong ELF architecture: {p}')
                if struct.unpack('<H', h[16:18])[0] == 2:
                    require(p.stat().st_mode & stat.S_IXUSR, f'ELF executable lacks permission: {p}')
        require(elfs > 0, 'no ELF binaries')
    with path.open('rb') as f:
        require(hashlib.file_digest(f, 'sha256').hexdigest() == digest, 'archive changed during audit')
    return dict(status='pass', architecture=arch, upstream_sha=lock['upstream_sha'],
                sha256=digest, size=size, unpacked_bytes=unpacked, members=len(entries))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('archive', type=Path)
    p.add_argument('--arch', choices=['x86_64', 'aarch64'], required=True)
    p.add_argument('--inputs', type=Path, required=True)
    p.add_argument('--metadata', type=Path, required=True)
    p.add_argument('--sha256')
    p.add_argument('--extract', type=Path)
    p.add_argument('--report', type=Path, required=True)
    a = p.parse_args()
    try:
        result = audit(a.archive, a.arch, json.loads(a.inputs.read_text()),
                       json.loads(a.metadata.read_text()), a.sha256, a.extract)
    except Exception as e:
        result = dict(status='fail', error=str(e))
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))
    raise SystemExit(0 if result['status'] == 'pass' else 1)
