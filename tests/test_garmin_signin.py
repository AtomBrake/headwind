"""Garmin sign-in without keeping the password (services/garmin.py _client, routes/garmin.py): syncs use Garmin's tokens only, an older install's
saved password is swapped for tokens and deleted, a sign-in Garmin turns down asks to sign in again, and no page or backup hands secrets back.
Full app, throwaway DB, a fake garminconnect.Garmin."""
import io
import sqlite3
import zipfile

import garminconnect
import pytest
from flask import Flask

import app as app_module
import config
import database
from services import credentials, garmin, tasks


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


class FakeGarmin:
    """Stands in for garminconnect.Garmin: records how it was made, and login() succeeds or is turned down."""
    made = []
    turn_down = False

    def __init__(self, email=None, password=None, **kw):
        self.email, self.password = email, password
        FakeGarmin.made.append((email, password))

    def login(self, tokenstore=None):
        if FakeGarmin.turn_down:
            raise garminconnect.GarminConnectAuthenticationError('DI token refresh failed: 401')
        return None, None


@pytest.fixture
def app(tmp_path, monkeypatch):
    path = str(tmp_path / 't.db')
    pre = Flask('pre')
    pre.config['DATABASE'] = path
    with pre.app_context():
        database.migrate_db()
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("UPDATE Settings SET garminEmail='tom@example.com', openaiKey='sk-openai-secret', claudeKey='sk-ant-secret', "
                   "mqttPassword='mqtt-secret' WHERE id=1")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        db.commit()
    monkeypatch.setattr(config.Config, 'DATABASE', path)
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.setattr(garmin, 'TOKEN_DIR', tmp_path / 'garmin_tokens')
    monkeypatch.setattr(garminconnect, 'Garmin', FakeGarmin)
    FakeGarmin.made, FakeGarmin.turn_down = [], False
    return app_module.create_app()


@pytest.fixture
def client(app):
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _settings(app):
    with app.app_context():
        return dict(database.get_db().execute('SELECT * FROM Settings WHERE id=1').fetchone())


def _set(app, sql, args=()):
    with app.app_context():
        db = database.get_db()
        db.execute(sql, args)
        db.commit()


def _sign_in():
    garmin.TOKEN_DIR.mkdir(exist_ok=True)
    (garmin.TOKEN_DIR / garmin.TOKEN_FILE).write_text('{}')


def test_connected_means_tokens_or_an_older_installs_password(app):
    assert not garmin.connected(_settings(app))                     # an email alone: signed out
    _sign_in()
    assert garmin.connected(_settings(app))
    garmin.forget_tokens()
    assert not garmin.connected(_settings(app))
    _set(app, "UPDATE Settings SET garminPassword='hunter2'")
    assert garmin.connected(_settings(app))                         # upgraded, not synced yet
    assert not garmin.connected({'garminEmail': None, 'garminPassword': 'hunter2'})


def test_a_sync_signs_in_with_the_tokens_alone(app):
    _sign_in()
    with app.app_context():
        garmin._client()
    assert FakeGarmin.made == [(None, None)]


def test_an_older_installs_password_is_used_once_then_deleted(app):
    _set(app, "UPDATE Settings SET garminPassword='hunter2'")
    with app.app_context():
        garmin._client()
    assert FakeGarmin.made == [('tom@example.com', 'hunter2')]       # so the library can sign in with it if there are no tokens yet
    assert _settings(app)['garminPassword'] is None
    with app.app_context():
        garmin._client()
    assert FakeGarmin.made[-1] == (None, None)


def test_a_sign_in_garmin_turns_down_asks_to_sign_in_again_until_one_works(app):
    _sign_in()
    _set(app, "UPDATE Settings SET garminPassword='hunter2'")       # an older install whose password no longer works (or needs MFA)
    FakeGarmin.turn_down = True
    with app.app_context(), pytest.raises(garmin.SignInNeeded, match='sign in again'):
        garmin._client()
    s = _settings(app)
    assert s['garminSignInNeeded'] and s['garminPassword'] is None
    with app.app_context():
        card = next(j for j in tasks.overview(database.get_db())['jobs'] if j['name'] == 'Garmin sync')
    assert card['state'] == 'failed' and 'sign in again' in card['detail'] and card['action']['label'] == 'Sign in again'

    FakeGarmin.turn_down = False                                    # a passing fault at Garmin: the next run that works clears it
    with app.app_context():
        garmin._client()
    assert _settings(app)['garminSignInNeeded'] is None


