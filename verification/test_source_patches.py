"""Patch provenance rejects altered patches, unrelated edits and stale sources."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'scripts'))
from source_patches import ROOT,apply,identity,verify


class SourcePatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.source=Path(self.tmp.name)
        # Hash and tampering tests need only the reviewed patch, no network.
        patch=(ROOT/'patches/vlc-tfo-eacces.patch').read_text()
        # A minimal source fixture cannot satisfy the full-file attestation.
        self.patch=patch

    def test_exact_application_unrelated_commit_and_postimage(self):
        import difflib,hashlib
        root=self.source/'recipe';(root/'patches').mkdir(parents=True)
        repo=self.source/'repo';repo.mkdir()
        subprocess.run(['git','init','-q',str(repo)],check=True)
        before=b'one\ntwo\n';after=b'one\nthree\n'
        (repo/'file').write_bytes(before)
        def commit():
            subprocess.run(['git','-C',str(repo),'add','.'],check=True)
            subprocess.run(['git','-C',str(repo),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','test'],check=True)
            return subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
        sha=commit()
        patch=''.join(difflib.unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),fromfile='a/file',tofile='b/file'))
        (root/'patches/test.patch').write_text(patch)
        item=dict(path='patches/test.patch',source='file',sha256=hashlib.sha256(patch.encode()).hexdigest(),
                  before_sha256=hashlib.sha256(before).hexdigest(),after_sha256=hashlib.sha256(after).hexdigest())
        (root/'patches/manifest.json').write_text(json.dumps(dict(schema=1,patches=[item])))
        first=identity(repo,sha,root)
        (repo/'unrelated').write_text('unrelated');sha=commit()
        lock=identity(repo,sha,root)
        self.assertEqual(first['patches'],lock['patches'])
        apply(repo,sha,lock,root);verify(repo,lock)
        self.assertEqual((repo/'file').read_bytes(),after)
        (repo/'file').write_bytes(after+b'unknown edit')
        with self.assertRaisesRegex(ValueError,'modified'):verify(repo,lock)

    def test_manifest_and_patch_hash(self):
        import hashlib
        d=json.loads((ROOT/'patches/manifest.json').read_text())
        self.assertEqual(d['schema'],1)
        for p in d['patches']:
            self.assertEqual(hashlib.sha256((ROOT/p['path']).read_bytes()).hexdigest(),p['sha256'])
            self.assertNotEqual(p['before_sha256'],p['after_sha256'])

    def test_changed_source_rejected(self):
        subprocess.run(['git','init','-q',str(self.source)],check=True)
        p=self.source/'src/network/stream.c';p.parent.mkdir(parents=True);p.write_text('unexpected source\n')
        subprocess.run(['git','-C',str(self.source),'add','.'],check=True)
        subprocess.run(['git','-C',str(self.source),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','test'],check=True)
        sha=subprocess.check_output(['git','-C',str(self.source),'rev-parse','HEAD'],text=True).strip()
        with self.assertRaisesRegex(ValueError,'source changed'):identity(self.source,sha)

    def test_modified_patch_rejected(self):
        import shutil
        root=self.source/'recipe';shutil.copytree(ROOT/'patches',root/'patches')
        (root/'patches/vlc-tfo-eacces.patch').write_text(self.patch+'\n')
        with self.assertRaisesRegex(ValueError,'checksum'):identity(self.source,'unused',root)

    def test_unexpected_tracked_edit_rejected(self):
        subprocess.run(['git','init','-q',str(self.source)],check=True)
        p=self.source/'file';p.write_text('before')
        subprocess.run(['git','-C',str(self.source),'add','.'],check=True)
        subprocess.run(['git','-C',str(self.source),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','test'],check=True)
        p.write_text('after')
        with self.assertRaisesRegex(ValueError,'Unexpected'):verify(self.source,{'patches':[]})


if __name__=='__main__':unittest.main()
