"""Exercise Git for Windows checkout settings, not native Windows runtime support.

The release runtime is a Linux container (Docker Desktop/WSL2 on Windows).
Only stdlib and Git are needed here; no generated scan/image examples are used.
Run from the repository root: python -m unittest discover -s tests -p test_checkout_portability.py -v
"""
from hashlib import file_digest
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


@unittest.skipUnless(shutil.which('git'), 'Git is required for checkout integration tests')
class CheckoutPortabilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory(prefix='checkout-portability-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.repo = Path(cls.temp.name) / 'source'
        cls.checkout = Path(cls.temp.name) / 'windows checkout'
        shutil.copytree(ROOT, cls.repo, ignore=shutil.ignore_patterns(
            '.git', '__pycache__', '.venv', 'node_modules', 'dist', '.local'))
        cls.env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        cls.git('init', '--quiet', str(cls.repo))
        cls.git('config', 'user.name', 'Checkout portability test')
        cls.git('config', 'user.email', 'checkout-test@example.invalid')
        cls.git('config', 'core.autocrlf', 'false')
        # Windows does not preserve POSIX executable bits. Do not require them.
        cls.git('config', 'core.filemode', 'false')
        cls.git('config', 'core.ignorecase', 'true')
        # Tiny opaque bytes exercise transport-file mechanics only, not scan data.
        # A binary part must not depend on Git's NUL/printable-byte heuristics.
        cls.probe = '.checkout-byte-probe/review.sqlite.part-000'
        cls.probe_bytes = b'opaque transport bytes\r\nleave this LF alone\n'
        (cls.repo / cls.probe).parent.mkdir()
        (cls.repo / cls.probe).write_bytes(cls.probe_bytes)
        cls.git('add', '--all')
        cls.git('commit', '--quiet', '-m', 'Private checkout test snapshot')
        cls.tracked = cls.git('ls-files', '-z').stdout.split('\0')[:-1]
        cls.git('config', 'core.autocrlf', 'true')
        cls.git('worktree', 'add', '--quiet', '--detach', str(cls.checkout), 'HEAD')

    @classmethod
    def git(cls, *args, cwd=None):
        return subprocess.run(
            ['git', '-c', f'core.attributesFile={os.devnull}', *args],
            cwd=cwd or cls.repo, env=cls.env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        )

    def test_binary_transport_does_not_rely_on_content_detection(self):
        self.assertEqual((self.checkout / self.probe).read_bytes(), self.probe_bytes)

    def test_crlf_checkout_preserves_frozen_package_bytes(self):
        frozen = [name for name in self.tracked if name.startswith((
            'training/dataset/', 'starter/full-bundle/')) or name in (
                'deployment/starter.full.sha256', 'deployment/starter.parts.sha256')]
        self.assertTrue(frozen, 'no frozen files were staged')
        changed = [name for name in frozen
                   if digest(self.repo / name) != digest(self.checkout / name)]
        self.assertEqual(changed, [], 'core.autocrlf=true changed frozen release bytes')

    def test_checkout_really_uses_windows_git_settings(self):
        self.assertEqual(self.git('config', 'core.autocrlf', cwd=self.checkout).stdout.strip(), 'true')
        self.assertEqual(self.git('config', 'core.filemode', cwd=self.checkout).stdout.strip(), 'false')
        self.assertEqual(self.git('config', 'core.ignorecase', cwd=self.checkout).stdout.strip(), 'true')
        self.assertTrue((self.checkout / '.git').is_file(), 'expected a real linked worktree')

    def test_frozen_assets_are_staged_and_explicitly_binary(self):
        images = [p for p in self.tracked if p.startswith('training/dataset/images/')]
        masks = [p for p in self.tracked if p.startswith('training/dataset/masks/')]
        parts = [p for p in self.tracked if p.startswith('starter/full-bundle/review.sqlite.part-')]
        self.assertEqual((len(images), len(masks), len(parts)), (48, 141, 3))
        # Include an ignored/untracked database name: attributes apply to it too.
        names = images + masks + parts + ['review.sqlite']
        attrs = self.git('check-attr', '-z', 'text', '--', *names, cwd=self.checkout).stdout.split('\0')
        self.assertEqual(len(attrs) - 1, len(names) * 3)
        for index in range(0, len(attrs) - 1, 3):
            self.assertEqual(attrs[index + 1:index + 3], ['text', 'unset'], attrs[index])

    def test_paths_have_no_windows_name_or_case_collisions(self):
        components = {}
        reserved = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', re.I)
        for name in self.tracked:
            path = Path(name)
            for parent in (path, *path.parents):
                if str(parent) == '.':
                    continue
                posix = parent.as_posix()
                self.assertEqual(components.setdefault(posix.casefold(), posix), posix)
                self.assertFalse(re.search(r'[<>:"\\|?*\x00-\x1f]', parent.name), posix)
                self.assertEqual(parent.name.rstrip(' .'), parent.name, posix)
                self.assertIsNone(reserved.match(parent.name), posix)

    def test_manifest_paths_keep_exact_original_png_names(self):
        import json
        rows = [json.loads(line) for line in
                (self.checkout / 'training/dataset/manifest.jsonl').read_bytes().splitlines()]
        self.assertEqual(len(rows), 48)
        tracked = set(self.tracked)
        for row in rows:
            name = row['source']['image']['original_filename']
            self.assertEqual(row['image'], f'images/{name}')
            references = [row['image']] + [label['mask'] for label in row['labels'].values()
                                          if 'mask' in label]
            for relative in references:
                self.assertIn('training/dataset/' + relative, tracked)
                self.assertTrue((self.checkout / 'training/dataset' / relative).is_file())

    def test_linux_container_sources_have_lf_without_executable_bit_dependency(self):
        import json
        suffixes = {'.py', '.go', '.js', '.jsx', '.css', '.html', '.json', '.jsonl',
                    '.yaml', '.md', '.sha256', '.mod', '.sum', '.txt'}
        for name in self.tracked:
            if Path(name).suffix in suffixes or Path(name).name in {'Dockerfile', 'SHA256SUMS'}:
                self.assertNotIn(b'\r\n', (self.checkout / name).read_bytes(), name)
        dockerfile = (self.checkout / 'Dockerfile').read_text()
        entrypoint = next(line for line in dockerfile.splitlines() if line.startswith('ENTRYPOINT '))
        # JSON exec-form Python invocation works when Windows drops executable bits.
        self.assertEqual(json.loads(entrypoint.removeprefix('ENTRYPOINT ')),
                         ['python', '/app/deployment/bootstrap.py'])
        for name in ('deployment/bootstrap.py', 'deployment/assemble_seed.py',
                     'python/multiscale_worker.py'):
            self.assertIn(name, self.tracked)
            mode = self.git('ls-files', '-s', '--', name).stdout.split()[0]
            self.assertEqual(mode, '100644', name)

    @unittest.skipUnless(sys.platform == 'linux', 'full verifier uses Linux fcntl; not a native Windows runtime')
    def test_crlf_checkout_passes_independent_full_package_verifier(self):
        result = subprocess.run(
            [sys.executable, 'training/verify_local_candidate.py'], cwd=self.checkout,
            env=dict(self.env, TMPDIR=self.temp.name, PYTHONDONTWRITEBYTECODE='1'),
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('30 frozen approvals and exact model unchanged', result.stdout)


if __name__ == '__main__':
    unittest.main()
