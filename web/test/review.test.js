import test from 'node:test';
import assert from 'node:assert/strict';
import { reviewPayload, isTrainingSplit, revisionLabel, DRAG, TARGETS } from '../src/review.js';

test('inspector and mask layers use the assignment legend colors', () => {
  assert.deepEqual(Object.fromEntries(TARGETS.map(({ id, color }) => [id, color])), {
    breech_face: [235, 65, 67], // Red
    aperture_shear: [65, 184, 88], // Green
    firing_pin_shear: [171, 101, 217], // Purple
    firing_pin_impression: [101, 214, 240], // Light blue
    [DRAG]: [49, 110, 246], // Blue
  });
});

test('distinguishes local estimates, external proposals and approved source masks', () => {
  assert.equal(revisionLabel({ kind: 'proposal', source: { method: 'local_prediction' } }), 'Estimate');
  assert.equal(revisionLabel({ kind: 'proposal', source: { method: 'external_proposal' } }), 'Proposal');
  assert.equal(revisionLabel({ kind: 'source' }, true), 'Approved source');
  assert.equal(revisionLabel({ kind: 'approved' }), 'Approved');
});

const encode = () => 'png-body';

test('review keeps unchanged masks by reference and strips geometry from non-present statuses', () => {
  const targets = {
    breech_face: { status: 'present', mask_url: '/api/mask', origin: 'estimate' },
    aperture_shear: { status: 'indeterminate', mask_url: '/api/old-mask' },
    [DRAG]: { status: 'present', start: [5, 6], end: [2, 1] },
  };
  const result = reviewPayload(7, true, targets, {}, new Set(), 8, 8, encode);
  assert.equal(result.base_revision, 7);
  assert.equal(result.approve, true);
  assert.deepEqual(result.targets.breech_face, { status: 'present' });
  assert.deepEqual(result.targets.aperture_shear, { status: 'indeterminate' });
  assert.deepEqual(result.targets.firing_pin_shear, { status: 'not_annotated' });
  assert.deepEqual(result.targets[DRAG], { status: 'present', start: [5, 6], end: [2, 1] });
});

test('review exports changed masks and refuses an empty present layer', () => {
  const targets = { breech_face: { status: 'present', mask_url: '/api/old-mask' } };
  const changed = new Set(['breech_face']);
  assert.equal(reviewPayload(7, false, targets, { breech_face: Uint8Array.of(1) }, changed, 1, 1, encode).targets.breech_face.mask_png, 'png-body');
  assert.throws(() => reviewPayload(7, false, targets, { breech_face: Uint8Array.of(0) }, changed, 1, 1, encode), /paint at least one pixel/);
});

test('refuses present arrows without distinct endpoints inside the native grid', () => {
  for (const end of [null, [0, 0], [4, 0]]) {
    assert.throws(() => reviewPayload(7, false, { [DRAG]: { status: 'present', start: [0, 0], end } }, {}, new Set(), 4, 4, encode), /distinct endpoints/);
  }
});

test('only the training split can opt into training', () => {
  assert.equal(isTrainingSplit('train'), true);
  for (const split of ['test', 'validation', 'holdout', 'heldout', undefined]) assert.equal(isTrainingSplit(split), false);
});
