import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { brushStampPath, nativePoint, renderMask } from './mask.js';
import { colorStyle, DRAG, REGIONS, TARGETS, targetLabel } from './review.js';
import { BRUSH_PATH, Icon } from './ui.jsx';

function Overlay({ region, plane, width, height, visible, canvases }) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    canvases.current[region.id] = ref.current;
    return () => { delete canvases.current[region.id]; };
  }, [canvases, region]);
  useLayoutEffect(() => {
    renderMask(ref.current, plane, region.color);
  }, [plane, region, width, height]);
  return <canvas ref={ref} width={width} height={height} hidden={!visible} aria-hidden="true" />;
}

const dragColor = colorStyle(TARGETS.find(({ id }) => id === DRAG).color);

function DragArrow({ arrow, width, height, scale, editing }) {
  if (!arrow?.start || !arrow.end) return null;
  const [x1, y1] = arrow.start.map(n => n + .5);
  const [x2, y2] = arrow.end.map(n => n + .5);
  const length = Math.hypot(x2 - x1, y2 - y1);
  const tip = Math.min(12 / scale, length * .55);
  const angle = Math.atan2(y2 - y1, x2 - x1);
  const wing = side => [x2 - tip * Math.cos(angle + side), y2 - tip * Math.sin(angle + side)];
  const line = `M${x1} ${y1} L${x2} ${y2} M${wing(-.55).join(' ')} L${x2} ${y2} L${wing(.55).join(' ')}`;
  return <svg className="drag-arrow" style={{ color: dragColor }} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
    {length > 0 && <>
      <path d={line} vectorEffect="non-scaling-stroke" stroke="#f4f7ff" strokeWidth="4.5" />
      <path d={line} vectorEffect="non-scaling-stroke" stroke="currentColor" strokeWidth="2.5" />
    </>}
    {editing && <>
      <circle cx={x1} cy={y1} r={4 / scale} vectorEffect="non-scaling-stroke" strokeWidth="1.5" className="arrow-tail" />
      {length > 0 && <circle cx={x2} cy={y2} r={4 / scale} vectorEffect="non-scaling-stroke" strokeWidth="1.5" className="arrow-tip" />}
    </>}
  </svg>;
}

const TOOLS = [ ['pan', 'Pan', 'pan'], ['brush', 'Brush', 'brush'], ['erase', 'Eraser', 'erase'], ['arrow', 'Arrow', 'arrow'] ];
const ZOOM_LEVELS = [0.05, 0.1, 0.2, 0.25, 0.33, 0.5, 0.67, 1, 1.5, 2, 3, 4, 6, 8, 12, 16];
const EDGE = 20;

