"""Frozen version 1 multiscale mask features and inference.

Keep the behavior for supported checkpoints stable. Changes to the feature or
cleanup contract require a new model version and an explicit reader.
"""
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

SIDE = 256
CANONICAL_SHAPE = (192, SIDE)
REGIONS = ('breech_face', 'aperture_shear', 'firing_pin_shear', 'firing_pin_impression')


def grid_size(size):
    # Keep native aspect ratio and cap feature work by the longest side.
    ratio = min(1., SIDE / max(size))
    return tuple(max(1, round(length * ratio)) for length in size)


def feature_image(im):
    w, h = grid_size(im.size)
    raw = np.asarray(im.resize((w, h), Image.Resampling.BILINEAR), dtype=np.float32) / 255
    lo, hi = np.percentile(raw, (2, 98))
    g = np.clip((raw - lo) / max(hi-lo, .04), 0, 1)
    y, x = np.indices(g.shape, dtype=np.float32)
    x = (x+.5)/w - .5
    y = (y+.5)/h - .5
    fs = [x, y, np.hypot(x, y), raw, g]
    # Different blur scales preserve both small marks and wider texture cues.
    for scale in (1, 3, 7, 15, 28):
        low = ndi.gaussian_filter(g, scale)
        dy, dx = (np.gradient(low, axis=i) if n > 1 else np.zeros_like(low)
                  for i, n in enumerate(low.shape))
        variance = np.maximum(0, ndi.gaussian_filter(g*g, scale) - low*low)
        fs.extend([low, g-low, dx, dy, np.sqrt(variance)])
    # Local spatial context; broad neighbors help distinguish dark structures.
    smooth = fs[10]
    for axis in (0, 1):
        for shift in (-18, -8, 8, 18):
            step = [0, 0]
            step[axis] = shift
            fs.append(ndi.shift(smooth, step, order=0, mode='nearest'))
    return np.stack(fs, axis=-1).astype(np.float32, copy=False)


def resize_prior(plane, shape):
    # Array shapes are (height, width); Pillow expects (width, height).
    if plane.shape == shape:
        return plane
    return np.asarray(Image.fromarray(plane.astype(np.float32)).resize(shape[::-1], Image.Resampling.BILINEAR))


def outputs(model, prior, fs):
    h, w, c = fs.shape
    features = fs.reshape(-1,c)
    plain, guided = {}, {}
    for k, clf in model.items():
        p = clf.predict_proba(features)[:, 1].reshape(h, w)
        plain[k] = p >= .5
        # Clean scattered pixels without forcing a specific specimen shape.
        s = ndi.gaussian_filter(p, .9)
        thresh = .50 + .13 * (.35 - resize_prior(prior[k], (h, w)))
        m = s >= thresh
        cc, _ = ndi.label(m)
        counts = np.bincount(cc.ravel())
        keep = counts >= (25 if k != REGIONS[0] else 65)
        keep[0] = False
        guided[k] = keep[cc]
    return plain, guided
