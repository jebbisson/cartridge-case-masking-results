"""Train and read legacy logistic checkpoints using only Pillow and Python.

The caller owns approval/export. Train consumes train rows only, skipping
proposal/prediction labels and unknown statuses. Omitted origin is supported
for trusted snapshot exports. A separate logistic classifier per region uses
gray-level/texture features and normalized position; masks can overlap. This
baseline does not learn directed keypoints or make specimen-level absence calls.
"""

import argparse
from collections import Counter
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import random
import tempfile

from PIL import Image, ImageChops, ImageFilter, __version__ as PILLOW_VERSION


MASK_TARGETS = ('breech_face', 'aperture_shear', 'firing_pin_shear', 'firing_pin_impression')
TARGETS = (*MASK_TARGETS, 'firing_pin_drag_direction')
MODEL_VERSION = 'review-pixel-logistic-v1'
FEATURES = ('bias', 'x', 'y', 'x²', 'xy', 'y²', 'gray', 'blur_1', 'blur_4',
            'blur_10', 'detail_1', 'detail_4', 'texture_1')
SETTINGS = {
    'max_grid_side': 128,
    'features': FEATURES,
    'image_resampling': 'bilinear',
    'mask_training_resampling': 'box_then_threshold_128',
    'mask_prediction_resampling': 'nearest',
    'seed': 413,
    'rng_scope': 'per_target',
    'max_samples_per_case_per_class': 800,
    'class_weighting': 'balanced',
    'epochs': 7,
    'learning_rate': 0.025,
    'epoch_decay': 0.35,
    'epoch_weight_shrink': 0.99,
    'logit_threshold': 0.0,
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f'duplicate JSON key: {key!r}')
        obj[key] = value
    return obj


def asset(root, value):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError(f'expected a relative asset path, got {value!r}')
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f'missing or out-of-root asset: {value!r}')
    return path


