import { encodeMask } from './mask.js';
import annotationColors from './annotation-colors.json' with { type: 'json' };

export const DRAG = 'firing_pin_drag_direction';
export const TARGETS = [
  { id: 'breech_face', label: 'Breech face' },
  { id: 'aperture_shear', label: 'Aperture shear' },
  { id: 'firing_pin_shear', label: 'Firing pin shear' },
  { id: 'firing_pin_impression', label: 'Firing pin impression' },
  { id: DRAG, label: 'Firing pin drag direction' },
].map(target => ({ ...target, color: annotationColors[target.id] }));
export const REGIONS = TARGETS.filter(target => target.id !== DRAG);
export const STATUSES = {
  not_annotated: 'Not annotated',
  present: 'Present',
  absent: 'Absent',
  indeterminate: 'Indeterminate',
};

export const isTrainingSplit = split => split === 'train';
export const revisionId = value => typeof value === 'object' ? value?.id : value;
export const textLabel = value => typeof value === 'string' ? value.replaceAll('_', ' ') : '';
export const targetLabel = id => TARGETS.find(target => target.id === id)?.label ?? textLabel(id);
export const colorStyle = color => `rgb(${color.join(' ')})`;
export const splitLabel = split => ({ train: 'Train', test: 'Test · held out', validation: 'Validation · held out' })[split] ?? (textLabel(split) || 'Unassigned');

export function revisionLabel(revision, approved = false) {
  const { kind, source } = revision || {};
  if (source?.method === 'local_prediction' && kind === 'proposal') return 'Estimate';
  if (kind === 'source') return approved ? 'Approved source' : 'Imported source';
  return ({ estimate: 'Estimate', proposal: 'Proposal', imported: 'Imported', draft: 'Draft', approved: 'Approved' })[kind] ?? (textLabel(kind) || 'Revision');
}

export function sourceLabel(source) {
  if (!source) return '';
  if (typeof source === 'string') return source;
  const method = source.method || source.name || source.kind || source.type;
  return [source.model, textLabel(method), source.version].filter(value => typeof value === 'string' && value).join(' · ');
}

export function reviewPayload(base_revision, approve, targets, planes, changed, width, height, encode = encodeMask) {
  const within = point => Array.isArray(point) && point.length === 2 &&
    point.every(Number.isInteger) && point[0] >= 0 && point[0] < width && point[1] >= 0 && point[1] < height;
  return { base_revision, approve, targets: Object.fromEntries(TARGETS.map(({ id, label }) => {
    const target = targets[id];
    const status = target?.status || 'not_annotated';
    const entry = { status };
    if (status === 'present') {
      if (id === DRAG) {
        const { start, end } = target;
        if (!within(start) || !within(end) || (start[0] === end[0] && start[1] === end[1])) {
          throw new Error(`${label}: set two distinct endpoints on the scan.`);
        }
        Object.assign(entry, { start, end });
      } else if (changed.has(id) || !target.mask_url) {
        const plane = planes[id];
        if (!plane?.includes(1)) throw new Error(`${label}: paint at least one pixel or change its status.`);
        entry.mask_png = encode(plane, width, height);
      }
    }
    return [id, entry];
  })) };
}
