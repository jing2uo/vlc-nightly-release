"""Release gates must reject absent, skipped, or mismatched native evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from archive import InvalidArtifact
from pair import REQUIRED, verify

class PairGate(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)
        self.lock=dict(upstream_sha='a'*40,version='4.0.0-dev-1-gaaaaaaaaaa',architectures={
            a:dict(sdk_commit='b'*64,platform_commit='c'*64) for a in ('x86_64','aarch64')})
        (self.directory/'inputs.json').write_text(json.dumps(self.lock))
        self.reports={}
        for arch in ('x86_64','aarch64'):
            (self.directory/f'vlc-{self.lock["version"]}-{arch}.tar.zst').touch()
            (self.directory/f'build-{arch}.json').write_text('{}')
            self.reports[arch]=dict(schema=2,architecture=arch,upstream_sha=self.lock['upstream_sha'],
                version=self.lock['version'],sdk_commit='b'*64,runtime_commit='c'*64,
                sha256='d'*64,size=123,verification_sha256='e'*64,automated_status='pass',
                checks=[dict(name=n,status='pass',mandatory=True) for n in REQUIRED])
    def run_pair(self):
        for arch,report in self.reports.items():
            (self.directory/f'verification-{arch}.json').write_text(json.dumps(report))
        def audited(path,arch,lock,metadata):
            return dict(upstream_sha=self.lock['upstream_sha'],sha256='d'*64,size=123)
        with patch('pair.audit',side_effect=audited):return verify(self.directory)
    def test_complete_pair(self): self.run_pair()
    def test_missing_check(self):
        self.reports['aarch64']['checks'].pop()
        with self.assertRaises(InvalidArtifact):self.run_pair()
    def test_skip_cannot_be_pass(self):
        self.reports['x86_64']['checks'][0]['status']='skipped'
        with self.assertRaises(InvalidArtifact):self.run_pair()
    def test_optional_cannot_replace_mandatory(self):
        self.reports['x86_64']['checks'][0]['mandatory']=False
        with self.assertRaises(InvalidArtifact):self.run_pair()
    def test_wrong_source_or_asset(self):
        for field in ('sha256','upstream_sha','runtime_commit'):
            saved=self.reports['aarch64'][field];self.reports['aarch64'][field]='0'*64
            with self.assertRaises(InvalidArtifact):self.run_pair()
            self.reports['aarch64'][field]=saved
    def test_different_verification_recipe(self):
        self.reports['aarch64']['verification_sha256']='f'*64
        with self.assertRaises(InvalidArtifact):self.run_pair()
    def test_unexpected_payload(self):
        (self.directory/'extra.tar.zst').touch()
        with self.assertRaises(InvalidArtifact):self.run_pair()
