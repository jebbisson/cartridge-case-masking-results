import { useEffect, useRef, useState } from 'react';
import { request } from './api.js';
import { targetLabel, textLabel } from './review.js';
import { EmptyState, Icon, Notice } from './ui.jsx';

const isActive = run => ['queued', 'pending', 'running', 'started'].includes(run.status);
const count = value => value?.length || 0;

function Changes({ heading, entries, openCase }) {
  return <section className="changes-section">
    <div className="heading-line"><h3>{heading}</h3><span className="mono quiet">{entries.length}</span></div>
    {entries.length ? <ul>{entries.map(row => (
      <li key={row.id}>
        <button type="button" className="change-row" onClick={() => openCase(row.id)}>
          <span><strong>{row.name}</strong>{row.targets?.length > 0 && <small>{row.targets.map(targetLabel).join(', ')}</small>}</span>
          <span className="change-revision mono">{row.previous_revision ? `r${row.previous_revision}` : ''}{row.previous_revision && row.revision ? ' → ' : ''}{row.revision ? `r${row.revision}` : ''}</span>
          <Icon name="right" size={15}/>
        </button>
      </li>))}</ul> : <p className="quiet">None</p>}
  </section>;
}

export default function Training({ openCase }) {
  const [preview, setPreview] = useState(null);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [feedback, setFeedback] = useState(null);
  const reads = useRef(null);
  const mounted = useRef(false);
  const active = runs.some(isActive);

  async function refresh(keepFeedback = false) {
    reads.current?.abort();
    const controller = new AbortController();
    reads.current = controller;
    setLoading(true);
    if (!keepFeedback) setFeedback(null);
    try {
      const [snapshot, jobs] = await Promise.all([
        request('/api/training/preview', { signal: controller.signal }),
        request('/api/training/runs', { signal: controller.signal }),
      ]);
      if (controller.signal.aborted) return;
      setPreview(snapshot);
      setRuns(jobs || []);
    } catch (error) {
      if (controller.signal.aborted) return;
      setPreview(null);
      setFeedback({ error: true, message: error.message });
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    mounted.current = true;
    refresh();
    return () => { mounted.current = false; reads.current?.abort(); };
  }, []);

  useEffect(() => {
    if (!active || loading || sending) return;
    const timer = setTimeout(() => refresh(true), 1600);
    return () => clearTimeout(timer);
  }, [runs, active, loading, sending]);

  async function train() {
    setSending(true);
    setFeedback(null);
    try {
      const run = await request('/api/training/runs', { body: { fingerprint: preview.fingerprint } });
      if (!mounted.current) return;
      setRuns(current => [run, ...current.filter(older => older.id !== run.id)]);
      setFeedback({ message: `Training run ${run.id} submitted.` });
      await refresh(true);
    } catch (error) {
      if (!mounted.current) return;
      if (error.status === 409) {
        setFeedback({ error: true, message: 'The preview changed. Review the refreshed snapshot and confirm again.' });
        await refresh(true);
      } else setFeedback({ error: true, message: error.message });
    } finally {
      if (mounted.current) setSending(false);
    }
  }

  return <main className="training-page" aria-label="Training changes">
    <header className="training-heading">
      <div><div className="eyebrow">Model workflow</div><h1>Training changes</h1><p>Compare eligible, approved cases with the last successful training snapshot.</p></div>
      <button type="button" onClick={() => refresh()} disabled={loading || sending}><Icon name="refresh" /> Refresh preview</button>
    </header>
    {feedback && <Notice error={feedback.error}>{feedback.message}</Notice>}
    {loading && !preview && <div className="training-panel"><EmptyState title="Loading training preview…" /></div>}
    {preview && <div className="training-layout">
      <section className="training-panel snapshot-panel" aria-labelledby="snapshot-title">
        <header><div><h2 id="snapshot-title">Pending snapshot</h2><p>Drafts, estimates, and held-out cases are not training inputs.</p></div></header>
        <dl className="snapshot-summary">
          <div><dt>Added</dt><dd>{count(preview.added)}</dd></div><div><dt>Corrected</dt><dd>{count(preview.corrected)}</dd></div>
          <div><dt>Excluded</dt><dd>{count(preview.excluded)}</dd></div><div><dt>Unchanged</dt><dd>{preview.unchanged}</dd></div>
          <div><dt>Total in snapshot</dt><dd>{preview.total}</dd></div>
        </dl>
        <Changes heading="Added" entries={preview.added || []} openCase={openCase} />
        <Changes heading="Corrected" entries={preview.corrected || []} openCase={openCase} />
        <Changes heading="Excluded" entries={preview.excluded || []} openCase={openCase} />
        <footer className="snapshot-actions">
          <div><span className="eyebrow">Snapshot fingerprint</span><div className="mono fingerprint" title={preview.fingerprint}>{preview.fingerprint}</div></div>
          <button type="button" className="primary" disabled={sending || loading || active || !preview.fingerprint || preview.total < 1} onClick={train}>
            <Icon name="check" /> {sending ? 'Submitting…' : active ? 'Training in progress' : 'Confirm & retrain'}
          </button>
        </footer>
      </section>
      <section className="training-panel runs-panel" aria-labelledby="runs-title">
        <header><div><h2 id="runs-title">Training runs</h2><p>Run status and model ID are reported by the local server.</p></div><span className="mono quiet">{runs.length}</span></header>
        {runs.length ? <ul className="runs-list">{runs.map(run => (
          <li key={run.id}><div className="heading-line"><strong>Run <span className="mono">{run.id}</span></strong><span className="pill run-status">{textLabel(run.status)}</span></div>
            {run.model && <div className="run-detail">Model <span className="mono">{run.model}</span></div>}
            {run.error && <p className="run-error">{run.error}</p>}
          </li>))}</ul> : <EmptyState title="No training runs yet">Confirm a nonempty snapshot to start a run.</EmptyState>}
      </section>
    </div>}
  </main>;
}
