import { useCallback, useEffect, useRef, useState } from 'react';
import { casePath } from './api.js';
import { brushStroke, decodeBinaryMask, readMask, renderMask, unionBounds } from './mask.js';
import { colorStyle, DRAG, isTrainingSplit, REGIONS, revisionId, revisionLabel, reviewPayload, sourceLabel, splitLabel, STATUSES, TARGETS, textLabel } from './review.js';
import Scan from './Scan.jsx';
import { Icon, Notice } from './ui.jsx';

const allVisible = Object.fromEntries(TARGETS.map(({ id }) => [id, true]));
const emptyPlanes = {};
function readPlanes(targets, width, height, signal) {
  return Promise.all(REGIONS.flatMap(({ id, label }) => {
    const url = targets[id]?.mask_url;
    if (!url) return [];
    return [readMask(url, width, height, signal).then(plane => [id, plane])
      .catch(error => { throw new Error(`${label}: ${error.message}`); })];
  })).then(Object.fromEntries);
}
const timestamp = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const revisionTime = created => Number.isFinite(Date.parse(created)) ? timestamp.format(new Date(created)) : '';
const UNDO_BUDGET = 32 * 1024 * 1024;

export default function Editor({ detail, dirty, setDirty, busy, feedback, stale, comparison, setComparison, reloadLatest, onAction, onEstimate, shortcutActive }) {
  const { selected, width, height } = detail;
  const selectedId = revisionId(selected) || 0;
  const approvedId = revisionId(detail.approved) || 0;
  const latestId = revisionId(detail.latest) || 0;
  const saved = detail.revisions?.find(revision => revision.id === comparison);
  const viewedId = saved?.id ?? selectedId;
  const initialTargets = selected?.targets || {};
  const [targets, setTargets] = useState(initialTargets);
  const [planes, setPlanes] = useState({});
  const [load, setLoad] = useState('loading');
  const [source, setSource] = useState('loading');
  const [active, setActive] = useState(REGIONS[0].id);
  const [visible, setVisible] = useState(allVisible);
  const [tool, setTool] = useState('pan');
  const [original, setOriginal] = useState(false);
  const [diameter, setDiameter] = useState(9);
  const [validation, setValidation] = useState('');
  const [assetAttempt, setAssetAttempt] = useState(0);
  const [comparisonAssets, setComparisonAssets] = useState(null);
  const [comparisonAttempt, setComparisonAttempt] = useState(0);
  const [canUndo, setCanUndo] = useState(false);
  const [estimateRun, setEstimateRun] = useState(null);
  const canvases = useRef({});
  const planeBuffer = useRef({});
  const changed = useRef(new Set());
  const otherDirty = useRef(false);
  const statusEdits = useRef({});
  const stroke = useRef(null);
  const undoHistory = useRef({ entries: [], bytes: 0 });
  const initialTargetsRef = useRef(initialTargets);
  const training = isTrainingSplit(detail.split);
  const editable = !busy && !saved && !stale && load === 'ready' && source === 'ready';
  const path = casePath(detail.id);
  const viewedTargets = saved?.targets ?? targets;
  const matchingAssets = comparisonAssets?.id === saved?.id && comparisonAssets?.attempt === comparisonAttempt ? comparisonAssets : null;
  const viewedPlanes = saved ? matchingAssets?.planes ?? emptyPlanes : planes;

  useEffect(() => {
    const controller = new AbortController();
    readPlanes(initialTargetsRef.current, width, height, controller.signal).then(buffers => {
      if (controller.signal.aborted) return;
      planeBuffer.current = buffers;
      setPlanes(buffers);
      setLoad('ready');
    }).catch(error => { if (!controller.signal.aborted) setLoad(error.message); });
    return () => controller.abort();
  }, [width, height, assetAttempt]);

  // Comparison assets are read-only and must never replace the edit buffers.
  useEffect(() => {
    if (!saved) return;
    const controller = new AbortController();
    const id = saved.id, attempt = comparisonAttempt;
    readPlanes(saved.targets, width, height, controller.signal).then(planes => {
      if (!controller.signal.aborted) setComparisonAssets({ id, attempt, planes });
    }).catch(error => {
      if (!controller.signal.aborted) setComparisonAssets({ id, attempt, error: error.message });
    });
    return () => controller.abort();
  }, [saved, width, height, comparisonAttempt]);

  function showLayer(id) {
    if (!visible[id]) setVisible(prev => ({ ...prev, [id]: true }));
  }

  function selectLayer(id) {
    if (id !== DRAG) setActive(id);
    if (!editable || original) return;
    showLayer(id);
    setTool(id === DRAG ? 'arrow' : tool === 'erase' ? 'erase' : 'brush');
  }

  function editTarget(id, changes) {
    otherDirty.current = true;
    statusEdits.current[id] = (statusEdits.current[id] || 0) + 1;
    setValidation('');
    setTargets(prev => ({ ...prev, [id]: { ...prev[id], ...changes } }));
    setDirty(true);
  }

  function beginStroke(id, value) {
    stroke.current = { id, value, pixels: [], bounds: null, hadPlane: Boolean(planeBuffer.current[id]),
      wasChanged: changed.current.has(id) };
  }

  function paint(id, from, to, size, value) {
    const entry = stroke.current;
    if (!entry || !editable || original) return;
    let plane = planeBuffer.current[id];
    if (!plane && value === 0) return;
    const fresh = !plane;
    if (fresh) plane = new Uint8Array(width * height);
    const bounds = brushStroke(plane, width, height, from, to, size, value, index => entry.pixels.push(index));
    if (!bounds) return;
    if (!entry.bounds && value) {
      entry.status = targets[id]?.status;
      entry.statusEdit = statusEdits.current[id];
      if (entry.status !== 'present') setTargets(prev => ({ ...prev, [id]: { ...prev[id], status: 'present' } }));
    }
    entry.bounds = unionBounds(entry.bounds, bounds);
    if (fresh) {
      planeBuffer.current = { ...planeBuffer.current, [id]: plane };
      setPlanes(planeBuffer.current);
    }
    changed.current.add(id);
    renderMask(canvases.current[id], plane, REGIONS.find(region => region.id === id).color, bounds);
    setValidation('');
    setDirty(true);
  }

  function finishStroke() {
    const entry = stroke.current;
    stroke.current = null;
    if (!entry?.bounds) return;
    // A gesture uses one value; every changed pixel originally had its inverse.
    entry.pixels = Uint32Array.from(entry.pixels);
    const history = undoHistory.current;
    history.entries.push(entry);
    history.bytes += entry.pixels.byteLength;
    while (history.entries.length > 1 && (history.bytes > UNDO_BUDGET || history.entries.length > 50)) {
      history.bytes -= history.entries.shift().pixels.byteLength;
    }
    setCanUndo(true);
  }

  const undoStroke = useCallback(() => {
    if (!editable || stroke.current) return false;
    const history = undoHistory.current;
    const entry = history.entries.pop();
    if (!entry) return false;
    history.bytes -= entry.pixels.byteLength;
    const { id, pixels, value, bounds, status, statusEdit, hadPlane, wasChanged } = entry;
    if (hadPlane) {
      const plane = planeBuffer.current[id];
      for (const index of pixels) plane[index] = 1 - value;
    } else {
      const { [id]: removed, ...remaining } = planeBuffer.current;
      planeBuffer.current = remaining;
      setPlanes(remaining);
    }
    renderMask(canvases.current[id], planeBuffer.current[id], REGIONS.find(region => region.id === id).color, bounds);
    if (value && status !== 'present' && statusEdits.current[id] === statusEdit) {
      setTargets(prev => ({ ...prev, [id]: { ...prev[id], status } }));
    }
    if (!wasChanged) changed.current.delete(id);
    setDirty(otherDirty.current || changed.current.size > 0);
    setCanUndo(history.entries.length > 0);
    setValidation('');
    return true;
  }, [editable, setDirty]);

  useEffect(() => {
    if (!shortcutActive || !editable || !canUndo) return;
    function shortcut(event) {
      if (event.defaultPrevented || !(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey ||
          event.key.toLowerCase() !== 'z' || event.target.isContentEditable ||
          event.target.closest?.('input, textarea, [role="textbox"]')) return;
      if (undoStroke()) event.preventDefault();
    }
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, [editable, shortcutActive, canUndo, undoStroke]);

  function setArrow(start, end) {
    const arrow = targets[DRAG];
    if (arrow?.status === 'present' && [0, 1].every(i => start[i] === arrow.start?.[i] && end[i] === arrow.end?.[i])) return;
    editTarget(DRAG, { status: 'present', start, end });
  }

  function applyEstimate(preview) {
    if (preview.base_revision !== selectedId) throw new Error('Estimate does not match the open revision.');
    const proposed = {};
    const buffers = { ...planeBuffer.current };
    const replaced = [];
    for (const { id } of TARGETS) {
      const entry = preview.targets[id];
      // No prediction is not an instruction to erase existing annotations.
      if (entry.status !== 'present') continue;
      proposed[id] = id === DRAG ? { status: 'present', start: entry.start, end: entry.end, origin: 'prediction' }
        : { status: 'present', origin: 'prediction' };
      if (id !== DRAG) {
        buffers[id] = decodeBinaryMask(Uint8Array.from(atob(entry.mask_png), c => c.charCodeAt(0)), width, height);
        replaced.push(id);
      }
    }
    if (!Object.keys(proposed).length) throw new Error('The model did not produce any annotations for this scan.');
    for (const id of replaced) changed.current.add(id);
    planeBuffer.current = buffers;
    setPlanes(buffers);
    setTargets(prev => ({ ...prev, ...proposed }));
    setVisible(prev => ({ ...prev, ...Object.fromEntries(Object.keys(proposed).map(id => [id, true])) }));
    setOriginal(false);
    otherDirty.current = true;
    setEstimateRun(preview.run_id);
    setValidation('');
    setDirty(true);
  }

  function save(approve) {
    try {
      const body = reviewPayload(selectedId, approve, targets, planeBuffer.current, changed.current, width, height);
      setValidation('');
      onAction(`${path}/review`, body, approve ? 'Revision approved.' : 'Draft saved.');
    } catch (error) {
      setValidation(error.message);
    }
  }

  const arrow = viewedTargets[DRAG];
  const hasArrow = arrow?.status === 'present' && arrow.start && arrow.end && (arrow.start[0] !== arrow.end[0] || arrow.start[1] !== arrow.end[1]);
  const hasMask = REGIONS.some(({ id }) => viewedTargets[id]?.mask_url);
  const kind = viewedId ? revisionLabel(saved ?? selected, viewedId === approvedId) : 'Not reviewed';
  const sourceSummary = sourceLabel((saved ?? selected)?.source);
  const assetError = [source, saved ? matchingAssets?.error ?? 'ready' : load]
    .find(state => state !== 'loading' && state !== 'ready');
  const awaitingAssets = source === 'loading' || (saved ? !matchingAssets : load === 'loading');
  const canApprove = editable && Boolean(selectedId) && (selectedId !== approvedId || dirty);
  const canDraft = editable && Boolean(selectedId) && (dirty || (selectedId !== approvedId && selected.kind === 'proposal'));

  return <>
    <main className="editor" aria-label="Case scan editor">
      <div className="case-heading">
        <div className="case-heading-text">
          <div className="eyebrow">Scan review <span>/</span> {splitLabel(detail.split)}</div>
          <h1 title={detail.name}>{detail.name}</h1>
        </div>
        <div className="case-indicators">
          <span className={`pill ${viewedId && viewedId === approvedId ? 'pill-saved' : ''}`}><span className="status-dot"/>{kind}</span>
          {viewedId > 0 && <span className="mono case-revision">r{viewedId}</span>}
        </div>
      </div>
      {feedback && <Notice error={feedback.error}>{feedback.message}</Notice>}
      {!saved && validation && <Notice error>{validation}</Notice>}
      {!saved && estimateRun !== null && <Notice>Unsaved estimate from Run #{estimateRun}. Review it before saving or approving.</Notice>}
      {assetError && <Notice error action={<button onClick={() => {
        if (source !== 'ready') reloadLatest();
        else if (saved) setComparisonAttempt(n => n + 1);
        else { setLoad('loading'); setAssetAttempt(n => n + 1); }
      }}>Retry assets</button>}>{assetError}</Notice>}
      <Scan detail={detail} targets={viewedTargets} planes={viewedPlanes} canvases={canvases} active={active} visible={visible} showLayer={showLayer}
        editable={editable} sourceReady={source === 'ready'} setSourceState={setSource} paint={paint} setArrow={setArrow}
        beginStroke={beginStroke} finishStroke={finishStroke} undoStroke={undoStroke} canUndo={canUndo && editable}
        tool={tool} setTool={setTool} original={original} setOriginal={setOriginal} diameter={diameter} setDiameter={setDiameter} />
      <div className="review-actions">
        <div className="review-state" role="status">
          {busy ? 'Working…' : saved ? (awaitingAssets ? 'Loading saved overlays…' : `${viewedId === latestId ? 'Saved revision' : 'Historical revision'} · read only`) : stale ? 'Revision changed on server' : dirty ? 'Unsaved edits' : awaitingAssets ? 'Loading scan assets…' : `Latest${approvedId ? ` · approved r${approvedId}` : ' · no approval'}`}
          {saved && dirty ? <small>Unsaved edits kept</small> : !busy && !dirty && sourceSummary && <small title={sourceSummary}>{sourceSummary}</small>}
        </div>
        <div className="action-buttons">
          {saved && <button type="button" onClick={() => setComparison(null)} disabled={busy}>{dirty ? 'Back to unsaved edits' : 'View latest'}</button>}
          {!saved && stale && !dirty && <button type="button" onClick={reloadLatest} disabled={busy}>Reload latest</button>}
          <button type="button" onClick={reloadLatest} disabled={busy || !dirty}>Cancel edits</button>
          <button type="button" disabled={!canDraft} onClick={() => save(false)}>Save draft</button>
          <button type="button" className="primary" disabled={!canApprove} onClick={() => save(true)}><Icon name="check" /> Approve</button>
        </div>
      </div>
    </main>
    <aside className="inspector" aria-label="Annotation inspector">
      <div className="inspector-label"><span className="eyebrow">Annotation</span><h2>Inspector</h2></div>
      <section className="inspector-section" aria-labelledby="target-heading">
        <div className="heading-line"><h3 id="target-heading">Targets</h3><span className="quiet mono">{TARGETS.filter(({ id }) => viewedTargets[id]?.status === 'present').length} / {TARGETS.length} present</span></div>
        <div className="targets">
          {TARGETS.map(({ id, label, color }) => {
            const target = viewedTargets[id];
            const selectedLayer = id === DRAG ? tool === 'arrow' : active === id && tool !== 'arrow';
            return <div className={`target ${selectedLayer ? 'selected-target' : ''}`} key={id}>
              <div className="target-name-line">
                <button className="layer-pick" type="button" onClick={() => selectLayer(id)} aria-pressed={selectedLayer}>
                  <span className="swatch" style={{ background: colorStyle(color) }}/><span>{label}</span>
                </button>
                <button type="button" className="icon-button layer-eye" aria-label={`${label} overlay`} title={`${visible[id] ? 'Hide' : 'Show'} ${label}`} aria-pressed={visible[id]} disabled={original}
                  onClick={() => setVisible(prev => ({ ...prev, [id]: !prev[id] }))}><Icon name={visible[id] ? 'eye' : 'hide'} size={17}/></button>
              </div>
              <div className="target-meta">
                <select aria-label={`${label} status`} disabled={!editable} value={target?.status || 'not_annotated'} onChange={event => editTarget(id, { status: event.target.value })}>
                  {Object.entries(STATUSES).map(([value, name]) => <option key={value} value={value}>{name}</option>)}
                </select>
                {target?.origin && <span className="quiet target-origin" title={textLabel(target.origin)}>{textLabel(target.origin)}</span>}
              </div>
              {id === DRAG && hasArrow && <div className="arrow-settings">
                <span className="mono" title="Tail → tip in native pixels">{arrow.start.join(',')} → {arrow.end.join(',')}</span>
                <button type="button" disabled={!editable || original} onClick={() => { selectLayer(DRAG); setArrow(arrow.end, arrow.start); }}>Reverse arrow</button>
              </div>}
            </div>;
          })}
        </div>
        {!hasMask && editable && !dirty && <p className="inspector-help">Select a target, then paint on the scan to create a mask.</p>}
      </section>
      <section className="inspector-section" aria-labelledby="training-case-heading">
        <h3 id="training-case-heading">Training eligibility</h3>
        <div className="inclusion-line">
          <label className="inclusion-control"><input type="checkbox" checked={training && detail.included} disabled={!training || busy || dirty || Boolean(saved) || stale}
            onChange={event => onAction(`${path}/inclusion`, { included: event.target.checked }, event.target.checked ? 'Marked for training when approved.' : 'Excluded from future training.')} /> Include in training</label>
          <span className="pill">{!training ? 'Held out' : !detail.included ? 'Excluded' : approvedId ? 'Eligible' : 'Needs approval'}</span>
        </div>
        <p className="inspector-help">{!training ? 'Held-out cases can be reviewed, but never enter training.' : 'Training uses the most recent approved revision only.'}</p>
      </section>
      <section className="inspector-section revision-section" aria-labelledby="revision-heading">
        <div className="heading-line"><h3 id="revision-heading">Revisions</h3><span className="quiet mono">{detail.revisions?.length || 0}</span></div>
        <button className="estimate-button" type="button" onClick={() => onEstimate(selectedId, applyEstimate)} disabled={!editable || dirty}>Run new estimate <Icon name="right"/></button>
        {detail.revisions?.length ? <ol className="revision-list">
          {detail.revisions.map(revision => <li key={revision.id}>
            <button type="button" className="revision-row" aria-current={revision.id === viewedId && (saved || !dirty) ? 'true' : undefined} disabled={busy}
              onClick={() => setComparison(revision.id === latestId && !dirty ? null : revision.id)}>
              <span className="revision-code mono">r{revision.id}</span>
              <span className="revision-description"><strong>{revisionLabel(revision, revision.id === approvedId)}</strong><small>{sourceLabel(revision.source) || revisionTime(revision.created)}</small></span>
              {revision.id === approvedId ? <span className="revision-tag">{training && detail.included ? 'Export revision' : 'Approved'}</span> : revision.id === latestId ? <span className="revision-tag">Latest</span> : null}
            </button>
          </li>)}
        </ol> : <p className="inspector-help">No saved revisions yet.</p>}
      </section>
    </aside>
  </>;
}
