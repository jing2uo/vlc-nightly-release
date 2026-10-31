import copy
import json
from pathlib import Path
import unittest
from runtime_paths import classify,evidence_matches,GNUTLS,SOFA

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
    def test_changed_relevant_source_or_configuration(self):
        for section in ('sources','recipes'):
            evidence=self.evidence();evidence[section][next(iter(evidence[section]))]='0'*64
            self.assertFalse(evidence_matches(evidence,SOURCE))
            self.assertEqual(classify(self.findings(SOFA,'share/libmysofa/default.sofa'),SOURCE,2,evidence)[0]['status'],'fail')
    def test_unknown_path_or_plugin_still_fails(self):
        for plugin,suffix in [(SOFA,'etc/unknown'),('lib/new.so','etc/gnutls/config')]:
            self.assertEqual(classify(self.findings(plugin,suffix),SOURCE,2,self.evidence())[0]['status'],'fail')
    def test_missing_or_mismatched_evidence(self):
        for evidence in (None,{},self.evidence('0'*40)):
            self.assertEqual(classify(self.findings(SOFA,'share/libmysofa/default.sofa'),SOURCE,2,evidence)[0]['status'],'fail')
    def test_old_unadapted_archive_still_fails(self):
        self.assertEqual(classify(self.findings(next(iter(GNUTLS)),'etc/gnutls/config'),SOURCE,0,self.evidence())[0]['status'],'fail')
    def test_configuration_text_is_diagnostic(self):
        self.assertEqual(classify([dict(path='lib/core',strings=["[ 123] /work/source/configure '--sysconfdir=/etc'"])],SOURCE,2,self.evidence()),[])