def test_connect_keeps_the_email_and_the_tokens_never_the_password(app, client, monkeypatch):
    _set(app, "UPDATE Settings SET garminPassword='old', garminSignInNeeded='2026-10-20T10:00:00+00:00'")
    monkeypatch.setattr(garmin, 'start_login', lambda e, p: {'ok': True})
    assert client.post('/garmin/connect', json={'email': 'tom@example.com', 'password': 'new-pw'}).get_json() == {'ok': True}
    s = _settings(app)
    assert s['garminEmail'] == 'tom@example.com' and s['garminPassword'] is None and s['garminSignInNeeded'] is None


def test_an_account_waiting_on_mfa_is_saved_only_once_the_code_works(app, client, monkeypatch):
    monkeypatch.setattr(garmin, 'start_login', lambda e, p: {'ok': False, 'needs_mfa': True, 'token': 'tok'})
    client.post('/garmin/connect', json={'email': 'new@example.com', 'password': 'pw'})
    assert _settings(app)['garminEmail'] == 'tom@example.com'       # the old account's sign-in still stands
    monkeypatch.setattr(garmin, 'complete_mfa', lambda t, c: {'ok': True, 'email': 'new@example.com'})
    assert client.post('/garmin/connect/mfa', json={'token': 'tok', 'code': '123456'}).get_json() == {'ok': True}
    s = _settings(app)
    assert s['garminEmail'] == 'new@example.com' and s['garminPassword'] is None


def test_sign_out_deletes_the_tokens(app, client):
    _sign_in()
    _set(app, "UPDATE Settings SET garminPassword='hunter2'")
    assert client.post('/garmin/disconnect').get_json() == {'ok': True}
    assert not garmin.signed_in() and garmin.TOKEN_DIR.is_dir()     # the folder is a Docker volume: only the files go
    s = _settings(app)
    assert s['garminPassword'] is None and s['garminEmail'] == 'tom@example.com'
    assert client.post('/garmin/sync').status_code == 400


def test_the_settings_form_never_saves_a_garmin_password_or_email(app, client):
    client.post('/settings/', data={'garminEmail': 'other@example.com', 'garminPassword': 'typed', 'garminSyncMode': 'full'})
    s = _settings(app)
    assert s['garminEmail'] == 'tom@example.com' and s['garminPassword'] is None and s['garminSyncMode'] == 'full'


def test_a_save_without_the_secret_fields_keeps_the_saved_secrets(app, client):
    client.post('/settings/', data={'units': 'metric'})
    s = _settings(app)
    assert (s['openaiKey'], s['claudeKey'], s['mqttPassword']) == ('sk-openai-secret', 'sk-ant-secret', 'mqtt-secret')


def test_the_settings_page_doesnt_carry_the_secrets(app, client):
    _sign_in()
    _set(app, "UPDATE Settings SET garminPassword='hunter2'")
    html = client.get('/settings/').get_data(as_text=True)
    for secret in ('hunter2', 'sk-openai-secret', 'sk-ant-secret', 'mqtt-secret'):
        assert secret not in html
    assert 'Saved: leave blank to keep it' in html and 'Sign out' in html


def test_a_backup_leaves_out_an_older_installs_password(app, client, tmp_path):
    _set(app, "UPDATE Settings SET garminPassword='hunter2'")
    r = client.get('/settings/backup/export')
    assert r.status_code == 200
    out = tmp_path / 'restored.db'
    out.write_bytes(zipfile.ZipFile(io.BytesIO(r.data)).read('headwind.db'))
    email, pw = sqlite3.connect(out).execute('SELECT garminEmail, garminPassword FROM Settings').fetchone()
    assert pw is None and email.startswith('enc:v1:')                # the email stays, encrypted (services/vault.py)
