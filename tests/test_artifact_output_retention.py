"""Generated intermediates can be rebuilt; APKs/reports/source cannot be removed."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.pilot import artifact_output_retention as retention


class ArtifactRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.base=self.root/'.local-pilot/artifact-builds';self.base.mkdir(parents=True)
        for i in range(7):
            folder=self.base/f'build-{i}';folder.mkdir();output=folder/'gradle-output'
            (folder/'fresh-build-output.gradle').write_text('allprojects { p -> p.layout.buildDirectory.set(new File("'+output.as_posix()+'", p.name)) }')
            (folder/'android-build.log').write_text('BUILD SUCCESSFUL in 10s')
            os.utime(folder/'android-build.log',(100+i,100+i));os.utime(folder/'fresh-build-output.gradle',(100+i,100+i))
            for name in ('app/intermediates/tmp.bin','app/outputs/apk/final.apk','app/reports/result.xml'):
                path=output/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'keep or derive')
            (folder/'project-cache').mkdir();(folder/'project-cache/cache.bin').write_bytes(b'derived')

    def test_apply_preserves_latest_five_and_all_apks_reports_and_recipes(self):
        with patch.object(retention.subprocess,'check_output',return_value='[]'):
            result=retention.execute(self.root,apply=True)
        self.assertEqual(len(result['removed']),4)
        for i in range(7):
            folder=self.base/f'build-{i}'
            self.assertEqual((folder/'gradle-output/app/intermediates').exists(),i>=2)
            self.assertTrue((folder/'gradle-output/app/outputs/apk/final.apk').exists())
            self.assertTrue((folder/'gradle-output/app/reports/result.xml').exists())
            self.assertTrue((folder/'fresh-build-output.gradle').exists())

    def test_plan_is_read_only_and_uncertain_log_or_wrong_recipe_is_excluded(self):
        first=self.base/'build-0';(first/'android-build.log').write_text('still running')
        second=self.base/'build-1';(second/'fresh-build-output.gradle').write_text('arbitrary Gradle code')
        result=retention.execute(self.root)
        self.assertEqual(result['targets'],[])
        self.assertEqual(len(result['skipped']),2)
        self.assertTrue((first/'gradle-output/app/intermediates/tmp.bin').exists())

    def test_running_build_is_refused_before_removal(self):
        if os.name!='nt':self.skipTest('Windows process admission')
        with patch.object(retention.subprocess,'check_output',return_value='java artifact-builds active'):
            with self.assertRaisesRegex(RuntimeError,'process_active'):retention.execute(self.root,apply=True)
        self.assertTrue((self.base/'build-0/gradle-output/app/intermediates/tmp.bin').exists())

    def test_source_or_path_outside_build_root_cannot_be_a_removal_target(self):
        outside=self.root/'source';outside.mkdir();(outside/'keep.kt').write_text('source')
        with self.assertRaisesRegex(ValueError,'retention_path'):
            retention.validate_target(outside,self.base)
        self.assertEqual((outside/'keep.kt').read_text(),'source')

    def test_recipe_for_another_output_is_not_an_ownership_marker(self):
        directory=self.base/'build-0'
        (directory/'fresh-build-output.gradle').write_text('allprojects { p -> p.layout.buildDirectory.set(new File("C:/outside", p.name)) }')
        _,eligible,_,skipped=retention.inventory(self.root)
        self.assertNotIn('build-0',[x['name'] for x in eligible])
        self.assertEqual(next(x for x in skipped if x['name']=='build-0')['reason'],'recipe_not_owned')


if __name__=='__main__':unittest.main()
