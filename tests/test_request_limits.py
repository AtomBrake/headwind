"""How big a request body can be, by who can send it (limit_body in app.py, the sizes in services/limits.py): checked before the login
check, by Content-Length and, for a body sent chunked, as it's read."""
import io

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
    monkeypatch.setattr('services.limits.MAX_PUBLIC_REQUEST', 1000)
    monkeypatch.setattr('services.limits.MAX_PHONE_REQUEST', 5000)
    monkeypatch.setattr('services.limits.MAX_PAGE_REQUEST', 10_000)
    return app_module.create_app().test_client()


def form(n):
    return {'username': 'x', 'password': 'y' * n}


def test_the_login_form_is_refused_past_the_public_limit(client):
    assert client.post('/login', data=form(2000)).status_code == 413
    assert client.post('/login', data=form(10)).status_code != 413


def test_a_chunked_body_stops_at_the_limit_as_its_read(client):
    """No Content-Length to check up front: the stream itself refuses to go past the limit."""
    def chunked(n):
        return client.post('/login', input_stream=io.BytesIO(b'username=x&password=' + b'y' * n),
                           content_type='application/x-www-form-urlencoded', environ_overrides={'wsgi.input_terminated': True})
    assert chunked(2000).status_code == 413
    assert chunked(10).status_code != 413


def test_a_signed_in_page_is_checked_before_the_login_redirect(client):
    assert client.post('/rides/1/photos', data=b'x' * 20_000, content_type='application/octet-stream').status_code == 413
    assert client.post('/rides/1/photos', data=b'x' * 2000, content_type='application/octet-stream').status_code == 302


def test_the_phone_api_and_the_ride_upload_get_the_phone_limit(client):
    assert client.post('/api/v1/health/days', data=b'x' * 2000, content_type='application/json').status_code == 401
    assert client.post('/api/v1/health/days', data=b'x' * 6000, content_type='application/json').status_code == 413
    assert client.post('/import/api/upload-ride', data=b'x' * 2000, content_type='application/octet-stream').status_code == 401
    assert client.post('/import/api/upload-ride', data=b'x' * 6000, content_type='application/octet-stream').status_code == 413


@pytest.mark.parametrize('path', ['/import/upload', '/settings/backup/import', '/setup/restore'])
def test_the_export_import_and_restores_keep_the_app_wide_limit(client, path):
    assert client.post(path, data=b'x' * 20_000, content_type='application/octet-stream').status_code == 302   # to sign in, not 413


def test_the_telemetry_ping_reads_at_most_4_kb(client, monkeypatch):
    sent = {}

    class Reply:
        content, status_code = b'{}', 200

    def post(url, data=None, **kw):
        sent['body'] = data
        return Reply()
    monkeypatch.setenv('TELEMETRY_FORWARD_URL', 'http://collector.invalid/ping')
    monkeypatch.setattr('routes.telemetry_forward.requests.post', post)
    monkeypatch.setattr('services.limits.MAX_PUBLIC_REQUEST', 100_000)
    assert client.post('/telemetry/ping', data=b'{' + b'x' * 9000, content_type='application/json').status_code == 200
    assert len(sent['body']) == 4096
