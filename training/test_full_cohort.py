"""Release contract: full inventory is separate from the frozen fitting inputs."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import unittest
from tempfile import TemporaryDirectory
from deployment.bootstrap import install_seed

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'training/dataset'

class FullCohortTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.seed = Path(cls.tmp.name)
        install_seed(ROOT/'starter/full-bundle', cls.seed,
                     trusted_manifest=ROOT/'deployment/starter.full.sha256',
                     trusted_parts=ROOT/'deployment/starter.parts.sha256')
    def test_inventory_and_frozen_training_manifest(self):
        rows = [json.loads(line) for line in (DATA / 'manifest.jsonl').read_text().splitlines()]
        self.assertEqual(Counter(r['split'] for r in rows), {'train': 30, 'validation': 6, 'test': 12})
        train = (DATA / 'train.jsonl').read_bytes()
        self.assertEqual(sha256(train).hexdigest(), 'c563e60a47479831139ea0c0ef4b9bb88e2019e1ff6be481bd741d13e456ff07')
        self.assertEqual([r for r in rows if r['split'] == 'train'], [json.loads(l) for l in train.splitlines()])

    def test_starter_full_inventory_with_only_frozen_approvals(self):
        uri = (self.seed / 'review.sqlite').as_uri() + '?mode=ro&immutable=1'
        with sqlite3.connect(uri, uri=True) as db:
            self.assertEqual(db.execute('select split,count(*) from cases group by split order by split').fetchall(), [('test',12),('train',30),('validation',6)])
            self.assertEqual(db.execute("select count(*) from cases where split!='train' and (included!=0 or approved is not null)").fetchone(), (0,))
            self.assertEqual(db.execute('select count(*) from revisions').fetchone(), (48,))
            self.assertEqual(db.execute('select fingerprint from runs').fetchone()[0], '8f02993551552c065e228d44a17e8d3eca10d787a4d3c2c486dac2706e24133c')

    def test_full_package_verifier(self):
        from training.verify_local_candidate import verify
        verify(ROOT/'starter/full-bundle', DATA)

    def test_native_assets_and_mixed_input_rejection(self):
        from PIL import Image
        from training.evaluation.grouped_cv import read_rows
        rows=[json.loads(l) for l in (DATA/'manifest.jsonl').read_text().splitlines()]
        with self.assertRaisesRegex(ValueError,'train-only'):
            read_rows((DATA/'manifest.jsonl').read_bytes())
        self.assertEqual(len(read_rows((DATA/'train.jsonl').read_bytes())),30)
        masks=0
        for row in rows:
            size=(row['width'],row['height'])
            with Image.open(DATA/row['image']) as image:
                self.assertEqual(image.size,size)
                self.assertEqual(sha256(image.convert('RGB').tobytes()).hexdigest(),row['decoded_pixel_sha256'])
            for label in row['labels'].values():
                if 'mask' not in label: continue
                with Image.open(DATA/label['mask']) as image:
                    self.assertEqual(image.size,size)
                    self.assertIn(image.mode,('1','L'))
                    histogram=image.convert('L').histogram()
                    self.assertGreater(histogram[255],0)
                    self.assertEqual(sum(histogram[1:255]),0)
                masks+=1
        self.assertEqual(masks,141)

if __name__ == '__main__':
    unittest.main()
