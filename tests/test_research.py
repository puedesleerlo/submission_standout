import json
import uuid
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.research import METHODS, ExperimentInput, summarize
from backend.service import ConflictError
from tests.fakes import FakeModel
from tests.test_protocol import KEYS, OBSERVER, LEARNER


@pytest.fixture
def lab(tmp_path):
    model = FakeModel()
    app = create_app(tmp_path, KEYS, model=model)
    model.store = app.state.store
    with TestClient(app) as client:
        client.headers.update(OBSERVER)
        exp = client.post('/api/research/demo', json={'request_key': str(uuid.uuid4())}).json()
        yield client, app.state.research, model, exp


def stage(lab, name):
    client, research, model, exp = lab
    job = research.start(exp['id'], {'stage': name, 'request_key': str(uuid.uuid4())}, dispatch=False)
    research.execute(exp['id'], job)
    detail = research.detail(exp['id'])
    assert detail['status']['state'] != 'failed', detail['status']
    return detail


def test_full_protocol_freezes_and_enforces_holdout(lab):
    client, r, model, exp = lab
    eid = exp['id']
    assert client.get('/api/research', headers=LEARNER).status_code == 403
    with pytest.raises(ConflictError):
        r.start(eid, {'stage': 'test', 'request_key': 'too-early-test'}, dispatch=False)
    detail = stage(lab, 'train')
    assert detail['status']['state'] == 'trained'
    planners = [c['inputs'] for c in model.calls if c['role'] == 'research_planner']
    assert len(planners) == 8
    for inputs in planners:
        text = json.dumps(inputs)
        assert 'Forest Observatory' not in text
        assert 'Health Evidence Lab' not in text
        if inputs['condition'] != 'full':
            assert 'PRIVATE_CRITIQUE_SENTINEL' not in text
            assert inputs['training_diagnostics'] == []
        if inputs['condition'] == 'random':
            assert not inputs['selection_feedback'] and not inputs['available_policies']
    assert any(c['training_diagnostics'] for c in planners if c['condition'] == 'full')
    samples = r.records('research_sample', eid)
    for o in [o for o in exp['opportunities'] if o['split'] == 'train']:
        assert len({tuple(d['world']['hash'] for d in s['decisions']) for s in samples if s['opportunity_id'] == o['id']}) == 1
    counts = [sum(s['method'] == m for s in samples) for m in METHODS]
    assert len(set(counts)) == 1
    trained_history = r.history(eid, 'adaptive', exp['seed'])
    detail = stage(lab, 'validation')
    assert detail['status']['state'] == 'frozen'
    freeze = detail['freeze'][0]
    assert set(freeze['policies']) == set(METHODS)
    for next_stage in ['train', 'validation']:
        with pytest.raises(ConflictError):
            r.start(eid, {'stage': next_stage, 'request_key': str(uuid.uuid4())}, dispatch=False)
    detail = stage(lab, 'test')
    assert detail['status']['state'] == 'completed'
    assert r.history(eid, 'adaptive', exp['seed']) == trained_history
    assert len([c for c in model.calls if c['role'] == 'research_planner']) == 8
    assert r.records('research_freeze', eid)[0] == freeze
    assert detail['summary']['complete_opportunities'] == 4
    assert all(m['interval'] is not None for m in detail['summary']['methods'])
    for s in r.records('research_sample', eid):
        if s['stage'] == 'test':
            assert s['policy_id'] == freeze['policies'][s['method']]['id']
    # Studio optimization cannot access these records through its normal project context.
    with r.store.connect() as conn:
        assert not r.store.list(conn, 'policy', eid)
        assert not r.store.list(conn, 'trial', eid)
    token = r.invite(eid)
    headers = {'Authorization': 'Bearer '+token}
    assert client.get('/api/research', headers=headers).status_code == 401
    assert client.get('/api/review', headers=OBSERVER).status_code == 403
    packets = client.get('/api/review', headers=headers).json()['packets']
    assert packets and 'method' not in packets[0] and 'judgment' not in packets[0]
    assert 'PRIVATE_CRITIQUE_SENTINEL' not in json.dumps(packets)
    review = dict(packet_id=packets[0]['packet_id'], clarity=4, specificity=3, credibility=4, feasibility=3, recommend=True, notes='Concrete contribution with adequate factual support.')
    assert client.post('/api/review', json=review, headers=headers).status_code == 200
    assert client.post('/api/review', json=review, headers=headers).status_code == 409
    assert r.detail(eid)['review_count'] == 1
    assert token not in json.dumps(r.export(eid))
    assert r.history(eid, 'adaptive', exp['seed']) == trained_history


