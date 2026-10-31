"""Every install sends the anti-framing / nosniff / referrer headers, not only the public demo; HSTS only over HTTPS."""
import pytest

import app as app_module
import config


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.delenv('HEADWIND_DEMO', raising=False)
    app = app_module.create_app()
    return app.test_client()


def _check(resp):
    assert resp.headers['X-Frame-Options'] == 'DENY'
    assert resp.headers['X-Content-Type-Options'] == 'nosniff'
    assert resp.headers['Referrer-Policy'] == 'same-origin'
    assert "frame-ancestors 'none'" in resp.headers['Content-Security-Policy']


def test_headers_outside_demo_mode(client):
    for path in ('/login', '/', '/static/does-not-exist.css'):
        resp = client.get(path)
        _check(resp)
        assert 'Strict-Transport-Security' not in resp.headers, path


def test_hsts_only_over_https(client):
    resp = client.get('/login', base_url='https://localhost')
    _check(resp)
    assert resp.headers['Strict-Transport-Security'].startswith('max-age=')


def test_hsts_via_trusted_proxy(client):
    resp = client.get('/login', headers={'X-Forwarded-Proto': 'https'}, environ_base={'REMOTE_ADDR': '127.0.0.1'})
    assert 'Strict-Transport-Security' in resp.headers
    resp = client.get('/login', headers={'X-Forwarded-Proto': 'https'}, environ_base={'REMOTE_ADDR': '203.0.113.5'})
    assert 'Strict-Transport-Security' not in resp.headers
