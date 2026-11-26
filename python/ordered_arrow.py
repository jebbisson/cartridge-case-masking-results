"""Best-effort ordered arrow proposals, never verified impact keypoints.

The bundled aggregate prior is fitted only to the released train snapshot's
reviewed ordered annotations. It contains no per-image lookup or image data.
"""
import json
from io import BytesIO
import re
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi

import review_worker as legacy

TARGET = 'firing_pin_drag_direction'
VERSION = 'ordered-arrow-prior-v1'


def validate_head(head):
    try:
        start = np.asarray(head['start'], dtype=float)
        direction = np.asarray(head['direction'], dtype=float)
        valid = (head['version'] == VERSION and start.shape == direction.shape == (2,)
                 and np.isfinite(start).all() and ((0 <= start) & (start < 1)).all()
                 and np.isfinite(direction).all() and np.isclose(np.linalg.norm(direction), 1.)
                 and type(head['length']) in (int, float) and 0 < head['length'] <= np.sqrt(2)
                 and type(head['annotation_count']) is int and head['annotation_count'] > 0
                 and isinstance(head['manifest_sha256'], str)
                 and re.fullmatch(r'[0-9a-f]{64}', head['manifest_sha256']) is not None)
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError('invalid ordered-arrow head or provenance')
    return head


def bundled_head():
    return validate_head(json.loads(Path(__file__).with_name('arrow_head_v1.json').read_text(encoding='utf-8')))


def fit(rows, root, manifest_sha256):
    """Fit a compact ordered prior; unknowns and machine suggestions supply no labels.

    Approval belongs to the caller/exporter. These checks enforce the exported
    split/origin contract, not an independent claim of annotation correctness.
    """
    points, used = [], []
    for row in rows:
        if row.get('split') != 'train':
            continue
        labels = row.get('labels')
        if not isinstance(labels, dict):
            raise ValueError('missing labels object')
        entry = labels.get(TARGET, {'status': 'not_annotated'})
        if not isinstance(entry, dict):
            raise ValueError('expected an arrow label object')
        if entry.get('origin', row.get('origin')) in ('proposal', 'prediction'):
            continue
        if entry.get('status') not in ('present', 'absent', 'indeterminate', 'not_annotated'):
            raise ValueError('invalid arrow label status')
        if entry['status'] != 'present':
            continue
        raw = legacy.asset(root, row.get('image')).read_bytes()
        if 'image_sha256' in row and legacy.sha256(raw) != row['image_sha256']:
            raise ValueError('arrow training image digest mismatch')
        image = legacy.read_image(BytesIO(raw))
        legacy.check_size(row, image.size)
        try:
            xy = np.asarray([entry['start'], entry['end']], dtype=float)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError('invalid reviewed arrow endpoints') from error
        if (xy.shape != (2, 2) or not np.isfinite(xy).all() or (xy < 0).any()
                or (xy >= image.size).any() or np.array_equal(xy[0], xy[1])):
            raise ValueError('reviewed arrow needs distinct finite in-frame ordered endpoints')
        points.append(xy / image.size)
        used.append(row['id'])
    if not points:
        return None, []
    points = np.asarray(points)
    vectors = points[:, 1] - points[:, 0]
    lengths = np.linalg.norm(vectors, axis=1)
    direction = np.mean(vectors / lengths[:, None], axis=0)
    if np.linalg.norm(direction) < 1e-12:
        # Opposing annotations can cancel; retain an observed order, not a
        # fabricated positive annotation, and never store a per-case lookup.
        direction = vectors[int(np.argmax(lengths))]
    direction /= np.linalg.norm(direction)
    return {'version': VERSION, 'start': np.median(points[:, 0], axis=0).tolist(),
            'direction': direction.tolist(), 'length': float(np.median(lengths)),
            'annotation_count': len(used), 'manifest_sha256': manifest_sha256}, used


