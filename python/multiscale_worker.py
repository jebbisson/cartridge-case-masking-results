"""Local multiscale masks and best-effort ordered-arrow worker for the workbench's train/predict CLI.

The app owns and digest-checks generated checkpoints. Do not load checkpoints
from untrusted sources: the multiscale payload contains fitted joblib objects.
"""
import argparse
import base64
from io import BytesIO
import json
import os
from pathlib import Path

# Cap numerical-library threads before import so local fits don't oversubscribe
# the workbench CPU.
for key, bound in {'OMP_NUM_THREADS': '3', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}.items():
    os.environ[key] = bound

import joblib
import numpy as np
import sklearn
import scipy
from PIL import Image

# These modules fit and score on the local CPU; neither calls GPT or the network.
import multiscale_inference_v1 as inference
import multiscale_training as training
import review_worker as legacy
import ordered_arrow as arrows

MASK_VERSION = 'review-multiscale-cleanup-v1'
VERSION = 'review-multiscale-arrow-v2'
MASK_SETTINGS = {'grid_width': inference.SIDE, 'boosting_iterations': training.ITERATIONS, 'arrow_prediction': False}
SETTINGS = {**MASK_SETTINGS, 'arrow_prediction': True}


def versions():
    return {'sklearn': sklearn.__version__, 'numpy': np.__version__, 'scipy': scipy.__version__,
            'pillow': legacy.PILLOW_VERSION, 'joblib': joblib.__version__}


def train(manifest, out):
    # Go freezes and exports approved revisions; reuse the legacy snapshot
    # parser so the two workers don't diverge on which rows reach fitting.
    raw = manifest.read_bytes()
    rows = list(legacy.manifest_rows(raw))
    arrow_head, arrow_ids = arrows.fit(rows, manifest.parent.resolve(), legacy.sha256(raw))
    grids, excluded = training.prepare(rows, manifest.parent.resolve())
    models, priors = training.fit_regions(grids, range(len(rows)), training.ITERATIONS)
    if not models:
        raise ValueError('no reviewed masks with usable positive and negative pixels')
    contributing = {key: [row['id'] for row, (_, labels) in zip(rows, grids, strict=True)
                         if key in labels] for key in models}
    if arrow_ids:
        contributing[arrows.TARGET] = arrow_ids
    # Joblib preserves the fitted scikit-learn objects and NumPy priors. Keep
    # provenance and compatibility metadata in the JSON envelope so callers
    # can inspect it without deserializing the fitted payload.
    payload = BytesIO()
    joblib.dump({'regions': models, 'priors': {key: priors[key] for key in models}}, payload, compress=3)
    legacy.write_json(out, {'version': VERSION, 'dependencies': versions(),
        'settings': SETTINGS,
        'training_policy': 'bounded-canonical-prior-v1', 'collapsed_positive_masks_skipped': excluded,
        'manifest_sha256': legacy.sha256(raw), 'arrow_head': arrow_head,
        'training_ids': sorted({cid for ids in contributing.values() for cid in ids}),
        'targets': {key: {'status': 'learned', 'training_ids': contributing[key]} if key in contributing
                    else {'status': 'unlearned', 'training_ids': []} for key in legacy.TARGETS},
        'payload_base64': base64.b64encode(payload.getvalue()).decode('ascii')})


