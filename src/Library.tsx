import { useEffect, useState } from 'react';
import { BookOpen, Plus } from 'lucide-react';
import { api, post } from './api';

interface Entry {
  id: string; key: string; bank: string; title: string; body: string; status: string;
  company: string; caveats: string; revision: number; event_date: string | null;
  sources: {reference: string; locator: string; accessed_on: string; note: string}[];
}
const banks = ['All', 'Fact', 'Experience', 'Company', 'Person', 'Hiring signal', 'Research', 'Artifact', 'Idea'];

export default function Library({projectId, onImport}: {projectId: string; onImport: () => void}) {
  const [bank, setBank] = useState('All');
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{total: number; entries: Entry[]}>({total: 0, entries: []});
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [pending, setPending] = useState('');
  useEffect(() => {
    let active = true;
    const timer = setTimeout(() => {
      const params = new URLSearchParams({query, offset: String(offset), limit: '25'});
      if (bank !== 'All') params.set('bank', bank);
      void api<{total: number; entries: Entry[]}>(`/library?${params}`).then(value => {
        if (active) {setData(value); setError('');}
      }).catch(e => {if (active) setError(String(e));});
    }, 180);
    return () => {active = false; clearTimeout(timer);};
  }, [bank, query, offset]);
  async function attach(entry: Entry) {
    setPending(entry.id); setError(''); setNotice('');
    try {
      await post(`/projects/${projectId}/library-import`, {entry_ids: [entry.id]});
      setNotice(`${entry.title} is attached to this project's evidence.`); onImport();
    } catch (e) {setError(String(e));} finally {setPending('');}
  }
  return <section>
    <p className="muted">Saved once, available across projects. Attach an entry to use its current revision in this opportunity. “Documented” means a source is recorded; it does not imply independent verification.</p>
    <div className="section-toolbar" style={{flexWrap: 'wrap', gap: 16}}>
      <label>Search<input aria-label="Search reusable banks" placeholder="Search facts, cases, people…" value={query} onChange={e => {setQuery(e.target.value); setOffset(0);}} /></label>
      <label>Bank <select aria-label="Reusable bank" value={bank} onChange={e => {setBank(e.target.value); setOffset(0);}}>{banks.map(b => <option key={b}>{b}</option>)}</select></label>
      <span className="muted">{data.total} {data.total === 1 ? 'entry' : 'entries'}</span>
    </div>
    {error && <p role="alert" className="form-error">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    <div className="evidence-list">{data.entries.map(entry => <article className="evidence-item" key={entry.id}>
      <div className="evidence-symbol"><BookOpen size={20}/></div>
      <div style={{minWidth: 0}}><div className="evidence-heading"><h3>{entry.title}</h3><span className="badge">{entry.bank}</span></div>
        <div className="source-line"><span className={`source-status ${entry.status === 'Hypothesis' ? 'assumed' : ''}`}><span/>{entry.status}</span>{entry.company && <span>{entry.company}</span>}<span>Revision {entry.revision}</span></div>
        <p style={{whiteSpace: 'pre-wrap'}}>{entry.body}</p>
        {entry.caveats && <p><strong>Source limits:</strong> {entry.caveats}</p>}
        <details><summary>Sources ({entry.sources.length})</summary>{entry.sources.map((s, i) => <p key={i} style={{overflowWrap: 'anywhere'}}>
          {/^https?:\/\//.test(s.reference) ? <a href={s.reference} target="_blank" rel="noreferrer">{s.reference}</a> : s.reference}
          {s.locator && ` · ${s.locator}`}<br/><small>Checked {s.accessed_on}{s.note && ` · ${s.note}`}</small>
        </p>)}</details>
        <button className="text-button" disabled={Boolean(pending)} onClick={() => void attach(entry)}><Plus size={14}/>{pending === entry.id ? 'Attaching…' : 'Use in this project'}</button>
      </div>
    </article>)}</div>
    {!data.total && <p className="muted">No entries match this search.</p>}
    {data.total > 25 && <div className="section-toolbar"><button className="button secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous</button><span>{offset + 1}–{Math.min(offset + 25, data.total)} of {data.total}</span><button className="button secondary" disabled={offset + 25 >= data.total} onClick={() => setOffset(offset + 25)}>Next</button></div>}
  </section>;
}
