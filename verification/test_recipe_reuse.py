"""Completed release reuse requires byte-equivalent tracked build inputs."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'scripts'))
import release

class RecipeReuseTests(unittest.TestCase):
    def test_publication_changes_only_and_build_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'scripts').mkdir()
            original=subprocess.run
            def git(*args):return subprocess.check_output(['git','-C',str(root),*args],text=True).strip()
            git('init','-q');git('config','user.name','Test');git('config','user.email','test@example.invalid')
            (root/'scripts/build.sh').write_text('build');(root/'scripts/publish.sh').write_text('publish')
            git('add','.');git('commit','-qm','initial');first=git('rev-parse','HEAD')
            (root/'scripts/publish.sh').write_text('new publication');(root/'scripts/production.py').write_text('publication helper')
            git('add','.');git('commit','-qm','publication only');second=git('rev-parse','HEAD')
            with patch.object(release.subprocess,'run',side_effect=lambda args,**kw:original(args,cwd=root,**kw)):
                self.assertTrue(release.build_recipe_equal({'recipe_commit':first},{'recipe_commit':second}))
            (root/'scripts/build.sh').write_text('different build flags')
            git('add','.');git('commit','-qm','changed build');third=git('rev-parse','HEAD')
            with patch.object(release.subprocess,'run',side_effect=lambda args,**kw:original(args,cwd=root,**kw)):
                self.assertFalse(release.build_recipe_equal({'recipe_commit':first},{'recipe_commit':third}))
                self.assertFalse(release.build_recipe_equal({'recipe_commit':third},{'recipe_commit':first}))
                self.assertFalse(release.build_recipe_equal({'recipe_commit':'bad'},{'recipe_commit':first}))

if __name__=='__main__':unittest.main()
