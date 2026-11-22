"""Test evaluation bookkeeping without simulated scans or private assets."""
import json
from pathlib import Path
import tempfile
import unittest

import grouped_cv as cv


def row(case, group, split: str | None = 'train'):
    return {'id': case, 'group_id': group, 'split': split, 'labels': {}}


def jsonl(rows):
    return '\n'.join(map(json.dumps, rows)).encode()


class CohortTests(unittest.TestCase):
    def test_groups_are_disjoint_and_order_independent(self):
        rows = [row(f'case-{g}-{i}', f'group-{g}') for g in range(6) for i in range(2)]
        folds = cv.grouped_folds(rows, count=3, seed=413)
        self.assertEqual(folds, cv.grouped_folds(list(reversed(rows)), count=3, seed=413))
        self.assertEqual([len(fold) for fold in folds], [4, 4, 4])
        self.assertCountEqual([r['id'] for fold in folds for r in fold], [r['id'] for r in rows])
        for held in range(len(folds)):
            fitting = {r['group_id'] for i, fold in enumerate(folds) if i != held for r in fold}
            self.assertTrue(fitting.isdisjoint(r['group_id'] for r in folds[held]))

    def test_fold_count_cannot_exceed_independent_groups(self):
        with self.assertRaisesRegex(ValueError, 'groups'):
            cv.grouped_folds([row('a', 'same'), row('b', 'same')], count=2, seed=413)

    def test_rejects_non_train_even_if_paths_are_missing(self):
        for split in ('validation', 'test', None):
            with self.subTest(split=split), self.assertRaisesRegex(ValueError, 'train-only'):
                cv.read_rows(jsonl([row('a', 'x'), row('b', 'y', split)]))

    def test_rejects_ambiguous_membership(self):
        for data in (jsonl([row('a', 'x'), row('a', 'y')]), jsonl([row('a', ' x')]),
                     b'{"id":"a","group_id":"x","group_id":"y","split":"train"}'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                cv.read_rows(data)

    def test_asset_path_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / 'dataset'
            root.mkdir()
            outside = base / 'outside.png'
            outside.touch()
            (root / 'safe.png').touch()
            self.assertEqual(cv.asset(root, 'safe.png'), root / 'safe.png')
            for path in ('../outside.png', str(outside), r'C:\outside.png', 'https://host/scan.png'):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    cv.asset(root, path)
            try:
                (root / 'link.png').symlink_to(outside)
            except OSError:
                self.skipTest('this host does not allow symlinks')
            with self.assertRaises(ValueError):
                cv.asset(root, 'link.png')


class MetricTests(unittest.TestCase):
    def test_positive_summary_counts_abstentions_as_zero_not_omissions(self):
        summary = cv.summarize_masks([
            cv.mask_result('present', predicted=3, reference=2, intersection=1),
            cv.mask_result('present', predicted=0, reference=4, intersection=0),
        ])
        self.assertEqual(summary['reviewed_present'], 2)
        self.assertEqual(summary['abstentions']['present'], 1)
        self.assertAlmostEqual(summary['median_iou'], 0.125)
        self.assertAlmostEqual(summary['p10_iou'], 0.025)
        self.assertAlmostEqual(summary['mean_precision'], 1 / 6)
        self.assertAlmostEqual(summary['mean_recall'], 0.25)

    def test_unknown_emissions_are_not_false_positives(self):
        summary = cv.summarize_masks([
            cv.mask_result('unknown', predicted=5),
            cv.mask_result('absent', predicted=1),
            cv.mask_result('absent', predicted=0),
        ])
        self.assertEqual(summary['reviewed_absent'], 2)
        self.assertEqual(summary['false_positive_on_absent'], 1)
        self.assertEqual(summary['emitted_on_unknown'], 1)
        self.assertEqual(summary['abstentions']['absent'], 1)
        self.assertIsNone(summary['median_iou'])
        self.assertIsNone(summary['mean_precision'])


if __name__ == '__main__':
    unittest.main()
