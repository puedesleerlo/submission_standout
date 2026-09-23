import asyncio
import json

import httpx
import pytest

from backend import mcp_server


def test_mcp_discovers_typed_tools_and_marks_paid_jobs():
    tools = {t.name: t for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert len(tools) == 9
    assert tools['standout_search_bank'].annotations.readOnlyHint
    assert tools['standout_save_bank'].annotations.idempotentHint
    assert tools['standout_start_job'].annotations.openWorldHint
    schema = tools['standout_save_bank'].inputSchema
    assert 'batch' in schema['properties'] and 'BankEntry' in schema['$defs']


def test_bridge_checks_identity_before_sending_credentials(monkeypatch, tmp_path):
    (tmp_path / 'access.json').write_text(json.dumps({'observer': 'private-test-key'}))
    monkeypatch.setenv('STANDOUT_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('STANDOUT_API_URL', 'http://127.0.0.1:9999')
    seen = []
    identified = False
    def handler(req):
        seen.append(req)
        if req.url.path == '/api/health':
            assert 'authorization' not in req.headers
            return httpx.Response(200, json={'application': 'submission-standout' if identified else 'other-app'})
        assert req.headers['authorization'] == 'Bearer private-test-key'
        return httpx.Response(200, json={'total': 0, 'entries': []})
    client = httpx.Client
    monkeypatch.setattr(mcp_server.httpx, 'Client', lambda **kw: client(**kw, transport=httpx.MockTransport(handler)))
    with pytest.raises(ValueError, match='not Submission Standout'):
        mcp_server.request('GET', '/api/library')
    assert len(seen) == 1
    identified = True
    assert mcp_server.request('GET', '/api/library')['total'] == 0
    assert len(seen) == 3


@pytest.mark.parametrize('url', ['https://example.com', 'http://127.0.0.1:8000/private', 'http://user@localhost', 'http://localhost?forward=1'])
def test_bridge_rejects_nonlocal_or_ambiguous_origins(monkeypatch, url):
    monkeypatch.setenv('STANDOUT_API_URL', url)
    with pytest.raises(ValueError, match='loopback'):
        mcp_server.request('GET', '/api/model')


def test_project_paths_cannot_escape_route():
    with pytest.raises(ValueError):
        mcp_server.project_path('project_foo/../../session')
