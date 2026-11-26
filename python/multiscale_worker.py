"""Local mask-only multiscale worker for the workbench's train/predict CLI.

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

VERSION = 'review-multiscale-cleanup-v1'
SETTINGS = {'grid_width': inference.SIDE, 'boosting_iterations': training.ITERATIONS, 'arrow_prediction': False}


def versions():
    return {'sklearn': sklearn.__version__, 'numpy': np.__version__, 'scipy': scipy.__version__,
            'pillow': legacy.PILLOW_VERSION, 'joblib': joblib.__version__}


def train(manifest, out):
    # Go freezes and exports approved revisions; reuse the legacy snapshot
    # parser so the two workers don't diverge on which rows reach fitting.
    raw = manifest.read_bytes()
    rows = list(legacy.manifest_rows(raw))
    grids, excluded = training.prepare(rows, manifest.parent.resolve())
    models, priors = training.fit_regions(grids, range(len(rows)), training.ITERATIONS)
    if not models:
        raise ValueError('no reviewed masks with usable positive and negative pixels')
    contributing = {key: [row['id'] for row, (_, labels) in zip(rows, grids, strict=True)
                         if key in labels] for key in models}
    # Joblib preserves the fitted scikit-learn objects and NumPy priors. Keep
    # provenance and compatibility metadata in the JSON envelope so callers
    # can inspect it without deserializing the fitted payload.
    payload = BytesIO()
    joblib.dump({'regions': models, 'priors': {key: priors[key] for key in models}}, payload, compress=3)
    legacy.write_json(out, {'version': VERSION, 'dependencies': versions(),
        'settings': SETTINGS,
        'training_policy': 'bounded-canonical-prior-v1', 'collapsed_positive_masks_skipped': excluded,
        'manifest_sha256': legacy.sha256(raw),
        'training_ids': sorted({cid for ids in contributing.values() for cid in ids}),
        'targets': {key: {'status': 'learned', 'training_ids': contributing[key]} if key in models
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
        legacy.predict(model, image, out, model_data=model_data)
        return
    # The version and settings pin the inference contract; exact dependency
    # matches avoid assuming fitted objects are portable across versions.
    if meta.get('version') != VERSION or meta.get('dependencies') != versions():
        raise ValueError('incompatible multiscale checkpoint or dependencies; retrain in the active environment')
    if meta.get('settings') != SETTINGS:
        raise ValueError('incompatible multiscale checkpoint settings')
    fitted = joblib.load(BytesIO(base64.b64decode(meta['payload_base64'], validate=True)))
    if not set(fitted['regions']).issubset(legacy.MASK_TARGETS) or set(fitted['priors']) != set(fitted['regions']):
        raise ValueError('invalid multiscale checkpoint targets')
    raw = image.read_bytes()
    source = legacy.read_image(BytesIO(raw))
    _, guided = inference.outputs(fitted['regions'], fitted['priors'], inference.feature_image(source))
    out.mkdir(parents=True, exist_ok=True)
    # Empty predictions and unsupported targets (including the arrow) abstain;
    # lack of a proposed mask is not evidence that the region is absent.
    targets = {key: {'status': 'indeterminate'} for key in legacy.TARGETS}
    for key, mask in guided.items():
        if mask.any():
            path = f'{key}.png'
            # Map the binary grid back to editor coordinates without interpolating labels.
            layer = Image.fromarray(mask.astype(np.uint8)*255).resize(source.size, Image.Resampling.NEAREST)
            layer.save(out/path, format='PNG')
            targets[key] = {'status': 'present', 'mask': path}
    legacy.write_json(out/'proposal.json', {'image_sha256': legacy.sha256(raw), 'targets': targets,
        'source': 'prediction', 'model_version': VERSION, 'model_sha256': actual_sha})


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
