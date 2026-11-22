import { useState } from 'react';
import { isTrainingSplit, revisionId, splitLabel } from './review.js';
import { EmptyState, Icon } from './ui.jsx';

function stateLabel(item) {
  const latest = revisionId(item.latest);
  const approved = revisionId(item.approved);
  return !latest ? 'Not reviewed' : latest === approved ? 'Approved' : approved ? 'Newer revision' : 'Unapproved revision';
}

export default function CaseQueue({ items, selected, loading, error, busy, openCase, refresh }) {
  const [query, setQuery] = useState('');
  const [split, setSplit] = useState('');
  const [status, setStatus] = useState('');
  const needle = query.trim().toLowerCase();
  const filtered = items.filter(item => {
    if (split && item.split !== split) return false;
    if (status === 'review' && revisionId(item.latest) && revisionId(item.latest) === revisionId(item.approved)) return false;
    if (status === 'approved' && !revisionId(item.approved)) return false;
    if (status === 'excluded' && (!isTrainingSplit(item.split) || item.included)) return false;
    return !needle || `${item.name} ${item.id}`.toLowerCase().includes(needle);
  });
  const splits = [...new Set(items.map(item => item.split))].filter(Boolean);
  return <aside className="queue" aria-label="Case queue">
    <div className="queue-top">
      <div className="heading-line"><div><div className="eyebrow">Case queue</div><h2>Cases</h2></div>
        <button type="button" className="icon-button" title="Refresh cases and open mask" aria-label="Refresh cases and open mask" onClick={refresh} disabled={busy || loading}><Icon name="refresh" size={18}/></button>
      </div>
      <label className="case-search"><Icon name="search"/><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search cases…" aria-label="Search cases" /></label>
      <div className="case-filters">
        <select aria-label="Filter by split" value={split} onChange={event => setSplit(event.target.value)}>
          <option value="">All splits</option>{splits.map(id => <option value={id} key={id}>{splitLabel(id)}</option>)}
        </select>
        <select aria-label="Filter by review status" value={status} onChange={event => setStatus(event.target.value)}>
          <option value="">All states</option><option value="review">Needs review</option><option value="approved">Has approval</option><option value="excluded">Excluded</option>
        </select>
      </div>
    </div>
    <div className="result-count"><span>Cases</span><span className="mono">{loading ? '…' : `${filtered.length} / ${items.length}`}</span></div>
    <div className="queue-list">
      {error && <div className="queue-message" role="alert">{error}</div>}
      {loading && !items.length && <p className="queue-message" role="status">Loading cases…</p>}
      {!loading && !error && !filtered.length && <EmptyState title={items.length ? 'No matches' : 'No cases available'}>{items.length ? 'Try changing the search or filters.' : 'The local API has not returned any scans.'}</EmptyState>}
      {!!filtered.length && <ul>
        {filtered.map(item => <li key={item.id}><button type="button" className="case-row" disabled={busy} aria-current={item.id === selected ? 'true' : undefined}
          onClick={() => openCase(item.id)}>
          <span className="case-row-title" title={item.name}>{item.name}</span>
          <span className="case-row-sub"><span className="pill">{splitLabel(item.split)}</span><span>{isTrainingSplit(item.split) && !item.included ? 'Excluded' : stateLabel(item)}</span></span>
          <Icon name="right" size={15} />
        </button></li>)}
      </ul>}
    </div>
  </aside>;
}
