"""Secrets out of the database file (services/vault.py): the keys, passwords and tokens saved in Settings and Friend are encrypted with a key
kept beside the database, so the file and its backups don't give them away. Plain values from before are encrypted at the next start, and a
database without its key (a backup restored on another server) starts, treats them as missing and says which to enter again.
Full app, throwaway databases, no network."""
import io
import os
import shutil
import sqlite3
import stat
import zipfile

import pytest
from flask import Flask

import app as app_module
import config
import database
from services import credentials, vault

OLD = {'openaiKey': 'sk-openai-plain-old', 'claudeKey': 'sk-ant-plain-old', 'haToken': 'ha-plain-old-token',
       'mqttPassword': 'mqtt-plain-old', 'garminEmail': 'old-garmin@example.com', 'garminPassword': 'garmin-plain-old'}
FRIEND_TOKEN = 'friend-plain-old-token'


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def _old_database(path):
    """A database as an install from before left it: every secret as typed."""
    pre = Flask('pre')
    pre.config['DATABASE'] = path
    with pre.app_context():
        database.migrate_db()
        db = database.get_db()
        db.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
        db.execute(f"UPDATE Settings SET {', '.join(f'{k}=?' for k in OLD)}, mqttHost='broker.lan', mqttUser='u' WHERE id=1", list(OLD.values()))
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        db.execute("INSERT INTO Friend (id, name, url, token) VALUES (1, 'Sam', 'https://sam.example', ?)", [FRIEND_TOKEN])
        db.execute("INSERT INTO Friend (id, name, url) VALUES (2, 'Lee', 'https://lee.example')")   # a row after Sam's: his moves when it grows
        db.commit()
        database.close_db()                 # checkpoints the WAL, so the file holds it all (a backup zips the file alone)