def predict(head, masks, size):
    """Return an in-frame, nonzero, ordered integer arrow, without confidence gating."""
    validate_head(head)
    bounds = np.asarray(size, dtype=int) - 1
    if (bounds < 0).any() or not bounds.any():
        raise ValueError('ordered integer arrow needs at least two image pixels')
    start = np.asarray(head['start']) * size
    vector = np.asarray(head['direction']) * head['length'] * size
    end = start + vector
    method = 'normalized_prior'
    # Project convention v2: PURPLE shear is the center pocket; CYAN
    # impression is the outgoing scrape. Stored IDs are not upstream anatomy.
    pocket = masks.get('firing_pin_shear')
    scrape = masks.get('firing_pin_impression')
    if pocket is not None and np.any(pocket):
        all_pocket = np.asarray(pocket, dtype=bool)
        components, _ = ndi.label(all_pocket)
        pocket = components == (np.argmax(np.bincount(components.ravel())[1:]) + 1)
        h, w = pocket.shape
        scale = np.asarray(size) / [w, h]
        pxy = (np.argwhere(pocket)[:, ::-1] + .5) * scale
        center = pxy.mean(axis=0)
        start = pxy[np.argmin(np.sum((pxy - center)**2, axis=1))]
        end = start + vector
        method = 'predicted_pocket_prior'
        if scrape is not None and np.any(scrape):
            if np.shape(scrape) != pocket.shape:
                raise ValueError('unaligned predicted arrow support')
            outside = np.asarray(scrape, dtype=bool) & ~all_pocket
            if outside.any():
                # Associate the strongest nearby exterior component, as in
                # component-projection geometry. No area/coherence gate hides
                # a weak result; missing geometry uses the learned prior.
                cc, _ = ndi.label(outside)
                gap = ndi.distance_transform_edt(~pocket, sampling=tuple(scale[::-1]))
                radius = max(float(np.sqrt(pocket.sum() * np.prod(scale) / np.pi)), 1.)
                strength = np.bincount(cc[outside], weights=np.exp(-gap[outside] / radius))
                chosen = cc == (int(np.argmax(strength[1:])) + 1)
                sxy = (np.argwhere(chosen)[:, ::-1] + .5) * scale
                axis = sxy.mean(axis=0) - start
                if np.linalg.norm(axis) < 1e-12:
                    axis = vector
                axis /= np.linalg.norm(axis)
                forward = (sxy - start) @ axis
                station = np.quantile(forward, .75)
                lateral = (sxy - start) @ np.array([-axis[1], axis[0]])
                end = sxy[np.argmin((forward - station)**2 + lateral**2)]
                method = 'predicted_support_geometry'
    elif scrape is not None and np.any(scrape):
        h, w = scrape.shape
        sxy = (np.argwhere(scrape)[:, ::-1] + .5) * (np.asarray(size) / [w, h])
        center = sxy.mean(axis=0)
        end = sxy[np.argmin(np.sum((sxy - center)**2, axis=1))]
        start = end - vector
        method = 'predicted_scrape_prior'
    points = np.clip(np.rint([start, end]).astype(int), 0, bounds)
    repaired = bool(np.array_equal(points[0], points[1]))
    if repaired:
        # Keep the ordered direction when clipping or rounding erases length:
        # move the tail inward if the tip cannot advance at the image boundary.
        delta = end - start
        preferred = np.where(bounds > 0, np.abs(delta), -1.)
        axis = int(np.argmax(preferred))
        sign = 1 if delta[axis] >= 0 else -1
        if 0 <= points[1, axis] + sign <= bounds[axis]:
            points[1, axis] += sign
        else:
            points[0, axis] -= sign
    return {'status': 'present', 'start': points[0].tolist(), 'end': points[1].tolist()}, {
        'method': method, 'fallback': method != 'predicted_support_geometry', 'best_effort': True,
        'quantization_repaired': repaired,
        'endpoint_semantics': 'ordered estimates, not verified impact points',
        'head_version': head['version'], 'head_manifest_sha256': head['manifest_sha256'],
        'annotation_count': head['annotation_count']}
