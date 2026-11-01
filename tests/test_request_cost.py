"""What every page pays before its own work (code review 2026-10-31): the login check and the page frame's units, appearance, rider mode and
badges, read in one statement per request (services/page_facts.py); auth_version kept until the login changes; WAL set once in migrate_db,
not on every connection. Full app, throwaway DB."""
import json
import os

import pytest
from flask import Flask

import app as app_module
import config
import database
from services import credentials, tasks


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
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        db.commit()
    monkeypatch.setattr(config.Config, 'DATABASE', path)
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
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


@pytest.fixture
def statements(monkeypatch):
    """Every SQL statement run from here on, the PRAGMAs a new connection runs included."""
    seen = []
    connect = database.sqlite3.connect

    def traced(*a, **kw):
        conn = connect(*a, **kw)
        conn.set_trace_callback(seen.append)
        return conn
    monkeypatch.setattr(database.sqlite3, 'connect', traced)
    return seen


FRAME = ('FROM Rider', 'appearance', 'SELECT units', "'startup:", 'StravaExportRead')     # what the six queries a page used to run read


def test_a_page_pays_for_its_frame_with_one_statement(client, statements):
    client.get('/settings/')                    # the first request after start-up also checks a rider exists
    for url, most in (('/settings/', 3), ('/friends', 4)):        # 7 and 9 before (2026-11-01)
        statements.clear()
        assert client.get(url).status_code == 200
        # per connection only the settings that aren't kept in the database file (not journal_mode)
        assert [s for s in statements if s.startswith('PRAGMA')] == ['PRAGMA synchronous = NORMAL', 'PRAGMA temp_store = MEMORY',
                                                                     'PRAGMA cache_size = -8000']
        frame = [s for s in statements if any(m in s for m in FRAME)]
        assert len(frame) == 1 and 'AS startupUnseen' in frame[0], statements
        assert len([s for s in statements if not s.startswith('PRAGMA')]) <= most, statements


def test_the_frame_still_follows_what_changes(app, client):
    page = client.get('/settings/').get_data(as_text=True)
    assert 'data-theme="auto"' in page
    client.post('/settings/', data={'units': 'metric', 'appearance': 'dark'})
    with app.app_context():
        db = database.get_db()
        tasks.record(db, 'startup:test', 'A repair', 'did a thing')
        tasks.record(db, 'Startup:other', 'Not a start-up repair', 'different case')
        db.commit()
        assert tasks.unseen_startup(db) == 1
    page = client.get('/settings/').get_data(as_text=True)
    assert 'data-theme="dark"' in page and '"system": "metric"' in page
    assert 'Tasks <span class="nav-badge">1</span>' in page          # the repair nobody has looked at
    client.get('/tasks')                                               # seen
    assert 'nav-badge' not in client.get('/settings/').get_data(as_text=True)


def test_a_new_install_is_still_sent_to_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'new.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    a = app_module.create_app()
    with a.app_context():
        av = credentials.auth_version()
    c = a.test_client()
    with c.session_transaction() as s:
        s['logged_in'], s['av'] = True, av
    assert c.get('/dashboard').headers['Location'].endswith('/setup')
    with a.app_context():
        db = database.get_db()
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        db.commit()
    assert c.get('/dashboard').status_code == 200


def test_the_database_is_in_wal_mode_from_migrate_db(app):
    with app.app_context():
        assert database.get_db().execute('PRAGMA journal_mode').fetchone()[0] == 'wal'


# ---------- auth_version ----------
@pytest.fixture
def creds(tmp_path, monkeypatch):
    monkeypatch.setattr(credentials, '_data_dir', lambda: str(tmp_path))
    monkeypatch.setattr(credentials, '_unsaved', None)
    monkeypatch.setattr(credentials, '_generated', None)
    monkeypatch.setattr(credentials, '_av', None)
    for k in ('APP_USERNAME', 'APP_PASSWORD'):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_auth_version_is_kept_until_the_login_changes(creds, tmp_path):
    creds.setenv('APP_PASSWORD', 'compose-pw-1')
    credentials.save_login('rob', 'first-password')
    reads = []
    read = credentials._read_login_file
    creds.setattr(credentials, '_read_login_file', lambda: reads.append(1) or read())
    first = credentials.auth_version()
    assert [credentials.auth_version() for _ in range(5)] == [first] * 5 and len(reads) == 1

    credentials.save_login(None, 'second-password')                 # changed in Settings, in this process
    second = credentials.auth_version()
    assert second != first

    path = tmp_path / '.admin_login'                                  # changed by another process: the file's time and size move
    d = json.loads(path.read_text())
    d['username'] = 'robert'
    path.write_text(json.dumps(d))
    os.utime(path, ns=(1, 1))
    third = credentials.auth_version()
    assert third not in (first, second)

    creds.setenv('APP_PASSWORD', 'operator-new-pw')                   # the environment edited: it wins, and sessions end
    assert credentials.auth_version() != third