def test_shuffle_preserves_marginal_breaks_association(lab):
    _, r, _, exp = lab
    for i in range(10):
        r.add('research_sample', exp['id'], {'stage': 'train', 'method': 'shuffled', 'policy_id': f'p{i}',
              'decisions': [{'passed': i < 5}], 'judgment': {}})
    feedback, diagnostics = r.history(exp['id'], 'shuffled', 17)
    assert sum(row['passed'] for row in feedback) == 5
    assert [row['passed'] for row in feedback] != [i < 5 for i in range(10)]
    assert not diagnostics


def test_failures_not_rewards_and_recovery(lab):
    _, r, model, exp = lab
    model.fail_role = 'judge'
    job = r.start(exp['id'], {'stage': 'train', 'request_key': 'failing-stage'}, dispatch=False)
    assert r.start(exp['id'], {'stage': 'train', 'request_key': 'failing-stage'}, dispatch=False)['id'] == job['id']
    r.execute(exp['id'], job)
    assert r.detail(exp['id'])['status']['state'] == 'failed'
    assert not r.records('research_sample', exp['id'])
    with pytest.raises(ConflictError):
        r.start(exp['id'], {'stage': 'train', 'request_key': 'retry-denied'}, dispatch=False)


def test_split_overlap_rejected():
    with pytest.raises(ValueError, match='family'):
        ExperimentInput(name='Invalid study', request_key='bad-study', assignments=[
            {'project_id': 'a', 'split': 'train', 'family': 'Same'},
            {'project_id': 'b', 'split': 'validation', 'family': 'Same'},
            {'project_id': 'c', 'split': 'test', 'family': 'Other'}])


def test_uncertainty_uses_opportunities_and_paired_deltas():
    exp = {'seed': 4, 'replicates': 2, 'opportunities': [{'id': str(i), 'split': 'test', 'family': str(i)} for i in range(4)]}
    samples = [{'id': f'{m}-{i}-{j}', 'method': m, 'stage': 'test', 'opportunity_id': str(i),
                'decisions': [{'passed': i > 1 if m == 'fixed' else i > 0}]*12}
               for m in METHODS for i in range(4) for j in range(2)]
    stats = summarize(exp, samples, [])
    adaptive = next(m for m in stats['methods'] if m['method'] == 'adaptive')
    assert adaptive['rate'] == .75 and adaptive['delta'] == .25
    assert adaptive['opportunities'] == 4 and stats['clusters'] == 4
    assert adaptive['interval'] is not None
    assert stats['methods'][0]['delta_interval'] == [0, 0]
    # Partial opportunities must not silently favor a faster method.
    partial = summarize(exp, [s for s in samples if s['id'] != 'full-0-0'], [])
    assert partial['complete_opportunities'] == 3


def test_attempt_ceiling_enforced_before_provider_dispatch(lab):
    _, r, model, exp = lab
    from backend.agent_contracts import SelectionDesign
    from backend.llm import ModelError
    job = {'id': 'ceiling-test', 'stage': 'train'}
    for _ in range(exp['budget']['shared_selector_calls']['train']):
        r.add('research_call', exp['id'], {'method': 'shared', 'stage': 'train'})
    with pytest.raises(ModelError, match='allowance'):
        r.call(exp, job, 'shared', 'selector_designer', '', {}, SelectionDesign)
    assert not model.calls


def test_daily_preflight_preserves_unstarted_stage(lab):
    _, r, model, exp = lab
    from backend.llm import ModelError
    original = model.describe
    model.describe = lambda: {**original(), 'max_calls_per_day': 20}
    with pytest.raises(ModelError, match='No calls started'):
        r.start(exp['id'], {'stage': 'train', 'request_key': 'blocked-budget'}, dispatch=False)
    assert r.detail(exp['id'])['status']['state'] == 'created'
    assert not model.calls


def test_related_projects_cannot_cross_splits_or_inflate_clusters(lab):
    client, r, _, _ = lab
    ids=[]
    for i, institution in enumerate(['Shared Institution', 'Shared Institution', 'Validation Group', 'Test Group']):
        p=client.post('/api/projects', json={'name':f'Opportunity {i}', 'institution':institution,
            'posting':f'Research opportunity number {i}. Design a concrete study with reproducible evaluation and a bounded scope.',
            'deadline':'2027-12-01','focus':['research']}).json()
        client.post(f"/api/projects/{p['id']}/evidence", json={'title':'Supported fact', 'body':'Built a reproducible data pipeline for a research project.', 'kind':'Experience'})
        ids.append(p['id'])
    payload={'name':'Grouping test','request_key':'grouping-study','assignments':[
        {'project_id':pid,'split':split,'family':f'Label {i}'} for i,(pid,split) in enumerate(zip(ids,['train','train','validation','test']))]}
    response=client.post('/api/research',json=payload)
    assert response.status_code == 201
    assert response.json()['opportunities'][0]['family'] == response.json()['opportunities'][1]['family']
    payload['request_key']='grouping-bad-study'
    payload['assignments'][1]['split']='test'
    assert client.post('/api/research',json=payload).status_code == 422
