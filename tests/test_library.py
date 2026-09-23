from fastapi.testclient import TestClient

from backend.app import create_app
from backend.engine import sample_worlds, select
from backend.agents import decide
from tests.test_protocol import KEYS, OBSERVER, LEARNER


def entry(**changes):
    return {"key": "example.risk-models", "bank": "Fact", "title": "Production risk models",
            "body": "The applicant reports building a portfolio of production models.",
            "sources": [{"reference": "/private/resume.docx", "accessed_on": "2026-09-21"}], **changes}


def test_bank_revision_idempotency_atomicity_and_private_boundary(tmp_path):
    with TestClient(create_app(tmp_path, KEYS)) as c:
        c.headers.update(OBSERVER)
        def save(value): return c.post('/api/library', json={"entries": [value]})
        first = save(entry()).json()['entries'][0]
        assert save(entry()).json()['entries'][0] == first
        second = save(entry(body="Changed source text with a new result to preserve.")).json()['entries'][0]
        assert second['revision'] == 2 and second['previous_id'] == first['id']
        assert c.get('/api/library').json()['total'] == 1
        assert c.get('/api/library/' + first['id']).json() == first
        assert c.get('/api/library?query=changed').json()['total'] == 1
        assert c.get('/api/library?bank=Company').json()['total'] == 0
        assert c.get('/api/library?offset=1').json()['entries'] == []
        assert c.get('/api/library?limit=101').status_code == 422
        assert save(entry(sources=[])).status_code == 422
        assert c.post('/api/library', json={'entries': [entry(), entry()]}).status_code == 422
        c.post('/api/session')
        for endpoint in ['/api/library', '/api/library/' + first['id'], '/api/schema']:
            assert c.get(endpoint, headers=LEARNER).status_code == 403
        assert c.post('/api/library', json={'entries': [entry()]}, headers=LEARNER).status_code == 403


def test_snapshot_import_deduplicates_and_revisions_cannot_change_frozen_evidence(tmp_path):
    with TestClient(create_app(tmp_path, KEYS)) as c:
        c.headers.update(OBSERVER)
        pid = c.get('/api/projects').json()[0]['id']
        base = '/api/projects/' + pid
        item = c.post('/api/library', json={'entries': [entry(bank='Company', caveats='Company claim, not an independently measured result.')]}).json()['entries'][0]
        initial_count = len(c.get(base).json()['evidence'])
        assert c.post(base + '/library-import', json={'entry_ids': [item['id'], 'missing']}).status_code == 404
        assert len(c.get(base).json()['evidence']) == initial_count
        selection = {'entry_ids': [item['id'], item['id']]}
        one = c.post(base + '/library-import', json=selection).json()
        assert c.post(base + '/library-import', json=selection).json() == one
        assert one['evidence'][0]['kind'] == 'Institution'
        assert 'Company claim' in one['evidence'][0]['body']
        next_item = c.post('/api/library', json={'entries': [entry(body='Updated interpretation of the same original source.')]}).json()['entries'][0]
        assert c.post(base + '/library-import', json={'entry_ids': [next_item['id']]}).status_code == 409
        assert len(c.get(base).json()['evidence']) == initial_count + 1
        assert c.post(base + '/library-import', json=selection, headers=LEARNER).status_code == 403


def test_unknown_deadline_does_not_invent_a_date_or_apply_rolling_penalty(tmp_path):
    with TestClient(create_app(tmp_path, KEYS)) as c:
        c.headers.update(OBSERVER)
        project = c.post('/api/projects', json={'name': 'Exploratory internship', 'institution': 'Example Company',
            'domain': 'Job', 'posting': 'Inferred brief for an exploratory conversation. No official posting exists.',
            'focus': ['forecasting']}).json()
        assert project['deadline'] is None
        world = sample_worlds(1, 1, project)[0]
        world.update(rule='rolling', places=2, rivals=[])
        judgment = {'ratings': [{'dimension': d, 'score': 90} for d in ['fit', 'evidence', 'feasibility', 'originality', 'voice']],
                    'integrity_passed': True, 'format_passed': True, 'style_flags': []}
        result = decide({"body": "Grounded applicant draft"}, judgment, world)
        assert result['gates'][0]['passed'] is True
        assert result['effective_places'] == 2
