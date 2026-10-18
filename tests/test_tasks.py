"""The Tasks page: start-up repairs are logged and announced once, background jobs show their state, and "Sync now" / "Try now" wake them.
Full app, throwaway DB."""
import pytest
from flask import Flask

import app as app_module
import config
import database
from services import credentials, garmin, tasks


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = str(tmp_path / 't.db')
    pre = Flask('pre')                                  # an install from before the update: one imported ride saved an hour early
    pre.config['DATABASE'] = path
    with pre.app_context():
        database.migrate_db()
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("UPDATE Settings SET utcStartFixDone=0, garminEmail='e', garminPassword='p', garminSyncMode='full', "
                   "garminLastError='HTTP 503', garminFailCount=2, garminHistoryFrom='all', garminWeightsRetryAt='2999-01-01T00:00:00+00:00', "
                   "garminWeightsStatus='Weight history: could not reach Garmin; trying again at 14:20.', garminHistoryDone=1, garminHistoryStatus='Health history complete.'")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        db.execute("INSERT INTO Activity (id, name, sportType, riderId, startDate, startDateLocal, distance, movingTime, elapsedTime) "
                   "VALUES ('555', 'Zwift', 'VirtualRide', 1, '2026-08-03T06:15:00', '2026-08-03T06:15:00', 20000, 1800, 1800)")
        db.commit()
    monkeypatch.setattr(config.Config, 'DATABASE', path)
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()                       # start-up: the repair runs and is logged
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def test_a_startup_repair_is_announced_once_and_listed(client):
    html = client.get('/dashboard').get_data(as_text=True)
    assert 'Headwind ran 1 start-up repair on your data' in html and 'nav-badge' in html
    html = client.get('/tasks').get_data(as_text=True)
    assert 'Start times of imported rides' in html and '1 ride moved from UTC to UK time' in html
    html = client.get('/dashboard').get_data(as_text=True)
    assert 'start-up repair' not in html and 'nav-badge' not in html                 # seen: the notice is gone


def test_job_cards_show_their_state_and_actions(client):
    html = client.get('/tasks').get_data(as_text=True)
    assert 'Garmin sync' in html and 'Failing (2 in a row): HTTP 503' in html and 'action="/tasks/run/garmin"' in html
    assert 'Health history complete.' in html
    assert 'Weight history: could not reach Garmin' in html and 'action="/tasks/run/weights"' in html
    assert 'setTimeout' in html                                                       # something is waiting: the page refreshes itself


def test_run_now_wakes_the_jobs(client):
    garmin.SYNC_WAKE.clear()
    client.post('/tasks/run/garmin')
    assert garmin.SYNC_WAKE.is_set()
    garmin.SYNC_WAKE.clear()
    garmin.HISTORY_WAKE.clear()
    client.post('/tasks/run/weights')
    assert garmin.HISTORY_WAKE.is_set()
    with client.application.app_context():
        assert database.get_db().execute('SELECT garminWeightsRetryAt FROM Settings').fetchone()[0] is None
    garmin.HISTORY_WAKE.clear()


def test_task_log_runs_failures_orphans_and_pruning(client):
    with client.application.app_context():
        db = database.get_db()
        with tasks.run(db, 'friend_sync', 'Friend sync') as t:
            t.result = '2 of 2 friends synced'
        with pytest.raises(RuntimeError):
            with tasks.run(db, 'friend_sync', 'Friend sync'):
                raise RuntimeError('no route to host')
        rows = db.execute("SELECT status, result, error FROM TaskLog WHERE task='friend_sync' ORDER BY id").fetchall()
        assert [tuple(r) for r in rows] == [('done', '2 of 2 friends synced', None), ('failed', None, 'no route to host')]
        tid = tasks.start(db, 'garmin_sync', 'Garmin sync')
        tasks.close_orphans(db)                                                       # Headwind restarted mid-run
        assert db.execute('SELECT status FROM TaskLog WHERE id=?', [tid]).fetchone()[0] == 'failed'
        for _ in range(tasks.KEEP + 20):
            tasks.record(db, 'x', 'x', 'x')
        db.commit()
        assert db.execute('SELECT COUNT(*) FROM TaskLog').fetchone()[0] <= tasks.KEEP + 1


class _NowThread:
    def __init__(self, target, args=(), **kw): self.target, self.args = target, args
    def start(self): self.target(*self.args)


class _Garmin:
    def get_activities(self, start, limit):
        return [{'activityId': 1, 'activityType': {'typeKey': 'lap_swimming'}, 'startTimeLocal': '2026-08-01 07:00:00'}] if start == 0 else []


def test_activity_type_check_runs_as_a_background_job(client, monkeypatch):
    from routes import garmin as garmin_routes
    with client.application.app_context():
        db = database.get_db()
        db.execute("INSERT INTO Activity (id, name, sportType, riderId, startDate, startDateLocal, distance, movingTime, elapsedTime) "
                   "VALUES ('garmin_1', 'Pool', 'Ride', 1, '2026-08-01T06:00:00', '2026-08-01T07:00:00', 1500, 1800, 1800)")
        db.commit()
    monkeypatch.setattr(garmin_routes.threading, 'Thread', _NowThread)
    monkeypatch.setattr(garmin, '_client', lambda *a: _Garmin())
    client.post('/garmin/sports/check')
    assert not garmin_routes._sports_lock.locked()
    html = client.get('/garmin/sports').get_data(as_text=True)
    assert 'Checked 1 of your 1 Garmin rides: 1 has the wrong sport.' in html and '1 with the wrong sport' in html
    html = client.get('/tasks').get_data(as_text=True)
    assert 'Activity type check' in html and 'href="/garmin/sports"' in html

    monkeypatch.setattr(garmin, '_client', lambda *a: (_ for _ in ()).throw(ConnectionError('timed out')))
    client.post('/garmin/sports/check')
    assert not garmin_routes._sports_lock.locked()
    assert 'Could not reach Garmin: timed out' in client.get('/tasks').get_data(as_text=True)


def test_activity_type_page_shows_a_running_check(client):
    with client.application.app_context():
        tasks.start(database.get_db(), 'sport_check', 'Activity type check')
    html = client.get('/garmin/sports').get_data(as_text=True)
    assert 'disabled>Asking Garmin' in html and 'location.reload' in html


def test_ride_page_links_to_where_it_came_from(client):
    html = client.get('/rides/555').get_data(as_text=True)                          # the fixture's ride has a Strava id
    assert 'href="https://www.strava.com/activities/555"' in html and 'Strava ↗' in html
