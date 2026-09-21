import { useEffect, useRef, useState } from 'react';
import { ArrowRight, BookOpen, Check, ChevronDown, Clock3, Copy, Download, FilePenLine, GitBranch, Layers3, LockKeyhole, Play, RefreshCw } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { api, post } from './api';
import type { AgentJob, Package, StudioData, Workspace } from './types';

export default function Studio({ workspace, onEvidence, onInspect, onRefresh }: {
  workspace:Workspace; onEvidence:()=>void; onInspect:(id:string)=>void; onRefresh:()=>void;
}) {
  const [data,setData]=useState<StudioData|null>(null);
  const [selected,setSelected]=useState(''); const [artifactType,setArtifactType]=useState('Proposal');
  const [brief,setBrief]=useState(''); const [error,setError]=useState(''); const [submitting,setSubmitting]=useState(false);
  const [editing,setEditing]=useState(false); const [body,setBody]=useState(''); const [saving,setSaving]=useState(false);
  const [notice,setNotice]=useState(''); const loaded=useRef(false); const lastStatus=useRef('');
  const mounted=useRef(true);
  const refreshRef=useRef(onRefresh); refreshRef.current=onRefresh;
  const endpoint=`/projects/${workspace.project.id}`;
  async function load() {
    const next=await api<StudioData>(`${endpoint}/studio`);
    if(!mounted.current)return next;
    setData(next);
    setSelected(previous=>next.packages.some(p=>p.id===previous)?previous:next.packages.at(-1)?.id||'');
    if (!loaded.current) {
      loaded.current=true;
      if(next.jobs[0]) {setArtifactType(next.jobs[0].artifact_type);setBrief(next.jobs[0].brief);}
    }
    const status=next.jobs[0] ? `${next.jobs[0].id}:${next.jobs[0].status}` : '';
    if(status!==lastStatus.current && next.jobs[0]?.status==='completed') refreshRef.current();
    lastStatus.current=status;
    return next;
  }
  useEffect(()=>{
    let active=true; let timer:ReturnType<typeof setTimeout>; mounted.current=true;
    const poll=async()=>{try{if(!active)return;const next=await load();if(active)timer=setTimeout(poll,next.jobs.some(j=>['queued','running'].includes(j.status))?1800:6500);}catch(e){if(active){setError((e as Error).message);timer=setTimeout(poll,6500);}}};
    void poll();return()=>{active=false;mounted.current=false;clearTimeout(timer);};
  },[workspace.project.id]);
  const latest=data?.jobs[0]; const active=Boolean(latest&&['queued','running'].includes(latest.status));
  const packages=data?.packages||[]; const draft=packages.find(p=>p.id===selected)||packages.at(-1);
  const strategy=data?.policies.find(p=>p.id===draft?.policy_id);
  const assessment=data?.assessments.filter(a=>a.package_id===draft?.id).at(-1);
  const selectedRun=data?.runs.filter(r=>r.package_ids.includes(draft?.id||'')).at(-1);
  const selector=data?.selection_models.find(m=>m.id===selectedRun?.selection_model_id)||data?.selection_models.at(-1);
  const matchingModel=data?.selection_models.some(m=>m.context_hash===workspace.context_hash&&m.artifact_type===artifactType);
  const facts=workspace.evidence.filter(e=>!['Institution','Idea'].includes(e.kind)&&e.status!=='Hypothesis');
  const ready=Boolean(data?.provider.configured&&facts.length&&!active&&!submitting);
  async function start(mode:'develop'|'iterate'|'evaluate', item?:Package) {
    setSubmitting(true);setError('');setNotice('');
    try {
      await post<AgentJob>(`${endpoint}/agent-jobs`,{mode,artifact_type:item?.artifact_type||artifactType,brief,request_key:crypto.randomUUID(),package_id:item?.id||null});
      await load();
    } catch(e){setError((e as Error).message);}finally{setSubmitting(false);}
  }
  async function save() {
    if(!draft)return;setSaving(true);setError('');
    try {const revised=await post<Package>(`${endpoint}/packages/${draft.id}/revisions`,{body});await load();setSelected(revised.id);setEditing(false);refreshRef.current();setNotice('New draft version saved. Evaluate it to get fresh feedback.');}
    catch(e){setError((e as Error).message);}finally{setSaving(false);}
  }
  async function copy() {
    if(!draft)return;try{await navigator.clipboard.writeText(draft.body);setNotice('Draft copied.');}catch{setError('Clipboard unavailable. Use Download instead.');}
  }
  function download() {
    if(!draft)return;const url=URL.createObjectURL(new Blob([draft.body],{type:'text/markdown'}));const a=document.createElement('a');a.href=url;a.download=`submission-${draft.id}.md`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  return <div className="studio">
    <section className="studio-brief" aria-label="Submission brief">
      <div className="studio-brief-heading"><span className="studio-eyebrow">YOUR NEXT SUBMISSION</span><span className="studio-model"><span className={data?.provider.configured?'available':''}/>{data?.provider.configured?'Kimi K3':'Kimi not configured'}</span></div>
      <h2>Turn your evidence into a compelling submission.</h2>
      <div className="studio-inputs"><label>What are we writing?<select value={artifactType} onChange={e=>setArtifactType(e.target.value)} disabled={active||submitting}>{['Proposal','Cover letter','Resume','Supporting statement'].map(s=><option key={s}>{s}</option>)}</select></label><label>Direction for this round<textarea value={brief} onChange={e=>setBrief(e.target.value)} disabled={active||submitting} rows={2} placeholder="What should this submission achieve? Add your preferred voice, length, or an approach you want to explore." maxLength={3000}/></label></div>
      <div className="studio-start"><div><button className="button primary" disabled={!ready} onClick={()=>start(matchingModel?'iterate':'develop')}><Play size={15}/>{submitting?'Starting…':active?'Round in progress':matchingModel?'Explore next round':'Develop submission'}</button>{matchingModel&&<button className="text-button" disabled={!ready} onClick={()=>start('develop')}>Rebuild judging assumptions</button>}</div><p>Two strategies. Two drafts. {matchingModel?'Up to 5':'Up to 6'} Kimi calls.<br/>The next round learns only from pass/fail outcomes.</p></div>
      {!facts.length&&<div className="studio-needs-evidence"><Layers3 size={18}/><div><strong>Give the writer something concrete to work with.</strong><p>Add your resume, experience, or research. Institutional context helps, too.</p></div><button className="button secondary" onClick={onEvidence}>Add evidence<ArrowRight size={15}/></button></div>}
    </section>
    {error&&<p role="alert" className="form-error studio-message">{error}</p>}
    {notice&&<p role="status" className="studio-notice"><Check size={16}/>{notice}</p>}
    {latest&&<section className={`agent-progress ${latest.status}`} aria-label="Agent round progress"><div className="agent-progress-top"><span>{active?<span className="spinner"/>:latest.status==='completed'?<Check size={18}/>:<Clock3 size={18}/>}</span><div><strong>{latest.stage}</strong><p>{latest.status==='completed'?'Drafts and experiment records are saved.':latest.status==='failed'?latest.error:'You can leave this page. Completed steps are saved as the agents work.'}</p></div>{latest.run_id&&<button className="text-button" onClick={()=>onInspect(latest.run_id!)}>Inspect round<ArrowRight size={15}/></button>}</div><details><summary>{latest.steps.length} recorded stages<ChevronDown size={14}/></summary><ol>{latest.steps.map(step=><li key={step.id}><span>{new Date(step.created_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</span>{step.stage}</li>)}</ol></details></section>}
    {!draft?<div className="studio-empty"><FilePenLine size={34}/><h3>Your submission will take shape here.</h3><p>The agents read your posting, choose evidence, write competing approaches, and test them against plausible selection scenarios.</p><div><span>01 · Understand the opportunity</span><span>02 · Write and compare</span><span>03 · Explore a better approach</span></div></div>:<>
      <div className="studio-results-heading"><div><h2>Your drafts</h2><p>Inspect the writing and the strategy that produced it.</p></div><label className="draft-choice">Saved version<select aria-label="Choose saved draft" value={draft.id} disabled={editing} onChange={e=>{setSelected(e.target.value);setNotice('');}}>{[...packages].reverse().map(p=><option key={p.id} value={p.id}>{data?.policies.find(s=>s.id===p.policy_id)?.name||p.title}{p.human_edited?' · edited':''} · {new Date(p.created_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</option>)}</select></label></div>
      <div className="studio-workspace"><article className="submission-paper"><div className="paper-toolbar"><span>{draft.artifact_type} · {draft.body.split(/\s+/).length} words</span><div><button className="icon-button" aria-label="Copy draft" onClick={copy}><Copy size={16}/></button><button className="icon-button" aria-label="Download draft" onClick={download}><Download size={16}/></button><button className="button secondary" disabled={saving} onClick={()=>{if(editing){setEditing(false);}else{setBody(draft.body);setEditing(true);}}}><FilePenLine size={14}/>{editing?'Cancel edit':'Edit draft'}</button></div></div>
        {editing?<div className="studio-editor"><label>Submission text<textarea value={body} onChange={e=>setBody(e.target.value)} rows={25}/></label><button className="button primary" disabled={saving||body.trim().length<100||body===draft.body} onClick={save}>{saving?'Saving…':'Save new version'}<Check size={15}/></button></div>:<div className="artifact-body"><ReactMarkdown components={{img:()=>null}}>{draft.body}</ReactMarkdown></div>}
        <div className="paper-footer"><span>{draft.human_edited?'Edited by you':'Written by Kimi K3'} · backed by {draft.evidence_snapshot.length} evidence items</span><button className="text-button" disabled={!ready||editing} onClick={()=>start('evaluate',draft)}>Evaluate this version<ArrowRight size={14}/></button></div>
      </article><aside className="strategy-notebook">
        {strategy&&<section><div className="notebook-label"><GitBranch size={16}/>The approach · v{strategy.version}</div><h3>{strategy.name}</h3><p>{strategy.hypothesis}</p><details open><summary>Why this strategy<ChevronDown size={13}/></summary><p>{strategy.reflection}</p></details><details><summary>Writing instructions<ChevronDown size={13}/></summary><p className="preserve-lines">{strategy.instructions}</p></details><details><summary>The tradeoff<ChevronDown size={13}/></summary><p>{strategy.tradeoff}</p></details>{Boolean(strategy.parents.length)&&<p className="notebook-parents">{strategy.operation==='merge'?'Merged from':'Branched from'} {strategy.parents.map(id=>data?.policies.find(p=>p.id===id)?.name||id).join(' + ')}</p>}
          <div className="binary-history"><LockKeyhole size={15}/><div><strong>{strategy.learning_observation?.length||0} previous binary observations</strong><p>{strategy.learning_observation?.length?`${strategy.learning_observation.filter(o=>o.passed).length} passes; ${strategy.learning_observation.filter(o=>!o.passed).length} non-passes. No scores or critiques were provided to the strategist.`:'An initial exploration, before any selection feedback.'}</p></div></div><details><summary>Exact feedback supplied<ChevronDown size={13}/></summary><pre className="feedback-json">{JSON.stringify(strategy.learning_observation||[],null,2)}</pre><p>The rationale above is the agent's hypothesis; these records contain the observed outcomes.</p></details>
        </section>}
        {assessment?<section className="observer-notes"><div className="notebook-label"><BookOpen size={16}/>Your private assessment</div><h3>What stands out</h3><ul>{assessment.strengths.map(s=><li key={s}>{s}</li>)}</ul><h3>What needs work</h3><ul>{assessment.weaknesses.map(s=><li key={s}>{s}</li>)}</ul><details><summary>Voice and claim checks<ChevronDown size={13}/></summary><p>{assessment.integrity_reason}</p>{assessment.style_flags.length?<ul>{assessment.style_flags.map(s=><li key={s}>{s}</li>)}</ul>:<p>No specific style flags were returned in this assessment.</p>}</details>{selectedRun&&<button className="button secondary full" onClick={()=>onInspect(selectedRun.id)}>See selection outcomes<ArrowRight size={14}/></button>}<p className="notebook-footnote">These notes are for you. The strategy agent receives only pass/fail outcomes.</p></section>:<section><p>{active?'Assessment will appear when the judge finishes.':'This version has not been assessed yet.'}</p></section>}
        {!!draft.missing_information?.length&&<section className="missing-notes"><h3>Information that would help</h3><ul>{draft.missing_information.map(s=><li key={s}>{s}</li>)}</ul><button className="text-button" onClick={onEvidence}>Add supporting evidence<ArrowRight size={14}/></button></section>}
      </aside></div>
      {selector&&<section className="studio-selection"><div className="section-title"><div><h2>How selection is being modeled</h2><p className="muted">Inferred from your supplied posting and context. No web research has been performed.</p></div><span className="badge warm">Assumptions to test</span></div><p>{selector.institutional_interests}</p><div className="scenario-grid">{selector.scenarios.map(s=><details key={s.id}><summary><strong>{s.name}</strong><span>{Math.round(s.probability*100)}%</span></summary><p>{s.rationale}</p><span className="badge">{s.rule.replace('_',' ')}</span></details>)}</div><details className="model-details"><summary>Personalized rubric and uncertainty<ChevronDown size={14}/></summary>{selector.rubric.map(r=><div key={r.dimension}><h3>{r.name}</h3><p>{r.question}</p><p><strong>Strong:</strong> {r.strong}</p><p><strong>Weak:</strong> {r.weak}</p></div>)}<h3>Still unknown</h3><ul>{selector.uncertainties.map(u=><li key={u}>{u}</li>)}</ul><p className="muted">Source basis: {selector.source_basis.join(' · ')}</p></details><p className="reference-caption">Kimi judges quality; code applies the frozen selection rules. Reused practice scenarios help compare revisions, but do not establish real acceptance odds or improvement on unseen opportunities.</p></section>}
    </>}
  </div>;
}
