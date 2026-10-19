"""Logging for fault finding (services/logs.py, services/diagnostics.py): a log file beside the database, an id on every request's lines and its
error page, secrets kept out, background runs tied to their lines, and the diagnostics zip. Full app, throwaway DB."""
import io
import json
import logging
import zipfile

import pytest
from flask import Flask

import app as app_module
import config
import database
from services import credentials, logs, tasks


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def app(tmp_path, monkeypatch):
    path = str(tmp_path / 't.db')
    pre = Flask('pre')
    pre.config['DATABASE'] = path
    with pre.app_context():
        database.migrate_db()
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("UPDATE Settings SET garminEmail='tom@example.com', garminPassword='hunter2', claudeKey='sk-ant-abcdefghijklmnopqrstuvwx', "
                   "heightCm=180, units='imperial', garminLastError='login failed for tom@example.com' WHERE id=1")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        db.commit()
    monkeypatch.delenv('LOG_DIR', raising=False)
    monkeypatch.delenv('LOG_FORMAT', raising=False)
    monkeypatch.setattr(config.Config, 'DATABASE', path)
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    a = app_module.create_app()

    @a.route('/boom')
    def boom():
        raise RuntimeError('kaboom token=abc123')

    @a.route('/api/v1/boom')
    def api_boom():
        raise RuntimeError('kaboom')

    yield a
    logs.setup()                                        # back to stderr only, so later tests don't write into this tmp folder


@pytest.fixture
def client(app):
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _log_text():
    for h in logging.getLogger().handlers:
        h.flush()
    return open(logs.file_path(), encoding='utf-8').read()


def test_the_log_file_sits_beside_the_database(app, tmp_path):
    assert logs.file_path() == str(tmp_path / 'logs' / 'headwind.log')
    assert 'Headwind' in _log_text() and 'starting' in _log_text()


def test_log_dir_off_means_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv('LOG_DIR', 'off')
    logs.setup(str(tmp_path / 'x.db'))
    assert logs.file_path() is None and logs.files() == []
    monkeypatch.delenv('LOG_DIR')
    logs.setup()


def test_every_response_carries_a_request_id_and_actions_are_logged(client):
    r = client.post('/tasks/run/history')
    rid = r.headers['X-Request-Id']
    assert len(rid) == 8
    assert f'[{rid}] headwind.request: POST /tasks/run/history → 302' in _log_text()
    assert client.get('/tasks').headers['X-Request-Id'] != rid


def test_an_unhandled_error_is_logged_with_its_id_and_quoted_on_the_page(client):
    r = client.get('/boom')
    assert r.status_code == 500
    rid = r.headers['X-Request-Id']
    html = r.get_data(as_text=True)
    assert rid in html and 'Download diagnostics' in html and 'kaboom' not in html     # the user gets the id, not the exception
    text = _log_text()
    assert f'[{rid}] headwind.error: Unhandled error in GET /boom (endpoint boom)' in text
    assert 'Traceback' in text and 'RuntimeError: kaboom token=***' in text and 'abc123' not in text


def test_an_api_error_answers_json_with_the_id(client):
    r = client.get('/api/v1/boom')
    assert r.status_code == 500 and r.get_json()['request_id'] == r.headers['X-Request-Id']


def test_not_found_is_still_a_plain_404(client):
    assert client.get('/no-such-page').status_code == 404


def test_secrets_are_blanked_in_log_lines():
    assert logs.redact('garminPassword=hunter2 ok') == 'garminPassword=*** ok'
    assert logs.redact('{"claudeKey": "sk-ant-abcdefghijklmnopqrstu"}') == '{"claudeKey": "***"}'
    assert 'hw_abcdefghijklmnopqrstuv' not in logs.redact('Authorization: Bearer hw_abcdefghijklmnopqrstuv')
    assert logs.redact('GET /data/2.5/onecall?lat=1&appid=deadbeef') == 'GET /data/2.5/onecall?lat=1&appid=***'
    assert logs.redact('used 1200 tokens in 3s') == 'used 1200 tokens in 3s'


def test_the_generated_password_reaches_the_console_but_never_the_file(app):
    console = io.StringIO()
    stream = next(h for h in logging.getLogger().handlers if type(h) is logging.StreamHandler)
    old = stream.setStream(console)
    try:
        logging.getLogger('services.credentials').warning('password: %s', 'S3cretPw', extra={'console_only': True})
    finally:
        stream.setStream(old)
    assert 'S3cretPw' not in _log_text()
    assert 'password: S3cretPw' in console.getvalue()


def test_outbound_calls_are_timed_without_their_query_string(app, monkeypatch):
    monkeypatch.setenv('LOG_LEVEL', 'DEBUG')
    logs.setup(app.config['DATABASE'])
    import requests
    from requests.adapters import HTTPAdapter

    class _Fake(HTTPAdapter):
        def send(self, request, **kw):
            r = requests.Response()
            r.status_code, r.url, r.request = 503, request.url, request
            return r

    s = requests.Session()
    s.mount('https://', _Fake())
    s.get('https://api.open-meteo.com/v1/forecast?latitude=1&apikey=zzz')
    text = _log_text()
    assert 'weather GET api.open-meteo.com/v1/forecast → 503 in' in text and 'zzz' not in text


def test_a_background_run_tags_its_lines_and_the_tasks_page_points_at_them(app, client):
    with app.app_context():
        db = database.get_db()
        row = tasks.start(db, 'friend_sync', 'Friend sync')
        assert logs.current_id() == f't{row}'
        logging.getLogger('routes.friends').warning('friend unreachable')
        tasks.finish(db, row, None, 'Bob: timed out')
        assert logs.current_id() is None
        assert db.execute('SELECT logId FROM TaskLog WHERE id=?', [row]).fetchone()[0] == f't{row}'
    text = _log_text()
    assert f'[t{row}] routes.friends: friend unreachable' in text and f'[t{row}] services.tasks: Friend sync failed: Bob: timed out' in text
    assert f'log lines marked <code>[t{row}]</code>' in client.get('/tasks').get_data(as_text=True)


def test_diagnostics_zip_has_the_logs_and_no_secrets(client):
    r = client.get('/tasks/diagnostics')
    assert r.status_code == 200 and r.mimetype == 'application/zip'
    z = zipfile.ZipFile(io.BytesIO(r.data))
    names = set(z.namelist())
    assert {'about.json', 'settings.json', 'row_counts.json', 'task_log.json', 'logs/headwind.log'} <= names
    blob = b''.join(z.read(n) for n in names).decode()
    for secret in ('hunter2', 'tom@example.com', 'sk-ant-abcdefghijklmnopqrstuvwx'):
        assert secret not in blob
    settings = json.loads(z.read('settings.json'))
    assert settings['garminPassword'] == 'set' and settings['claudeKey'] == 'set' and settings['heightCm'] == 'set'
    assert settings['units'] == 'imperial' and settings['garminLastError'] == 'login failed for <email>'
    assert json.loads(z.read('row_counts.json'))['Rider'] == 1
    assert json.loads(z.read('about.json'))['version']
