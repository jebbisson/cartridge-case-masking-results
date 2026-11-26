"""Exercise the public worker contracts without distributing scans or checkpoints."""
import hashlib
from importlib import import_module
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

WORKERS = Path(__file__).resolve().parents[1] / 'python'
TARGETS = ('breech_face', 'aperture_shear', 'firing_pin_shear', 'firing_pin_impression',
           'firing_pin_drag_direction')


def sha(data):
    return hashlib.sha256(data).hexdigest()


class WorkerCLI(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def cli(self, script, *args, model_sha=None):
        env = os.environ.copy()
        env.pop('REVIEWAPP_MODEL_SHA256', None)
        if model_sha is not None:
            env['REVIEWAPP_MODEL_SHA256'] = model_sha
        return subprocess.run([sys.executable, '-B', '-E', str(WORKERS / script), *map(str, args)],
                              cwd=self.root, env=env, capture_output=True, text=True, timeout=90)

    def snapshot(self):
        rows = []
        # Two different grids exercise canonical-prior resampling. The larger
        # scan also exercises lifting the predicted mask back to native pixels.
        for name, size, box in (('wide', (272, 160), (77, 39, 177, 118)),
                                ('small', (96, 73), (27, 21, 58, 51))):
            scan = Image.new('L', size, 180)
            mask = Image.new('L', size)
            ImageDraw.Draw(scan).rectangle(box, fill=40)
            ImageDraw.Draw(mask).rectangle(box, fill=255)
            scan.save(self.root / f'{name}.png')
            mask.save(self.root / f'{name}-mask.png')
            rows.append({'id': name, 'split': 'train', 'width': size[0], 'height': size[1],
                         'image': f'{name}.png', 'labels': {
                             'breech_face': {'status': 'present', 'mask': f'{name}-mask.png'},
                             'aperture_shear': {'status': 'absent'}}})
        # Non-training and non-supervising rows deliberately have no scan to open.
        rows.extend([
            {'id': 'holdout', 'split': 'test', 'image': 'missing.png', 'labels': rows[0]['labels']},
            {'id': 'unknown', 'split': 'train', 'image': 'missing.png', 'labels': {
                'breech_face': {'status': 'indeterminate'},
                'aperture_shear': {'status': 'present', 'origin': 'prediction', 'mask': 'missing.png'},
                'firing_pin_drag_direction': {'status': 'present', 'start': [1, 1], 'end': [2, 2]}}},
        ])
        manifest = self.root / 'manifest.jsonl'
        manifest.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        return manifest, self.root / 'wide.png'

    def train(self, script, manifest):
        model = self.root / 'checkpoint.json'
        result = self.cli(script, 'train', '--manifest', manifest, '--out', model)
        self.assertEqual(result.returncode, 0, result.stderr)
        return model

    def verify_proposal(self, out, model, image, version):
        proposal = json.loads((out / 'proposal.json').read_text(encoding='utf-8'))
        self.assertEqual(proposal['source'], 'prediction')
        self.assertEqual(proposal['model_version'], version)
        self.assertEqual(proposal['model_sha256'], sha(model.read_bytes()))
        self.assertEqual(proposal['image_sha256'], sha(image.read_bytes()))
        self.assertEqual(set(proposal['targets']), set(TARGETS))
        self.assertEqual(proposal['targets']['breech_face'], {'status': 'present', 'mask': 'breech_face.png'})
        for key in TARGETS[1:]:
            self.assertEqual(proposal['targets'][key], {'status': 'indeterminate'})
        with Image.open(image) as scan, Image.open(out / 'breech_face.png') as mask:
            self.assertEqual((mask.format, mask.mode, mask.size), ('PNG', 'L', scan.size))
            self.assertEqual(set(mask.tobytes()), {0, 255})
            return sha(mask.tobytes())

    def test_multiscale_cli_matches_frozen_native_pixels(self):
        version = 'review-multiscale-cleanup-v1'
        manifest, image = self.snapshot()
        model = self.train('multiscale_worker.py', manifest)
        meta = json.loads(model.read_text(encoding='utf-8'))
        self.assertEqual(meta['version'], version)
        self.assertEqual(meta['settings'], {'grid_width': 256, 'boosting_iterations': 160, 'arrow_prediction': False})
        self.assertEqual(meta['manifest_sha256'], sha(manifest.read_bytes()))
        self.assertEqual(meta['training_ids'], ['small', 'wide'])
        self.assertEqual(meta['targets'], {
            'breech_face': {'status': 'learned', 'training_ids': ['wide', 'small']},
            **{key: {'status': 'unlearned', 'training_ids': []} for key in TARGETS[1:]},
        })
        out = self.root / 'predicted'
        # Go passes the trusted digest via the environment.
        result = self.cli('multiscale_worker.py', 'predict', '--model', model, '--image', image,
                          '--out', out, model_sha=sha(model.read_bytes()))
        self.assertEqual(result.returncode, 0, result.stderr)
        # Frozen with the pre-refactor worker, on generated inputs only.
        self.assertEqual(self.verify_proposal(out, model, image, version),
                         '8e43ead988c4c3f63aeb69bb8eb2fc3a592e57aaa83cd12758587c07188c0b3e')

    def test_multiscale_cli_reads_legacy_checkpoint(self):
        manifest, image = self.snapshot()
        model = self.train('review_worker.py', manifest)
        direct = self.root / 'direct'
        bridged = self.root / 'bridged'
        version = 'review-pixel-logistic-v1'
        result = self.cli('review_worker.py', 'predict', '--model', model, '--image', image, '--out', direct)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.cli('multiscale_worker.py', 'predict', '--model', model, '--image', image, '--out', bridged,
                          '--expected-model-sha256', sha(model.read_bytes()), model_sha='0' * 64)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.verify_proposal(direct, model, image, version),
                         self.verify_proposal(bridged, model, image, version))
        self.assertEqual((direct / 'proposal.json').read_bytes(), (bridged / 'proposal.json').read_bytes())


class MultiscaleGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(WORKERS))
        cls.addClassCleanup(sys.path.remove, str(WORKERS))
        cls.worker = import_module('multiscale_worker')
        cls.training = import_module('multiscale_training')

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_collapsed_positive_is_not_a_negative(self):
        size = (512, 384)
        Image.new('L', size, 90).save(self.root / 'scan.png')
        tiny = Image.new('L', size)
        tiny.putpixel((200, 200), 255)
        tiny.save(self.root / 'tiny.png')
        row = {'id': 'tiny', 'width': size[0], 'height': size[1], 'image': 'scan.png', 'labels': {
            'breech_face': {'status': 'present', 'mask': 'tiny.png'},
            'aperture_shear': {'status': 'absent'}}}
        grids, excluded = self.training.prepare([row], self.root)
        self.assertEqual(set(grids[0][1]), {'aperture_shear'})
        self.assertFalse(grids[0][1]['aperture_shear'].any())
        self.assertEqual(excluded, [{'id': 'tiny', 'target': 'breech_face'}])

    def test_budget_is_checked_before_opening_scans(self):
        row = {'id': 'scan', 'width': 2500, 'height': 2500, 'image': 'not-opened.png',
               'labels': {'breech_face': {'status': 'absent'}}}
        with patch.object(self.training, 'MAX_TRAIN_GRID_CELLS', 1000):
            with self.assertRaisesRegex(ValueError, 'training grid budget'):
                self.training.prepare([row], self.root)

    def test_extreme_aspect_ratio_stays_bounded(self):
        features = self.worker.inference.feature_image(Image.new('L', (32, 24000), 80))
        self.assertEqual(features.shape[:2], (256, 1))
        self.assertTrue(self.worker.np.isfinite(features).all())

    def test_wrong_digest_is_rejected_before_deserializing(self):
        checkpoint = self.root / 'checkpoint.json'
        checkpoint.write_text(json.dumps({'version': self.worker.VERSION}), encoding='utf-8')
        with patch.object(self.worker.joblib, 'load') as load:
            with self.assertRaisesRegex(ValueError, 'checkpoint digest'):
                self.worker.predict(checkpoint, self.root / 'unused.png', self.root / 'output', '0' * 64)
        load.assert_not_called()

    def test_dependency_mismatch_is_rejected_before_deserializing(self):
        checkpoint = self.root / 'checkpoint.json'
        raw = json.dumps({'version': self.worker.VERSION, 'dependencies': {}}).encode()
        checkpoint.write_bytes(raw)
        with patch.object(self.worker.joblib, 'load') as load:
            with self.assertRaisesRegex(ValueError, 'incompatible multiscale checkpoint or dependencies'):
                self.worker.predict(checkpoint, self.root / 'unused.png', self.root / 'output', sha(raw))
        load.assert_not_called()
