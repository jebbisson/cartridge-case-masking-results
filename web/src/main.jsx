import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { casePath, request } from './api.js';
import { revisionId } from './review.js';
import AddScan from './AddScan.jsx';
import CaseQueue from './CaseQueue.jsx';
import Editor from './Editor.jsx';
import Training from './Training.jsx';
import { EmptyState, Icon, Notice } from './ui.jsx';
import './style.css';

const sortCases = items => [...items].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }) || a.id.localeCompare(b.id));

function App() {
  const [tab, setTab] = useState('review');
  const [items, setItems] = useState([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState('');
  const [detail, setDetail] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [opening, setOpening] = useState(false);
  const [epoch, setEpoch] = useState(0);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [stale, setStale] = useState(false);
  const [adding, setAdding] = useState(false);
  const pending = useRef(false);
  const listRequest = useRef(null);
  const detailRequest = useRef(null);

  useEffect(() => {
    refreshList(true);
    return () => { listRequest.current?.abort(); detailRequest.current?.abort(); };
  }, []);

  useEffect(() => {
    if (!dirty) return;
    const protect = event => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', protect);
    return () => window.removeEventListener('beforeunload', protect);
  }, [dirty]);

  function patchList(caseDetail) {
    const { id, name, group_id, split, included, width, height, latest, approved } = caseDetail;
    setItems(previous => sortCases([...previous.filter(item => item.id !== id), { id, name, group_id, split, included, width, height, latest, approved }]));
  }

  async function refreshList(initial = false) {
    listRequest.current?.abort();
    const controller = new AbortController();
    listRequest.current = controller;
    setListLoading(true);
    setListError('');
    try {
      const rows = sortCases(await request('/api/cases', { signal: controller.signal }) || []);
      if (controller.signal.aborted) return;
      setItems(rows);
      if ((initial || !detail) && rows[0] && !pending.current && !detailRequest.current) loadDetail(rows[0].id);
    } catch (error) {
      if (!controller.signal.aborted) setListError(error.message);
    } finally {
      if (!controller.signal.aborted) setListLoading(false);
    }
  }

  async function loadDetail(id, success) {
    detailRequest.current?.abort();
    const controller = new AbortController();
    detailRequest.current = controller;
    setOpening(true);
    setFeedback(null);
    try {
      const updated = await request(casePath(id), { signal: controller.signal });
      if (controller.signal.aborted) return;
      setDetail(updated);
      setComparison(null);
      patchList(updated);
      setDirty(false);
      setStale(false);
      setEpoch(n => n + 1);
      if (success) setFeedback({ message: success });
    } catch (error) {
      if (!controller.signal.aborted) setFeedback({ error: true, message: error.message });
    } finally {
      if (!controller.signal.aborted) {
        detailRequest.current = null;
        setOpening(false);
      }
    }
  }

  const mayDiscard = () => !dirty || window.confirm('Discard unsaved edits to this revision?');

  async function refreshCases() {
    if (pending.current || detailRequest.current || !mayDiscard()) return;
    if (!detail) return refreshList();
    pending.current = true;
    setBusy(true);
    try {
      await loadDetail(detail.id);
      await refreshList();
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  function openCase(id) {
    if (pending.current || detailRequest.current) return;
    if (id === detail?.id) {
      setTab('review');
      setComparison(null);
      return;
    }
    if (!mayDiscard()) return;
    setTab('review');
    loadDetail(id);
  }

  function reloadLatest() {
    if (!pending.current && !detailRequest.current && detail && mayDiscard()) loadDetail(detail.id);
  }

  async function onAction(path, body, message) {
    if (pending.current || detailRequest.current) return;
    pending.current = true;
    setBusy(true);
    setFeedback(null);
    try {
      const updated = await request(path, { body });
      setDetail(updated);
      setComparison(null);
      patchList(updated);
      setStale(false);
      setDirty(false);
      setFeedback({ message });
    } catch (error) {
      if (error.status === 409 && path.endsWith('/review')) {
        setStale(true);
        setFeedback({ error: true, message: 'This revision is no longer current. Unsaved edits are still displayed; reload the latest revision to continue.' });
      } else setFeedback({ error: true, message: error.message });
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  async function onEstimate(base, apply) {
    if (!detail || pending.current || detailRequest.current || dirty) return;
    pending.current = true;
    setBusy(true);
    setFeedback(null);
    try {
      const preview = await request(`${casePath(detail.id)}/estimate`, { body: { base_revision: base } });
      apply(preview);
    } catch (error) {
      setFeedback({ error: true, message: error.message });
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  function onAdded(data) {
    setAdding(false);
    setTab('review');
    const imported = data.case ?? data;
    loadDetail(imported.id, 'Original scan imported.');
  }

  return <div className="shell">
    <header className="masthead">
      <div className="identity"><div className="identity-mark"><Icon name="mark" size={20}/></div><div><strong>Cartridge Case Review</strong><span>MASK ANNOTATION WORKBENCH</span></div></div>
      <nav className="workspace-nav" aria-label="Workspace">
        <button type="button" aria-current={tab === 'review' ? 'page' : undefined} onClick={() => setTab('review')}>Case review</button>
        <button type="button" aria-current={tab === 'training' ? 'page' : undefined} onClick={() => setTab('training')}>Training changes</button>
      </nav>
      <div className="masthead-end"><button type="button" onClick={() => { if (mayDiscard()) setAdding(true); }} disabled={busy || opening}>＋ <span>Add scan</span></button><span className="environment"><span className="status-dot" /> Local workspace</span></div>
    </header>
    <div className="workbench" hidden={tab !== 'review'}>
      <CaseQueue items={items} selected={detail?.id} loading={listLoading} error={listError} busy={busy || opening} openCase={openCase} refresh={refreshCases} />
      {detail ? <Editor key={`${detail.id}:${revisionId(detail.selected) || 0}:${epoch}`} detail={detail} dirty={dirty} setDirty={setDirty} busy={busy || opening}
        feedback={feedback} stale={stale} comparison={comparison} setComparison={setComparison} reloadLatest={reloadLatest}
        onAction={onAction} onEstimate={onEstimate} shortcutActive={tab === 'review' && !adding} /> :
        <main className="editor empty-editor" aria-label="Scan workspace">
          {feedback && <Notice error={feedback.error}>{feedback.message}</Notice>}
          <EmptyState icon="image" title={opening || listLoading ? 'Loading scan workspace…' : 'Select a case'}>{!opening && !listLoading && 'Choose a scan from the case queue.'}</EmptyState>
        </main>}
    </div>
    {tab === 'training' && <Training openCase={openCase} />}
    {adding && <AddScan items={items} loading={listLoading} listError={listError} onClose={() => setAdding(false)} onAdded={onAdded} />}
  </div>;
}

createRoot(document.getElementById('root')).render(<App />);
