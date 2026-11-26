"""Split seed transport must reconstruct exact bytes, rejecting corrupt input."""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from deployment import bootstrap

class SplitSeedTest(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.bundle=self.root/'bundle';self.bundle.mkdir()
        self.model='review.sqlite.runs/1/checkpoint.json'
        (self.bundle/self.model).parent.mkdir(parents=True)
        (self.bundle/self.model).write_bytes(b'model')
        self.parts={'review.sqlite.part-000':b'database ', 'review.sqlite.part-001':b'bytes'}
        for name,raw in self.parts.items(): (self.bundle/name).write_bytes(raw)
        self.pins=''.join(f'{sha256(raw).hexdigest()}  {name}\n' for name,raw in self.parts.items())
        (self.bundle/'PARTS.sha256').write_text(self.pins)
        self.trust=self.root/'parts.sha256';self.trust.write_text(self.pins)
        (self.bundle/'SHA256SUMS').write_text(f'{sha256(b"database bytes").hexdigest()}  review.sqlite\n{sha256(b"model").hexdigest()}  {self.model}\n')
    def test_split_bootstrap_reconstructs_exact_database(self):
        self.assertTrue(bootstrap.install_seed(self.bundle,self.root/'work',trusted_parts=self.trust))
        self.assertEqual((self.root/'work/review.sqlite').read_bytes(),b'database bytes')
    def test_corrupt_part_never_installs_database(self):
        (self.bundle/'review.sqlite.part-001').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'checksum'):
            bootstrap.install_seed(self.bundle,self.root/'work',trusted_parts=self.trust)
        self.assertFalse((self.root/'work/review.sqlite').exists())
    def test_bundle_cannot_choose_part_hashes(self):
        (self.bundle/'PARTS.sha256').write_text(self.pins.replace('part-001','part-002'))
        with self.assertRaises(ValueError):
            bootstrap.install_seed(self.bundle,self.root/'work',trusted_parts=self.trust)
    def test_part_order_must_be_canonical(self):
        (self.bundle/'PARTS.sha256').write_text('\n'.join(reversed(self.pins.splitlines()))+'\n')
        with self.assertRaises(ValueError):
            bootstrap.install_seed(self.bundle,self.root/'work',trusted_parts=self.trust)
    def test_missing_part_never_installs_database(self):
        (self.bundle/'review.sqlite.part-001').unlink()
        with self.assertRaises(OSError):
            bootstrap.install_seed(self.bundle,self.root/'work',trusted_parts=self.trust)
        self.assertFalse((self.root/'work/review.sqlite').exists())
    def test_full_database_pin_checked_as_well_as_parts(self):
        p=self.bundle/'SHA256SUMS';p.write_text(p.read_text().replace(sha256(b'database bytes').hexdigest(),'0'*64))
        with self.assertRaisesRegex(ValueError,'checksum'):
            bootstrap.install_seed(self.bundle,self.root/'work',trusted_parts=self.trust)
        self.assertFalse((self.root/'work/review.sqlite').exists())
if __name__=='__main__': unittest.main()