def manifest_rows(data):
    # Reject ambiguous snapshots and never expose held-out rows to fitting.
    seen = set()
    for number, line in enumerate(data.decode('utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line, object_pairs_hook=unique_object)
            if not isinstance(row, dict):
                raise ValueError('expected a JSON object')
            case_id = row.get('id')
            if not isinstance(case_id, str) or not case_id or case_id != case_id.strip() or case_id in seen:
                raise ValueError(f'invalid or duplicate id {case_id!r}')
            if row.get('split') not in ('train', 'validation', 'test'):
                raise ValueError(f'invalid split for {case_id}')
        except ValueError as error:
            raise ValueError(f'manifest line {number}: {error}') from error
        seen.add(case_id)
        if row['split'] == 'train':
            yield row


def supervised_masks(row):
    labels = row.get('labels')
    if not isinstance(labels, dict):
        raise ValueError('missing labels object')
    for key in MASK_TARGETS:
        entry = labels.get(key, {'status': 'not_annotated'})
        if not isinstance(entry, dict):
            raise ValueError(f'{key}: expected a label object')
        if entry.get('origin', row.get('origin')) in ('proposal', 'prediction'):
            continue
        status = entry.get('status')
        if status not in ('present', 'absent', 'indeterminate', 'not_annotated'):
            raise ValueError(f'{key}: invalid label status {status!r}')
        if status == 'present':
            mask = entry.get('mask')
            if not isinstance(mask, str) or not mask or Path(mask).is_absolute():
                raise ValueError(f'{key}: present label needs a relative mask path')
            yield key, mask
        elif status == 'absent':
            if 'mask' in entry:
                raise ValueError(f'{key}: absent label cannot have a mask')
            yield key, None


def read_image(path_or_stream):
    with Image.open(path_or_stream) as im:
        if im.format != 'PNG' or getattr(im, 'n_frames', 1) != 1:
            raise ValueError('expected a single-frame PNG image')
        return im.convert('L')


def check_size(row, size):
    # Raw pilot uses *_px; the compact review snapshot uses width and height.
    for key, actual in zip(('width', 'height'), size, strict=True):
        values = [row[name] for name in (key, f'{key}_px') if name in row]
        if not values or any(type(v) is not int or v != actual for v in values):
            raise ValueError(f'{key} does not match image')


def grid_size(size):
    factor = min(1.0, SETTINGS['max_grid_side'] / max(size))
    return tuple(max(1, round(n * factor)) for n in size)


def feature_grid(image):
    gray = image.resize(grid_size(image.size), Image.Resampling.BILINEAR)
    blur_1, blur_4, blur_10 = (gray.filter(ImageFilter.GaussianBlur(r)) for r in (1, 4, 10))
    texture = ImageChops.difference(gray, blur_1).filter(ImageFilter.GaussianBlur(1))
    w, h = gray.size
    x_coords = [(2 * i + 1) / w - 1 for i in range(w)]
    y_coords = [(2 * i + 1) / h - 1 for i in range(h)]
    result = []
    for i, (g, b1, b4, b10, tex) in enumerate(zip(
        *(im.tobytes() for im in (gray, blur_1, blur_4, blur_10, texture)), strict=True
    )):
        x, y = x_coords[i % w], y_coords[i // w]
        result.append((1.0, x, y, x*x, x*y, y*y, g / 255, b1 / 255, b4 / 255, b10 / 255,
                       (g-b1) / 64, (g-b4) / 64, tex / 64))
    return gray.size, result


def class_indices(root, mask_path, size, grid):
    if mask_path is None:
        return [], range(math.prod(grid))
    with Image.open(asset(root, mask_path)) as im:
        if (im.format != 'PNG' or im.mode not in ('1', 'L') or im.size != size
                or getattr(im, 'n_frames', 1) != 1):
            raise ValueError('mask must be an aligned grayscale PNG')
        mask = im.convert('L')
        histogram = mask.histogram()
        if sum(histogram[1:255]) or not histogram[255]:
            raise ValueError('present mask must be nonempty and binary (0/255)')
        positives, negatives = [], []
        for i, v in enumerate(mask.resize(grid, Image.Resampling.BOX).tobytes()):
            (positives if v >= 128 else negatives).append(i)
        # Do not quietly turn sub-grid positive annotations into negatives.
        return (positives, negatives) if positives else ([], [])


def logit(weights, features):
    return sum(w * v for w, v in zip(weights, features, strict=True))


def fit(examples, counts, rng):
    """Class-weighted logistic loss, optimized by seeded stochastic gradient descent."""
    weights = [0.0] * len(FEATURES)
    scale = [len(examples) / (2 * counts[y]) for y in (0, 1)]
    for epoch in range(SETTINGS['epochs']):
        rng.shuffle(examples)
        lr = SETTINGS['learning_rate'] / (1 + SETTINGS['epoch_decay'] * epoch)
        for features, y in examples:
            z = max(-40, min(40, logit(weights, features)))
            residual = lr * scale[y] * (y - 1 / (1 + math.exp(-z)))
            for i, v in enumerate(features):
                weights[i] += residual * v
        weights[1:] = [w * SETTINGS['epoch_weight_shrink'] for w in weights[1:]]
    return weights


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write in the destination filesystem so replacement is atomic.
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
        pending = Path(handle.name)
    try:
        pending.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def train(manifest, out):
    data = manifest.read_bytes()
    root = manifest.parent.resolve()
    rng = {key: random.Random(f"{SETTINGS['seed']}:{key}") for key in MASK_TARGETS}
    examples = {key: [] for key in MASK_TARGETS}
    counts = {key: Counter() for key in MASK_TARGETS}
    used = {key: [] for key in TARGETS}
    for row in sorted(manifest_rows(data), key=lambda r: r['id']):
        case_id = row['id']
        try:
            labels = list(supervised_masks(row))
            if not labels:
                continue
            image = read_image(asset(root, row.get('image')))
            check_size(row, image.size)
            grid, features = feature_grid(image)
            for key, mask_path in labels:
                positives, negatives = class_indices(root, mask_path, image.size, grid)
                if positives or negatives:
                    used[key].append(case_id)
                for y, indices in ((1, positives), (0, negatives)):
                    sample = rng[key].sample(indices, min(len(indices), SETTINGS['max_samples_per_case_per_class']))
                    examples[key].extend((features[i], y) for i in sample)
                    counts[key][y] += len(sample)
        except (ValueError, OSError) as error:
            raise ValueError(f'{case_id}: {error}') from error

    targets = {}
    all_used = set()
    for key in TARGETS:
        support = counts.get(key, Counter())
        entry = {'status': 'unlearned', 'training_ids': [],
                 'sampled_positive_pixels': support[1], 'sampled_negative_pixels': support[0]}
        if support[1] and support[0]:
            entry.update(status='learned', training_ids=used[key], weights=fit(examples[key], support, rng[key]))
            all_used.update(used[key])
        targets[key] = entry
    if not all_used:
        raise ValueError('no eligible masks with usable positive and negative pixels')
    write_json(out, {'version': MODEL_VERSION, 'manifest_sha256': sha256(data),
                     'settings': SETTINGS, 'pillow_version': PILLOW_VERSION,
                     'training_ids': sorted(all_used), 'targets': targets})


def predict(model, image_path, out, *, model_data=None):
    if model_data is None:
        model_data = model.read_bytes()
    checkpoint = json.loads(model_data, object_pairs_hook=unique_object)
    if (not isinstance(checkpoint, dict) or checkpoint.get('version') != MODEL_VERSION
            or checkpoint.get('settings') != json.loads(json.dumps(SETTINGS))):
        raise ValueError('unsupported checkpoint version or settings')
    fitted = checkpoint.get('targets')
    if not isinstance(fitted, dict) or set(fitted) != set(TARGETS):
        raise ValueError('checkpoint does not contain the canonical targets')
    image_data = image_path.read_bytes()
    image = read_image(BytesIO(image_data))
    grid, features = feature_grid(image)
    targets = {key: {'status': 'indeterminate'} for key in TARGETS}
    layers = {}
    for key in MASK_TARGETS:
        entry = fitted[key]
        if not isinstance(entry, dict) or entry.get('status') not in ('unlearned', 'learned'):
            raise ValueError(f'{key}: invalid checkpoint target')
        if entry['status'] == 'unlearned':
            continue
        weights = entry.get('weights')
        if (not isinstance(weights, list) or len(weights) != len(FEATURES)
                or any(type(w) not in (int, float) or not math.isfinite(w) for w in weights)):
            raise ValueError(f'{key}: invalid checkpoint weights')
        values = bytes(255 if logit(weights, f) >= SETTINGS['logit_threshold'] else 0 for f in features)
        if 255 in values:
            filename = f'{key}.png'
            layers[filename] = Image.frombytes('L', grid, values).resize(image.size, Image.Resampling.NEAREST)
            targets[key] = {'status': 'present', 'mask': filename}
    out.mkdir(parents=True, exist_ok=True)
    for filename, layer in layers.items():
        layer.save(out / filename, format='PNG')
    write_json(out / 'proposal.json', {'image_sha256': sha256(image_data), 'targets': targets,
                                       'source': 'prediction', 'model_version': MODEL_VERSION,
                                       'model_sha256': sha256(model_data)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    training = sub.add_parser('train')
    training.add_argument('--manifest', type=Path, required=True)
    training.add_argument('--out', type=Path, required=True)
    prediction = sub.add_parser('predict')
    prediction.add_argument('--model', type=Path, required=True)
    prediction.add_argument('--image', type=Path, required=True)
    prediction.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'train':
            train(args.manifest, args.out)
        else:
            predict(args.model, args.image, args.out)
    except (ValueError, OSError) as error:
        parser.exit(1, f'{args.command}: {error}\n')


if __name__ == '__main__':
    main()
