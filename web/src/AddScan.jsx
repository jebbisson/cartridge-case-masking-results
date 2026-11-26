import { useEffect, useRef, useState } from 'react';
import { request } from './api.js';
import { isTrainingSplit, splitLabel } from './review.js';
import { Notice } from './ui.jsx';

// Match SQLite NOCASE (ASCII only) for group identity; names are only search hints.
const groupKey = value => value.replace(/[A-Z]/g, c => c.toLowerCase());

function findGroups(items, query) {
  const needle = query.trim().toLowerCase();
  if (needle.length < 2) return [];
  const words = needle.split(/\s+/);
  const groups = new Map();
  for (const item of items) {
    if (!item.group_id) continue;
    const key = groupKey(item.group_id);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  const matches = [];
  for (const members of groups.values()) {
    const found = members.find(item => groupKey(item.group_id).includes(needle) ||
      words.every(word => item.name.toLowerCase().includes(word)));
    if (!found) continue;
    matches.push({ id: found.group_id, name: found.name,
      members: members.toSorted((a, b) => a.name.localeCompare(b.name)),
      blocked: members.some(item => !isTrainingSplit(item.split)) });
  }
  return matches.toSorted((a, b) => a.name.localeCompare(b.name));
}

function GroupMembers({ members }) {
  return <ul className="source-members" aria-label="Cases in this group">{members.map(item => <li key={item.id}>
    <span>{item.name}</span><span className="pill">{splitLabel(item.split)}</span>
  </li>)}</ul>;
}

export default function AddScan({ items, loading, listError, onClose, onAdded }) {
  const dialog = useRef(null);
  const searchInput = useRef(null);
  const changeGroupButton = useRef(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [name, setName] = useState('');
  const [hasFile, setHasFile] = useState(false);
  const [mode, setMode] = useState('existing');
  const [query, setQuery] = useState('');
  const [newID, setNewID] = useState('');
  const [linked, setLinked] = useState(null);
  const useExisting = mode === 'existing';
  const matches = useExisting && !linked ? findGroups(items, query) : [];
  const shown = matches.slice(0, 6);
  const groupID = useExisting ? linked?.id ?? '' : newID.trim();
  const sameID = groupID ? items.filter(item => item.group_id && groupKey(item.group_id) === groupKey(groupID)) : [];
  const blocked = sameID.some(item => !isTrainingSplit(item.split));
  const duplicateID = !useExisting && sameID.length > 0;
  const canSubmit = !busy && hasFile && Boolean(name.trim() && groupID) && !blocked && !duplicateID;
  const focusAfterSelection = useRef(false);

  useEffect(() => {
    dialog.current.showModal();
  }, []);

  useEffect(() => {
    if (!focusAfterSelection.current) return;
    focusAfterSelection.current = false;
    (linked ? changeGroupButton : searchInput).current?.focus();
  }, [linked]);

  function switchMode(next) {
    setMode(next);
    setLinked(null);
    setQuery('');
    setNewID('');
    setError('');
  }

  async function submit(event) {
    event.preventDefault();
    if (!canSubmit) return;
    const data = new FormData(event.currentTarget);
    const file = data.get('image');
    const name = data.get('name').trim();
    const group = groupID;
    setError('');
    if (!file?.size || (file.type !== 'image/png' && !/\.png$/i.test(file.name)) || !name || !group) {
      setError('Select a PNG and provide a case name and known source group ID.');
      return;
    }
    data.set('name', name);
    data.set('group_id', group);
    data.delete('source_mode'); // This is a form choice, not an intake API field.
    setBusy(true);
    try {
      const result = await request('/api/cases', { body: data });
      onAdded(result);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return <dialog ref={dialog} className="add-dialog" aria-labelledby="add-heading" onCancel={event => {
    event.preventDefault();
    if (!busy) onClose();
  }}>
    <form onSubmit={submit}>
      <header><div className="eyebrow">Case intake</div><h2 id="add-heading">Add scan</h2><p>Import an original PNG from this computer.</p></header>
      {error && <Notice error>{error}</Notice>}
      <label>Original scan <input type="file" name="image" accept="image/png,.png" required disabled={busy} onChange={event => {
        const file = event.target.files[0];
        setHasFile(Boolean(file?.size));
        if (file && !name.trim()) setName(file.name.replace(/\.png$/i, ''));
      }} /></label>
      <label>New scan name <input type="text" name="name" required disabled={busy} value={name}
        onChange={event => setName(event.target.value)} aria-describedby="scan-name-help" /></label>
      <p id="scan-name-help">Names this scan only. Group membership is set below.</p>
      <fieldset className="source-fieldset" disabled={busy}>
        <legend>Source group</legend>
        <div className="source-choices">
          <label><input id="source-existing" type="radio" name="source_mode" checked={useExisting}
            onChange={() => switchMode('existing')} /> Use existing group</label>
          <label><input id="source-new" type="radio" name="source_mode" checked={!useExisting}
            onChange={() => switchMode('new')} /> Enter new group ID</label>
        </div>
        {useExisting && (linked ? <div className="source-lookup source-selected">
          <div className="heading-line"><strong role="status">Source group selected</strong>
            <button type="button" ref={changeGroupButton} onClick={() => {
              focusAfterSelection.current = true;
              setLinked(null);
              setError('');
            }}>Change group</button></div>
          <GroupMembers members={linked.members} />
          <label>Source group ID <input type="text" name="group_id" value={linked.id} readOnly /></label>
        </div> : <div className="source-lookup">
          <label>Find existing source group <input ref={searchInput} id="source-group-search" type="search"
            placeholder="Case name or group ID" value={query} onChange={event => setQuery(event.target.value)}
            autoComplete="off" aria-describedby="case-lookup-status" /></label>
          <p id="case-lookup-status" role="status">{loading ? 'Loading existing cases…' : listError ? 'Existing case lookup is unavailable.' :
            query.trim().length < 2 ? 'Type at least two characters to look up existing groups.' : !matches.length ? 'No matching existing cases.' :
            `Showing ${shown.length} of ${matches.length} matching source groups. Choose only a confirmed match.`}</p>
          {!!shown.length && <ul className="source-matches" aria-label="Matching source groups">
            {shown.map(match => <li className="source-match" key={groupKey(match.id)}>
              <GroupMembers members={match.members} />
              <code>{match.id}</code>
              <button type="button" disabled={busy || match.blocked}
                aria-label={match.blocked ? `Held-out group for ${match.name}` : `Use source group for ${match.name}`}
                onClick={() => { focusAfterSelection.current = true; setLinked(match); setError(''); }}>
                {match.blocked ? 'Held out — not available for training intake' : 'Use source group'}
              </button>
            </li>)}
          </ul>}
        </div>)}
        {!useExisting && <div>
          <label>New source group ID <input type="text" name="group_id" required spellCheck={false}
            aria-describedby="group-help" value={newID} onChange={event => setNewID(event.target.value)} /></label>
          <p id="group-help" role="status">{blocked ? 'This source group is held out and cannot be used for training intake.' :
            duplicateID ? 'This source group already exists. Select it using Use existing group.' :
            'Use a recorded ID for a known new source. Do not create one for a scan from an existing group.'}</p>
        </div>}
      </fieldset>
      <div className="action-buttons">
        <button type="button" onClick={onClose} disabled={busy}>Cancel</button><button type="submit" className="primary" disabled={!canSubmit}>{busy ? 'Adding…' : 'Add scan'}</button>
      </div>
    </form>
  </dialog>;
}
