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
        rows[0]['labels'][TARGETS[-1]] = {'status': 'present', 'origin': 'review',
                                             'start': [40, 50], 'end': [100, 50]}
        # Non-training and non-supervising rows deliberately have no scan to open.
        rows.extend([
            {'id': 'holdout', 'split': 'test', 'image': 'missing.png', 'labels': rows[0]['labels']},
            {'id': 'unknown', 'split': 'train', 'image': 'missing.png', 'labels': {
                'breech_face': {'status': 'indeterminate'},
                'aperture_shear': {'status': 'present', 'origin': 'prediction', 'mask': 'missing.png'},
                'firing_pin_drag_direction': {'status': 'present', 'origin': 'prediction',
                                              'start': [1, 1], 'end': [2, 2]}}},
        ])
        manifest = self.root / 'manifest.jsonl'
        manifest.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        return manifest, self.root / 'wide.png'

    def train(self, script, manifest):
        model = self.root / 'checkpoint.json'
        result = self.cli(script, 'train', '--manifest', manifest, '--out', model)
        self.assertEqual(result.returncode, 0, result.stderr)
        return model

    def verify_proposal(self, out, model, image, version, *, arrow=True):
        proposal = json.loads((out / 'proposal.json').read_text(encoding='utf-8'))
        self.assertEqual(proposal['source'], 'prediction')
        self.assertEqual(proposal['model_version'], version)
        self.assertEqual(proposal['model_sha256'], sha(model.read_bytes()))
        self.assertEqual(proposal['image_sha256'], sha(image.read_bytes()))
        self.assertEqual(set(proposal['targets']), set(TARGETS))
        self.assertEqual(proposal['targets']['breech_face'], {'status': 'present', 'mask': 'breech_face.png'})
        for key in TARGETS[1:-1]:
            self.assertEqual(proposal['targets'][key], {'status': 'indeterminate'})
        if arrow:
            directed = proposal['targets'][TARGETS[-1]]
            self.assertEqual(directed['status'], 'present')
            self.assertNotEqual(directed['start'], directed['end'])
        else:
            self.assertEqual(proposal['targets'][TARGETS[-1]], {'status': 'indeterminate'})
        with Image.open(image) as scan, Image.open(out / 'breech_face.png') as mask:
            self.assertEqual((mask.format, mask.mode, mask.size), ('PNG', 'L', scan.size))
            self.assertEqual(set(mask.tobytes()), {0, 255})
            return sha(mask.tobytes())

    def test_multiscale_cli_matches_frozen_native_pixels(self):
        version = 'review-multiscale-arrow-v2'
        manifest, image = self.snapshot()
        model = self.train('multiscale_worker.py', manifest)
        meta = json.loads(model.read_text(encoding='utf-8'))
        self.assertEqual(meta['version'], version)
        self.assertEqual(meta['settings'], {'grid_width': 256, 'boosting_iterations': 160, 'arrow_prediction': True})
        self.assertEqual(meta['arrow_head']['annotation_count'], 1)
        self.assertEqual(meta['arrow_head']['manifest_sha256'], sha(manifest.read_bytes()))
        self.assertEqual(meta['manifest_sha256'], sha(manifest.read_bytes()))
        self.assertEqual(meta['training_ids'], ['small', 'wide'])
        self.assertEqual(meta['targets'], {
            'breech_face': {'status': 'learned', 'training_ids': ['wide', 'small']},
            **{key: {'status': 'unlearned', 'training_ids': []} for key in TARGETS[1:-1]},
            TARGETS[-1]: {'status': 'learned', 'training_ids': ['wide']},
        })
        out = self.root / 'predicted'
        # Go passes the trusted digest via the environment.
        result = self.cli('multiscale_worker.py', 'predict', '--model', model, '--image', image,
                          '--out', out, model_sha=sha(model.read_bytes()))
        self.assertEqual(result.returncode, 0, result.stderr)
        # Frozen with the pre-refactor worker, on generated inputs only.
        self.assertEqual(self.verify_proposal(out, model, image, version),
                         '8e43ead988c4c3f63aeb69bb8eb2fc3a592e57aaa83cd12758587c07188c0b3e')
        proposal = json.loads((out / 'proposal.json').read_text())
        self.assertEqual(proposal['targets'][TARGETS[-1]],
                         {'status': 'present', 'start': [40, 50], 'end': [100, 50]})

    def test_training_tracks_arrow_only_rows_and_no_arrow_fallback(self):
        manifest, image = self.snapshot()
        rows = [json.loads(line) for line in manifest.read_text().splitlines()]
        rows[0]['labels'].pop(TARGETS[-1])
        manifest.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        model = self.train('multiscale_worker.py', manifest)
        meta = json.loads(model.read_text())
        self.assertIsNone(meta['arrow_head'])
        self.assertEqual(meta['targets'][TARGETS[-1]], {'status': 'unlearned', 'training_ids': []})
        out = self.root / 'fallback'
        result = self.cli('multiscale_worker.py', 'predict', '--model', model, '--image', image,
                          '--out', out, model_sha=sha(model.read_bytes()))
        self.assertEqual(result.returncode, 0, result.stderr)
        proposal = json.loads((out / 'proposal.json').read_text())
        self.assertEqual(proposal['targets'][TARGETS[-1]]['status'], 'present')
        self.assertTrue(proposal['arrow_prediction']['fallback'])
        rows.append({'id': 'arrow-only', 'split': 'train', 'image': 'wide.png',
                     'width': 272, 'height': 160, 'labels': {TARGETS[-1]: {
                         'status': 'present', 'origin': 'review', 'start': [130, 60], 'end': [70, 60]}}})
        manifest.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        model = self.train('multiscale_worker.py', manifest)
        meta = json.loads(model.read_text())
        self.assertEqual(meta['training_ids'], ['arrow-only', 'small', 'wide'])
        self.assertEqual(meta['targets'][TARGETS[-1]], {'status': 'learned', 'training_ids': ['arrow-only']})
        result = self.cli('multiscale_worker.py', 'predict', '--model', model, '--image', image,
                          '--out', out, model_sha=sha(model.read_bytes()))
        self.assertEqual(result.returncode, 0, result.stderr)
        proposal = json.loads((out / 'proposal.json').read_text())
        self.assertEqual(proposal['targets'][TARGETS[-1]],
                         {'status': 'present', 'start': [130, 60], 'end': [70, 60]})

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
        self.assertEqual(self.verify_proposal(direct, model, image, version, arrow=False),
                         self.verify_proposal(bridged, model, image, version))
        original = json.loads((direct / 'proposal.json').read_text())
        updated = json.loads((bridged / 'proposal.json').read_text())
        updated.pop('arrow_prediction')
        updated['targets'][TARGETS[-1]] = original['targets'][TARGETS[-1]]
        self.assertEqual(original, updated)


class ArrowHeadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(WORKERS))
        cls.addClassCleanup(sys.path.remove, str(WORKERS))
        cls.arrows = import_module('ordered_arrow')

    def test_v2_semantics_tail_is_in_purple_shear_pocket_tip_in_cyan_impression_scrape(self):
        import numpy as np
        purple_pocket = np.zeros((12, 16), dtype=bool)
        purple_pocket[4:8, 3:7] = True
        cyan_scrape = np.zeros_like(purple_pocket)
        cyan_scrape[5:7, 9:13] = True  # Explicitly separate exterior support.
        arrow, info = self.arrows.predict(self.arrows.bundled_head(), {
            'firing_pin_shear': purple_pocket, 'firing_pin_impression': cyan_scrape}, (160, 120))
        tail = arrow['start'][1] // 10, arrow['start'][0] // 10
        tip = arrow['end'][1] // 10, arrow['end'][0] // 10
        self.assertTrue(purple_pocket[tail], 'tail must lie in v2 purple firing_pin_shear pocket')
        self.assertTrue(cyan_scrape[tip], 'tip must lie in v2 cyan firing_pin_impression scrape')
        self.assertFalse(purple_pocket[tip], 'tip must be exterior to the purple pocket')
        self.assertEqual(info['method'], 'predicted_support_geometry')
        self.assertLess(arrow['start'][0], arrow['end'][0])

    def test_v2_scrape_tip_excludes_all_purple_pocket_components(self):
        import numpy as np
        purple_pocket = np.zeros((12, 20), dtype=bool)
        purple_pocket[3:9, 2:8] = True
        purple_pocket[5:8, 10:14] = True
        cyan_scrape = np.zeros_like(purple_pocket)
        cyan_scrape[5:8, 10:14] = True  # Overlap is not exterior support.
        cyan_scrape[5:7, 14:16] = True
        arrow, info = self.arrows.predict(self.arrows.bundled_head(), {
            'firing_pin_shear': purple_pocket, 'firing_pin_impression': cyan_scrape}, (200, 120))
        tail = arrow['start'][1] // 10, arrow['start'][0] // 10
        tip = arrow['end'][1] // 10, arrow['end'][0] // 10
        self.assertTrue(purple_pocket[tail])
        self.assertTrue(cyan_scrape[tip])
        self.assertFalse(purple_pocket[tip], 'exterior excludes every purple component, not just the largest')
        self.assertEqual(info['method'], 'predicted_support_geometry')

    def test_bundled_prior_matches_actual_public_seventeen_ordered_annotations(self):
        import numpy as np
        manifest = WORKERS.parent / 'training' / 'dataset' / 'train.jsonl'
        if not manifest.is_file():
            self.skipTest('public training snapshot is not installed')
        raw = manifest.read_bytes()
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
        eligible = [row for row in rows if row['split'] == 'train'
                    and row['labels'][TARGETS[-1]]['status'] == 'present'
                    and row['labels'][TARGETS[-1]].get('origin', row.get('origin'))
                    not in ('proposal', 'prediction')]
        self.assertEqual(len(eligible), 17)
        self.assertEqual(sum(row['labels'][TARGETS[-1]]['status'] == 'not_annotated' for row in rows), 13)
        points = np.array([[row['labels'][TARGETS[-1]]['start'], row['labels'][TARGETS[-1]]['end']]
                           for row in eligible], dtype=float)
        sizes = np.array([[row['width'], row['height']] for row in eligible])
        normalized = points / sizes[:, None, :]
        vectors = normalized[:, 1] - normalized[:, 0]
        lengths = np.linalg.norm(vectors, axis=1)
        direction = np.mean(vectors / lengths[:, None], axis=0)
        direction /= np.linalg.norm(direction)
        bundled = self.arrows.bundled_head()
        self.assertEqual(bundled['manifest_sha256'], sha(raw))
        self.assertEqual(bundled['annotation_count'], 17)
        np.testing.assert_array_equal(bundled['start'], np.median(normalized[:, 0], axis=0))
        np.testing.assert_array_equal(bundled['direction'], direction)
        self.assertEqual(bundled['length'], float(np.median(lengths)))
        # Exercise the production fitter on those real approved annotations too.
        fitted, used = self.arrows.fit(rows, manifest.parent.resolve(), sha(raw))
        self.assertEqual(len(used), 17)
        self.assertEqual(fitted, bundled)

    def test_predicted_support_orders_pocket_to_exterior_scrape_without_mutating_masks(self):
        import numpy as np
        pocket = np.zeros((12, 16), dtype=bool)
        pocket[4:8, 3:7] = True
        scrape = np.zeros_like(pocket)
        scrape[5:7, 6:12] = True
        before = (pocket.tobytes(), scrape.tobytes())
        arrow, info = self.arrows.predict(self.arrows.bundled_head(), {
            'firing_pin_shear': pocket, 'firing_pin_impression': scrape}, (160, 120))
        self.assertEqual(info['method'], 'predicted_support_geometry')
        self.assertLess(arrow['start'][0], arrow['end'][0])
        self.assertTrue(pocket[arrow['start'][1] // 10, arrow['start'][0] // 10])
        self.assertTrue(scrape[arrow['end'][1] // 10, arrow['end'][0] // 10])
        self.assertFalse(pocket[arrow['end'][1] // 10, arrow['end'][0] // 10])
        self.assertEqual(before, (pocket.tobytes(), scrape.tobytes()))
        for masks, expected in (({'firing_pin_shear': pocket}, 'predicted_pocket_prior'),
                                ({'firing_pin_impression': scrape}, 'predicted_scrape_prior'),
                                ({'firing_pin_shear': pocket, 'firing_pin_impression': pocket},
                                 'predicted_pocket_prior')):
            with self.subTest(method=expected):
                result, details = self.arrows.predict(self.arrows.bundled_head(), masks, (160, 120))
                self.assertEqual(details['method'], expected)
                self.assertNotEqual(result['start'], result['end'])

    def test_empty_boundary_and_tiny_support_always_yield_valid_integer_geometry(self):
        import numpy as np
        for size in ((1, 2), (2, 1), (2, 2), (7, 3), (32, 24000), (24000, 1)):
            for corner in ([0., 0.], [.99999, .99999]):
                for direction in ([1., 0.], [-1., 0.], [0., 1.], [0., -1.]):
                    head = {**self.arrows.bundled_head(), 'start': corner,
                            'direction': direction, 'length': 1e-10}
                    for masks in ({}, {'firing_pin_impression': np.ones((1, 1), dtype=bool),
                                       'firing_pin_shear': np.ones((1, 1), dtype=bool)}):
                        with self.subTest(size=size, corner=corner, direction=direction):
                            arrow, _ = self.arrows.predict(head, masks, size)
                            self.assertEqual(arrow['status'], 'present')
                            self.assertNotEqual(arrow['start'], arrow['end'])
                            for point in (arrow['start'], arrow['end']):
                                self.assertTrue(all(type(v) is int for v in point))
                                self.assertTrue(all(0 <= v < n for v, n in zip(point, size)))
        # Go's integer-point contract cannot represent two points on a 1x1 scan.
        with self.assertRaisesRegex(ValueError, 'at least two image pixels'):
            self.arrows.predict(self.arrows.bundled_head(), {}, (1, 1))

    def test_quantization_preserves_learned_order_at_boundaries(self):
        for start in ([0., 0.], [.9999, .9999]):
            for direction in ([1., 0.], [-1., 0.], [0., 1.], [0., -1.]):
                with self.subTest(start=start, direction=direction):
                    head = {**self.arrows.bundled_head(), 'start': start,
                            'direction': direction, 'length': 1e-10}
                    arrow, info = self.arrows.predict(head, {}, (8, 8))
                    dot = sum((e - s) * d for s, e, d in zip(arrow['start'], arrow['end'], direction))
                    self.assertGreater(dot, 0)
                    self.assertTrue(info['quantization_repaired'])

    def test_fit_rejects_invalid_reviewed_geometry_and_asset_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new('L', (20, 10), 80).save(root / 'scan.png')
            base = {'id': 'reviewed', 'split': 'train', 'width': 20, 'height': 10,
                    'image': 'scan.png', 'labels': {TARGETS[-1]: {
                        'status': 'present', 'start': [3, 4], 'end': [12, 4]}}}
            invalid_entries = ({'start': [float('nan'), 2]}, {'end': [20, 4]},
                               {'start': [-1, 4]}, {'end': [3, 4]}, {'start': [1]},
                               {'start': None}, {'end': 'bad'}, {'status': 'invalid'})
            for override in invalid_entries:
                with self.subTest(override=override), self.assertRaises(ValueError):
                    self.arrows.fit([{**base, 'labels': {
                        TARGETS[-1]: {**base['labels'][TARGETS[-1]], **override}}}], root, 'a' * 64)
            for override in ({'image': '../outside.png'}, {'width': 19}, {'image_sha256': '0' * 64}):
                with self.subTest(override=override), self.assertRaises(ValueError):
                    self.arrows.fit([{**base, **override}], root, 'a' * 64)
            missing = json.loads(json.dumps(base))
            missing['labels'][TARGETS[-1]].pop('start')
            with self.assertRaises(ValueError):
                self.arrows.fit([missing], root, 'a' * 64)

    def test_invalid_serialized_heads_do_not_generate_successful_estimates(self):
        for override in ({'version': 'future'}, {'start': [float('nan'), .5]},
                         {'start': [.5]}, {'direction': [0., 0.]}, {'length': 0.},
                         {'length': float('inf')}, {'annotation_count': 0},
                         {'manifest_sha256': 'invalid'}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.arrows.predict({**self.arrows.bundled_head(), **override}, {}, (20, 10))

    def test_fit_uses_only_reviewed_train_arrows_and_learns_corrections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new('L', (20, 10), 80).save(root / 'scan.png')
            reviewed = {'id': 'approved', 'split': 'train', 'width': 20, 'height': 10,
                        'image': 'scan.png', 'labels': {TARGETS[-1]: {
                            'status': 'present', 'origin': 'review', 'start': [3, 4], 'end': [12, 4]}}}
            rows = [reviewed]
            # These must not be read, fitted, or treated as invented negatives.
            for index, override in enumerate(({'split': 'test'}, {'split': 'validation'},
                                              {'origin': 'prediction'}, {'origin': 'proposal'})):
                row = {**reviewed, 'id': f'excluded-{index}', 'image': 'missing.png', **override}
                if 'origin' in override:
                    row['labels'] = {TARGETS[-1]: {k: v for k, v in reviewed['labels'][TARGETS[-1]].items()
                                                   if k != 'origin'}}
                rows.append(row)
            rows.append({'id': 'unknown', 'split': 'train', 'image': 'missing.png',
                         'labels': {TARGETS[-1]: {'status': 'not_annotated'}}})
            rows.append({**reviewed, 'id': 'suggestion', 'image': 'missing.png',
                         'labels': {TARGETS[-1]: {'status': 'present', 'origin': 'prediction'}}})
            before = json.dumps(rows, sort_keys=True)
            head, used = self.arrows.fit(rows, root, 'a' * 64)
            self.assertEqual(used, ['approved'])
            self.assertEqual(head['annotation_count'], 1)
            self.assertEqual(head['manifest_sha256'], 'a' * 64)
            self.assertEqual(head['start'], [3 / 20, 4 / 10])
            self.assertEqual(head['direction'], [1., 0.])
            self.assertAlmostEqual(head['length'], 9 / 20)
            self.assertEqual(json.dumps(rows, sort_keys=True), before)
            corrected = json.loads(json.dumps(reviewed))
            corrected['labels'][TARGETS[-1]].update(start=[12, 4], end=[3, 4])
            changed, _ = self.arrows.fit([corrected], root, 'b' * 64)
            self.assertEqual(changed['direction'], [-1., 0.])
            self.assertNotEqual(changed, head)
            self.assertEqual(self.arrows.fit(rows[1:], root, 'a' * 64), (None, []))


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

    def test_old_mask_only_checkpoint_always_proposes_an_ordered_arrow(self):
        from io import BytesIO
        import base64
        payload = BytesIO()
        self.worker.joblib.dump({'regions': {}, 'priors': {}}, payload)
        raw = json.dumps({'version': 'review-multiscale-cleanup-v1',
                          'dependencies': self.worker.versions(),
                          'settings': {'grid_width': 256, 'boosting_iterations': 160,
                                       'arrow_prediction': False},
                          'payload_base64': base64.b64encode(payload.getvalue()).decode()}).encode()
        checkpoint = self.root / 'old.json'
        checkpoint.write_bytes(raw)
        image = self.root / 'empty.png'
        Image.new('L', (32, 24), 0).save(image)
        out = self.root / 'predicted'
        self.worker.predict(checkpoint, image, out, sha(raw))
        proposal = json.loads((out / 'proposal.json').read_text())
        arrow = proposal['targets'][TARGETS[-1]]
        self.assertEqual(arrow['status'], 'present')
        self.assertNotEqual(arrow['start'], arrow['end'])
        for point in (arrow['start'], arrow['end']):
            self.assertTrue(0 <= point[0] < 32 and 0 <= point[1] < 24)
        self.assertEqual(proposal['arrow_prediction']['method'], 'normalized_prior')
        self.assertTrue(proposal['arrow_prediction']['best_effort'])
        self.assertEqual(checkpoint.read_bytes(), raw)

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

    def test_new_head_provenance_is_validated_before_deserializing(self):
        checkpoint = self.root / 'checkpoint.json'
        raw = json.dumps({'version': self.worker.VERSION, 'dependencies': self.worker.versions(),
                          'settings': self.worker.SETTINGS, 'manifest_sha256': 'a' * 64,
                          'arrow_head': self.worker.arrows.bundled_head()}).encode()
        checkpoint.write_bytes(raw)
        with patch.object(self.worker.joblib, 'load') as load:
            with self.assertRaisesRegex(ValueError, 'arrow.*provenance'):
                self.worker.predict(checkpoint, self.root / 'unused.png', self.root / 'output', sha(raw))
        load.assert_not_called()

    def test_dependency_mismatch_is_rejected_before_deserializing(self):
        checkpoint = self.root / 'checkpoint.json'
        raw = json.dumps({'version': self.worker.VERSION, 'dependencies': {}}).encode()
        checkpoint.write_bytes(raw)
        with patch.object(self.worker.joblib, 'load') as load:
            with self.assertRaisesRegex(ValueError, 'incompatible multiscale checkpoint or dependencies'):
                self.worker.predict(checkpoint, self.root / 'unused.png', self.root / 'output', sha(raw))
        load.assert_not_called()
