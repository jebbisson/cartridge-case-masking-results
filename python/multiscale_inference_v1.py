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
    # Pillow's bilinear resize trades native detail for a bounded intensity grid.
    # Keep both raw intensity and percentile-normalized contrast; the span floor
    # limits noise amplification on nearly flat scans.
    raw = np.asarray(im.resize((w, h), Image.Resampling.BILINEAR), dtype=np.float32) / 255
    lo, hi = np.percentile(raw, (2, 98))
    g = np.clip((raw - lo) / max(hi-lo, .04), 0, 1)
    y, x = np.indices(g.shape, dtype=np.float32)
    x = (x+.5)/w - .5
    y = (y+.5)/h - .5
    # Fitted trees address columns by index: centered x, y and radius give a
    # location cue, followed by raw intensity and normalized contrast.
    fs = [x, y, np.hypot(x, y), raw, g]
    # At each scale, append the SciPy Gaussian level, fine residual, NumPy x/y
    # gradients and local standard deviation, in that order. The same groups
    # expose narrow edges and broader texture without resizing the feature grid.
    for scale in (1, 3, 7, 15, 28):
        low = ndi.gaussian_filter(g, scale)
        dy, dx = (np.gradient(low, axis=i) if n > 1 else np.zeros_like(low)
                  for i, n in enumerate(low.shape))
        variance = np.maximum(0, ndi.gaussian_filter(g*g, scale) - low*low)
        fs.extend([low, g-low, dx, dy, np.sqrt(variance)])
    # After five base planes and five sigma-1 planes, fs[10] is the sigma-3
    # intensity plane. Its neighbors add context less sensitive to pixel noise.
    # Append row shifts before column shifts; nearest-edge padding avoids
    # introducing artificial dark borders.
    smooth = fs[10]
    for axis in (0, 1):
        for shift in (-18, -8, 8, 18):
            step = [0, 0]
            step[axis] = shift
            fs.append(ndi.shift(smooth, step, order=0, mode='nearest'))
    return np.stack(fs, axis=-1).astype(np.float32, copy=False)


def resize_prior(plane, shape):
    # The prior is a soft field, not a binary mask: interpolate with Pillow to
    # compare relative locations across scan sizes. Pillow takes width first.
    if plane.shape == shape:
        return plane
    return np.asarray(Image.fromarray(plane.astype(np.float32)).resize(shape[::-1], Image.Resampling.BILINEAR))


def outputs(model, prior, fs):
    h, w, c = fs.shape
    features = fs.reshape(-1,c)
    plain, guided = {}, {}
    for k, clf in model.items():
        # The unguided baseline cuts raw scores at .50. For proposals, smooth
        # isolated score spikes, then use the prior to shift the cutoff: .35 is
        # neutral, higher values lower the cutoff, and .13 scales the adjustment.
        # These v1 heuristics favor common locations without imposing a shape.
        p = clf.predict_proba(features)[:, 1].reshape(h, w)
        plain[k] = p >= .5
        s = ndi.gaussian_filter(p, .9)
        thresh = .50 + .13 * (.35 - resize_prior(prior[k], (h, w)))
        m = s >= thresh
        # SciPy labels islands so they can be filtered by area. V1 rejects
        # small breech-face islands more strictly (65 grid cells vs. 25 for
        # other regions); these are cleanup cutoffs, not physical size limits.
        cc, _ = ndi.label(m)
        counts = np.bincount(cc.ravel())
        keep = counts >= (25 if k != REGIONS[0] else 65)
        keep[0] = False
        guided[k] = keep[cc]
    return plain, guided
