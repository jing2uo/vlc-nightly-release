import copy
import json
from pathlib import Path
import unittest
import tempfile
import subprocess
from unittest.mock import patch
from runtime_paths import classify,evidence_matches,collect_evidence,hash_drift,GNUTLS,SOFA

SOURCE='c7834066e27cf07a2a15f1e8aab17c12df97e5d4'
class RuntimePaths(unittest.TestCase):
    def evidence(self,sha=SOURCE):
        value=json.loads(Path(__file__).with_name('runtime-path-policy.json').read_text());value['source_sha']=sha;return value
    def findings(self,path,suffix):
        return [dict(path=path,strings=['[ 123] /work/deps/'+'a'*64+'/contrib/x86_64-unknown-linux-gnu/'+suffix])]
    def test_reviewed_gnutls(self):
        for plugin in GNUTLS:
            self.assertEqual(classify(self.findings(plugin,'etc/gnutls/config'),SOURCE,2,self.evidence())[0]['status'],'pass')
    def test_unrelated_commit_and_revision(self):
        sha='0'*40;evidence=self.evidence(sha)
        self.assertTrue(evidence_matches(evidence,sha))
        self.assertEqual(classify(self.findings(SOFA,'share/libmysofa/default.sofa'),sha,3,evidence)[0]['status'],'pass')
    def test_source_or_configuration_drift_is_informational(self):
        for section in ('sources','recipes'):
            evidence=self.evidence();name=next(iter(evidence[section]));evidence[section][name]='0'*64
            self.assertTrue(evidence_matches(evidence,SOURCE))
            self.assertIn(name,hash_drift(evidence)[section]['changed'])
            self.assertEqual(classify(self.findings(SOFA,'share/libmysofa/default.sofa'),SOURCE,2,evidence)[0]['status'],'pass')
    def test_evidence_tampering_fails_against_actual_inputs(self):
        actual=self.evidence()
        for section in ('sources','recipes'):
            for action in ('modify','remove','add'):
                evidence=copy.deepcopy(actual);name=next(iter(evidence[section]))
                if action=='modify':evidence[section][name]='0'*64
                elif action=='remove':del evidence[section][name]
                else:evidence[section][name+'.new']='1'*64
                self.assertFalse(evidence_matches(evidence,SOURCE,actual))
    def test_bad_evidence_shape_and_paths_rejected(self):
        for section in ('sources','recipes'):
            for name,digest in [('../escape','a'*64),('/absolute','a'*64),('scripts/build.sh','bad')]:
                evidence=self.evidence();evidence[section][name]=digest
                self.assertFalse(evidence_matches(evidence,SOURCE))
    def test_added_removed_and_changed_files_reported(self):
        evidence=self.evidence();before=copy.deepcopy(evidence)
        for section in ('sources','recipes'):
            names=list(evidence[section]);evidence[section][names[0]]='0'*64
            del evidence[section][names[1]]
        evidence['sources']['contrib/src/gnutls/new.patch']='1'*64
        drift=hash_drift(evidence)
        self.assertEqual(drift['sources']['added'],{'contrib/src/gnutls/new.patch':'1'*64})
        for section in ('sources','recipes'):
            names=list(before[section])
            self.assertEqual(drift[section]['removed'],{names[1]:before[section][names[1]]})
            self.assertEqual(drift[section]['changed'][names[0]],dict(before=before[section][names[0]],after='0'*64))
    def test_collect_uses_pinned_git_tree_including_removals(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';source.mkdir()
            subprocess.run(['git','init','-q',str(source)],check=True)
            for name,text in [('contrib/bootstrap','original'),('contrib/src/gnutls/removed.patch','removed')]:
                p=source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
            def commit():
                subprocess.run(['git','-C',str(source),'add','-A'],check=True)
                subprocess.run(['git','-C',str(source),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','fixture'],check=True)
                return subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
            old=commit();original=collect_evidence(source,old,root)
            (source/'contrib/bootstrap').unlink()
            (source/'contrib/src/gnutls/removed.patch').unlink()
            (source/'contrib/src/gnutls/new.patch').write_text('new')
            new=commit();actual=collect_evidence(source,new,root)
            self.assertTrue(evidence_matches(actual,new,collect_evidence(source,new,root)))
            self.assertNotIn('contrib/bootstrap',actual['sources'])
            self.assertIn('contrib/src/gnutls/new.patch',actual['sources'])
            self.assertEqual(collect_evidence(source,old,root),original)
            self.assertFalse(evidence_matches(original,new,actual))
            (source/'contrib/src/gnutls/new.patch').write_text('uncommitted')
            self.assertEqual(collect_evidence(source,new,root),actual)
    def test_unknown_path_or_plugin_still_fails(self):
        for plugin,suffix in [(SOFA,'etc/unknown'),('lib/new.so','etc/gnutls/config')]:
            self.assertEqual(classify(self.findings(plugin,suffix),SOURCE,2,self.evidence())[0]['status'],'fail')
    def test_unknown_paths_fail_even_with_source_drift(self):
        evidence=self.evidence();evidence['sources']['contrib/bootstrap']='0'*64
        for findings in (self.findings('lib/new.so','etc/gnutls/config'),
                         self.findings(SOFA,'share/new-data'),
                         [dict(path=SOFA,strings=['[ 123] /tmp/build/share/new-data'])]):
            self.assertEqual(classify(findings,SOURCE,3,evidence)[0]['status'],'fail')
    def test_missing_or_mismatched_evidence(self):
        for evidence in (None,{},self.evidence('0'*40)):
            self.assertEqual(classify(self.findings(SOFA,'share/libmysofa/default.sofa'),SOURCE,2,evidence)[0]['status'],'fail')
    def test_old_unadapted_archive_still_fails(self):
        self.assertEqual(classify(self.findings(next(iter(GNUTLS)),'etc/gnutls/config'),SOURCE,0,self.evidence())[0]['status'],'fail')
    def test_configuration_text_is_diagnostic(self):
        self.assertEqual(classify([dict(path='lib/core',strings=["[ 123] /work/source/configure '--sysconfdir=/etc'"])],SOURCE,2,self.evidence()),[])

    def test_metadata_resolve_accepts_drift_and_check_rejects_tampering(self):
        import contextlib
        import io
        import os
        import runpy
        from contextlib import ExitStack
        root=Path(__file__).resolve().parent.parent
        evidence=self.evidence();evidence['sources']['contrib/bootstrap']='0'*64
        evidence['sources'].pop('modules/access/rist.h')
        evidence['sources']['contrib/src/gnutls/new.patch']='1'*64
        original_read=Path.read_text
        def read(path,*args,**kwargs):
            name=str(path)
            if name.startswith('/work/qt-'):return '{}'
            if name.startswith('/work/') and name.endswith('.commit'):return 'b'*64
            if name=='/recipe/scripts/contrib.sh':return original_read(root/'scripts/contrib.sh',*args,**kwargs)
            return original_read(path,*args,**kwargs)
        def git_output(command,**kwargs):
            if command[3:]==['rev-parse','HEAD']:return SOURCE
            if '--format=%ct' in command:return '1'
            return 'a'*40
        # metadata.py also hashes the contrib recipe through read_bytes.
        original_bytes=Path.read_bytes
        def read_bytes(path):
            if str(path)=='/recipe/scripts/contrib.sh':return original_bytes(root/'scripts/contrib.sh')
            return original_bytes(path)
        import sys
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch.object(sys,'path',[str(root/'scripts')]+sys.path))
            lock=Path(directory)/'inputs.json'
            stack.enter_context(patch.object(Path,'read_text',read))
            stack.enter_context(patch.object(Path,'read_bytes',read_bytes))
            stack.enter_context(patch('subprocess.check_output',side_effect=git_output))
            stack.enter_context(patch('runtime_paths.collect_evidence',return_value=evidence))
            stack.enter_context(patch('source_patches.identity',return_value={'patches':[]}))
            stack.enter_context(patch('qt_identity.validate_inputs'))
            stack.enter_context(patch('qt_identity.release_identity',return_value='c'*64))
            stack.enter_context(patch('qt_identity.artifact_version',return_value='fixture-version'))
            stack.enter_context(patch.dict(os.environ,VLC_SHA=SOURCE,VLC_VERSION='fixture-version'))
            stderr=io.StringIO()
            with patch('sys.argv',['metadata.py','resolve',str(lock)]),contextlib.redirect_stderr(stderr):
                runpy.run_path(str(root/'scripts/metadata.py'),run_name='__main__')
            resolved=__import__('json').loads(original_read(lock))
            self.assertEqual(resolved['runtime_path_evidence'],evidence)
            self.assertIn('contrib/bootstrap',stderr.getvalue())
            self.assertIn('removed',stderr.getvalue())
            with patch('sys.argv',['metadata.py','check',str(lock)]):
                runpy.run_path(str(root/'scripts/metadata.py'),run_name='__main__')
            for section in ('sources','recipes'):
                tampered=copy.deepcopy(resolved)
                tampered['runtime_path_evidence'][section][next(iter(tampered['runtime_path_evidence'][section]))]='f'*64
                lock.write_text(json.dumps(tampered))
                with patch('sys.argv',['metadata.py','check',str(lock)]),self.assertRaisesRegex(AssertionError,'pinned build inputs'):
                    runpy.run_path(str(root/'scripts/metadata.py'),run_name='__main__')