def predict(model, image, out, expected_sha):
    # Verify the bytes we will deserialize against an independently trusted digest.
    # A checksum supplied alongside an untrusted checkpoint grants no trust.
    model_data = model.read_bytes()
    actual_sha = legacy.sha256(model_data)
    if actual_sha != expected_sha:
        raise ValueError('checkpoint digest missing or mismatched; use a trusted pinned digest')
    meta = json.loads(model_data, object_pairs_hook=legacy.unique_object)
    if not isinstance(meta, dict):
        raise ValueError('invalid checkpoint object')
    if meta.get('version') == legacy.MODEL_VERSION:
        # Keep old successful runs usable without refitting. Pass the exact
        # digest-checked bytes so the legacy JSON reader need not reopen the file.
        source = legacy.read_image(image)
        # The integer geometry contract has no distinct endpoints on a 1x1 PNG.
        if source.size == (1, 1):
            raise ValueError('ordered integer arrow needs at least two image pixels')
        legacy.predict(model, image, out, model_data=model_data)
        proposal = json.loads((out/'proposal.json').read_text(encoding='utf-8'))
        support = {}
        for key in ('firing_pin_impression', 'firing_pin_shear'):
            entry = proposal['targets'][key]
            if entry['status'] == 'present':
                with Image.open(out/entry['mask']) as layer:
                    support[key] = np.asarray(layer.resize(inference.grid_size(source.size),
                                                          Image.Resampling.NEAREST)) != 0
        proposal['targets'][arrows.TARGET], proposal['arrow_prediction'] = arrows.predict(
            arrows.bundled_head(), support, source.size)
        legacy.write_json(out/'proposal.json', proposal)
        return
    # The version and settings pin the inference contract; exact dependency
    # matches avoid assuming fitted objects are portable across versions.
    if meta.get('version') not in (MASK_VERSION, VERSION) or meta.get('dependencies') != versions():
        raise ValueError('incompatible multiscale checkpoint or dependencies; retrain in the active environment')
    expected_settings = MASK_SETTINGS if meta['version'] == MASK_VERSION else SETTINGS
    if meta.get('settings') != expected_settings:
        raise ValueError('incompatible multiscale checkpoint settings')
    head = meta.get('arrow_head') if meta['version'] == VERSION else None
    if head is not None:
        arrows.validate_head(head)
        if head['manifest_sha256'] != meta.get('manifest_sha256'):
            raise ValueError('ordered-arrow head provenance does not match checkpoint snapshot')
    fitted = joblib.load(BytesIO(base64.b64decode(meta['payload_base64'], validate=True)))
    if not set(fitted['regions']).issubset(legacy.MASK_TARGETS) or set(fitted['priors']) != set(fitted['regions']):
        raise ValueError('invalid multiscale checkpoint targets')
    raw = image.read_bytes()
    source = legacy.read_image(BytesIO(raw))
    if source.size == (1, 1):
        raise ValueError('ordered integer arrow needs at least two image pixels')
    _, guided = inference.outputs(fitted['regions'], fitted['priors'], inference.feature_image(source))
    out.mkdir(parents=True, exist_ok=True)
    # Empty mask predictions abstain; no mask is not evidence of absence.
    # The ordered arrow is always a best-effort proposal, never suppressed.
    targets = {key: {'status': 'indeterminate'} for key in legacy.TARGETS}
    for key, mask in guided.items():
        if mask.any():
            path = f'{key}.png'
            # Map the binary grid back to editor coordinates without interpolating labels.
            layer = Image.fromarray(mask.astype(np.uint8)*255).resize(source.size, Image.Resampling.NEAREST)
            layer.save(out/path, format='PNG')
            targets[key] = {'status': 'present', 'mask': path}
    targets[arrows.TARGET], arrow_info = arrows.predict(
        head if head is not None else arrows.bundled_head(), guided, source.size)
    legacy.write_json(out/'proposal.json', {'image_sha256': legacy.sha256(raw), 'targets': targets,
        'source': 'prediction', 'model_version': meta['version'], 'model_sha256': actual_sha,
        'arrow_prediction': arrow_info})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name, attrs in (('train', ('manifest', 'out')), ('predict', ('model', 'image', 'out'))):
        cmd = sub.add_parser(name)
        for attr in attrs:
            cmd.add_argument('--'+attr, type=Path, required=True)
        if name == 'predict':
            cmd.add_argument('--expected-model-sha256', default=os.environ.get('REVIEWAPP_MODEL_SHA256'))
    args = parser.parse_args()
    try:
        if args.command == 'train':
            train(args.manifest, args.out)
        else:
            predict(args.model, args.image, args.out, args.expected_model_sha256)
    except (ValueError, OSError) as error:
        parser.exit(1, f'{args.command}: {error}\n')
