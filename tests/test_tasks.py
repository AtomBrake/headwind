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
    assert 'tasks.js' in html and ' data-refresh="20"' in html                        # something is waiting: the page refreshes itself


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


def test_a_long_run_shows_its_progress(client):
    with client.application.app_context():
        db = database.get_db()
        tid = tasks.start(db, 'track_summaries', 'Map summaries of activities')
        tasks.progress(db, tid, 1250, 5000)
        db.commit()
    html = client.get('/tasks').get_data(as_text=True)
    assert '1,250 of 5,000 done' in html and 'role="progressbar"' in html and 'aria-valuenow="25"' in html
    assert ' data-refresh="5"' in html                                                # a moving bar: refreshed more often
    with client.application.app_context():
        tasks.finish(database.get_db(), tid, '5,000 activities summarised')
    html = client.get('/tasks').get_data(as_text=True)
    assert 'role="progressbar"' not in html and '5,000 activities summarised' in html


def test_opening_tasks_waits_for_no_write(client):
    """The page marks the start-up notice seen once; after that it only reads, so a long write by the worker can't hold it up."""
    import _thread                                                                    # threading.Thread is stubbed out by the fixture
    import sqlite3
    import threading
    client.get('/tasks')                                                              # the notice is seen
    other = sqlite3.connect(client.application.config['DATABASE'], isolation_level=None)
    other.execute('BEGIN IMMEDIATE')                                                  # the worker in the middle of a write
    got, done = [], threading.Event()
    _thread.start_new_thread(lambda: (got.append(client.get('/tasks').status_code), done.set()), ())
    in_time = done.wait(5)
    other.execute('ROLLBACK')
    done.wait()
    assert in_time and got == [200]


class _NowThread:
    def __init__(self, target, args=(), **kw): self.target, self.args = target, args
    def start(self): self.target(*self.args)


class _Garmin:
    def get_activities(self, start, limit):
        return [{'activityId': 1, 'activityType': {'typeKey': 'lap_swimming'}, 'startTimeLocal': '2026-08-01 07:00:00'}] if start == 0 else []


def test_activity_type_check_runs_as_a_background_job(client, monkeypatch):
    from services import jobs
    with client.application.app_context():
        db = database.get_db()
        db.execute("INSERT INTO Activity (id, name, sportType, riderId, startDate, startDateLocal, distance, movingTime, elapsedTime) "
                   "VALUES ('garmin_1', 'Pool', 'Ride', 1, '2026-08-01T06:00:00', '2026-08-01T07:00:00', 1500, 1800, 1800)")
        db.commit()
    monkeypatch.setattr(garmin, '_client', lambda *a: _Garmin())
    client.post('/garmin/sports/check')
    client.post('/garmin/sports/check')                                      # pressed again before the worker took it: one job
    assert jobs.run_queued(client.application) == 1
    html = client.get('/garmin/sports').get_data(as_text=True)
    assert 'Checked 1 of your 1 Garmin rides: 1 has the wrong sport.' in html and '1 with the wrong sport' in html
    html = client.get('/tasks').get_data(as_text=True)
    assert 'Activity type check' in html and 'href="/garmin/sports"' in html

    assert 'Since then, Headwind has listed more' not in html

    # A later start lists more from the types kept at the last sync (sport_fix.from_seen): the check's own count no longer covers the list
    with client.application.app_context():
        db = database.get_db()
        db.execute("INSERT INTO TaskLog (task, label, startedAt, finishedAt, status, result) VALUES ('startup:garmin_sports', 'Garmin activities "
                   "with another sport', '2999-01-01T00:00:00+00:00', '2999-01-01T00:00:00+00:00', 'done', '1 Garmin activity…')")
        db.commit()
    assert 'Since then, Headwind has listed more' in client.get('/garmin/sports').get_data(as_text=True)

    monkeypatch.setattr(garmin, '_client', lambda *a: (_ for _ in ()).throw(ConnectionError('timed out')))
    client.post('/garmin/sports/check')
    assert jobs.run_queued(client.application) == 1
    assert 'Could not reach Garmin: timed out' in client.get('/tasks').get_data(as_text=True)
    with client.application.app_context():
        assert jobs.last(database.get_db(), 'garmin_sports_check')['state'] == 'failed'


def test_activity_type_page_shows_a_running_check(client):
    with client.application.app_context():
        tasks.start(database.get_db(), 'sport_check', 'Activity type check')
    html = client.get('/garmin/sports').get_data(as_text=True)
    assert 'disabled>Asking Garmin' in html and ' data-running>' in html


def test_ride_page_links_to_where_it_came_from(client):
    html = client.get('/activities/555').get_data(as_text=True)                          # the fixture's ride has a Strava id
    assert 'href="https://www.strava.com/activities/555"' in html and 'Strava ↗' in html
