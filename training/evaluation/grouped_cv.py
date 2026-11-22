"""Run train-only grouped development cross-validation through the production worker."""
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / 'python' / 'multiscale_worker.py'
sys.path.insert(0, str(WORKER.parent))
import review_worker as worker  # noqa: E402 (shared snapshot/asset contract)


def read_rows(raw):
    """Reject mixed manifests before validating or opening any asset paths."""
    rows = []
    seen = set()
    for number, line in enumerate(raw.decode('utf-8').splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line, object_pairs_hook=worker.unique_object)
        if not isinstance(row, dict) or row.get('split') != 'train':
            raise ValueError(f'manifest line {number}: expected a train-only row')
        for key in ('id', 'group_id'):
            value = row.get(key)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f'manifest line {number}: invalid {key}')
        if row['id'] in seen:
            raise ValueError(f'manifest line {number}: duplicate id')
        seen.add(row['id'])
        rows.append(row)
    if not rows:
        raise ValueError('empty train-only manifest')
    return rows


def grouped_folds(rows, count, seed):
    groups = defaultdict(list)
    for row in sorted(rows, key=lambda r: r['id']):
        groups[row['group_id']].append(row)
    if not 2 <= count <= len(groups):
        raise ValueError('fold count must be between 2 and the number of source groups')

    # Use reviewed sparse-mask presence for balance, not any prediction or arrow.
    sparse = {gid: sum(any(key == 'firing_pin_impression' and path is not None
                           for key, path in worker.supervised_masks(row)) for row in group)
              for gid, group in groups.items()}

    def order(gid):
        tie = worker.sha256(f'{seed}:{gid}'.encode('utf-8'))
        return (-len(groups[gid]), -sparse[gid], tie, gid)

    folds = [[] for _ in range(count)]
    positives = [0] * count
    for gid in sorted(groups, key=order):
        i = min(range(count), key=lambda n: (len(folds[n]), positives[n], n))
        folds[i].extend(groups[gid])
        positives[i] += sparse[gid]
    return folds


def asset(root, value):
    if (not isinstance(value, str) or '\\' in value or ':' in value or '\x00' in value
            or '..' in Path(value).parts):
        raise ValueError('expected a relative asset path without parent traversal')
    return worker.asset(root, value)


@dataclass(frozen=True)
class Scan:
    image: Path
    size: tuple[int, int]
    image_sha: str
    # Missing key: not scored. None: reviewed absent. Path: reviewed present.
    reference: dict[str, Path | None]


def load_scans(rows, root):
    scans = {}
    pixel_groups = {}
    for row in rows:
        path = asset(root, row.get('image'))
        image = worker.read_image(path)
        worker.check_size(row, image.size)
        fingerprint = image.size, worker.sha256(image.tobytes())
        group = row['group_id']
        if pixel_groups.setdefault(fingerprint, group) != group:
            raise ValueError('duplicate decoded worker-input pixels across source groups')
        reference = {key: asset(root, mask) if mask is not None else None
                     for key, mask in worker.supervised_masks(row)}
        scans[row['id']] = Scan(path, image.size, worker.sha256(path.read_bytes()), reference)
    return scans


def native_mask(path, size):
    with Image.open(path) as image:
        if (image.format != 'PNG' or image.mode not in ('1', 'L') or image.size != size
                or getattr(image, 'n_frames', 1) != 1):
            raise ValueError('expected an aligned native-resolution grayscale PNG mask')
        plane = image.convert('L')
        histogram = plane.histogram()
        if not histogram[255] or sum(histogram[1:255]):
            raise ValueError('present mask must be nonempty and binary (0/255)')
        return np.asarray(plane) == 255


def mask_result(status, predicted, reference=0, intersection=0):
    if status != 'present':
        return status, bool(predicted), None
    return status, bool(predicted), (
        intersection / (predicted + reference - intersection),
        intersection / predicted if predicted else 0.0,
        intersection / reference,
    )


def summarize_masks(results):
    support = Counter(status for status, _, _ in results)
    abstentions = Counter(status for status, emitted, _ in results if not emitted)
    scores = [score for _, _, score in results if score is not None]
    iou, precision, recall = zip(*scores, strict=True) if scores else ((), (), ())
    return {
        'reviewed_present': support['present'],
        'reviewed_absent': support['absent'],
        'unscored_reference': support['unknown'],
        'abstentions': {status: abstentions[status] for status in ('present', 'absent', 'unknown')},
        'false_positive_on_absent': support['absent'] - abstentions['absent'],
        'emitted_on_unknown': support['unknown'] - abstentions['unknown'],
        'median_iou': float(np.median(iou)) if scores else None,
        'p10_iou': float(np.quantile(iou, 0.1, method='linear')) if scores else None,
        'mean_precision': float(np.mean(precision)) if scores else None,
        'mean_recall': float(np.mean(recall)) if scores else None,
    }


def stage_fit(ids, scans, folder):
    """Provide only fitting-complement assets beneath the worker manifest root."""
    assets = folder / 'assets'
    assets.mkdir()
    staged = {}

    def stage(path):
        if path not in staged:
            target = assets / f'{len(staged)}.png'
            # Prefer a hard link; a different filesystem may require a local copy.
            try:
                target.hardlink_to(path)
            except OSError:
                shutil.copyfile(path, target)
            staged[path] = target.relative_to(folder).as_posix()
        return staged[path]

    manifest = folder / 'manifest.jsonl'
    with manifest.open('w', encoding='utf-8', newline='\n') as output:
        for case in ids:
            scan = scans[case]
            labels = {key: {'status': 'absent'} if path is None else
                      {'status': 'present', 'mask': stage(path)}
                      for key, path in scan.reference.items()}
            row = {'id': case, 'split': 'train', 'image': stage(scan.image),
                   'width': scan.size[0], 'height': scan.size[1], 'labels': labels}
            output.write(json.dumps(row, sort_keys=True) + '\n')
    return manifest


