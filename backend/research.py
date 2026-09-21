"""Controlled, isolated prompt-policy experiments. No research records enter studio history."""
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from datetime import date, timedelta
import random
import secrets
from statistics import mean
from typing import Literal

from pydantic import Field, model_validator

from backend.schemas import StrictModel
from backend.agent_contracts import SelectionDesign, Strategy, WrittenPackage, Judgment
from backend.agents import frozen_worlds, decide
from backend.engine import public_context
from backend.prompts import BASE, WRITER, JUDGE, SELECTOR_DESIGNER
from backend.llm import ModelError
from backend.service import ConflictError
from backend.store import digest, record_id, timestamp

METHODS = ['fixed', 'random', 'adaptive', 'full', 'shuffled']
LABELS = dict(zip(METHODS, ['Fixed drafting', 'Random exploration', 'Binary adaptation', 'Full feedback', 'Shuffled feedback']))
FIXED = dict(name='Evidence and bounded delivery', hypothesis='Concrete evidence and feasible commitments support a useful application.',
             instructions='Identify the institutional problem. Choose relevant supported facts. Explain a bounded contribution and a feasible delivery plan. Write direct, specific prose, avoiding boilerplate. Never invent qualifications or commitments.',
             tradeoff='Prefer a defensible scope over ambitious unsupported promises.', reflection='Predeclared fixed baseline; no outcome feedback.', parents=[], evidence_ids=[])
RESEARCH_PLANNER = BASE + '''
Return two reusable writing policies, not finished documents. They must transfer to NEW opportunities.
Do not embed institution names, individual credentials, posting text, or evidence IDs in instructions.
Use the supplied training opportunities and feedback only. Treat outcomes as uncertain observations.
Specify emphasis, evidence selection logic, structure, feasible offer, tradeoff and natural voice.
parents may reference only available_policies; evidence_ids must be empty (writers select from each dossier).
For random exploration propose independent policies with no parents; do not infer unavailable outcomes.
For binary feedback, causes, scores and rival identities are unavailable: do not invent them.
For the privileged full-feedback condition you may use supplied training diagnostics.
'''


class Assignment(StrictModel):
    project_id: str
    split: Literal['train', 'validation', 'test']
    family: str = Field(min_length=2, max_length=160)


class TransferPolicy(Strategy):
    evidence_ids: list[str] = Field(default_factory=list, max_length=0)


class TransferBatch(StrictModel):
    strategies: list[TransferPolicy] = Field(min_length=2, max_length=2)


class ExperimentInput(StrictModel):
    name: str = Field(min_length=3, max_length=120)
    assignments: list[Assignment] = Field(min_length=3, max_length=30)
    rounds: int = Field(default=2, ge=2, le=5)
    replicates: int = Field(default=2, ge=2, le=5)
    seed: int = Field(default=17, ge=0, le=2**31-1)
    artifact_type: Literal['Proposal', 'Cover letter', 'Resume', 'Supporting statement'] = 'Proposal'
    request_key: str = Field(min_length=8, max_length=100)

    @model_validator(mode='after')
    def partitions(self):
        if {a.split for a in self.assignments} != {'train', 'validation', 'test'}:
            raise ValueError('Assign at least one opportunity to each split.')
        if len({a.project_id for a in self.assignments}) != len(self.assignments):
            raise ValueError('An opportunity may belong to only one split.')
        families = {}
        for a in self.assignments:
            family = a.family.casefold().strip()
            if family in families and families[family] != a.split:
                raise ValueError('Keep an opportunity family entirely within one split.')
            families[family] = a.split
        return self


class StageInput(StrictModel):
    stage: Literal['train', 'validation', 'test']
    request_key: str = Field(min_length=8, max_length=100)


