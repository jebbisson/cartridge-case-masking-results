import { convertIndexedToRgb, decode, encode } from 'fast-png';

export function nativePoint(x, y, rect, width, height) {
  const pixel = (offset, shown, size) => Math.max(0, Math.min(size - 1, Math.floor(offset * size / shown)));
  return [pixel(x - rect.left, rect.width, width), pixel(y - rect.top, rect.height, height)];
}

// Interpolate a stroke on the native grid and return its changed bounding box.
export function brushStroke(plane, width, height, from, to, diameter, value, onPixel) {
  const [x0, y0] = from;
  const dx = to[0] - x0;
  const dy = to[1] - y0;
  const steps = Math.max(Math.abs(dx), Math.abs(dy), 1);
  const radius = (diameter - 1) / 2;
  const extent = Math.floor(radius);
  let left = width, top = height, right = -1, bottom = -1;
  for (let step = 0; step <= steps; step++) {
    const cx = Math.round(x0 + dx * step / steps);
    const cy = Math.round(y0 + dy * step / steps);
    for (let y = Math.max(0, cy - extent); y <= Math.min(height - 1, cy + extent); y++) {
      for (let x = Math.max(0, cx - extent); x <= Math.min(width - 1, cx + extent); x++) {
        const index = y * width + x;
        if ((x - cx) ** 2 + (y - cy) ** 2 > radius ** 2 || plane[index] === value) continue;
        plane[index] = value;
        onPixel?.(index);
        left = Math.min(left, x);
        right = Math.max(right, x);
        top = Math.min(top, y);
        bottom = Math.max(bottom, y);
      }
    }
  }
  return right < 0 ? null : [left, top, right - left + 1, bottom - top + 1];
}

export function unionBounds(a, b) {
  if (!a) return b;
  const x = Math.min(a[0], b[0]), y = Math.min(a[1], b[1]);
  return [x, y, Math.max(a[0] + a[2], b[0] + b[2]) - x, Math.max(a[1] + a[3], b[1] + b[3]) - y];
}

// Exact native pixels of a single dab, in the same disk as brushStroke.
export function brushStampPath(diameter) {
  const r = (diameter - 1) / 2;
  return Array.from({ length: diameter }, (_, y) => {
    const half = Math.floor(Math.sqrt(r ** 2 - (y - r) ** 2));
    const span = 2 * half + 1;
    return `M${r - half} ${y}h${span}v1h${-span}Z`;
  }).join('');
}

export function binaryPNG(plane, width, height) {
  const bytes = plane.map(value => value ? 255 : 0);
  return encode({ width, height, depth: 8, channels: 1, data: bytes });
}

export function decodeBinaryMask(bytes, width, height) {
  // Canvas readback can add fingerprinting noise to exact binary samples.
  const png = decode(bytes);
  if (png.width !== width || png.height !== height) throw new Error('Mask and scan dimensions differ.');
  const { palette, transparency } = png;
  const data = palette ? convertIndexedToRgb(png) : png.data;
  const channels = palette ? palette[0].length : png.channels;
  const depth = palette ? 8 : png.depth;
  const white = (2 ** depth) - 1;
  const stride = Math.ceil(width * depth / 8);
  const plane = new Uint8Array(width * height);
  for (let i = 0; i < plane.length; i++) {
    const j = i * channels;
    const bit = (i % width) * depth;
    const v = depth >= 8 ? data[j] : (data[Math.floor(i / width) * stride + (bit >> 3)] >> (8 - depth - (bit % 8))) & white;
    if ((v !== 0 && v !== white) ||
      (channels >= 3 && (data[j + 1] !== v || data[j + 2] !== v)) ||
      ((channels === 2 || channels === 4) && data[j + channels - 1] !== white) ||
      (transparency && transparency.every(sample => sample === v))) {
      throw new Error('Expected an opaque binary mask.');
    }
    plane[i] = v === white ? 1 : 0;
  }
  return plane;
}

export async function readMask(url, width, height, signal) {
  const response = await fetch(url, { signal, mode: 'same-origin' });
  if (!response.ok) throw new Error(`Mask asset returned HTTP ${response.status}.`);
  return decodeBinaryMask(new Uint8Array(await response.arrayBuffer()), width, height);
}

export function encodeMask(plane, width, height) {
  const bytes = binaryPNG(plane, width, height);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 16384) binary += String.fromCharCode(...bytes.subarray(i, i + 16384));
  return btoa(binary);
}

export function renderMask(canvas, plane, color, bounds) {
  if (!canvas) return;
  const [left, top, width, height] = bounds ?? [0, 0, canvas.width, canvas.height];
  const context = canvas.getContext('2d');
  if (!plane) {
    context.clearRect(left, top, width, height);
    return;
  }
  const image = context.createImageData(width, height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (!plane[(top + y) * canvas.width + left + x]) continue;
      const i = (y * width + x) * 4;
      image.data[i] = color[0];
      image.data[i + 1] = color[1];
      image.data[i + 2] = color[2];
      image.data[i + 3] = 100;
    }
  }
  context.putImageData(image, left, top);
}
