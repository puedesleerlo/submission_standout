import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { ArrowDownToLine, ArrowRight, ArrowUpRight, Beaker, BookOpen, Check, CheckCheck, ChevronDown, ChevronRight, CircleHelp, Clock3, Copy, FileText, FlaskConical, GitBranch, GitMerge, Layers3, LockKeyhole, Plus, RefreshCw, ShieldCheck, X } from 'lucide-react';
import { api, ApiError, post, signIn } from './api';
import Studio from './Studio';
import Research, { Reviewer } from './Research';
import Showcase from './Showcase';
import type { Evidence, Package, Page, Policy, Project, Run, RunDetail, Trial, Workspace, Provider } from './types';

const dimensions: Record<string, string> = { fit: 'Focus coverage', evidence: 'Evidence', feasibility: 'Plan structure', originality: 'Hypothesis framing', voice: 'Style checks' };
const framingNames = { evidence: 'Evidence first', delivery: 'Delivery plan', hypothesis: 'Research hypothesis', mission: 'Institutional contribution' };
const navigation: { id: Page; name: string; icon: typeof FileText }[] = [
  { id: 'studio', name: 'Submission studio', icon: FileText },
  { id: 'brief', name: 'Project brief', icon: FileText }, { id: 'evidence', name: 'Evidence bank', icon: Layers3 },
  { id: 'strategies', name: 'Strategies', icon: GitBranch }, { id: 'experiments', name: 'Experiments', icon: FlaskConical },
  { id: 'research', name: 'Research study', icon: ShieldCheck },
];
const dateLabel = (date: string) => new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(new Date(date));
const timeLabel = (date: string) => new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(date));
type ModalState = { kind: 'project' | 'evidence' | 'run' } | { kind: 'policy'; parent?: Policy } | { kind: 'draft'; package: Package } | { kind: 'trial'; trial: Trial } | null;

function Dialog({ title, subtitle, children, close, wide = false }: { title: string; subtitle?: string; children: ReactNode; close: () => void; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); return () => ref.current?.close(); }, []);
  return <dialog ref={ref} className={`dialog ${wide ? 'dialog-wide' : ''}`} onCancel={close} onClick={event => { if (event.target === ref.current) close(); }}>
    <header className="dialog-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div><button className="icon-button" aria-label="Close dialog" onClick={close}><X size={20} /></button></header>
    {children}
  </dialog>;
}

function Outcome({ passed }: { passed: boolean }) { return <span className={`outcome ${passed ? 'pass' : 'fail'}`}>{passed ? <Check size={13} /> : <X size={13} />}{passed ? 'Pass' : 'No pass'}</span>; }
function Empty({ title, body, action }: { title: string; body: string; action?: ReactNode }) { return <div className="empty"><BookOpen size={27} /><h3>{title}</h3><p>{body}</p>{action}</div>; }

function Login({ onLogin, initialError }: { onLogin: () => void; initialError: string }) {
  const [token, setToken] = useState(''); const [error, setError] = useState(initialError); const [busy, setBusy] = useState(false);
  return <main className="login"><div className="brand-mark"><GitBranch size={26} /></div><h1>Submission Standout</h1><p>Open your local research workspace.</p>
    <form onSubmit={async e => { e.preventDefault(); setBusy(true); try { await signIn(token.trim()); onLogin(); } catch (err) { setError((err as Error).message); } finally { setBusy(false); } }}>
      <label>Local access key<input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} required /></label>
      {error && <p className="form-error" role="alert">{error}</p>}<button className="button primary" disabled={busy}>{busy ? 'Opening…' : 'Open workspace'}<ArrowRight size={16} /></button>
    </form><p className="help">Run <code>pnpm access</code> in the project folder to get a sign-in link. The key stays out of the application bundle.</p>
  </main>;
}

export default function App() {
  if (import.meta.env.VITE_SHOWCASE_ONLY === '1') return <Showcase/>;
  if (window.location.pathname === '/showcase') return <Showcase/>;
  if (window.location.pathname === '/review') return <Reviewer/>;
  return <Workbench/>;
}

