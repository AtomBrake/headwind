"""Work a page starts that the background worker runs (services/jobs.py), with what the page shows read from the job, so any process serving
pages sees it: the weather backfill on Tasks and the friends' automatic sync. Full app, throwaway database, no network; the tests run the
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


def _weather_row(client):
    from services import tasks
    html = client.get('/tasks').get_data(as_text=True)
    assert 'Weather for older activities' in html
    with client.application.app_context():
        return next(j for j in tasks.overview(database.get_db())['jobs'] if j['name'] == 'Weather for older activities')


def test_the_weather_backfill_runs_in_the_worker_and_the_tasks_page_follows_it(app, client, monkeypatch):
    from services import weather
    _ride(app, 'a')
    _ride(app, 'b', lat=1)                                             # Open-Meteo has nothing for this one
    with app.app_context():                                            # a ride in a virtual world gets none, so it isn't waiting for any
        db = database.get_db()
        db.execute("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal, startLat, startLng) VALUES ('z', 'Zwift', 'VirtualRide', 1, "
                   "'2026-10-02T08:00:00', -11.6, 166.9)")
        db.commit()
    sunny = {'weatherTempC': 12, 'weatherWindKph': 10, 'weatherGustKph': 20, 'weatherWindDir': 180, 'weatherHumidity': 60, 'weatherRainMm': 0,
             'weatherCode': 0, 'weatherSummary': 'Sunny', 'weatherWindRel': None}
    monkeypatch.setattr(weather, 'fetch_weather', lambda lat, *a, **k: sunny if lat > 1 else None)
    weather._FAILED.clear()
    row = _weather_row(client)
    assert row['state'] == 'idle' and row['detail'].startswith('2 activities have no weather yet') and row['action']['url'] == '/tasks/run/weather'
    client.post('/tasks/run/weather')
    client.post('/tasks/run/weather')                                  # not twice
    with app.app_context():
        assert database.get_db().execute("SELECT COUNT(*) FROM Job WHERE kind='weather_backfill'").fetchone()[0] == 1
    assert _weather_row(client)['state'] == 'running'
    assert jobs.run_queued(app) == 1
    row = _weather_row(client)                                         # the one that failed isn't offered again
    assert row['state'] == 'done' and not row['action'] and 'nothing for the 1' in row['detail']
    client.post('/tasks/run/weather')                                  # nor queued by hand
    with app.app_context():
        db = database.get_db()
        assert db.execute("SELECT weatherSummary FROM Activity WHERE id='a'").fetchone()[0]
        assert db.execute("SELECT COUNT(*) FROM Job WHERE kind='weather_backfill'").fetchone()[0] == 1


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


# ── Long scans a page starts: queued for the worker, with their progress on Tasks ──

def _track_ride(app, rid, km=12):
    """A ride with a track due north from London, a point every 10 m at 10 m/s, long enough for the 5-mile best effort."""
    import json
    from services import streams as _streams
    n = km * 100
    pts = [[51.5 + i * 10 / 111_320.0, -0.1] for i in range(n)]
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT INTO Activity (id, name, sportType, type, riderId, startDate, startDateLocal, distance, movingTime, elapsedTime, rawData) "
                   "VALUES (?, 'Ride', 'Ride', 'Ride', 1, '2026-10-01T08:00:00', '2026-10-01T08:00:00', ?, ?, ?, '{}')", [rid, n * 10.0, n, n])
        _streams.save(db, rid, json.dumps({'latlng': {'data': pts}, 'time': {'data': list(range(n))},
                                           'distance': {'data': [i * 10.0 for i in range(n)]}}))
        db.commit()


def test_the_best_efforts_rescan_runs_in_the_worker_with_its_progress(app, client):
    _track_ride(app, 'r1')
    job = client.post('/data/scan-efforts').get_json()['job']
    assert job and client.post('/data/scan-efforts').get_json()['job'] == job        # asked again while queued: the same job
    with app.app_context():
        assert not database.get_db().execute('SELECT COUNT(*) FROM BestEffort').fetchone()[0]
    assert jobs.run_queued(app) == 1
    with app.app_context():
        db = database.get_db()
        assert db.execute("SELECT activityId FROM BestEffort WHERE distanceMi=5").fetchone()[0] == 'r1'
        row = db.execute("SELECT status, result, done, total FROM TaskLog WHERE task='best_efforts_scan'").fetchone()
        assert tuple(row) == ('done', 'Worked out again for 1 ride', 1, 1)


def test_segment_scans_run_in_the_worker_with_their_progress(app, client):
    _track_ride(app, 'r1')
    d = 1 / 111_320.0
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT INTO Segment (id, name, startLat, startLng, endLat, endLng, distanceM, sport) VALUES (1, 'North', ?, -0.1, ?, -0.1, 2000, 'ride')",
                   [51.5 + 1000 * d, 51.5 + 3000 * d])
        db.commit()
    job = client.post('/segments/scan').get_json()['job']
    assert job and client.post('/segments/scan').get_json()['job'] == job            # one rescan of everything at a time
    assert 'id="segmentMatching"' in client.get('/segments/1').get_data(as_text=True)  # the page says it's being matched, and follows the job
    assert jobs.run_queued(app) == 1
    with app.app_context():
        db = database.get_db()
        assert db.execute('SELECT activityId, isPR FROM SegmentEffort WHERE segmentId=1').fetchall()[0][:] == ('r1', 1)
        row = db.execute("SELECT label, status, result, done, total FROM TaskLog WHERE task='segment_scan'").fetchone()
        assert tuple(row) == ('Matching every segment', 'done', '1 effort found', 1, 1)
    assert 'id="segmentMatching"' not in client.get('/segments/1').get_data(as_text=True)


def test_a_long_run_shows_in_the_background_pill_while_it_runs(app, client):
    from services import tasks
    with app.app_context():
        db = database.get_db()
        tid = tasks.start(db, 'segment_scan', 'Matching every segment')
        tasks.progress(db, tid, 30, 120)
        db.commit()
    items = client.get('/tasks/background').get_json()['items']
    assert {'id': 'task', 'state': 'running', 'url': '/tasks', 'text': 'Matching every segment · 30 / 120', 'pct': 25} in items
    with app.app_context():
        tasks.finish(database.get_db(), tid, 'done')
    assert not [i for i in client.get('/tasks/background').get_json()['items'] if i['id'] == 'task']


def test_an_import_asks_for_the_weather_before_it_writes(app, monkeypatch, tmp_path):
    """The weather service is slow: an import holding its write lock across it made every page's save wait (routes/import_rides._weather_first)."""
    import io
    import zipfile
    from datetime import datetime, timedelta
    from routes import import_rides
    from services import weather
    held = []

    def ask(*a, **k):
        held.append(database.get_db().in_transaction)
        return {'weatherTempC': 12.0, 'weatherWindKph': 10, 'weatherGustKph': 20, 'weatherWindDir': 180, 'weatherHumidity': 60, 'weatherRainMm': 0,
                'weatherCode': 0, 'weatherSummary': 'Sunny', 'weatherWindRel': None}
    monkeypatch.setattr(weather, 'fetch_weather', ask)
    start = datetime(2026, 10, 1, 8, 0)
    pts = ''.join(f'<trkpt lat="{51.5 + i * 0.0001:.6f}" lon="-0.1"><time>{(start + timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>'
                  for i in range(60))
    gpx = f'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>{pts}</trkseg></trk></gpx>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('activities.csv', 'Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Filename\n'
                                      '111,"Oct 1, 2026, 8:00:00 AM",Strava one,Ride,60,0.67,activities/111.gpx\n')
        zf.writestr('activities/111.gpx', gpx)
        zf.writestr('other.gpx', gpx.replace('2026-10-01T08', '2026-10-02T08'))
    single = tmp_path / 'single.gpx'
    single.write_text(gpx.replace('2026-10-01T08', '2026-10-03T08'))
    with app.app_context():
        zf = zipfile.ZipFile(buf)
        list(import_rides._process_strava_export(zf, set(zf.namelist()), 1, photos=False))
        list(import_rides._process_generic_zip(zipfile.ZipFile(io.BytesIO(_only(buf, 'other.gpx'))), {'other.gpx'}, 1))
        list(import_rides._process_single_file(str(single), 'single.gpx', 1))
        db = database.get_db()
        assert db.execute('SELECT COUNT(*) FROM Activity WHERE weatherTempC = 12.0').fetchone()[0] == 3
    assert held == [False, False, False]


def _only(buf, name):
    import io
    import zipfile
    out = io.BytesIO()
    with zipfile.ZipFile(buf) as src, zipfile.ZipFile(out, 'w') as dst:
        dst.writestr(name, src.read(name))
    return out.getvalue()
