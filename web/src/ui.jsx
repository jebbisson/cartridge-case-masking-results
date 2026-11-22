export const BRUSH_PATH = 'm10 14 7-9 2 2-9 9m1 0c0 3-3 4-6 4 1-1 1-2 1-3 0-3 4-4 5-1Z';

const paths = {
  mark: <><circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2.5"/><path d="M12 2v4m0 12v4M2 12h4m12 0h4"/></>,
  search: <><circle cx="10.5" cy="10.5" r="5.5"/><path d="m15 15 4 4"/></>,
  refresh: <><path d="M19 9a7 7 0 1 0 0 6m0-11v5h-5"/></>,
  pan: <><path d="M12 3v18m-9-9h18M9 6l3-3 3 3M9 18l3 3 3-3M6 9l-3 3 3 3m12-6 3 3-3 3"/></>,
  brush: <path d={BRUSH_PATH}/>,
  erase: <path d="m5 13 8-8a2 2 0 0 1 3 0l4 4a2 2 0 0 1 0 3l-7 7H9l-4-4a1.5 1.5 0 0 1 0-2Zm4-4 7 7m-3 3h8"/>,
  undo: <path d="M8 5 3 10l5 5m-5-5h11a5 5 0 0 1 0 10h-2"/>,
  arrow: <path d="M5 19 19 5m-9 0h9v9"/>,
  eye: <><path d="M2 12s4-6 10-6 10 6 10 6-4 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="2.5"/></>,
  hide: <><path d="M3 3l18 18M9.5 6.4A10 10 0 0 1 12 6c6 0 10 6 10 6a16 16 0 0 1-3 3.3M6.3 7.7A17 17 0 0 0 2 12s4 6 10 6c1.5 0 2.9-.4 4.1-1"/></>,
  fit: <path d="M9 4H4v5m11-5h5v5m0 6v5h-5m-6 0H4v-5"/>,
  down: <path d="m8 10 4 4 4-4"/>,
  right: <path d="m10 8 4 4-4 4"/>,
  check: <path d="m5 12 4 4 10-10"/>,
  image: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="m3 16 5-5 4 4 3-3 6 6"/><circle cx="16" cy="9" r="1"/></>,
  layers: <><path d="m3 8 9-5 9 5-9 5-9-5Zm0 4 9 5 9-5M3 16l9 5 9-5"/></>,
};

export function Icon({ name, size = 16 }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export function EmptyState({ icon = 'layers', title, children }) {
  return <div className="empty-state"><Icon name={icon} size={26}/><strong>{title}</strong>{children && <p>{children}</p>}</div>;
}

export function Notice({ error, children, action }) {
  return <div className="notice" role={error ? 'alert' : 'status'}><span>{children}</span>{action}</div>;
}
