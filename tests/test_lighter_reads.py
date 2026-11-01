"""Reading less (code review 2026-10-31): duplicate detection reads the days around an activity without their streams, and only the candidates
that pass the cheap checks whole; the AI batch reads one ride at a time; kudos reads the whole row only once it'll analyse it; deleting a friend
refreshes PRs only on the segments their activities were on; a friend sync started from the page runs in the background. Full app, throwaway
DB."""
import json

import pytest
from flask import Flask

import app as app_module
import config
import database
from services import credentials, duplicates


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


def _track(n=600, start=0):
    return json.dumps({'latlng': {'data': [[51.5 + (start + i) * 5e-5, -0.12] for i in range(n)]}, 'time': {'data': list(range(n))}})


def _add(db, aid, local, sport='Ride', dist=10000, secs=1800, rider=1, streams=None):
    db.execute("INSERT INTO Activity (id, name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedTime, rawData, riderId, "
               "streams) VALUES (?,?,?,?,?,?,?,?,?,'{}',?,?)", [aid, aid, sport, sport, local, local, dist, secs, secs, rider, streams or _track()])


def test_the_window_is_the_same_days_as_before(app, monkeypatch):
    with app.app_context():
        db = database.get_db()
        for aid, local in (('out-early', '2026-01-08T23:59:59'), ('first', '2026-01-09T00:00:00'), ('same-day', '2026-01-10T18:00:00'),
                           ('last', '2026-01-12T23:59:59'), ('out-late', '2026-01-13T00:00:00'), ('other-rider', '2026-01-10T12:00:00')):
            _add(db, aid, local, rider=2 if aid == 'other-rider' else 1)
        _add(db, 'new', '2026-01-10T12:00:00')
        db.commit()
        monkeypatch.setattr(duplicates, 'same_ride', lambda a, b, fragments=True: True)
        new = db.execute("SELECT * FROM Activity WHERE id='new'").fetchone()
        found = duplicates.find_duplicates(db, new)
        assert [r['id'] for r in found] == ['first', 'same-day', 'last']        # the day before to two days after, as it always was
        assert all(r['streams'] for r in found)                        # whole rows, for pick_winner and park


def test_only_a_candidate_that_passes_the_cheap_checks_is_read_whole(app):
    with app.app_context():
        db = database.get_db()
        _add(db, 'garmin_1', '2026-01-10T12:00:30', dist=10100)        # the same ride from another device
        _add(db, 'later', '2026-01-10T17:00:00')                         # another ride that day
        _add(db, 'yesterday', '2026-01-09T12:00:00')
        _add(db, 'new', '2026-01-10T12:00:00')
        db.commit()
        new = db.execute("SELECT * FROM Activity WHERE id='new'").fetchone()
        seen = []
        db.set_trace_callback(seen.append)
        found = duplicates.find_duplicates(db, new)
        db.set_trace_callback(None)
        assert [r['id'] for r in found] == ['garmin_1']
        assert [s for s in seen if s.startswith('SELECT * FROM Activity')] == ["SELECT * FROM Activity WHERE id='garmin_1'"]
        assert not any('streams' in s for s in seen if 'startDateLocal >=' in s)


def test_a_piece_whose_track_is_elsewhere_is_still_turned_down_once_read_whole(app):
    with app.app_context():
        db = database.get_db()
        elsewhere = json.dumps({'latlng': {'data': [[53.0 + i * 5e-5, -2.0] for i in range(300)]}, 'time': {'data': list(range(300))}})
        _add(db, 'piece', '2026-01-10T12:10:00', dist=1500, secs=300, streams=elsewhere)
        _add(db, 'new', '2026-01-10T12:00:00', secs=3600, streams=_track(3600))
        db.commit()
        new = db.execute("SELECT * FROM Activity WHERE id='new'").fetchone()
        assert duplicates.find_duplicates(db, new) == []
        db.execute("UPDATE Activity SET streams=? WHERE id='piece'", [_track(300, start=600)])      # where the whole ride was then
        assert [r['id'] for r in duplicates.find_duplicates(db, new)] == ['piece']


def test_the_ai_batch_reads_one_ride_at_a_time(app, client, monkeypatch):
    with app.app_context():
        db = database.get_db()
        for i in range(3):
            _add(db, f'r{i}', f'2026-01-1{i}T12:00:00')
        db.commit()
    got = []
    import services.ai
    monkeypatch.setattr(services.ai, 'analyse_ride', lambda db, activity, **kw: got.append((activity['id'], bool(activity['streams']))) or 'ok')
    body = client.get('/ai/bulk-analyse?force=1').get_data(as_text=True)
    assert got == [('r0', True), ('r1', True), ('r2', True)]
    assert '"type": "done", "analysed": 3, "skipped": 0' in body


