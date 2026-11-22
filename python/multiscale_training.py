"""Prepare supervised snapshot grids and fit the production multiscale mask model."""
import math

import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from sklearn.ensemble import HistGradientBoostingClassifier

import multiscale_inference_v1 as inference
import review_worker as legacy

ITERATIONS = 160
SEED = 413
# ~319 MiB of retained float feature grids, excluding fit/asset overhead.
MAX_TRAIN_GRID_CELLS = 2_200_000


def prepare(rows, root):
    """Read supervised masks from train rows and track positives lost at grid scale."""
    # The app owns approval; shared snapshot rules distinguish explicit absence
    # from unknown, proposal and prediction labels, which give no supervision.
    supervision = [list(legacy.supervised_masks(row)) for row in rows]
    # Check the total retained feature budget before decoding any assets.
    cells = 0
    for row, labels in zip(rows, supervision, strict=True):
        if labels:
            size = row.get('width'), row.get('height')
            if any(type(n) is not int or n < 1 for n in size):
                raise ValueError('invalid training scan dimensions')
            cells += math.prod(inference.grid_size(size))
    if cells > MAX_TRAIN_GRID_CELLS:
        raise ValueError('multiscale training grid budget exceeded; no checkpoint produced')
    grids, excluded = [], []
    for row, labels in zip(rows, supervision, strict=True):
        if not labels:
            grids.append((None, {}))
            continue
        masks = {}
        image = legacy.read_image(legacy.asset(root, row['image']))
        legacy.check_size(row, image.size)
        w, h = inference.grid_size(image.size)
        for key, path in labels:
            if path is None:
                masks[key] = np.zeros((h, w), dtype=bool)
                continue
            with Image.open(legacy.asset(root, path)) as mask:
                if (mask.format != 'PNG' or mask.mode not in ('1', 'L') or mask.size != image.size
                        or getattr(mask, 'n_frames', 1) != 1):
                    raise ValueError(f"{row['id']}: expected aligned grayscale mask for {key}")
                plane = mask.convert('L')
                hist = plane.histogram()
                if not hist[255] or sum(hist[1:255]):
                    raise ValueError(f"{row['id']}: expected nonempty binary mask for {key}")
                pixels = np.asarray(plane.resize((w, h), Image.Resampling.BOX)) >= 128
            # A positive that vanishes on the grid must not become a negative.
            if pixels.any():
                masks[key] = pixels
            else:
                excluded.append({'id': row['id'], 'target': key})
        grids.append((inference.feature_image(image), masks) if masks else (None, {}))
    return grids, excluded


def new_classifier(iterations):
    return HistGradientBoostingClassifier(max_iter=iterations, max_leaf_nodes=31,
        min_samples_leaf=45, learning_rate=.11, l2_regularization=1.5,
        early_stopping=False, random_state=SEED)


def fit_regions(grids, indices, iterations):
    """Fit one classifier per region that has both positive and negative support."""
    models = {}
    priors = {}
    for key in legacy.MASK_TARGETS:
        rng = np.random.default_rng(SEED + legacy.MASK_TARGETS.index(key))
        xs, ys, ws, masks = [], [], [], []
        for i in indices:
            fs, labels = grids[i]
            if key not in labels:
                continue
            m = labels[key]
            data = fs.reshape(-1, fs.shape[-1])
            yes, no = np.flatnonzero(m), np.flatnonzero(~m)
            if len(yes):
                masks.append(m)
            # Bound samples per scan, retaining hard negatives near mask edges.
            edge = np.flatnonzero(ndi.binary_dilation(m, iterations=6) & ~m)
            p = rng.choice(yes, min(len(yes), 1600), replace=False)
            n = np.unique(np.r_[rng.choice(no, min(len(no), 2300), replace=False),
                                rng.choice(edge, min(len(edge), 1000), replace=False)])
            xs.extend((data[p], data[n]))
            ys.extend((np.ones(len(p), dtype=np.uint8), np.zeros(len(n), dtype=np.uint8)))
            ws.extend((np.full(len(p), 1800/max(1,len(p))), np.full(len(n), 2800/max(1,len(n)))))
        if masks:
            # Positive masks share a canonical grid even when scans differ in size.
            shape = inference.CANONICAL_SHAPE
            average = np.mean([inference.resize_prior(m, shape) for m in masks], axis=0).astype(np.float32)
            priors[key] = ndi.gaussian_filter(average, 2.0)
        if ys and len(np.unique(np.concatenate(ys))) == 2:
            models[key] = new_classifier(iterations).fit(np.concatenate(xs), np.concatenate(ys),
                                                       sample_weight=np.concatenate(ws))
    return models, priors
