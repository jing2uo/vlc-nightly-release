"""Partial OSTree pulls must fetch symlink objects, not only directory metadata."""
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'scripts'))
from qt_identity import collect, library_target


class PartialRepository:
    def __init__(self):
        self.fetched=set()
        self.commands=[]
        self.body=b'actual pinned Qt library bytes'

    def command(self,argv,**kwargs):
        self.commands.append(argv)
        if argv[0]=='flatpak':return 'Flatpak 1.17.0\n'
        operation=argv[2]
        if operation=='pull':
            path=next(x.split('=',1)[1] for x in argv if x.startswith('--subpath='))
            self.fetched.add((argv[-1],path))
            return ''
        if operation=='ls':
            commit,path=argv[-2:]
            if path.endswith('/private') or path in ('/files/lib/qml','/files/lib/plugins'):
                if not any(c==commit and p.startswith(path+'/') for c,p in self.fetched):
                    raise AssertionError('directory metadata not fetched')
                return f'd00755 0 0 0 {"b"*64} {path}\n'
            if (commit,path) not in self.fetched:
                raise subprocess.CalledProcessError(1,argv,stderr="Opening content object: Couldn't find file object 'missing-symlink'")
            if path.endswith('.so.6'):
                return f'l00777 0 0 0 {"a"*64} {path} -> {Path(path).name}.11.3\n'
            return f'-00755 0 0 0 {"c"*64} {path}\n'
        raise AssertionError(argv)

    def cat(self,argv,**kwargs):
        if (argv[-2],argv[-1]) not in self.fetched:raise AssertionError('library bytes not fetched')
        body=self.body
        class Process:
            stdout=io.BytesIO(body)
            def wait(self):return 0
        return Process()


class QtIdentityLookup(unittest.TestCase):
    def test_fresh_partial_repository_for_both_architectures(self):
        for arch in ('x86_64','aarch64'):
            with self.subTest(arch=arch):
                repository=PartialRepository()
                with patch('qt_identity.subprocess.check_output',side_effect=repository.command), \
                     patch('qt_identity.subprocess.Popen',side_effect=repository.cat):
                    result=collect('/chosen/repo',arch,'sdk-pin','platform-pin',pull=True)
                self.assertEqual(result['deployments'],dict(sdk_commit='sdk-pin',platform_commit='platform-pin'))
                for section,commit in [('sdk','sdk-pin'),('platform','platform-pin')]:
                    for name,library in result[section]['libraries'].items():
                        path=f'/files/lib/{arch}-linux-gnu/{name}'
                        self.assertIn((commit,path),repository.fetched)
                        self.assertEqual(library['sha256'],hashlib.sha256(repository.body).hexdigest())
                        self.assertEqual(library['object'],'c'*64)
                for section in ('sdk','platform'):
                    self.assertEqual(result[section]['runtime_trees'],dict(qml='b'*64,plugins='b'*64))
                self.assertFalse(any('--subpath=/files' in argv for argv in repository.commands))
                self.assertTrue(all(argv[1]=='--repo=/chosen/repo' for argv in repository.commands if argv[0]=='ostree'))

    def test_missing_object_reports_full_ostree_stderr_without_fallback(self):
        repository=PartialRepository()
        with patch('qt_identity.subprocess.check_output',side_effect=repository.command):
            with self.assertRaisesRegex(RuntimeError,"Couldn't find file object 'missing-symlink'") as error:
                collect('/chosen/repo','x86_64','sdk-pin','platform-pin',pull=False)
        self.assertIn('sdk-pin',str(error.exception))
        self.assertIn('/chosen/repo',str(error.exception))
        self.assertFalse(repository.fetched)

    def test_pull_failure_preserves_diagnostics(self):
        failure=subprocess.CalledProcessError(1,['ostree'],stderr='signature verification failed\nfull detail\n')
        def fail(argv,**kwargs):
            if argv[0]=='flatpak':return 'Flatpak 1.17.0'
            raise failure
        with patch('qt_identity.subprocess.check_output',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'signature verification failed\nfull detail'):
                collect('/chosen/repo','x86_64','sdk-pin','platform-pin',pull=True)

    def test_safe_adjacent_versioned_symlink(self):
        row='l00777 0 0 0 hash /files/lib/libQt6Gui.so.6 -> libQt6Gui.so.6.11.3'.split()
        self.assertEqual(library_target('libQt6Gui.so.6',row),('libQt6Gui.so.6.11.3','6.11.3'))

    def test_unsafe_or_unexpected_links_fail_closed(self):
        for target in ['/usr/lib/libQt6Gui.so.6.11.3','../libQt6Gui.so.6.11.3',
                       'nested/libQt6Gui.so.6.11.3','libQt6Core.so.6.11.3','another-link']:
            with self.subTest(target=target),self.assertRaises(ValueError):
                library_target('libQt6Gui.so.6',f'l00777 0 0 0 hash path -> {target}'.split())
        for row in [[],['-00755','0','0','0','hash','path']]:
            with self.assertRaises(ValueError):library_target('libQt6Gui.so.6',row)

    def test_target_must_be_regular_file(self):
        repository=PartialRepository()
        original=repository.command
        def linked_target(argv,**kwargs):
            output=original(argv,**kwargs)
            if argv[0]=='ostree' and argv[2]=='ls' and argv[-1].endswith('.11.3'):
                return output.replace('-00755','l00777')+' -> another-link'
            return output
        with patch('qt_identity.subprocess.check_output',side_effect=linked_target):
            with self.assertRaisesRegex(ValueError,'must be a regular file'):
                collect('/chosen/repo','x86_64','sdk-pin','platform-pin',pull=True)


if __name__=='__main__':unittest.main()