// Keep a paintbrush visible even before the first positioned hover preview.
const brushCursors = Object.fromEntries(REGIONS.map(({ id, color }) => {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="25" height="25" viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><path d="${BRUSH_PATH}" fill="rgb(${color.join(',')})" stroke="#171c22" stroke-width="3.5"/><path d="${BRUSH_PATH}" fill="none" stroke="#f4f7ff" stroke-width="1"/></svg>`;
  return [id, `url("data:image/svg+xml,${encodeURIComponent(svg)}") 5 20, default`];
}));

function BrushPreview({ point, width, height, diameter, color }) {
  const stamp = useMemo(() => brushStampPath(diameter), [diameter]);
  const [x, y, glyphLeft, glyphBelow] = point;
  return <div className="brush-preview" aria-hidden="true" style={{ color }}>
    <div className="brush-footprint" style={{ left: `${100 * (x + .5) / width}%`, top: `${100 * (y + .5) / height}%`,
      width: `${100 * diameter / width}%`, height: `${100 * diameter / height}%` }}>
      <svg className="brush-stamp" viewBox={`0 0 ${diameter} ${diameter}`} preserveAspectRatio="none">
        <path d={stamp} fill="currentColor" fillOpacity=".39" />
      </svg>
      <span className="brush-ring" />
      <span className={`brush-glyph ${glyphLeft ? 'glyph-left' : ''} ${glyphBelow ? 'glyph-below' : ''}`}><Icon name="brush" size={19}/></span>
    </div>
  </div>;
}

export default function Scan({ detail, targets, planes, canvases, active, visible, showLayer, editable, sourceReady,
  setSourceState, paint, setArrow, beginStroke, finishStroke, undoStroke, canUndo,
  tool, setTool, original, setOriginal, diameter, setDiameter }) {
  const { width, height, image_url } = detail;
  const viewport = useRef(null);
  const scan = useRef(null);
  const gesture = useRef(null);
  const hover = useRef(null);
  const center = useRef(null);
  const [viewportSize, setViewportSize] = useState([0, 0]);
  const [zoom, setZoom] = useState(null);
  const [position, setPosition] = useState(null);
  const fit = Math.min(1, Math.max(1, viewportSize[0] - EDGE * 2) / width, Math.max(1, viewportSize[1] - EDGE * 2) / height);
  const scale = zoom ?? fit;
  const arrow = targets[DRAG];
  const brushTool = tool === 'brush' || tool === 'erase';
  const manipulating = editable && !original && (brushTool || tool === 'arrow');
  const showingBrush = manipulating && tool === 'brush';
  const activeColor = colorStyle(REGIONS.find(({ id }) => id === active).color);

  useEffect(() => {
    const node = viewport.current;
    // Readout and arrow handles only; CSS sizes the sheet directly from the viewport.
    const observer = new ResizeObserver(([{ contentRect }]) => setViewportSize([contentRect.width, contentRect.height]));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useLayoutEffect(() => {
    const base = center.current;
    if (!base) return;
    center.current = null;
    const rect = scan.current.getBoundingClientRect();
    const bounds = viewport.current.getBoundingClientRect();
    viewport.current.scrollLeft += rect.left + base[0] * rect.width - (bounds.left + viewport.current.clientWidth / 2);
    viewport.current.scrollTop += rect.top + base[1] * rect.height - (bounds.top + viewport.current.clientHeight / 2);
  }, [zoom]);

  function adjustZoom(next) {
    if (next === zoom) return;
    const rect = scan.current.getBoundingClientRect();
    const bounds = viewport.current.getBoundingClientRect();
    center.current = rect.width && rect.height ? [
      (bounds.left + viewport.current.clientWidth / 2 - rect.left) / rect.width,
      (bounds.top + viewport.current.clientHeight / 2 - rect.top) / rect.height,
    ] : null;
    setZoom(next);
  }

  function point(event) {
    return nativePoint(event.clientX, event.clientY, scan.current.getBoundingClientRect(), width, height);
  }

  function updatePosition() {
    const p = hover.current;
    const r = scan.current.getBoundingClientRect();
    const v = viewport.current.getBoundingClientRect();
    const top = Math.max(r.top, v.top), right = Math.min(r.right, v.left + viewport.current.clientWidth);
    let at = null;
    if (p && p.clientX >= Math.max(r.left, v.left) && p.clientY >= top &&
      p.clientX < right && p.clientY < Math.min(r.bottom, v.top + viewport.current.clientHeight)) {
      const [x, y] = nativePoint(p.clientX, p.clientY, r, width, height);
      const cx = r.left + (x + .5) * r.width / width, cy = r.top + (y + .5) * r.height / height;
      // Place the glyph next to the hotspot, not the edge of the scaled footprint.
      at = [x, y, right - cx < 30, cy - top < 30];
    }
    setPosition(prev => at?.every((value, i) => value === prev?.[i]) ? prev : at);
  }

  useLayoutEffect(updatePosition, [zoom, viewportSize, width, height]);

  function trackPointer(event) {
    hover.current = event.pointerType === 'touch' ? null : { clientX: event.clientX, clientY: event.clientY };
    updatePosition();
  }

  function pointerDown(event) {
    if (event.button !== 0 || gesture.current) return;
    const inside = scan.current.contains(event.target);
    if (!manipulating || !inside) {
      gesture.current = { pointer: event.pointerId, tool: 'pan', x: event.clientX, y: event.clientY,
        left: viewport.current.scrollLeft, top: viewport.current.scrollTop };
    } else {
      const at = point(event);
      if (tool === 'arrow') {
        showLayer(DRAG);
        const { start, end } = arrow || {};
        const dist = p => Math.hypot(p[0] - at[0], p[1] - at[1]);
        const editStart = start && end && (start[0] !== end[0] || start[1] !== end[1]) && dist(start) * scale < 10 && dist(start) < dist(end);
        const fixed = editStart ? end : start || at;
        gesture.current = { pointer: event.pointerId, tool, editStart, fixed };
        if (!editStart) setArrow(fixed, at);
      } else {
        showLayer(active);
        event.currentTarget.focus({ preventScroll: true });
        const value = tool === 'brush' ? 1 : 0;
        gesture.current = { pointer: event.pointerId, tool, last: at, target: active, diameter };
        beginStroke(active, value);
        paint(active, at, at, diameter, value);
      }
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  function pointerMove(event) {
    const current = gesture.current;
    if (current?.pointer === event.pointerId && current.tool === 'pan') {
      viewport.current.scrollLeft = current.left - (event.clientX - current.x);
      viewport.current.scrollTop = current.top - (event.clientY - current.y);
      return;
    }
    trackPointer(event);
    if (!current || current.pointer !== event.pointerId) return;
    const at = point(event);
    if (current.tool === 'arrow') {
      if (current.editStart) setArrow(at, current.fixed);
      else setArrow(current.fixed, at);
    } else if (current.last[0] !== at[0] || current.last[1] !== at[1]) {
      paint(current.target, current.last, at, current.diameter, current.tool === 'brush' ? 1 : 0);
      current.last = at;
    }
  }

  function pointerEnd(event) {
    const current = gesture.current;
    if (current?.pointer !== event.pointerId) return;
    gesture.current = null;
    if (current.tool === 'brush' || current.tool === 'erase') finishStroke();
  }

  return <>
    <div className="scan-toolbar" aria-label="Scan tools">
      <div className="tool-group" aria-label="Editing tools">
        {TOOLS.map(([id, label, icon]) => <button type="button" key={id} onClick={() => setTool(id)}
          aria-pressed={tool === id} title={label} disabled={id !== 'pan' && (!editable || original)}><Icon name={icon}/><span>{label}</span></button>)}
      </div>
      {brushTool && !original && <label className="brush-control">Size
        <select aria-label="Brush size (native pixels)" value={diameter} onChange={e => setDiameter(Number(e.target.value))}>
          {[1, 3, 5, 9, 15, 25, 41].map(px => <option key={px} value={px}>{px} px</option>)}
        </select>
      </label>}
      <button type="button" className="undo-stroke" onClick={undoStroke} disabled={!canUndo}
        aria-keyshortcuts="Control+Z Meta+Z" title="Undo stroke (Ctrl+Z / ⌘Z)"><Icon name="undo"/> Undo</button>
      <div className="toolbar-spacer" />
      <div className="tool-group zoom-controls" aria-label="Zoom controls">
        <button type="button" aria-label="Zoom out" title="Zoom out" onClick={() => adjustZoom(ZOOM_LEVELS.findLast(n => n < scale - .0001) ?? scale)} disabled={scale <= ZOOM_LEVELS[0]}>−</button>
        <button type="button" className="zoom-value" aria-label="Set zoom to 100 percent" title="Actual size (100%)" onClick={() => adjustZoom(1)}>{Math.round(scale * 100)}%</button>
        <button type="button" aria-label="Zoom in" title="Zoom in" onClick={() => adjustZoom(ZOOM_LEVELS.find(n => n > scale + .0001) ?? scale)} disabled={scale >= ZOOM_LEVELS.at(-1)}>+</button>
        <button type="button" aria-label="Fit scan to view" title="Fit scan to view" aria-pressed={zoom === null} onClick={() => adjustZoom(null)}><Icon name="fit" /></button>
      </div>
      <button className="original-toggle" type="button" aria-pressed={original} onClick={() => setOriginal(!original)} title="Show the unmodified scan without overlays"><Icon name={original ? 'eye' : 'layers'} /> Original</button>
    </div>
    <div ref={viewport} className={`scan-viewport ${zoom === null ? 'is-fit' : ''} ${manipulating ? '' : 'is-panning'} ${showingBrush ? 'is-brushing' : ''}`} aria-label="Scan viewport" tabIndex={-1}
      style={{ '--scan-edge': `${EDGE}px` }}
      onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={event => { if (gesture.current?.tool !== 'pan') pointerMove(event); pointerEnd(event); }}
      onPointerCancel={event => { pointerEnd(event); hover.current = null; setPosition(null); }}
      onLostPointerCapture={pointerEnd} onPointerLeave={() => { hover.current = null; setPosition(null); }} onScroll={updatePosition}>
      <div className="scan-space">
        <div className={`scan-sheet${showingBrush && position ? ' has-brush-preview' : ''}`} ref={scan}
          onPointerEnter={trackPointer} style={{ '--scan-width': `${width}px`, '--scan-ratio': width / height,
          '--brush-cursor': showingBrush ? brushCursors[active] : undefined,
          width: zoom === null ? undefined : width * zoom }}>
          <img src={image_url} width={width} height={height} alt={`Original scan: ${detail.name}`} draggable={false}
            onLoad={event => {
              const img = event.currentTarget;
              setSourceState(img.naturalWidth === width && img.naturalHeight === height ? 'ready' : 'Scan and case dimensions differ.');
            }} onError={() => setSourceState('The original scan could not be loaded.')} />
          {!sourceReady && <div className="scan-loading">Original scan</div>}
          {REGIONS.map(region => <Overlay key={region.id} region={region} plane={planes[region.id]} width={width} height={height}
            canvases={canvases} visible={sourceReady && !original && visible[region.id] && targets[region.id]?.status === 'present'} />)}
          {sourceReady && !original && visible[DRAG] && arrow?.status === 'present' && <DragArrow arrow={arrow} width={width} height={height} scale={scale} editing={tool === 'arrow' && editable} />}
          {showingBrush && position && <BrushPreview point={position} width={width} height={height} diameter={diameter} color={activeColor} />}
        </div>
      </div>
    </div>
    <div className="scan-readout">
      <span className="readout-mode"><Icon name={original ? 'image' : 'layers'} /> {original ? 'Original only' : 'Scan + overlays'}</span>
      {!original && brushTool && <span className="active-readout"><span className="swatch" style={{ background: activeColor }} />{targetLabel(active)}</span>}
      {!original && tool === 'arrow' && editable && <span className="arrow-hint">Drag handles, or drag from tail to tip.</span>}
      <span className="readout-pixels mono">{position ? `x ${position[0]}  y ${position[1]}` : `${width} × ${height} px`}</span>
    </div>
  </>;
}