function Workbench() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [provider, setProvider] = useState<Provider|null>(null);
  const [projects, setProjects] = useState<Project[]>([]); const [projectId, setProjectId] = useState('');
  const [workspace, setWorkspace] = useState<Workspace | null>(null); const [page, setPage] = useState<Page>(new URLSearchParams(location.search).get('view') === 'research' ? 'research' : 'studio');
  const [selectedRun, setSelectedRun] = useState(''); const [run, setRun] = useState<RunDetail | null>(null);
  const [modal, setModal] = useState<ModalState>(null); const [busy, setBusy] = useState('');
  const [error, setError] = useState(''); const [modalError, setModalError] = useState(''); const [notice, setNotice] = useState('');
  const [evidenceFilter, setEvidenceFilter] = useState('All'); const [trialPolicy, setTrialPolicy] = useState('all');
  const [draftBody, setDraftBody] = useState(''); const [inspectorView, setInspectorView] = useState<'learner' | 'observer'>('learner');
  const [loading, setLoading] = useState(false); const loadSequence = useRef(0);

  useEffect(() => {
    const access = new URLSearchParams(window.location.hash.slice(1)).get('access');
    if (access) history.replaceState(null, '', window.location.pathname + window.location.search);
    (async () => {
      try { if (access) await signIn(access); else await api('/session'); setAuthenticated(true); }
      catch (err) { setAuthenticated(false); if (!(err instanceof ApiError && err.status === 401)) setError((err as Error).message); }
    })();
  }, []);

  useEffect(() => {
    if (!authenticated) return;
    api<Provider>('/model').then(setProvider).catch(() => setProvider(null));
    api<Project[]>('/projects').then(items => {
      setProjects(items);
      const saved = localStorage.getItem('standout.project');
      setProjectId(items.find(item => item.id === saved)?.id || items[0]?.id || '');
    }).catch(err => setError(err.message));
  }, [authenticated]);

  async function refresh(id = projectId) {
    if (!id) return;
    const sequence = ++loadSequence.current;
    setLoading(true);
    try {
      const data = await api<Workspace>(`/projects/${id}`);
      if (sequence !== loadSequence.current) return;
      setWorkspace(data); setError('');
      setSelectedRun(previous => data.runs.some(item => item.id === previous) ? previous : data.runs[0]?.id || '');
    } catch (err) { if (sequence === loadSequence.current) setError((err as Error).message); }
    finally { if (sequence === loadSequence.current) setLoading(false); }
  }
  useEffect(() => { if (projectId) { localStorage.setItem('standout.project', projectId); setWorkspace(null); setRun(null); setTrialPolicy('all'); void refresh(projectId); } }, [projectId]);
  useEffect(() => {
    let alive = true; setRun(null);
    if (projectId && selectedRun && workspace?.project.id === projectId && workspace.runs.some(item => item.id === selectedRun)) api<RunDetail>(`/projects/${projectId}/runs/${selectedRun}`).then(data => { if (alive) setRun(data); }).catch(err => { if (alive) setError(err.message); });
    return () => { alive = false; };
  }, [projectId, selectedRun]);
  useEffect(() => { if (!notice) return; const timer = setTimeout(() => setNotice(''), 5000); return () => clearTimeout(timer); }, [notice]);

  const open = (next: ModalState) => { setModalError(''); setModal(next); if (next?.kind === 'draft') setDraftBody(next.package.body); if (next?.kind === 'trial') setInspectorView('learner'); };
  const close = () => { if (!busy) setModal(null); };
  const policyName = (id: string) => workspace?.policies.find(item => item.id === id)?.name || 'Strategy';

  async function action<T>(name: string, task: () => Promise<T>): Promise<T | undefined> {
    setBusy(name); setError(''); setModalError('');
    try { return await task(); } catch (err) { const message = (err as Error).message; setError(message); setModalError(message); return undefined; }
    finally { setBusy(''); }
  }
  async function generate(policy: Policy) {
    if (policy.author === 'kimi') { const latest = workspace?.packages.filter(p => p.policy_id === policy.id).at(-1); if (latest) open({kind:'draft',package:latest}); else setPage('studio'); return; }
    await action('draft', async () => {
      const draft = await post<Package>(`/projects/${projectId}/packages`, { policy_id: policy.id });
      await refresh(); open({ kind: 'draft', package: draft }); setNotice('Draft saved as an immutable package.');
    });
  }
  async function evaluatePackage(item: Package) {
    if (item.generator === 'kimi-writer-v1') { await action('run', async () => { await post(`/projects/${projectId}/agent-jobs`, {mode:'evaluate',artifact_type:item.artifact_type||'Proposal',brief:'',package_id:item.id,request_key:crypto.randomUUID()}); setModal(null);setPage('studio'); }); return; }
    await action('run', async () => {
      const result = await post<Run>(`/projects/${projectId}/runs`, { package_ids: [item.id], policy_ids: [], worlds: 12, seed: 17, delay_days: 0, request_key: crypto.randomUUID() });
      await refresh(); setSelectedRun(result.id); setPage('experiments'); setModal(null); setNotice('12 reference decisions recorded.');
    });
  }
  async function submitForm(event: FormEvent<HTMLFormElement>, kind: string) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    const text = (key: string) => String(form.get(key) || '');
    await action(kind, async () => {
      if (kind === 'project') {
        const item = await post<Project>('/projects', { name: text('name'), institution: text('institution'), posting: text('posting'), deadline: text('deadline'), domain: text('domain'), focus: text('focus').split(',').map(s => s.trim()).filter(Boolean), reservation_conditions: text('constraints') });
        setProjects(await api<Project[]>('/projects')); setProjectId(item.id); setPage('studio');
      } else if (kind === 'evidence') {
        await post<Evidence>(`/projects/${projectId}/evidence`, { title: text('title'), body: text('body'), kind: text('kind'), source: text('source'), status: text('status') });
        await refresh(); setNotice('Evidence added. Existing experiment snapshots are preserved.');
      } else if (kind === 'policy') {
        const base = modal?.kind === 'policy' ? modal.parent : undefined;
        const parents = [base?.id, text('merge')].filter(Boolean);
        await post<Policy>(`/projects/${projectId}/policies`, { name: text('name'), hypothesis: text('hypothesis'), parents, config: { framing: text('framing'), evidence_limit: Number(text('limit')), plan_depth: Number(text('depth')), compare_alternative: form.get('alternative') === 'on' } });
        await refresh(); setPage('strategies'); setNotice(parents.length === 2 ? 'Merged strategy version saved. Evaluate it to test the combination.' : 'Strategy version saved.');
      } else if (kind === 'run') {
        const result = await post<Run>(`/projects/${projectId}/runs`, { policy_ids: form.getAll('policies'), package_ids: [], worlds: Number(text('worlds')), seed: Number(text('seed')), delay_days: Number(text('delay')), request_key: crypto.randomUUID() });
        await refresh(); setSelectedRun(result.id); setPage('experiments'); setTrialPolicy('all'); setNotice(`${result.trial_ids.length} reference decisions recorded.`);
      }
      setModal(null);
    });
  }
  async function exportProject() {
    await action('export', async () => {
      const payload = await api(`/projects/${projectId}/export`);
      const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }));
      const link = document.createElement('a'); link.href = url; link.download = `standout-${projectId}.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 2000);
      setNotice('Complete observer dataset exported. It contains private diagnostics.');
    });
  }

  if (authenticated === null) return <div className="boot"><GitBranch size={28} /><p>Opening your workspace…</p></div>;
  if (!authenticated) return <Login onLogin={() => { setError(''); setAuthenticated(true); }} initialError={error} />;
  const project = workspace?.project;
  const selectedTrial = modal?.kind === 'trial' ? modal.trial : null;

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={event => { event.preventDefault(); setPage('studio'); }}><span className="brand-mark"><GitBranch size={22} /></span><span>Standout<span className="brand-sub">Submission research</span></span></a>
      <div className="project-switch"><label htmlFor="project-choice">Your workspace</label><div className="select-wrap"><select id="project-choice" value={projectId} disabled={Boolean(busy)} onChange={e => setProjectId(e.target.value)}>{projects.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><ChevronDown size={14} /></div><button className="sidebar-new" onClick={() => open({ kind: 'project' })}><Plus size={14} />New project</button></div>
      <nav aria-label="Main navigation">{navigation.map(item => <button key={item.id} className={`nav-item ${page === item.id ? 'active' : ''}`} onClick={() => setPage(item.id)}><item.icon size={18} /><span>{item.name}</span>{item.id === 'experiments' && Boolean(workspace?.runs.length) && <span className="nav-count">{workspace?.runs.length}</span>}</button>)}</nav>
      <div className="sidebar-bottom"><div className="lab-indicator"><span />{provider?.configured ? 'Kimi K3 configured' : 'Kimi not configured'}</div><p>Drafts saved locally.<br />{provider?.configured ? 'Moonshot writes and assesses.' : 'Connect a model to develop drafts.'}</p><button className="sidebar-export" disabled={!workspace || Boolean(busy)} onClick={exportProject}><ArrowDownToLine size={15} />Export experiment data</button></div>
    </aside>

    <main className="main">
      <div className="topbar"><span>{project?.domain || 'Workspace'}<ChevronRight size={13} />{navigation.find(item => item.id === page)?.name}</span><span className="local-pill"><ShieldCheck size={14} />Observer workspace</span></div>
      {error && <div className="error-banner" role="alert"><span>{error}</span><button onClick={() => refresh()}><RefreshCw size={14} />Retry</button></div>}
      {notice && <div className="toast" role="status"><CheckCheck size={17} />{notice}<button aria-label="Dismiss notification" onClick={() => setNotice('')}><X size={15} /></button></div>}
      {page === 'research' ? <div className="page-body"><Research projects={projects}/></div> : !workspace ? <div className="page-body">{loading ? <div className="loading"><span className="spinner" />Loading project…</div> : <Empty title="Create your first submission project" body="Start with a posting and the opportunity you want to pursue." action={<button className="button primary" onClick={() => open({ kind: 'project' })}>New project<Plus size={16} /></button>} />}</div> : <div className="page-body">
        {project?.synthetic && <div className="sample-notice"><Beaker size={16} /><span>Synthetic example. The institution, evidence, and rivals are illustrative.</span><button onClick={() => open({ kind: 'project' })}>Use your own opportunity<ArrowUpRight size={14} /></button></div>}
        <header className="page-header"><div><h1>{page === 'brief' || page === 'studio' ? project?.name : navigation.find(item => item.id === page)?.name}</h1><p>{page === 'studio' ? `${project?.institution} · Submission studio` : page === 'brief' ? `${project?.institution} · ${project?.domain} application` : page === 'evidence' ? 'The facts and sources behind your submission.' : page === 'strategies' ? 'Version the approach. Keep the reasoning behind every change.' : 'Compare strategies against the same hidden selection worlds.'}</p></div>
          {page !== 'studio' && <button className="button secondary" disabled={Boolean(busy) || !workspace.policies.some(p => p.author !== 'kimi')} onClick={() => open({ kind: 'run' })}><FlaskConical size={16} />Reference comparison</button>}
        </header>

        {page === 'studio' && <Studio key={projectId} workspace={workspace} onEvidence={() => setPage('evidence')} onInspect={id => {setSelectedRun(id);setPage('experiments');}} onRefresh={() => {void refresh();}} />}

        {page === 'brief' && <>
          <div className="brief-layout"><section className="opportunity"><div className="section-title"><h2>The opportunity</h2><span className="badge">{project?.domain}</span></div><p className="posting">{project?.posting}</p><div className="focus-tags">{project?.focus.map(term => <span key={term}>{term}</span>)}</div><div className="deadline"><Clock3 size={18} /><div><span>Submission deadline</span><strong>{dateLabel(project!.deadline)} · 23:59 UTC</strong></div></div><details className="constraints" open><summary>Reservation conditions<ChevronDown size={15} /></summary><p>{project?.reservation_conditions || 'No conditions recorded yet.'}</p><small>These need your review before any real commitment. This prototype does not infer feasibility from prose.</small></details></section>
          <section className="latest-panel"><div className="section-title"><h2>Latest comparison</h2><span className="live-dot" /></div>{workspace.runs.length > 0 ? <><p className="muted">{workspace.runs[0].world_count} matched worlds · {workspace.runs[0].policy_ids.length} strategy versions</p><div className="latest-list">{run && run.id === workspace.runs[0].id ? run.summaries.map(summary => <div key={summary.policy_id}><div><GitBranch size={15} /><span>{policyName(summary.policy_id)}</span></div><strong>{summary.passed}<span> / {summary.total}</span></strong></div>) : workspace.runs[0].policy_ids.map(id => <div key={id}><span>{policyName(id)}</span><Check size={15} /></div>)}</div><p className="reference-caption">{workspace.runs[0].origin === 'llm-simulation' ? 'Kimi-assessed passes under assumed selection scenarios. These are not real acceptance odds.' : 'Passes in the reference simulator. These are not real acceptance odds.'}</p><button className="button secondary full" onClick={() => { setSelectedRun(workspace.runs[0].id); setPage('experiments'); }}>Inspect comparison<ArrowRight size={16} /></button></> : <Empty title="Ready for a first comparison" body="Add evidence and a strategy, then run a reference experiment." />}</section></div>
          <div className="section-title section-gap"><div><h2>From evidence to a decision</h2><p className="muted">Each round records the submission and the feedback available to a learner.</p></div></div>
          <div className="process-strip"><button onClick={() => setPage('evidence')}><Layers3 size={20} /><strong>{workspace.evidence.length} evidence items</strong><span>Traceable inputs</span></button><ChevronRight className="process-arrow" size={18} /><button onClick={() => setPage('strategies')}><GitBranch size={20} /><strong>{workspace.policies.length} strategy versions</strong><span>Inspectable approaches</span></button><ChevronRight className="process-arrow" size={18} /><button onClick={() => setPage('experiments')}><LockKeyhole size={20} /><strong>Pass or fail</strong><span>The learner's feedback</span></button></div>
          <section className="assumptions section-gap"><div className="section-title"><h2>Reference-lab assumptions</h2><span className="badge warm">Illustrative priors</span></div><p className="muted">These frozen scenarios exercise the system. Their weights have not been inferred from a real institution.</p><div className="scenario-grid">{workspace.scenarios.map(scenario => <div key={scenario.id}><div className="scenario-heading"><strong>{scenario.name}</strong><span>{Math.round(scenario.probability * 100)}%</span></div><div className="scenario-bar"><span style={{ width: `${scenario.probability * 100}%` }} /></div><p>{Object.entries(scenario.weights).sort((a,b) => b[1]-a[1]).slice(0,2).map(([key]) => dimensions[key]).join(' and ')}</p></div>)}</div></section>
        </>}

        {page === 'evidence' && <><div className="section-toolbar"><div className="filter-tabs" aria-label="Evidence type">{['All', 'Experience', 'Research', 'Artifact', 'Institution', 'Idea'].map(kind => <button key={kind} className={evidenceFilter === kind ? 'selected' : ''} onClick={() => setEvidenceFilter(kind)}>{kind}</button>)}</div><button className="button secondary" onClick={() => open({ kind: 'evidence' })}><Plus size={16} />Add evidence</button></div>
          <div className="evidence-list">{workspace.evidence.filter(item => evidenceFilter === 'All' || item.kind === evidenceFilter).map(item => <article className="evidence-item" key={item.id}><div className="evidence-symbol">{item.kind === 'Institution' ? <BookOpen size={20} /> : <FileText size={20} />}</div><div><div className="evidence-heading"><h3>{item.title}</h3><span className="badge">{item.kind}</span></div><p>{item.body}</p><div className="source-line"><span className={`source-status ${item.status === 'Hypothesis' ? 'assumed' : ''}`}><span />{item.status}</span><span>{item.source || 'No source recorded'}</span><span>{item.kind === 'Institution' ? 'Shared context' : 'Applicant evidence'}</span></div></div></article>)}</div>
          {!workspace.evidence.filter(item => evidenceFilter === 'All' || item.kind === evidenceFilter).length && <Empty title="No evidence in this bank yet" body="Add a concrete fact or source to make it available to future drafts." action={<button className="button secondary" onClick={() => open({ kind: 'evidence' })}>Add evidence<Plus size={16} /></button>} />}
          <p className="footnote"><ShieldCheck size={15} />Evidence is snapshotted when a package is created. Later additions do not rewrite earlier trials.</p></>}

        {page === 'strategies' && <><div className="section-toolbar"><span className="muted">{workspace.policies.length} immutable versions</span><button className="button secondary" onClick={() => open({ kind: 'policy' })}><Plus size={16} />New strategy</button></div><div className="policy-list">{workspace.policies.map(policy => { const latest = workspace.packages.filter(item => item.policy_id === policy.id).at(-1); return <article className={`policy-item ${policy.parents.length ? 'descendant' : ''}`} key={policy.id}><div className="policy-marker">{policy.parents.length === 2 ? <GitMerge size={20} /> : <GitBranch size={20} />}</div><div className="policy-main"><div className="policy-heading"><h3>{policy.name}</h3><span className="version">v{policy.version}</span></div>{Boolean(policy.parents.length) && <p className="parent-line">{policy.parents.map(id => policyName(id)).join(' + ')}<ArrowRight size={12} />{policy.operation}</p>}<p>{policy.hypothesis}</p><div className="policy-settings">{policy.author === 'kimi' ? <><span>Executable writing policy</span><span>{policy.learning_observation?.length || 0} binary observations</span><span>Kimi K3</span></> : <><span>{framingNames[policy.config.framing]}</span><span>{policy.config.evidence_limit} evidence passages</span><span>{policy.config.plan_depth} milestones</span>{policy.config.compare_alternative && <span>Alternative comparison</span>}</>}</div></div><div className="policy-actions"><button className="button secondary" disabled={Boolean(busy)} onClick={() => generate(policy)}><FileText size={15} />{policy.author === 'kimi' ? 'Open draft' : 'Generate draft'}</button><button className="text-button" onClick={() => policy.author === 'kimi' ? setPage('studio') : open({ kind: 'policy', parent: policy })}><GitBranch size={14} />{policy.author === 'kimi' ? 'Explore in studio' : 'Branch or merge'}</button>{latest && <button className="text-button" onClick={() => open({ kind: 'draft', package: latest })}>Open latest draft<ArrowUpRight size={13} /></button>}</div></article>; })}</div>
          {!workspace.policies.length && <Empty title="Give your first strategy a hypothesis" body="Choose what to emphasize and how to use your evidence. Each change is saved as a new version." action={<button className="button primary" onClick={() => open({ kind: 'policy' })}>New strategy<Plus size={16} /></button>} />}
          <div className="method-note"><CircleHelp size={18} /><p>The reference compositor uses the settings shown here. Manual reference strategies use numeric settings. Kimi strategies execute full writing instructions; develop and iterate them in the submission studio.</p></div></>}

        {page === 'experiments' && (workspace.runs.length ? <><div className="experiment-picker"><label htmlFor="comparison">Comparison</label><select id="comparison" value={selectedRun} onChange={e => { setSelectedRun(e.target.value); setTrialPolicy('all'); }}>{workspace.runs.map((item, index) => <option key={item.id} value={item.id}>#{workspace.runs.length - index} · {timeLabel(item.created_at)} · {item.trial_ids.length} decisions</option>)}</select><span className="badge">{run?.origin === 'llm-simulation' ? 'Kimi assessment' : 'Reference simulation'}</span></div>
          {!run ? <div className="loading"><span className="spinner" />Loading decisions…</div> : <><div className="comparison-meta"><span><Layers3 size={15} />{run.world_count} matched worlds</span><span><GitBranch size={15} />{run.policy_ids.length} strategy versions</span><span><LockKeyhole size={15} />Binary feedback</span><span>Seed {run.seed}</span><span>{run.delay_days} day delay</span></div>
          <section className="comparison-section"><div className="section-title"><h2>How each strategy performed</h2><span className="muted small">Passes / simulated trials</span></div><div className="table-scroll"><table className="comparison-table"><thead><tr><th>Strategy</th><th>Sampled mixture</th>{(run.scenarios || workspace.scenarios).map(s => <th key={s.id}>{s.name}</th>)}</tr></thead><tbody>{run.summaries.map(summary => <tr key={summary.policy_id}><td><strong>{policyName(summary.policy_id)}</strong><span>v{workspace.policies.find(p => p.id === summary.policy_id)?.version}</span></td><td><div className="rate"><strong>{summary.passed}<span> / {summary.total}</span></strong><div className="rate-track"><span style={{ width: `${summary.passed / summary.total * 100}%` }} /></div></div></td>{summary.by_scenario.map(s => <td key={s.scenario_id}>{s.total ? <span className={`fraction ${s.passed === s.total ? 'good' : ''}`}>{s.passed} <span>/ {s.total}</span></span> : <span className="muted">Not sampled</span>}</td>)}</tr>)}</tbody></table></div><p className="reference-caption">{run.origin === 'llm-simulation' ? 'Kimi evaluates each document once. Its scores are tested under frozen counterfactual worlds. These are practice comparisons, not independent judge votes or real acceptance probabilities.' : 'A comparison of fixed documents under a sampled synthetic pool. Small counts describe this run only; they are not calibrated acceptance probabilities.'}</p></section>
          <section className="trials-section"><div className="section-title"><div><h2>Decision records</h2><p className="muted">Inspect the exact learner observation and the private evaluation behind it.</p></div><select aria-label="Filter trials by strategy" value={trialPolicy} onChange={e => setTrialPolicy(e.target.value)}><option value="all">All strategies</option>{run.policy_ids.map(id => <option key={id} value={id}>{policyName(id)}</option>)}</select></div><div className="table-scroll"><table className="trial-table"><thead><tr><th>World</th><th>Strategy</th><th>Selector</th><th>Outcome</th><th>Score</th><th><span className="sr-only">Inspect</span></th></tr></thead><tbody>{run.trials.filter(t => trialPolicy === 'all' || t.policy_id === trialPolicy).map(trial => <tr key={trial.id}><td>{String(trial.evaluation.world.index + 1).padStart(2, '0')}</td><td>{policyName(trial.policy_id)}</td><td><span className="muted">{trial.evaluation.world.scenario.name}</span></td><td><Outcome passed={trial.observation.passed} /></td><td className="numeric">{trial.evaluation.score.toFixed(1)}</td><td><button className="inspect-button" aria-label={`Inspect world ${trial.evaluation.world.index + 1}, ${policyName(trial.policy_id)}`} onClick={() => open({ kind: 'trial', trial })}><ArrowUpRight size={16} /></button></td></tr>)}</tbody></table></div></section>
          <p className="footnote"><Clock3 size={15} />{run.origin === 'llm-simulation' ? `${run.cost.model_calls} Kimi calls · ${run.cost.model_tokens?.toLocaleString() || '—'} tokens · Cost billed by Moonshot` : `${run.cost.reference_evaluations} reference evaluations · $${(run.cost.external_cost_usd || 0).toFixed(2)} external cost`}. Scores are observer-only.</p></>}
          </> : <Empty title="Run your first controlled comparison" body="Each strategy receives the same public context and is tested in a separate copy of each hidden world." action={<button className="button primary" disabled={!workspace.policies.length} onClick={() => open({ kind: 'run' })}>New comparison<FlaskConical size={16} /></button>} />)}
      </div>}
    </main>

    {modal?.kind === 'project' && <Dialog title="New submission project" subtitle="Start with the opportunity you want to pursue." close={close}><form onSubmit={e => submitForm(e, 'project')}><div className="form-body"><label>Project name<input name="name" placeholder="Research fellowship application" required minLength={2} maxLength={120} /></label><div className="form-grid"><label>Institution<input name="institution" required minLength={2} maxLength={160} /></label><label>Opportunity type<select name="domain"><option>Fellowship</option><option>Grant</option><option>Job</option></select></label></div><label>Original posting<textarea name="posting" rows={5} required minLength={30} placeholder="Paste the posting and its requirements." /></label><div className="form-grid"><label>Deadline (UTC)<input name="deadline" type="date" required /></label><label>Focus terms<input name="focus" required placeholder="research methods, public health" /></label></div><label>Reservation conditions<textarea name="constraints" rows={2} placeholder="Your limits on time, location, scope, or other commitments." /></label>{modalError && <p className="form-error" role="alert">{modalError}</p>}</div><footer className="dialog-footer"><button type="button" className="button secondary" disabled={Boolean(busy)} onClick={close}>Cancel</button><button className="button primary" disabled={Boolean(busy)}>Create project<Plus size={16} /></button></footer></form></Dialog>}

    {modal?.kind === 'evidence' && <Dialog title="Add evidence" subtitle="Keep facts, ideas, and institutional context traceable." close={close}><form onSubmit={e => submitForm(e, 'evidence')}><div className="form-body"><label>Title<input name="title" required minLength={2} maxLength={140} /></label><div className="form-grid"><label>Bank<select name="kind">{['Experience', 'Research', 'Artifact', 'Idea', 'Institution'].map(kind => <option key={kind}>{kind}</option>)}</select></label><label>Evidence status<select name="status"><option>User supplied</option><option>Documented</option><option>Hypothesis</option></select></label></div><label>Fact or observation<textarea name="body" required minLength={15} rows={5} placeholder="What happened, what you contributed, and what the evidence supports." /></label><label>Source or reference<input name="source" placeholder="Source URL, document title, or a note about provenance" /></label><p className="form-help">Institution items enter shared context. Other banks remain private until included in a submission.</p>{modalError && <p className="form-error" role="alert">{modalError}</p>}</div><footer className="dialog-footer"><button type="button" className="button secondary" disabled={Boolean(busy)} onClick={close}>Cancel</button><button className="button primary" disabled={Boolean(busy)}>Save evidence<Check size={16} /></button></footer></form></Dialog>}

    {modal?.kind === 'policy' && <Dialog title={modal.parent ? 'Branch or merge a strategy' : 'New strategy'} subtitle="Record the change you want to test." close={close}><form onSubmit={e => submitForm(e, 'policy')}><div className="form-body">{modal.parent && <div className="parent-summary"><GitBranch size={16} />From {modal.parent.name} · v{modal.parent.version}</div>}<label>Strategy name<input name="name" defaultValue={modal.parent ? `${modal.parent.name} — refinement` : ''} required minLength={2} maxLength={100} /></label><label>Change hypothesis<textarea name="hypothesis" defaultValue={modal.parent?.hypothesis} required minLength={10} rows={3} placeholder="What will change, and why might it improve the submission?" /></label><label>Opening emphasis<select name="framing" defaultValue={modal.parent?.config.framing || 'evidence'}>{Object.entries(framingNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><div className="form-grid"><label>Evidence passages<input name="limit" type="number" min={1} max={6} defaultValue={modal.parent?.config.evidence_limit || 3} required /></label><label>Timed milestones<input name="depth" type="number" min={0} max={3} defaultValue={modal.parent?.config.plan_depth ?? 1} required /></label></div><label className="checkbox"><input name="alternative" type="checkbox" defaultChecked={modal.parent?.config.compare_alternative} /><span>Include a hypothesis and alternative comparison</span></label>{modal.parent && <label>Optional second parent<select name="merge"><option value="">Create a branch from one parent</option>{workspace?.policies.filter(p => p.id !== modal.parent!.id).map(p => <option key={p.id} value={p.id}>{p.name} · v{p.version}</option>)}</select></label>}<p className="form-help">The settings above drive the reference draft. When merging, choose the combined settings explicitly; parent histories are preserved.</p>{modalError && <p className="form-error" role="alert">{modalError}</p>}</div><footer className="dialog-footer"><button type="button" className="button secondary" disabled={Boolean(busy)} onClick={close}>Cancel</button><button className="button primary" disabled={Boolean(busy)}>Save strategy version<GitBranch size={16} /></button></footer></form></Dialog>}

    {modal?.kind === 'run' && <Dialog title="New comparison" subtitle="Generate a fresh package per strategy, then test them in matched worlds." close={close}><form onSubmit={e => submitForm(e, 'run')}><div className="form-body"><fieldset><legend>Strategy versions</legend>{workspace?.policies.filter(p => p.author !== 'kimi').map((policy, i) => <label className="checkbox policy-check" key={policy.id}><input type="checkbox" name="policies" value={policy.id} defaultChecked={i < 3} /><span>{policy.name}<small>Version {policy.version} · {framingNames[policy.config.framing]}</small></span></label>)}</fieldset><div className="form-grid"><label>Hidden worlds<input name="worlds" type="number" min={1} max={30} defaultValue={12} required /></label><label>Environment seed<input name="seed" type="number" min={0} max={2147483647} defaultValue={17} required /></label></div><label>Simulated submission delay (days)<input name="delay" type="number" min={0} max={365} defaultValue={0} required /></label><div className="method-note compact"><Beaker size={17} /><p>Rules-based reference experiment. No model calls or external applications. Each strategy faces its own copy of the same rival pool.</p></div>{modalError && <p className="form-error" role="alert">{modalError}</p>}</div><footer className="dialog-footer"><button type="button" className="button secondary" disabled={Boolean(busy)} onClick={close}>Cancel</button><button className="button primary" disabled={Boolean(busy)}>{busy ? 'Running…' : 'Run comparison'}<FlaskConical size={16} /></button></footer></form></Dialog>}

    {modal?.kind === 'draft' && <Dialog title={policyName(modal.package.policy_id)} subtitle={`${modal.package.human_edited ? 'Human-edited version' : modal.package.generator === 'kimi-writer-v1' ? 'Kimi draft' : 'Reference template draft'} · ${modal.package.body.split(/\s+/).length} words · ${modal.package.evidence_snapshot.length} attached evidence items`} close={close} wide><div className="draft-layout"><label className="draft-editor">Submission text<textarea value={draftBody} onChange={e => setDraftBody(e.target.value)} rows={20} /></label><aside className="draft-sources"><h3>Attached evidence</h3>{modal.package.evidence_snapshot.map((item, i) => <div key={item.id}><span className="citation-number">{i + 1}</span><strong>{item.title}</strong><p>{item.source || 'User supplied'}</p></div>)}<p className="form-help">Saving creates a new version. The original package and its prior evaluations remain unchanged.</p><details><summary>Snapshot identifiers</summary><p className="hash">Context {modal.package.context_hash.slice(0,16)}<br />Package {modal.package.content_hash.slice(0,16)}</p></details></aside></div>{modalError && <p className="form-error padded" role="alert">{modalError}</p>}<footer className="dialog-footer"><button className="button secondary" disabled={Boolean(busy) || draftBody === modal.package.body || draftBody.trim().length < 30} onClick={() => action('save-draft', async () => { const updated = await post<Package>(`/projects/${projectId}/packages/${modal.package.id}/revisions`, { body: draftBody }); await refresh(); open({ kind: 'draft', package: updated }); setNotice('New document version saved.'); })}><Copy size={15} />Save new version</button><button className="button primary" disabled={Boolean(busy) || draftBody !== modal.package.body} onClick={() => evaluatePackage(modal.package)}>Evaluate saved version<FlaskConical size={16} /></button></footer></Dialog>}

    {selectedTrial && <Dialog title={`World ${selectedTrial.evaluation.world.index + 1} · ${policyName(selectedTrial.policy_id)}`} subtitle="Two views of the same recorded decision." close={close} wide><div className="inspector-tabs" role="tablist" aria-label="Feedback visibility"><button role="tab" aria-selected={inspectorView === 'learner'} onClick={() => setInspectorView('learner')} className={inspectorView === 'learner' ? 'selected' : ''}><LockKeyhole size={15} />Learner view</button><button role="tab" aria-selected={inspectorView === 'observer'} onClick={() => setInspectorView('observer')} className={inspectorView === 'observer' ? 'selected' : ''}><BookOpen size={15} />Observer view</button></div>
      {inspectorView === 'learner' ? <div className="learner-panel"><div className={`verdict-icon ${selectedTrial.observation.passed ? 'success' : ''}`}>{selectedTrial.observation.passed ? <Check size={32} /> : <X size={32} />}</div><h3>{selectedTrial.observation.passed ? 'Pass' : 'No pass'}</h3><p>This is the only selection feedback available through the learner API.</p><pre>{JSON.stringify(selectedTrial.observation, null, 2)}</pre><div className="sealed-note"><LockKeyhole size={15} />Scores, rival profiles, and selection parameters stay sealed.</div></div> : <div className="observer-panel"><div className="evaluation-summary"><div><span className="muted small">{selectedTrial.evaluation.world.scenario.name}</span><h3>{selectedTrial.evaluation.score.toFixed(1)} <span>/ 100 {selectedTrial.evaluation.evaluator === 'kimi-semantic-v1' ? 'rubric points' : 'reference points'}</span></h3><p>{selectedTrial.evaluation.reason}</p></div><Outcome passed={selectedTrial.observation.passed} /></div><div className="gates">{selectedTrial.evaluation.gates.map(g => <span key={g.name} className={g.passed ? '' : 'gate-failed'}>{g.passed ? <Check size={14} /> : <X size={14} />}{g.name}</span>)}</div><h3 className="subheading">What contributed to the score</h3>{selectedTrial.evaluation.ratings.map(rating => <details className="rating" key={rating.dimension}><summary><span>{selectedTrial.evaluation.evaluator === 'kimi-semantic-v1' ? ({fit:'Institutional fit',evidence:'Evidence',feasibility:'Feasibility',originality:'Distinctiveness',voice:'Voice & specificity'} as Record<string,string>)[rating.dimension] : dimensions[rating.dimension]}</span><div className="rating-track"><span style={{ width: `${rating.score}%` }} /></div><strong>{rating.score}</strong><span className="weight-label">{Math.round(selectedTrial.evaluation.world.scenario.weights[rating.dimension] * 100)}% weight</span><ChevronDown size={14} /></summary><p>{rating.explanation}</p></details>)}<h3 className="subheading">Synthetic comparison pool</h3><div className="rival-list">{[...selectedTrial.evaluation.world.rivals, { name: 'Your package', score: selectedTrial.evaluation.score, features: {} }].sort((a,b) => b.score-a.score).map((rival, i) => <div key={rival.name} className={rival.name === 'Your package' ? 'our-package' : ''}><span>{i + 1}</span><strong>{rival.name}</strong><span>{rival.score.toFixed(1)}</span></div>)}</div><p className="reference-caption">{selectedTrial.evaluation.world.rule === 'threshold' ? 'Threshold selection; rank is informational' : `${selectedTrial.evaluation.effective_places ?? selectedTrial.evaluation.world.places} available places`} · minimum score {selectedTrial.evaluation.world.minimum_score}. Rival feature ratings are sampled assumptions.</p></div>}
      <footer className="dialog-footer"><span className="muted small">Immutable decision · {timeLabel(selectedTrial.created_at)}</span><button className="button secondary" disabled={Boolean(busy)} onClick={() => action('replay', async () => { const result = await post<{ matches: boolean }>(`/projects/${projectId}/trials/${selectedTrial.id}/replay`, {}); setNotice(result.matches ? 'Replay matches the stored decision and its saved assessment.' : 'Replay differs from the stored decision.'); })}><RefreshCw size={15} />Verify replay</button></footer></Dialog>}
  </div>;
}
