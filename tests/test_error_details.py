"""A failure the user didn't cause answers with a short message and the log id, never the exception's text (it can carry paths and
internals); messages Headwind writes for the user on purpose still come through. Full app, throwaway DB."""
import io
import json

import pytest
from flask import Flask

import app as app_module
import config
import database
from services import ai, backup, credentials, garmin, logs

LEAK = 'boom at /srv/headwind/secret.py'


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
        db.execute("UPDATE Settings SET garminEmail='rider@example.com', garminPassword='pw' WHERE id=1")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Rider', 1)")
        db.execute("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal, distance, movingTime, elapsedTime) "
                   "VALUES ('r1', 'Morning ride', 'Ride', 1, '2026-10-01T08:00:00', 20000, 3600, 3600)")
        db.commit()
    monkeypatch.delenv('LOG_DIR', raising=False)
    monkeypatch.setattr(config.Config, 'DATABASE', path)
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    yield app_module.create_app()
    logs.setup()


@pytest.fixture
def client(app):
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _raise(exc):
    def f(*a, **kw):
        raise exc
    return f


def _quotes_id(msg, r):
    return LEAK not in msg and r.headers['X-Request-Id'] in msg


def test_kudos_hides_the_exception_but_keeps_our_own_words(client, monkeypatch):
    import routes.kudos
    monkeypatch.setattr(routes.kudos, 'analyse_ride', _raise(RuntimeError(LEAK)))
    r = client.post('/rides/r1/kudos', json={})
    assert r.status_code == 500 and _quotes_id(r.get_json()['error'], r)
    monkeypatch.setattr(routes.kudos, 'analyse_ride', _raise(ai.AIUnavailable('Add an AI key in Settings to enable AI coaching')))
    assert client.post('/rides/r1/kudos', json={}).get_json()['error'] == 'Add an AI key in Settings to enable AI coaching'


def test_bulk_analyse_sends_no_traceback(client, monkeypatch):
    monkeypatch.setattr(ai, 'analyse_ride', _raise(RuntimeError(LEAK)))
    r = client.get('/ai/bulk-analyse')
    events = [json.loads(line[6:]) for line in r.get_data(as_text=True).splitlines() if line.startswith('data: ')]
    err = next(e for e in events if e['type'] == 'error')
    assert 'Traceback' not in err['detail'] and _quotes_id(err['detail'], r)
    assert events[-1] == {'type': 'done', 'analysed': 0, 'skipped': 1}


def test_garmin_sync_hides_the_exception(client, monkeypatch):
    monkeypatch.setattr(garmin, 'sync_garmin', _raise(RuntimeError(LEAK)))
    r = client.post('/garmin/sync')
    assert r.status_code == 500 and _quotes_id(r.get_json()['error'], r)
    monkeypatch.setattr(garmin, 'sync_garmin', _raise(garmin.SignInNeeded(garmin.SIGN_IN_AGAIN)))
    assert client.post('/garmin/sync').get_json()['error'] == garmin.SIGN_IN_AGAIN


def test_garmin_sync_error_wording():
    assert 'try again in a while' in garmin.sync_error(RuntimeError('HTTP 429 Too Many Requests'))
    assert garmin.sync_error(RuntimeError(LEAK)) == 'Garmin sync failed. The details are in the log.'     # no request: no id to quote


def test_friend_probe_hides_the_exception(client, monkeypatch):
    import routes.friends
    monkeypatch.setattr(routes.friends, 'open_peer', _raise(OSError(LEAK)))
    r = client.post('/friends/probe', json={'url': 'http://friend.invalid', 'token': 't'})
    assert _quotes_id(r.get_json()['error'], r)
    from services import peer_http
    monkeypatch.setattr(routes.friends, 'open_peer', peer_http.open_peer)
    r = client.post('/friends/probe', json={'url': 'ftp://friend.invalid', 'token': 't'})
    assert r.get_json()['error'] == 'friend URL must start with http:// or https://'


def test_friend_sync_hides_the_network_error(app, client, monkeypatch):
    import routes.friends
    with app.app_context():
        db = database.get_db()
        fid = db.execute("INSERT INTO Friend (name, url, token) VALUES ('Sam', 'http://friend.invalid', 't')").lastrowid
        db.commit()
    monkeypatch.setattr(routes.friends, '_spawn', lambda fn: fn())      # the sync runs in the background: here, before the answer
    monkeypatch.setattr(routes.friends, 'open_peer', _raise(OSError(LEAK)))
    r = client.post(f'/friends/{fid}/sync')
    assert r.get_json() == {'ok': True, 'running': True}
    err = client.get(f'/friends/{fid}/sync/status').get_json()['error']
    assert err.startswith('Could not connect to their server') and _quotes_id(err, r)      # the id of the request that started it

    class Broken(io.BytesIO):
        def readline(self, *a):
            raise OSError(LEAK)
    monkeypatch.setattr(routes.friends, 'open_peer', lambda *a, **kw: Broken())
    r = client.post(f'/friends/{fid}/sync')
    err = client.get(f'/friends/{fid}/sync/status').get_json()['error']
    assert err.startswith('The feed from their server stopped part-way') and _quotes_id(err, r)


def test_restore_hides_the_exception(client, monkeypatch):
    monkeypatch.setattr(backup, 'stage_upload', _raise(RuntimeError(LEAK)))
    r = client.post('/settings/backup/import', data={'backup': (io.BytesIO(b'x'), 'b.zip')}, content_type='multipart/form-data')
    with client.session_transaction() as s:
        msg = s['_flashes'][-1][1]
    assert msg.startswith('Restore failed.') and _quotes_id(msg, r)
    monkeypatch.setattr(backup, 'stage_upload', _raise(backup.BackupError('Not a Headwind backup.')))
    client.post('/settings/backup/import', data={'backup': (io.BytesIO(b'x'), 'b.zip')}, content_type='multipart/form-data')
    with client.session_transaction() as s:
        assert s['_flashes'][-1][1] == 'Not a Headwind backup.'


def test_setup_wizard_restore_hides_the_exception(app, client, monkeypatch):
    with app.app_context():
        db = database.get_db()
        db.execute('DELETE FROM Activity'); db.execute('DELETE FROM Rider'); db.commit()
    monkeypatch.setattr(backup, 'stage_upload', _raise(RuntimeError(LEAK)))
    r = client.post('/setup/restore', data={'backup': (io.BytesIO(b'x'), 'b.zip')}, content_type='multipart/form-data')
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and 'Could not restore the backup.' in html and _quotes_id(html, r)
    monkeypatch.setattr(backup, 'stage_upload', _raise(backup.BackupError('Not a Headwind backup.')))
    r = client.post('/setup/restore', data={'backup': (io.BytesIO(b'x'), 'b.zip')}, content_type='multipart/form-data')
    assert r.status_code == 200 and 'Not a Headwind backup.' in r.get_data(as_text=True)    # was a 500: the page lacked its HA context
