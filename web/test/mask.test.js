import assert from 'node:assert/strict';
import test from 'node:test';
import { decode, encode } from 'fast-png';
import * as mask from '../src/mask.js';
const { nativePoint, brushStroke } = mask;

test('maps a scrolled and scaled viewport to integer native pixels', () => {
  const rect = { left: -20, top: 100, width: 80, height: 40 };
  assert.deepEqual(nativePoint(1, 107, rect, 20, 10), [5, 1]);
  assert.deepEqual(nativePoint(-21, 200, rect, 20, 10), [0, 9]);
  assert.deepEqual(nativePoint(60, 140, rect, 20, 10), [19, 9]);
});

test('a one-pixel brush fills a fast stroke without holes; eraser changes only its pixel', () => {
  const plane = new Uint8Array(15);
  assert.deepEqual(brushStroke(plane, 5, 3, [0, 1], [4, 1], 1, 1), [0, 1, 5, 1]);
  assert.deepEqual(brushStroke(plane, 5, 3, [2, 1], [2, 1], 1, 0), [2, 1, 1, 1]);
  assert.equal(brushStroke(plane, 5, 3, [2, 1], [2, 1], 1, 0), null);
  assert.deepEqual([...plane], [0, 0, 0, 0, 0, 1, 1, 0, 1, 1, 0, 0, 0, 0, 0]);
});

test('export round-trips exact opaque black and white samples without canvas readback', () => {
  const bytes = mask.binaryPNG(Uint8Array.of(0, 1, 0), 3, 1);
  const image = decode(bytes);
  assert.deepEqual([image.width, image.height, image.depth, image.channels], [3, 1, 8, 1]);
  assert.deepEqual([...image.data], [0, 255, 0]);
  assert.deepEqual([...mask.decodeBinaryMask(bytes, 3, 1)], [0, 1, 0]);
  assert.deepEqual(Buffer.from(mask.encodeMask(Uint8Array.of(0, 1, 0), 3, 1), 'base64'), Buffer.from(bytes));
  assert.throws(() => mask.decodeBinaryMask(bytes, 1, 3), /dimensions/);
});

test('decodes opaque RGBA binary masks without thresholding nonbinary input', () => {
  const png = (data) => encode({ width: 1, height: 1, channels: 4, depth: 8, data: Uint8Array.from(data) });
  assert.deepEqual([...mask.decodeBinaryMask(png([255, 255, 255, 255]), 1, 1)], [1]);
  assert.throws(() => mask.decodeBinaryMask(png([0, 1, 0, 255]), 1, 1), /binary/);
  assert.throws(() => mask.decodeBinaryMask(png([0, 0, 0, 254]), 1, 1), /binary/);
});
