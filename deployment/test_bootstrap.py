import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from deployment.bootstrap import install_seed

DB = 'review.sqlite'
CHECKPOINT = 'review.sqlite.runs/1/checkpoint.json'


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.bundle, self.workspace = root / 'bundle', root / 'workspace'
        chunks = {DB: b'test database', CHECKPOINT: b'test checkpoint'}
        for rel, content in chunks.items():
            p = self.bundle / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
        (self.bundle / 'SHA256SUMS').write_text(''.join(
            f'{hashlib.sha256(content).hexdigest()}  {rel}\n' for rel, content in chunks.items()
        ))

    def test_seed_once_and_preserve_edits(self):
        self.assertTrue(install_seed(self.bundle, self.workspace))
        self.assertEqual((self.workspace / CHECKPOINT).read_bytes(), b'test checkpoint')
        user_db = self.workspace / DB
        user_db.write_bytes(b'user edits')
        self.assertFalse(install_seed(self.bundle / 'missing', self.workspace))
        self.assertEqual(user_db.read_bytes(), b'user edits')

    def test_bad_digest_leaves_no_database(self):
        (self.bundle / CHECKPOINT).write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            install_seed(self.bundle, self.workspace)
        self.assertFalse((self.workspace / DB).exists())

    def test_recovers_checkpoint_written_before_database(self):
        checkpoint = self.workspace / CHECKPOINT
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_bytes(b'test checkpoint')
        self.assertTrue(install_seed(self.bundle, self.workspace))
        self.assertEqual((self.workspace / DB).read_bytes(), b'test database')

    def test_refuses_to_replace_an_unexpected_checkpoint(self):
        checkpoint = self.workspace / CHECKPOINT
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_bytes(b'already there')
        with self.assertRaisesRegex(ValueError, 'checkpoint'):
            install_seed(self.bundle, self.workspace)
        self.assertFalse((self.workspace / DB).exists())
        self.assertEqual(checkpoint.read_bytes(), b'already there')

    def test_bundle_cannot_supply_its_own_trust_pins(self):
        trust = self.bundle.parent / 'trusted.sha256'
        trust.write_text((self.bundle / 'SHA256SUMS').read_text())
        mutated = b'new model bytes'
        (self.bundle / CHECKPOINT).write_bytes(mutated)
        old = hashlib.sha256(b'test checkpoint').hexdigest()
        new = hashlib.sha256(mutated).hexdigest()
        manifest = self.bundle / 'SHA256SUMS'
        manifest.write_text(manifest.read_text().replace(old, new))
        with self.assertRaisesRegex(ValueError, 'trusted'):
            install_seed(self.bundle, self.workspace, trusted_manifest=trust)
        self.assertFalse((self.workspace / DB).exists())


if __name__ == '__main__':
    unittest.main()
