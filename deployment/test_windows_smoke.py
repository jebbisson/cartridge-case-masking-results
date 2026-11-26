"""Exercise the PowerShell acceptance checker against a disposable real app.

Set WORKBENCH_TEST_URL and WORKBENCH_PWSH explicitly; never target a live
review workspace. These tests do not fit models, save revisions or approve.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

SCRIPT = Path(__file__).with_name('Test-Windows.ps1')


class PowerShellSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pwsh = os.environ.get('WORKBENCH_PWSH') or shutil.which('pwsh')
        cls.base = os.environ.get('WORKBENCH_TEST_URL')
        if not cls.pwsh or not cls.base:
            raise unittest.SkipTest('Requires PowerShell and an explicit disposable WORKBENCH_TEST_URL')

    def run_script(self, url):
        assert self.pwsh is not None
        return subprocess.run([self.pwsh, '-NoProfile', '-File', str(SCRIPT), '-BaseUrl', url],
                              capture_output=True, text=True, timeout=240)

    def test_full_seed_and_unsaved_estimates(self):
        result = self.run_script(self.base)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report['cases'], 48)
        self.assertEqual(report['splits'], {'train': 30, 'validation': 6, 'test': 12})
        self.assertEqual(report['training_total'], 30)
        self.assertEqual(report['training_unchanged'], 30)
        self.assertEqual({row['split'] for row in report['estimates']}, {'train', 'validation', 'test'})
        self.assertTrue(all(row['native_mask_count'] > 0 for row in report['estimates']))
        self.assertTrue(report['saved_state_unchanged'])
        self.assertEqual(report['baseline_fingerprint'], '8f02993551552c065e228d44a17e8d3eca10d787a4d3c2c486dac2706e24133c')

    def test_reports_are_stable_across_powershell_processes(self):
        first = self.run_script(self.base)
        second = self.run_script(self.base)
        self.assertEqual(first.returncode, 0, first.stderr or first.stdout)
        self.assertEqual(second.returncode, 0, second.stderr or second.stdout)
        one, two = json.loads(first.stdout), json.loads(second.stdout)
        self.assertEqual(one['saved_state_sha256'], two['saved_state_sha256'])
        self.assertEqual(one['estimates'], two['estimates'])

    def test_non_loopback_target_is_refused_before_requests(self):
        result = self.run_script('https://example.com/')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('loopback', (result.stderr + result.stdout).lower())


if __name__ == '__main__':
    unittest.main()