class HumanReview(StrictModel):
    packet_id: str
    clarity: int = Field(ge=1, le=5)
    specificity: int = Field(ge=1, le=5)
    credibility: int = Field(ge=1, le=5)
    feasibility: int = Field(ge=1, le=5)
    recommend: bool
    notes: str = Field(min_length=10, max_length=3000)


def budget(config, opportunities):
    counts = {s: sum(o['split'] == s for o in opportunities) for s in ['train', 'validation', 'test']}
    r, n = config['rounds'], config['replicates']
    # All arms have identical draft/judge slots and proposal ceilings. Fixed leaves proposal slots unused.
    per = {'train': r + 4*r*n*counts['train'], 'validation': 4*n*counts['validation'], 'test': 2*n*counts['test']}
    return {'per_method_call_ceiling': per, 'shared_selector_calls': counts,
            'total_call_ceiling': sum(per.values())*len(METHODS)+len(opportunities),
            'basis': 'Equal draft and judge slots; equal proposal allowance. Fixed drafting leaves proposal calls unused. Tokens and elapsed time are measured, not equalized.'}


def summarize(exp, samples, reviews):
    rows = [s for s in samples if s['stage'] == 'test']
    by_opp = defaultdict(list)
    for s in rows:
        by_opp[(s['method'], s['opportunity_id'])].append(mean(d['passed'] for d in s['decisions']))
    complete = {o['id']: o for o in exp['opportunities'] if o['split'] == 'test' and all(
        len(by_opp[(m, o['id'])]) == exp['replicates'] for m in METHODS)}
    clusters = defaultdict(list)
    for o in complete.values():
        clusters[o['family']].append(o['id'])
    rng = random.Random(exp['seed'])
    keys = sorted(clusters)
    draws = [rng.choices(keys, k=len(keys)) for _ in range(2000)] if len(keys) >= 3 else []
    result = []
    for method in METHODS:
        values = {oid: mean(by_opp[(method, oid)]) for oid in complete}
        differences = {oid: v-mean(by_opp[('fixed', oid)]) for oid, v in values.items()}
        def interval(data):
            if not draws:
                return None
            estimates = sorted(mean(data[oid] for family in draw for oid in clusters[family]) for draw in draws)
            return [estimates[49], estimates[1949]]
        result.append({'method': method, 'rate': mean(values.values()) if values else None,
                       'interval': interval(values), 'delta': mean(differences.values()) if values else None,
                       'delta_interval': interval(differences), 'opportunities': len(values), 'by_opportunity': values})
    review_by_sample = {r['packet_id']: r for r in reviews}
    human = []
    for method in METHODS:
        scores = defaultdict(list)
        for s in rows:
            if s['method'] == method and s['id'] in review_by_sample:
                r = review_by_sample[s['id']]
                scores[s['opportunity_id']].append(mean(r[k] for k in ['clarity', 'specificity', 'credibility', 'feasibility']))
        human.append({'method': method, 'reviewed': sum(len(v) for v in scores.values()),
                      'score': mean(mean(v) for v in scores.values()) if scores else None})
    return {'methods': result, 'human': human, 'clusters': len(keys), 'complete_opportunities': len(complete),
            'planned_opportunities': sum(o['split'] == 'test' for o in exp['opportunities']),
            'interval_note': '95% paired family-cluster percentile bootstrap; exploratory, no multiplicity adjustment.' if draws else 'Intervals withheld: at least 3 independent test families required. A small pilot is not confirmatory.',
            'unit': 'Opportunity means, clustered by family; worlds and draft replicates are not independent opportunities.'}


