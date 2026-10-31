"""Platform visibility and actual ELF requirements; never fall back to SDK Qt."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from qt_abi import inspect, runtime_library


class QtRuntimeLookup(unittest.TestCase):
    def test_build_explicitly_mounts_exact_platform_readonly(self):
        script=(Path(__file__).resolve().parents[1]/'scripts/environment.sh').read_text()
        command='exec flatpak build'+script.split('exec flatpak build',1)[1]
        with tempfile.TemporaryDirectory() as directory:
            fake=Path(directory)/'flatpak'
            fake.write_text('#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
            fake.chmod(0o755)
            result=subprocess.run(['bash','-eu','-c',command],env=dict(os.environ,
                PATH=directory+':'+os.environ['PATH'],runtime_root='/exact/pinned/platform/files',arch='aarch64'),
                capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            argv=json.loads(result.stdout)
            self.assertIn('--filesystem=/exact/pinned/platform/files:ro',argv)
            self.assertIn('--env=TARGET_RUNTIME_ROOT=/exact/pinned/platform/files',argv)

    def test_symlinks_and_architecture_specific_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for arch in ('x86_64','aarch64'):
                lib=root/'lib'/f'{arch}-linux-gnu';lib.mkdir(parents=True)
                target=lib/'libQt6Svg.so.6.11.3';target.write_bytes(arch.encode())
                (lib/'libQt6Svg.so.6').symlink_to(target.name)
                self.assertEqual(runtime_library(root,arch,'libQt6Svg.so.6'),target)

    def test_hidden_root_and_genuinely_missing_library_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with self.assertRaisesRegex(ValueError,'root is not accessible'):
                runtime_library(root/'hidden','x86_64','libQt6Svg.so.6')
            for arch in ('x86_64','aarch64'):
                with self.assertRaisesRegex(ValueError,'Platform lacks libQt6Svg.so.6'):
                    runtime_library(root,arch,'libQt6Svg.so.6')

    def test_dangling_and_sdk_escaping_links_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);platform=root/'platform';lib=platform/'lib/x86_64-linux-gnu'
            lib.mkdir(parents=True);sdk=root/'sdk.so';sdk.write_bytes(b'SDK only')
            link=lib/'libQt6Svg.so.6';link.symlink_to(sdk)
            with self.assertRaisesRegex(ValueError,'escapes target Platform'):
                runtime_library(platform,'x86_64',link.name)
            sdk.unlink()
            with self.assertRaisesRegex(ValueError,'Platform lacks'):
                runtime_library(platform,'x86_64',link.name)

    def inspect_fixture(self,arch,missing=False,version='6.11.3'):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);payload=root/'payload';platform=root/'platform'
            plugin=payload/'lib/vlc/plugins/gui/libqt_plugin.so';plugin.parent.mkdir(parents=True);plugin.touch()
            provenance=payload/'share/vlc/build';provenance.mkdir(parents=True)
            (provenance/'toolchain.log').write_text('QT_VERSION:6.11.3\n')
            lib=platform/'lib'/f'{arch}-linux-gnu';lib.mkdir(parents=True)
            for name in ('Core','Svg'):
                if missing and name=='Svg':continue
                target=lib/f'libQt6{name}.so.{version}';target.write_bytes(b'fixture ELF bytes')
                (lib/f'libQt6{name}.so.6').symlink_to(target.name)
            (root/'sdk-only').mkdir();(root/'sdk-only/libQt6BuildOnly.so.6').touch()
            def output(argv,**kwargs):
                if argv[0]=='readelf':return '(NEEDED) Shared library: [libQt6Core.so.6]\n(NEEDED) Shared library: [libQt6Svg.so.6]\n'
                if argv[-1]==str(plugin):return '000 DF *UND* 000 (Qt_6_PRIVATE_API) private_symbol\n'
                return '000 g DF .text 000 Qt_6_PRIVATE_API private_symbol\n'
            with patch('qt_abi.subprocess.check_output',side_effect=output):
                return inspect(payload,platform,arch)

    def test_only_elf_runtime_requirements_are_mandatory(self):
        for arch in ('x86_64','aarch64'):
            result=self.inspect_fixture(arch)
            self.assertEqual(result['status'],'pass')
            self.assertEqual(set(result['runtime_libraries']),{'libQt6Core.so.6','libQt6Svg.so.6'})
            with self.assertRaisesRegex(ValueError,'Platform lacks libQt6Svg.so.6'):
                self.inspect_fixture(arch,missing=True)

    def test_private_version_mismatch_remains_fatal(self):
        for arch in ('x86_64','aarch64'):
            result=self.inspect_fixture(arch,version='6.11.4')
            self.assertEqual(result['status'],'fail')
            self.assertTrue(any('private ABI build/runtime mismatch' in x for x in result['failures']))


if __name__=='__main__':unittest.main()