def _make_app(path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', path)
    return app_module.create_app()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.setenv('AVATAR_DIR', str(tmp_path / 'avatars'))
    path = str(tmp_path / 'a' / 't.db')
    os.makedirs(os.path.dirname(path))
    _old_database(path)
    return path, _make_app(path, monkeypatch)


def _client(app):
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _file_bytes(path):
    return b''.join(open(p, 'rb').read() for p in (path, path + '-wal') if os.path.exists(p))


def _read(app, sql):
    with app.app_context():
        return database.get_db().execute(sql).fetchone()


def _forget_keys():
    vault._keys.clear()


def test_old_plain_secrets_are_encrypted_at_start_and_gone_from_the_file(setup):
    path, app = setup
    data = _file_bytes(path)
    for secret in [*OLD.values(), FRIEND_TOKEN]:
        assert secret.encode() not in data
    raw = sqlite3.connect(path).execute(f"SELECT {', '.join(OLD)} FROM Settings").fetchone()
    assert all(v.startswith(vault.PREFIX) for v in raw)
    assert sqlite3.connect(path).execute('SELECT token FROM Friend').fetchone()[0].startswith(vault.PREFIX)
    # read through the app, as before
    s = _read(app, 'SELECT * FROM Settings WHERE id=1')
    assert {k: s[k] for k in OLD} == OLD
    assert _read(app, 'SELECT f.token FROM Friend f')['token'] == FRIEND_TOKEN
    assert _read(app, 'SELECT haToken AS v FROM Settings')['v'].startswith(vault.PREFIX)   # another name: as stored


def test_the_key_is_private_beside_the_database_and_a_second_start_changes_nothing(setup, monkeypatch):
    path, app = setup
    key = os.path.join(os.path.dirname(path), '.secrets_key')
    assert stat.S_IMODE(os.stat(key).st_mode) == 0o600
    before = sqlite3.connect(path).execute('SELECT openaiKey FROM Settings').fetchone()
    with app.app_context():
        assert vault.seal_plain(database.get_db()) == 0
    assert sqlite3.connect(path).execute('SELECT openaiKey FROM Settings').fetchone() == before


def test_each_secret_saved_is_stored_encrypted(setup):
    path, app = setup
    c = _client(app)
    new = {'openaiKey': 'sk-openai-typed-new', 'claudeKey': 'sk-ant-typed-new', 'mqttPassword': 'mqtt-typed-new'}
    assert c.post('/settings/', data={**new, 'mqttHost': 'broker.lan', 'mqttUser': 'u'}).status_code == 302
    assert c.post('/settings/home-assistant/save', json={'url': 'http://ha.lan:8123', 'token': 'ha-typed-new'}).get_json() == {'ok': True}
    c.post('/friends/add', data={'name': 'Kim', 'url': 'https://kim.example', 'token': 'kim-typed-token'})
    c.post('/friends/1/token', data={'token': 'sam-typed-new-token'})
    from routes.garmin import _signed_in_as
    with app.test_request_context():
        _signed_in_as('new-garmin@example.com')
    typed = [*new.values(), 'ha-typed-new', 'kim-typed-token', 'sam-typed-new-token', 'new-garmin@example.com']
    data = _file_bytes(path)
    for secret in typed:
        assert secret.encode() not in data
    s = _read(app, 'SELECT * FROM Settings WHERE id=1')
    assert (s['openaiKey'], s['claudeKey'], s['mqttPassword'], s['haToken'], s['garminEmail']) == (*new.values(), 'ha-typed-new', 'new-garmin@example.com')
    with app.app_context():
        tokens = dict(database.get_db().execute('SELECT name, token FROM Friend').fetchall())
    assert tokens == {'Sam': 'sam-typed-new-token', 'Lee': None, 'Kim': 'kim-typed-token'}
    # a save that leaves the key fields blank keeps them, still encrypted
    c.post('/settings/', data={'units': 'metric'})
    assert _read(app, 'SELECT openaiKey FROM Settings')['openaiKey'] == 'sk-openai-typed-new'
    assert b'sk-openai-typed-new' not in _file_bytes(path)


def test_without_its_key_the_database_starts_and_asks_for_the_secrets_again(setup, monkeypatch):
    path, app = setup
    os.remove(os.path.join(os.path.dirname(path), '.secrets_key'))
    _forget_keys()
    app = _make_app(path, monkeypatch)
    c = _client(app)
    s = _read(app, 'SELECT * FROM Settings WHERE id=1')
    assert all(s[k] is None for k in OLD)
    html = c.get('/settings/').get_data(as_text=True)
    assert 'Saved: leave blank to keep it' not in html                  # every key field asks for one
    assert 'saved — leave blank to keep' not in c.get('/settings/home-assistant/').get_data(as_text=True)
    with app.test_request_context():
        lost = vault.unreadable(database.get_db())
    assert lost == ['the OpenAI API key (Settings → AI)', 'the Claude API key (Settings → AI)',
                    'the Home Assistant token (Home Assistant page)', 'the MQTT password (Settings → MQTT)',
                    'the Garmin sign-in (Settings → Garmin Connect)', "Sam's feed token (Friends)"]
    # entering one again works, with the new key
    c.post('/settings/', data={'openaiKey': 'sk-openai-again'})
    assert _read(app, 'SELECT openaiKey FROM Settings')['openaiKey'] == 'sk-openai-again'


def _export(client):
    r = client.get('/settings/backup/export')
    assert r.status_code == 200
    return r.data


def _flashes(client):
    """The messages waiting to be shown, taken (as showing them would)."""
    with client.session_transaction() as s:
        return s.pop('_flashes', [])


def test_a_backup_keeps_them_encrypted_and_restores_on_the_same_server(setup):
    path, app = setup
    c = _client(app)
    zipped = _export(c)
    inside = zipfile.ZipFile(io.BytesIO(zipped))
    assert '.secrets_key' not in ' '.join(inside.namelist())
    db = inside.read('headwind.db')
    for secret in [*OLD.values(), FRIEND_TOKEN]:
        assert secret.encode() not in db
    c.post('/settings/', data={'openaiKey': 'sk-changed-after-the-backup'})
    _flashes(c)
    c.post('/settings/backup/import', data={'backup': (io.BytesIO(zipped), 'headwind-backup.zip')}, content_type='multipart/form-data')
    assert [cat for cat, _ in _flashes(c)] == ['success']
    assert _read(app, 'SELECT openaiKey FROM Settings')['openaiKey'] == OLD['openaiKey']


def test_a_backup_restored_on_another_server_says_what_to_enter_again(setup, tmp_path, monkeypatch):
    path, app = setup
    zipped = _export(_client(app))
    other = str(tmp_path / 'b' / 't.db')
    os.makedirs(os.path.dirname(other))
    pre = Flask('fresh')
    pre.config['DATABASE'] = other
    with pre.app_context():
        database.migrate_db()
        database.get_db().execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'New', 1)")
        database.get_db().commit()
        database.close_db()
    app_b = _make_app(other, monkeypatch)
    c = _client(app_b)
    c.post('/settings/backup/import', data={'backup': (io.BytesIO(zipped), 'headwind-backup.zip')}, content_type='multipart/form-data')
    (_, ok), (cat, note) = _flashes(c)
    assert cat == 'error' and 'Enter them again' in note and 'the OpenAI API key' in note and "Sam's feed token" in note
    assert 'the Garmin sign-in' in note and '.secrets_key' in note
    assert _read(app_b, 'SELECT claudeKey FROM Settings')['claudeKey'] is None
    # copying the old server's key across brings them back
    shutil.copy(os.path.join(os.path.dirname(path), '.secrets_key'), os.path.join(os.path.dirname(other), '.secrets_key'))
    _forget_keys()
    assert _read(app_b, 'SELECT claudeKey FROM Settings')['claudeKey'] == OLD['claudeKey']


def test_a_backup_from_before_encryption_is_encrypted_when_restored(setup, tmp_path):
    path, app = setup
    old = str(tmp_path / 'old' / 'headwind.db')
    os.makedirs(os.path.dirname(old))
    _old_database(old)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.write(old, 'headwind.db')
    c = _client(app)
    c.post('/settings/backup/import', data={'backup': (io.BytesIO(buf.getvalue()), 'headwind-backup.zip')}, content_type='multipart/form-data')
    assert [cat for cat, _ in _flashes(c)] == ['success']
    assert sqlite3.connect(path).execute('SELECT mqttPassword FROM Settings').fetchone()[0].startswith(vault.PREFIX)
    assert _read(app, 'SELECT mqttPassword FROM Settings')['mqttPassword'] == OLD['mqttPassword']