def test_kudos_reads_the_whole_activity_only_to_analyse_it(app, client, monkeypatch):
    import routes.kudos
    with app.app_context():
        db = database.get_db()
        _add(db, 'run', '2026-01-10T12:00:00', sport='Run')
        _add(db, 'ride', '2026-01-10T17:00:00')
        db.commit()
    seen = []
    connect = database.sqlite3.connect

    def traced(*a, **kw):
        conn = connect(*a, **kw)
        conn.set_trace_callback(seen.append)
        return conn
    monkeypatch.setattr(database.sqlite3, 'connect', traced)
    assert client.post('/rides/run/kudos', json={}).status_code == 400
    assert not [s for s in seen if s.startswith('SELECT * FROM Activity')]
    monkeypatch.setattr(routes.kudos, 'analyse_ride', lambda db, activity, **kw: f"{activity['id']} {bool(activity['streams'])}")
    assert client.post('/rides/ride/kudos', json={}).get_json() == {'kudos': 'ride True'}


def test_deleting_a_friend_refreshes_only_the_segments_they_were_on(app, client, monkeypatch):
    import routes.friends
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT INTO Rider (id, name) VALUES (2, 'Sam')")
        fid = db.execute("INSERT INTO Friend (name, url, token, riderId) VALUES ('Sam', 'https://sam.example', 't', 2)").lastrowid
        segs = [db.execute("INSERT INTO Segment (name, startLat, startLng, endLat, endLng, distanceM, sport, friendId) VALUES (?,51,0,51.01,0,1000,'ride',?)",
                           [name, mine]).lastrowid for name, mine in (('Both', None), ('Only mine', None), ('Theirs', fid))]
        _add(db, 'f1_1', '2026-01-10T12:00:00', rider=2)
        _add(db, 'mine', '2026-01-11T12:00:00')
        for sid, aid in ((segs[0], 'f1_1'), (segs[0], 'mine'), (segs[1], 'mine'), (segs[2], 'f1_1')):
            db.execute('INSERT INTO SegmentEffort (segmentId, activityId, elapsedSecs) VALUES (?,?,100)', [sid, aid])
        db.commit()
    refreshed = []
    monkeypatch.setattr(routes.friends, '_refresh_prs', lambda db, sid: refreshed.append(sid))
    assert client.post(f'/friends/{fid}/delete').status_code == 302
    assert refreshed == [segs[0]]                   # not "Only mine", and "Theirs" went with them
    with app.app_context():
        db = database.get_db()
        assert db.execute("SELECT COUNT(*) FROM Activity WHERE riderId=2").fetchone()[0] == 0
        assert [r[0] for r in db.execute('SELECT segmentId FROM SegmentEffort ORDER BY segmentId')] == [segs[0], segs[1]]


def test_a_friend_sync_from_the_page_runs_in_the_background(app, client, monkeypatch):
    import routes.friends
    with app.app_context():
        db = database.get_db()
        fid = db.execute("INSERT INTO Friend (name, url, token) VALUES ('Sam', 'https://sam.example', 't')").lastrowid
        db.commit()
    waiting = []
    monkeypatch.setattr(routes.friends, '_spawn', waiting.append)          # started, not run yet
    monkeypatch.setattr(routes.friends, '_do_sync_once', lambda f: (3, None))
    assert client.post(f'/friends/{fid}/sync').get_json() == {'ok': True, 'running': True}
    assert client.get(f'/friends/{fid}/sync/status').get_json() == {'running': True}
    assert 'data-syncing' in client.get('/friends').get_data(as_text=True)          # a page opened meanwhile waits for it too
    client.post(f'/friends/{fid}/sync')                                        # pressed again: no second sync
    assert routes.friends._do_sync(fid) == (0, 'Already syncing')              # nor the automatic one
    assert len(waiting) == 1
    waiting[0]()
    assert client.get(f'/friends/{fid}/sync/status').get_json() == {'running': False, 'ok': True, 'synced': 3, 'error': None}
    with app.app_context():
        row = database.get_db().execute("SELECT status, result FROM TaskLog WHERE task='friend_sync'").fetchone()
    assert tuple(row) == ('done', 'Sam: 3 new or changed activities.')
    assert client.post('/friends/999/sync').status_code == 404


def test_a_friend_sync_that_raises_shows_on_the_tasks_page(app, client, monkeypatch):
    import routes.friends
    with app.app_context():
        db = database.get_db()
        fid = db.execute("INSERT INTO Friend (name, url, token) VALUES ('Sam', 'https://sam.example', 't')").lastrowid
        db.commit()

    def boom(f):
        raise RuntimeError('boom at /srv/secret.py')
    monkeypatch.setattr(routes.friends, '_spawn', lambda fn: fn())
    monkeypatch.setattr(routes.friends, '_do_sync_once', boom)
    r = client.post(f'/friends/{fid}/sync')
    status = client.get(f'/friends/{fid}/sync/status').get_json()
    assert status['ok'] is False and 'secret' not in status['error'] and r.headers['X-Request-Id'] in status['error']
    with app.app_context():
        row = database.get_db().execute("SELECT status, error FROM TaskLog WHERE task='friend_sync'").fetchone()
    assert row['status'] == 'failed' and row['error'].startswith('Sam: The sync failed')
    with pytest.raises(RuntimeError):
        routes.friends._do_sync(fid)                                           # free again, not 'Already syncing'
