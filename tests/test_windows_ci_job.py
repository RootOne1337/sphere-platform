"""A killed local executor must not leave its test process tree alive."""
import ctypes
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt", "Windows kernel job acceptance")
class WindowsJobLifetimeTest(unittest.TestCase):
    def test_executor_death_terminates_assigned_test_child(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "child.pid"
            code = (
                "import subprocess,sys,time; from pathlib import Path; "
                "from scripts.pilot.windows_ci_job import WindowsChildJob; "
                "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); "
                "job=WindowsChildJob(p); Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(60)"
            )
            driver = subprocess.Popen([sys.executable, "-c", code, str(file)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 10
                while not file.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(file.exists(), "driver did not attach its owned child")
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
                kernel.OpenProcess.restype = ctypes.c_void_p
                kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
                kernel.WaitForSingleObject.restype = ctypes.c_ulong
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                handle = kernel.OpenProcess(0x00100000, 0, int(file.read_text()))
                self.assertTrue(handle)
                try:
                    driver.terminate()
                    driver.wait(timeout=10)
                    self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0,
                                     "assigned child survived the executor")
                finally:
                    kernel.CloseHandle(handle)
            finally:
                if driver.poll() is None:
                    driver.terminate()
                    driver.wait(timeout=10)
                driver.stderr.close()


if __name__ == "__main__":
    unittest.main()