class Research:
    def __init__(self, store, model):
        self.store, self.model = store, model
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='standout-research')

    def add(self, kind, eid, payload, identity=None):
        with self.store.connect(write=True) as conn:
            return self.store.add(conn, kind, eid, payload, identity)

    def records(self, kind, eid):
        with self.store.connect() as conn:
            return self.store.list(conn, kind, eid)

    def experiment(self, eid):
        with self.store.connect() as conn:
            return self.store.get(conn, 'experiment', eid)

    def status(self, conn, eid):
        events = self.store.list(conn, 'research_state', eid)
        return events[-1] if events else {'state': 'created', 'message': 'Protocol registered. Ready to train.'}

    def recover(self):
        with self.store.connect(write=True) as conn:
            for exp in self.store.list(conn, 'experiment'):
                if self.status(conn, exp['id'])['state'] == 'running':
                    self.store.add(conn, 'research_state', exp['id'], {'state': 'failed', 'message': 'Interrupted experiment. Partial records are retained; no automatic paid retries.'})

    def create(self, request, demo=False):
        with self.store.connect(write=True) as conn:
            for old in self.store.list(conn, 'experiment'):
                if old['request_key'] == request['request_key']:
                    if old['request_hash'] != digest(request):
                        raise ConflictError('Experiment request key already used with different inputs.')
                    return old
            opportunities, split_guard = [], {}
            if demo:
                domains = [('train', 'Estuary Lab', 'coastal flood records'), ('validation', 'Open Methods Institute', 'reproducible research tools'),
                           ('test', 'Civic Data Centre', 'public transport access'), ('test', 'Health Evidence Lab', 'clinical evidence retrieval'),
                           ('test', 'Forest Observatory', 'forest monitoring uncertainty'), ('test', 'Learning Research Centre', 'classroom assessment validity')]
                for index, (split, institution, topic) in enumerate(domains):
                    project = {'id': f'fixture-{index}', 'name': f'{institution} fellowship', 'institution': institution,
                               'posting': f'Fictional research fellowship: develop a reproducible study of {topic}. Explain the question, evidence, evaluation baseline, limitations and a feasible twelve-week plan. Submit a concise proposal.',
                               'deadline': (date.today()+timedelta(days=90)).isoformat(), 'domain': 'Fellowship', 'focus': [topic, 'reproducibility'],
                               'reservation_conditions': 'No more than twelve weeks; no access to private datasets assumed.', 'synthetic': True}
                    evidence = [{'id': f'fixture-evidence-{index}', 'kind': 'Research', 'status': 'User supplied', 'title': 'Synthetic applicant record',
                                 'body': 'For a university project I implemented a Python data-cleaning pipeline, compared two baselines, and documented errors and reproducibility limitations.', 'source': 'Fictional demonstration dossier'}]
                    opportunities.append(self.snapshot(project, evidence, split, institution.casefold()))
            else:
                for a in request['assignments']:
                    project = self.store.get(conn, 'project', a['project_id'])
                    evidence = self.store.list(conn, 'evidence', a['project_id'])
                    # Family labels cannot bypass identical postings or institution overlap.
                    groups = ['family:'+a['family'].casefold(), 'institution:'+' '.join(project['institution'].casefold().split()), 'posting:'+digest(' '.join(project['posting'].casefold().split()))]
                    for group in groups:
                        if group in split_guard and split_guard[group] != a['split']:
                            raise ValueError('Related institutions, families or identical postings cannot cross splits.')
                        split_guard[group] = a['split']
                    opportunities.append({**self.snapshot(project, evidence, a['split'], a['family'].casefold()), '_groups': groups})
                # Merge dependence groups transitively, even when a user labels two postings
                # from the same institution with different family names within a split.
                parents = {}
                def root(key):
                    parents.setdefault(key, key)
                    while parents[key] != key:
                        key = parents[key]
                    return key
                for o in opportunities:
                    for key in o['_groups'][1:]:
                        parents[root(key)] = root(o['_groups'][0])
                names = {}
                for o in opportunities:
                    key = root(o['_groups'][0])
                    names[key] = min(names.get(key, o['family']), o['family'])
                for o in opportunities:
                    o['family'] = names[root(o.pop('_groups')[0])]
                    o.pop('hash')
                    o['hash'] = digest(o)
            eid = record_id('experiment')
            config = {**request, 'opportunities': opportunities, 'demo': demo, 'methods': METHODS,
                      'provider': self.model.describe(), 'protocol': 'heldout-v1', 'request_hash': digest(request),
                      'budget': budget(request, opportunities), 'prompt_hashes': {k: digest(v) for k, v in
                          {'planner': RESEARCH_PLANNER, 'writer': WRITER, 'judge': JUDGE, 'selector': SELECTOR_DESIGNER}.items()}}
            config['protocol_hash'] = digest(config)
            return self.store.add(conn, 'experiment', eid, config, eid)

    def snapshot(self, project, evidence, split, family):
        facts = [e for e in evidence if e['kind'] not in ('Institution', 'Idea') and e['status'] != 'Hypothesis']
        if not facts:
            raise ValueError(f"Add factual evidence to {project['name']} before registering the experiment.")
        result = {'id': project['id'], 'name': project['name'], 'split': split, 'family': family,
                  'context': public_context(project, evidence), 'evidence': facts,
                  'constraints': project['reservation_conditions'], 'synthetic': project['synthetic']}
        result['hash'] = digest(result)
        return result

    def start(self, eid, request, dispatch=True):
        with self.store.connect(write=True) as conn:
            exp = self.store.get(conn, 'experiment', eid)
            for job in self.store.list(conn, 'research_job', eid):
                if job['request_key'] == request['request_key']:
                    if job['stage'] != request['stage']:
                        raise ConflictError('Request key already used for another stage.')
                    return job
            expected = {'train': 'created', 'validation': 'trained', 'test': 'frozen'}[request['stage']]
            if self.status(conn, eid)['state'] != expected:
                raise ConflictError(f"{request['stage']} requires state {expected}. Stages cannot be repeated or reopened.")
            if not self.model.describe()['configured']:
                raise ModelError('Configure the model before starting a paid experiment.')
            if exp['provider']['model'] != self.model.describe()['model']:
                raise ConflictError('The model changed after registration. Register a new experiment.')
            current = {k: digest(v) for k, v in {'planner': RESEARCH_PLANNER, 'writer': WRITER, 'judge': JUDGE, 'selector': SELECTOR_DESIGNER}.items()}
            if current != exp['prompt_hashes']:
                raise ConflictError('Prompts changed after registration. Register a new experiment.')
            cap = self.model.describe().get('max_calls_per_day')
            required = exp['budget']['per_method_call_ceiling'][request['stage']]*len(METHODS)+exp['budget']['shared_selector_calls'][request['stage']]
            attempted = sum(c['created_at'][:10] == timestamp()[:10] for c in self.store.list(conn, 'model_call'))
            if cap is not None and required > cap-attempted:
                raise ModelError(f'This stage reserves up to {required} calls; {max(0,cap-attempted)} remain in the UTC daily allowance. No calls started. Wait for reset or configure STANDOUT_MAX_MODEL_CALLS and restart the server.')
            job = self.store.add(conn, 'research_job', eid, request)
            self.store.add(conn, 'research_state', eid, {'state': 'running', 'stage': request['stage'], 'job_id': job['id'], 'message': f"Starting {request['stage']}"})
        if dispatch:
            self.executor.submit(self.execute, eid, job)
        return job

    def call(self, exp, job, method, role, system, inputs, contract):
        eid = exp['id']
        # Count attempts before dispatch, including failed attempts. Shared design has its own ceiling.
        with self.store.connect(write=True) as conn:
            prior = [c for c in self.store.list(conn, 'research_call', eid) if c['method'] == method and c['stage'] == job['stage']]
            cap = exp['budget']['shared_selector_calls'][job['stage']] if method == 'shared' else exp['budget']['per_method_call_ceiling'][job['stage']]
            if len(prior) >= cap:
                raise ModelError('Registered call allowance exhausted. No extra calls permitted.')
            ledger = self.store.add(conn, 'research_call', eid, {'method': method, 'stage': job['stage'], 'role': role, 'job_id': job['id']})
        value, call_id = self.model.complete(eid, ledger['id'], role, system, inputs, contract)
        self.add('research_call_link', eid, {'ledger_id': ledger['id'], 'call_id': call_id})
        return value

    def history(self, eid, method, seed):
        # Never read studio, validation, test or human-review history into a planner.
        samples = [s for s in self.records('research_sample', eid) if s['stage'] == 'train' and s['method'] == method]
        feedback = [{'policy_id': s['policy_id'], 'package_id': s['id'], 'passed': d['passed']} for s in samples for d in s['decisions']]
        if method == 'shuffled':
            labels = [r['passed'] for r in feedback]
            random.Random(seed+len(samples)).shuffle(labels)
            feedback = [{**r, 'passed': label} for r, label in zip(feedback, labels)]
        if method in ('random', 'fixed'):
            return [], []
        diagnostics = [{'policy_id': s['policy_id'], 'judgment': s['judgment'],
                        'decisions': [{k: d[k] for k in ['passed', 'score', 'rank', 'reason']} for d in s['decisions']]}
                       for s in samples] if method == 'full' else []
        return feedback, diagnostics

    def execute(self, eid, job):
        exp = self.experiment(eid)
        stage = job['stage']
        try:
            opportunities = [o for o in exp['opportunities'] if o['split'] == stage]
            selectors = {}
            for o in opportunities:
                self.add('research_progress', eid, {'job_id': job['id'], 'message': f"Building matched worlds for {o['name']}"})
                design = self.call(exp, job, 'shared', 'selector_designer', SELECTOR_DESIGNER,
                                   {'public_context': o['context'], 'artifact_type': exp['artifact_type']}, SelectionDesign)
                selectors[o['id']] = self.add('research_selector', eid, {'opportunity_id': o['id'], 'stage': stage, 'design': design,
                    'worlds': frozen_worlds(design, o['context'], seed=exp['seed']+int(o['hash'][:6], 16))})
            if stage == 'train':
                for round_index in range(exp['rounds']):
                    order = METHODS.copy()
                    random.Random(exp['seed']+round_index).shuffle(order)
                    for method in order:
                        policies = self.propose(exp, job, method, round_index, opportunities)
                        self.evaluate(exp, job, method, policies, opportunities, selectors)
                end = 'trained'
            else:
                if stage == 'validation':
                    selections = {m: self.finalists(eid, m) for m in METHODS}
                else:
                    frozen = self.records('research_freeze', eid)[0]
                    selections = {m: [frozen['policies'][m]] for m in METHODS}
                    if frozen['hash'] != digest(frozen['policies']):
                        raise ValueError('Frozen policy hash mismatch.')
                order = METHODS.copy()
                random.Random(exp['seed']+100).shuffle(order)
                for method in order:
                    self.evaluate(exp, job, method, selections[method], opportunities, selectors)
                if stage == 'validation':
                    chosen = {m: self.best(eid, m, 'validation', selections[m])[0] for m in METHODS}
                    self.add('research_freeze', eid, {'policies': chosen, 'hash': digest(chosen), 'protocol_hash': exp['protocol_hash'],
                        'rule': 'Highest validation opportunity-mean pass rate; ties use stable policy ID. No test data consulted.'})
                    end = 'frozen'
                else:
                    end = 'completed'
            self.add('research_state', eid, {'state': end, 'stage': stage, 'job_id': job['id'], 'message': f'{stage.title()} complete.'})
        except Exception as exc:
            error = str(exc) if isinstance(exc, (ModelError, ValueError)) else 'Unexpected experiment failure. Completed stages and call records are preserved.'
            self.add('research_state', eid, {'state': 'failed', 'stage': stage, 'job_id': job['id'], 'message': error})

    def propose(self, exp, job, method, round_index, opportunities):
        eid = exp['id']
        feedback, diagnostics = self.history(eid, method, exp['seed'])
        prior = [p for p in self.records('research_policy', eid) if p['method'] == method]
        visible = [{k: p[k] for k in ['id', 'name', 'hypothesis', 'instructions', 'reflection', 'parents']} for p in prior] if method not in ('random', 'fixed') else []
        if method == 'fixed':
            strategies = [dict(FIXED), dict(FIXED)]
        else:
            inputs = {'condition': 'binary' if method in ('adaptive', 'shuffled') else method, 'training_opportunities': [{k: o[k] for k in ['context', 'evidence', 'constraints']} for o in opportunities],
                      'available_policies': visible, 'selection_feedback': feedback, 'training_diagnostics': diagnostics,
                      'round': round_index, 'artifact_type': exp['artifact_type']}
            inputs['binary_counts'] = [{'policy_id': pid, 'trials': sum(r['policy_id'] == pid for r in feedback),
                                        'passes': sum(r['passed'] for r in feedback if r['policy_id'] == pid)}
                                       for pid in dict.fromkeys(r['policy_id'] for r in feedback)]
            strategies = self.call(exp, job, method, 'research_planner', RESEARCH_PLANNER, inputs, TransferBatch)['strategies']
            allowed = {p['id'] for p in visible}
            if any(s['evidence_ids'] or not set(s['parents']) <= allowed for s in strategies):
                raise ModelError('Research policies must be reusable and reference only authorized parent policies.')
        return [self.add('research_policy', eid, {**s, 'method': method, 'round': round_index, 'hash': digest(s),
                'feedback_received': feedback, 'diagnostics_received': diagnostics}) for s in strategies]

    def evaluate(self, exp, job, method, policies, opportunities, selectors):
        for o in opportunities:
            selector = selectors[o['id']]
            for policy in policies:
                for replicate in range(exp['replicates']):
                    self.add('research_progress', exp['id'], {'job_id': job['id'], 'message': f"{LABELS[method]} · {o['name']} · draft {replicate+1}"})
                    written = self.call(exp, job, method, 'writer', WRITER, {'public_context': o['context'], 'artifact_type': exp['artifact_type'],
                        'brief': '', 'reservation_conditions': o['constraints'], 'strategy': {k: policy[k] for k in ['name', 'hypothesis', 'instructions', 'tradeoff']},
                        'applicant_evidence': o['evidence']}, WrittenPackage)
                    if any(not set(c['evidence_ids']) <= {e['id'] for e in o['evidence']} for c in written['claims']):
                        raise ModelError('Generated draft cited evidence outside its frozen dossier.')
                    judgment = self.call(exp, job, method, 'judge', JUDGE, {'public_context': o['context'], 'artifact_type': exp['artifact_type'],
                        'rubric': selector['design']['rubric'], 'submission': written['body'], 'attached_evidence': o['evidence']}, Judgment)
                    self.add('research_sample', exp['id'], {'stage': job['stage'], 'method': method, 'opportunity_id': o['id'], 'replicate': replicate,
                        'policy_id': policy['id'], 'policy_hash': policy['hash'], 'written': written, 'judgment': judgment,
                        'selector_id': selector['id'], 'decisions': [decide(written, judgment, world) for world in selector['worlds']],
                        'generation': 'Fresh stateless provider call; provider determinism not guaranteed.'})

    def best(self, eid, method, stage, policies):
        samples = [s for s in self.records('research_sample', eid) if s['method'] == method and s['stage'] == stage]
        def score(policy):
            by_opp = defaultdict(list)
            for s in samples:
                if s['policy_id'] == policy['id']:
                    by_opp[s['opportunity_id']].append(mean(d['passed'] for d in s['decisions']))
            return mean(mean(v) for v in by_opp.values()) if by_opp else -1
        return sorted(policies, key=lambda p: (-score(p), p['id']))

    def finalists(self, eid, method):
        policies = [p for p in self.records('research_policy', eid) if p['method'] == method]
        return self.best(eid, method, 'train', policies)[:2]

    def detail(self, eid):
        exp = self.experiment(eid)
        samples, reviews = self.records('research_sample', eid), self.records('research_review', eid)
        with self.store.connect() as conn:
            state = self.status(conn, eid)
        ledger = self.records('research_call', eid)
        results = {r['job_id']: r for r in self.records('model_result', eid)}
        usage = []
        for method in ['shared']+METHODS:
            calls = [c for c in ledger if c['method'] == method]
            usage.append({'method': method, 'calls': len(calls), 'tokens': sum(results.get(c['id'], {}).get('usage', {}).get('total_tokens', 0) for c in calls),
                          'elapsed_ms': sum(results.get(c['id'], {}).get('elapsed_ms', 0) for c in calls)})
        return {'experiment': exp, 'status': state, 'progress': self.records('research_progress', eid)[-1:],
                'policies': self.records('research_policy', eid), 'freeze': self.records('research_freeze', eid),
                'sample_count': len(samples), 'review_count': len(reviews), 'usage': usage, 'summary': summarize(exp, samples, reviews)}

    def invite(self, eid):
        with self.store.connect(write=True) as conn:
            self.store.get(conn, 'experiment', eid)
            if self.status(conn, eid)['state'] != 'completed':
                raise ConflictError('Complete testing before opening blinded human review.')
            invitations = self.store.list(conn, 'research_invite', eid)
            if invitations:
                return invitations[0]['token']
            token = secrets.token_urlsafe(32)
            samples = [s['id'] for s in self.store.list(conn, 'research_sample', eid) if s['stage'] == 'test']
            random.Random(secrets.randbits(64)).shuffle(samples)
            self.store.add(conn, 'research_invite', eid, {'token': token, 'packet_ids': samples})
            return token

    def review_context(self, token):
        with self.store.connect() as conn:
            for exp in self.store.list(conn, 'experiment'):
                for invite in self.store.list(conn, 'research_invite', exp['id']):
                    if secrets.compare_digest(invite['token'], token):
                        return exp, invite
        raise PermissionError('Invalid reviewer capability.')

    def packets(self, token):
        exp, invite = self.review_context(token)
        samples = {s['id']: s for s in self.records('research_sample', exp['id'])}
        reviewed = {r['packet_id'] for r in self.records('research_review', exp['id'])}
        opportunities = {o['id']: o for o in exp['opportunities']}
        packets = []
        for index, sid in enumerate(invite['packet_ids']):
            s = samples[sid]
            o = opportunities[s['opportunity_id']]
            packets.append({'packet_id': sid, 'label': f'Document {index+1}', 'body': s['written']['body'],
                            'context': o['context'], 'evidence': o['evidence'], 'reviewed': sid in reviewed})
        return {'packets': packets, 'instructions': 'Rate 1 (weak) to 5 (strong). Assess the submitted text against the posting and evidence. Generating method and model scores are concealed.'}

    def review(self, token, review):
        exp, invite = self.review_context(token)
        if review['packet_id'] not in invite['packet_ids']:
            raise ValueError('Document is outside this review assignment.')
        with self.store.connect(write=True) as conn:
            if any(r['packet_id'] == review['packet_id'] for r in self.store.list(conn, 'research_review', exp['id'])):
                raise ConflictError('This document has already been reviewed. Reviews are immutable.')
            self.store.add(conn, 'research_review', exp['id'], review)
        return {'saved': True}

    def export(self, eid):
        result = self.detail(eid)
        for kind in ['research_job', 'research_call', 'research_call_link', 'research_selector', 'research_sample', 'research_review', 'model_call', 'model_result']:
            result[kind] = self.records(kind, eid)
        return result  # Reviewer capabilities and provider credentials deliberately excluded.
