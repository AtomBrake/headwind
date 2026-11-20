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


def test_csp_limits_script_sources(client):
    csp = client.get('/login').headers['Content-Security-Policy']
    script_src = next(d for d in csp.split(';') if d.strip().startswith('script-src')).split()[1:]
    assert "'self'" in script_src
    assert not any(s in script_src for s in ('*', 'https:', "'unsafe-eval'", 'https://cdn.jsdelivr.net', 'https://unpkg.com'))


def test_no_page_loads_from_another_site():
    """The libraries are served from static/vendor (scripts/vendor.py): no script or stylesheet from a CDN, and every vendored file a
    template names is there (a version bumped in scripts/vendor.py but not in the templates would 404)."""
    import pathlib
    import re
    root = pathlib.Path(app_module.__file__).parent
    assert not any(s.startswith('http') for s in app_module.SCRIPT_SOURCES)
    named = 0
    for f in (root / 'templates').rglob('*.html'):
        text = f.read_text(encoding='utf-8', errors='replace')
        assert not re.findall(r'<(?:script|link)[^>]*\b(?:src|href)=["\']https?://', text), f.name
        for path in re.findall(r"url_for\('static', filename='(vendor/[^']+)'\)", text):
            named += 1
            assert (root / 'static' / path).is_file(), f'{f.name}: static/{path} is missing'
    assert named
