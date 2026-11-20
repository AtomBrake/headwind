"""Work a page starts that the background worker runs (services/jobs.py), with what the page shows read from the job, so any process serving
pages sees it: the weather backfill on Settings and the friends' automatic sync. Full app, throwaway database, no network; the tests run the
queue as the worker would."""
import pytest

import app as app_module
import config
import database
from services import credentials, jobs


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    a = app_module.create_app()
    with a.app_context():
        db = database.get_db()
        db.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        db.commit()
    return a


@pytest.fixture
def client(app):
    c = app.test_client()
    with app.app_context(), c.session_transaction() as s:
        s['logged_in'], s['av'] = True, credentials.auth_version()
    return c


def _ride(app, rid, lat=51.5):
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal, startLat, startLng) VALUES (?, 'Ride', 'Ride', 1, "
                   "'2026-10-01T08:00:00', ?, -0.1)", [rid, lat])
        db.commit()


def test_the_weather_backfill_runs_in_the_worker_and_the_page_follows_it(app, client, monkeypatch):
    from services import weather
    _ride(app, 'a')
    _ride(app, 'b', lat=1)                                             # Open-Meteo has nothing for this one
    sunny = {'weatherTempC': 12, 'weatherWindKph': 10, 'weatherGustKph': 20, 'weatherWindDir': 180, 'weatherHumidity': 60, 'weatherRainMm': 0,
             'weatherCode': 0, 'weatherSummary': 'Sunny', 'weatherWindRel': None}
    monkeypatch.setattr(weather, 'fetch_weather', lambda lat, *a, **k: sunny if lat > 1 else None)
    weather._FAILED.clear()
    assert client.post('/settings/weather-backfill').get_json() == {'done': 0, 'failed': 0, 'remaining': 2, 'started': True}
    assert client.post('/settings/weather-backfill').get_json() == {'done': 0, 'failed': 0, 'remaining': 2, 'running': True}    # not twice
    assert jobs.run_queued(app) == 1
    assert client.post('/settings/weather-backfill').get_json() == {'done': 1, 'failed': 1, 'remaining': 0}    # the one that failed isn't tried again
    with app.app_context():
        assert database.get_db().execute("SELECT weatherSummary FROM Activity WHERE id='a'").fetchone()[0]


def test_the_automatic_friend_sync_is_one_run_and_the_page_sees_each_friend(app, client, monkeypatch):
    import routes.friends
    with app.app_context():
        db = database.get_db()
        sam = db.execute("INSERT INTO Friend (name, url, token) VALUES ('Sam', 'https://sam.example', 't')").lastrowid
        jo = db.execute("INSERT INTO Friend (name, url, token) VALUES ('Jo', 'https://jo.example', 't')").lastrowid
        db.commit()
        jobs.enqueue(db, 'friends_autosync')                            # as app._friends_autosync does every interval
    seen = []

    def sync(fid):
        seen.append(client.get(f'/friends/{fid}/sync/status').get_json())     # mid-run, from a page
        return (2, None) if fid == sam else (0, 'Could not connect to their server')
    monkeypatch.setattr(routes.friends, '_do_sync_once', sync)
    assert client.get(f'/friends/{sam}/sync/status').get_json()['ok'] is False      # nothing has run yet
    jobs.run_queued(app)
    assert seen == [{'running': True}, {'running': True}]
    assert client.get(f'/friends/{sam}/sync/status').get_json() == {'running': False, 'ok': True, 'synced': 2, 'error': None}
    assert client.get(f'/friends/{jo}/sync/status').get_json()['error'] == 'Could not connect to their server'
    with app.app_context():
        row = database.get_db().execute("SELECT status, result FROM TaskLog WHERE task='friend_sync'").fetchone()
    assert row['status'] == 'done' and row['result'].startswith('1 of 2 friends synced, 2 new or changed activities. Failed: Jo:')
