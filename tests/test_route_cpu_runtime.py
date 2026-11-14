import os
import unittest
from unittest.mock import patch
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime


class RouteCpuRuntimeTests(unittest.TestCase):
    def test_thread_override_is_scoped_to_import_not_child_environment(self):
        for before in (None,'8'):
            with self.subTest(before=before),patch.dict(os.environ,{},clear=False):
                if before is None:os.environ.pop('OPENBLAS_NUM_THREADS',None)
                else:os.environ['OPENBLAS_NUM_THREADS']=before
                seen=[]
                result=initialize_route_cpu_runtime(load=lambda:seen.append(os.environ.get('OPENBLAS_NUM_THREADS')))
                self.assertEqual(seen,['1'])
                self.assertEqual(os.environ.get('OPENBLAS_NUM_THREADS'),before)
                self.assertTrue(result['childEnvironmentRestored'])

    def test_failed_import_also_restores_prior_environment(self):
        def fail():
            self.assertEqual(os.environ['OPENBLAS_NUM_THREADS'],'1')
            raise RuntimeError('import failed')
        with patch.dict(os.environ,{'OPENBLAS_NUM_THREADS':'7'}):
            with self.assertRaisesRegex(RuntimeError,'import failed'):initialize_route_cpu_runtime(load=fail)
            self.assertEqual(os.environ['OPENBLAS_NUM_THREADS'],'7')


if __name__=='__main__':unittest.main()
