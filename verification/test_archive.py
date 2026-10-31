"""Adversarial archive headers; no target application execution required."""
import unittest
import tarfile
from archive import namespace, extract, inspect, InvalidArtifact
from pathlib import Path
import tempfile
import subprocess


def entry(name, kind=tarfile.REGTYPE, target='', mode=0o755):
    m=tarfile.TarInfo(name);m.type=kind;m.linkname=target;m.mode=mode
    return m


class ArchiveSafety(unittest.TestCase):
    def reject(self, entries):
        with self.assertRaises(InvalidArtifact): namespace(entries)
    def test_traversal_and_absolute(self):
        for name in ('/extra/a','extra/../escape','extra//a','extra/./a','../extra/a','C:/extra/a'):
            self.reject([entry(name)])
    def test_escaping_links(self):
        for target in ('/etc/passwd','../../escape','..\\escape'):
            self.reject([entry('extra/a',tarfile.SYMTYPE,target)])
    def test_symlink_parent(self):
        self.reject([entry('extra/a',tarfile.SYMTYPE,'b'),entry('extra/a/c')])
    def test_cycles_and_dangling(self):
        self.reject([entry('extra/a',tarfile.SYMTYPE,'b'),entry('extra/b',tarfile.SYMTYPE,'a')])
        self.reject([entry('extra/a',tarfile.SYMTYPE,'missing')])
    def test_special_duplicate_and_privilege(self):
        self.reject([entry('extra/a',tarfile.CHRTYPE)])
        self.reject([entry('extra/a'),entry('extra/a')])
        self.reject([entry('extra/a',mode=0o4755)])
    def test_safe_relative_link(self):
        namespace([entry('extra/lib/a'),entry('extra/lib/b',tarfile.SYMTYPE,'a')])
    def test_hardlink_chain_order(self):
        with tempfile.TemporaryDirectory() as directory:
            directory=Path(directory);tar=directory/'input.tar'
            with tarfile.open(tar,'w') as tf:
                members=[entry('extra/a',tarfile.LNKTYPE,'extra/b'),
                         entry('extra/b',tarfile.LNKTYPE,'extra/c'),entry('extra/c')]
                for member in members:tf.addfile(member)
            compressed=directory/'input.tar.zst'
            subprocess.run(['zstd','-q',str(tar),'-o',str(compressed)],check=True)
            entries,_=namespace(members);extract(compressed,directory/'out',entries)
            self.assertEqual((directory/'out/extra/a').stat().st_ino,(directory/'out/extra/c').stat().st_ino)
    def test_trailing_non_tar_data(self):
        with tempfile.TemporaryDirectory() as directory:
            directory=Path(directory);tar=directory/'input.tar'
            with tarfile.open(tar,'w') as tf:tf.addfile(entry('extra/a'))
            with tar.open('ab') as f:f.write(b'unsafe trailing content')
            compressed=directory/'input.tar.zst'
            subprocess.run(['zstd','-q',str(tar),'-o',str(compressed)],check=True)
            with self.assertRaises(InvalidArtifact):inspect(compressed)
    def test_unpacked_budget(self):
        m=entry('extra/huge');m.size=9*2**30;self.reject([m])


if __name__ == '__main__': unittest.main()