def run_worker(command, *args):
    subprocess.run([sys.executable, '-B', '-E', str(WORKER), command, *map(str, args)], check=True)


def score_proposal(folder, scan, model_sha):
    proposal = json.loads((folder / 'proposal.json').read_bytes(), object_pairs_hook=worker.unique_object)
    if (proposal.get('image_sha256') != scan.image_sha or proposal.get('model_sha256') != model_sha
            or proposal.get('source') != 'prediction'):
        raise ValueError('proposal does not match image and fold checkpoint')
    for key in worker.MASK_TARGETS:
        result = proposal['targets'][key]
        prediction = None
        if result['status'] == 'present':
            prediction = native_mask(asset(folder, result.get('mask')), scan.size)
        elif result['status'] != 'indeterminate' or 'mask' in result:
            raise ValueError(f'unexpected production proposal status for {key}')
        predicted = int(np.count_nonzero(prediction)) if prediction is not None else 0
        if key not in scan.reference:
            yield key, mask_result('unknown', predicted)
        elif (path := scan.reference[key]) is None:
            yield key, mask_result('absent', predicted)
        else:
            reference = native_mask(path, scan.size)
            intersection = int(np.count_nonzero(prediction & reference)) if prediction is not None else 0
            yield key, mask_result('present', predicted, int(np.count_nonzero(reference)), intersection)


def evaluate(manifest, count, seed):
    raw = manifest.read_bytes()
    rows = read_rows(raw)
    folds = grouped_folds(rows, count, seed)
    scans = load_scans(rows, manifest.parent.resolve())
    results = defaultdict(list)
    summaries = []
    settings = None
    for i, scoring in enumerate(folds):
        scoring_ids = sorted(row['id'] for row in scoring)
        fitting = [row for j, fold in enumerate(folds) if j != i for row in fold]
        fitting_ids = sorted(row['id'] for row in fitting)
        scoring_groups = {row['group_id'] for row in scoring}
        fitting_groups = {row['group_id'] for row in fitting}
        if not scoring_ids or not fitting_ids or not scoring_groups.isdisjoint(fitting_groups):
            raise ValueError('invalid grouped fold')

        # Keep private manifests, images, checkpoints and proposals in disposable scratch.
        with TemporaryDirectory(prefix='grouped-cv-') as temp:
            folder = Path(temp).resolve()
            snapshot = stage_fit(fitting_ids, scans, folder)
            model = folder / 'checkpoint.json'
            print(f'Fold {i + 1}/{count}: fit {len(fitting_ids)}, score {len(scoring_ids)}',
                  file=sys.stderr, flush=True)
            run_worker('train', '--manifest', snapshot, '--out', model)
            checkpoint = model.read_bytes()  # freshly trained locally, never supplied by the caller
            model_sha = worker.sha256(checkpoint)
            meta = json.loads(checkpoint, object_pairs_hook=worker.unique_object)
            contributors = set(meta['training_ids'])
            if (meta['manifest_sha256'] != worker.sha256(snapshot.read_bytes())
                    or not contributors or not contributors.issubset(fitting_ids)):
                raise ValueError('checkpoint does not match the fitting complement')
            settings = {key: meta[key] for key in ('version', 'settings', 'dependencies')}
            for case in scoring_ids:
                scan = scans[case]
                with TemporaryDirectory(dir=folder, prefix='prediction-') as out:
                    run_worker('predict', '--model', model, '--image', scan.image, '--out', out,
                               '--expected-model-sha256', model_sha)
                    for key, result in score_proposal(Path(out), scan, model_sha):
                        results[key].append(result)
            summaries.append({'fold': i + 1, 'fit_scans': len(fitting_ids),
                              'fit_groups': len(fitting_groups), 'score_scans': len(scoring_ids),
                              'score_groups': len(scoring_groups), 'contributing_fit_scans': len(contributors),
                              'learned_masks': [key for key in worker.MASK_TARGETS
                                                if meta['targets'][key]['status'] == 'learned']})
    if any(len(results[key]) != len(rows) for key in worker.MASK_TARGETS):
        raise ValueError('each scan must be scored exactly once')
    return {
        'protocol': 'grouped-train-development-v1', 'seed': seed,
        'manifest_sha256': worker.sha256(raw), 'python_version': sys.version.split()[0], 'model': settings,
        'scans': len(rows), 'groups': len({row['group_id'] for row in rows}), 'folds': summaries,
        'masks': {key: summarize_masks(results[key]) for key in worker.MASK_TARGETS},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'training/dataset/manifest.jsonl',
                        help='approved train-only JSONL (default: training/dataset/manifest.jsonl)')
    parser.add_argument('--folds', type=int, default=3, help='number of development folds (default: 3)')
    parser.add_argument('--seed', type=int, default=413, help='group tie-break seed (default: 413)')
    args = parser.parse_args()
    try:
        report = evaluate(args.manifest.resolve(), args.folds, args.seed)
    except subprocess.CalledProcessError as error:
        parser.exit(1, f'grouped CV: production worker failed (exit {error.returncode})\n')
    except (OSError, ValueError) as error:
        parser.exit(1, f'grouped CV: {error}\n')
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
