"""Routes that follow a line (services/planned_routes.py): from GPX files, from an activity's own points and from a Strava export's routes/, as
a track with its heights; shown, exported and edited as a copy in the planner (routes/route_builder.py). Throwaway DB, no network."""
import io
import json
import sqlite3
import zipfile

import pytest
from flask import Flask

import app as app_module
import config
import database
from routes import import_rides
from services import credentials, logs, planned_routes
from tests.page_data import page_data
from services import streams as _streams


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def trk(n=50, name='Bodmin loop', kind='mountain_biking', meta=True, ele=True):
    """A GPX <trk> heading north, ~33 m between points, climbing 1 m each."""
    pts = ''.join(f'<trkpt lat="{50.4 + i * 0.0003:.5f}" lon="-4.7">' + (f'<ele>{100 + i}</ele>' if ele else '') + '</trkpt>' for i in range(n))
    return ('<?xml version="1.0"?><gpx version="1.1" creator="StravaGPX" xmlns="http://www.topografix.com/GPX/1/1">'
            + (f'<metadata><name>{name}</name></metadata>' if meta else '')
            + f'<trk><name>{name}</name>' + (f'<type>{kind}</type>' if kind else '') + f'<trkseg>{pts}</trkseg></trk></gpx>').encode()


@pytest.fixture
def db(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
        yield d


@pytest.fixture
def app(tmp_path, monkeypatch):
    path = str(tmp_path / 't.db')
    pre = Flask('pre')
    pre.config['DATABASE'] = path
    with pre.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Rider', 1)")
        d.execute("INSERT INTO Activity (id, name, sportType, type, riderId, startDateLocal, distance, movingTime, elapsedTime) "
                  "VALUES ('run1', 'Canal run', 'Run', 'Run', 1, '2026-10-01T08:00:00', 3000, 900, 900)")
        _streams.save(d, 'run1', {'latlng': {'data': [[51.5 + i * 0.0003, -0.1] for i in range(40)] + [[51.5117, -0.1]] * 5},
                                  'altitude': {'data': [10 + i * 0.5 for i in range(45)]}})
        d.execute("INSERT INTO Activity (id, name, sportType, type, riderId, startDateLocal, distance, movingTime, elapsedTime) "
                  "VALUES ('zw1', 'Watopia', 'VirtualRide', 'VirtualRide', 1, '2026-10-02T08:00:00', 3000, 900, 900)")
        _streams.save(d, 'zw1', {'latlng': {'data': [[-11.6 + i * 0.0003, 166.9] for i in range(40)]}})
        d.commit()
    monkeypatch.delenv('LOG_DIR', raising=False)
    monkeypatch.delenv('HEADWIND_DEMO', raising=False)
    monkeypatch.setenv('AVATAR_DIR', str(tmp_path / 'avatars'))
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


def no_network(monkeypatch):
    def refuse(*a, **kw):
        raise AssertionError('the export of a route with its own heights looked them up')
    monkeypatch.setattr('routes.route_builder.requests.get', refuse)


# ---------- reading and simplifying ----------

def test_a_gpx_track_reads_with_its_name_sport_and_heights():
    got = planned_routes.from_gpx(trk(), 'routes/1.gpx')
    assert got['name'] == 'Bodmin loop' and got['sportType'] == 'MountainBikeRide'
    assert len(got['track']) == 50 and got['track'][0] == [50.4, -4.7, 100.0]
    assert 1600 < planned_routes.distance_m(got['track']) < 1700
    assert planned_routes.gain_m(got['track']) == pytest.approx(49, abs=1)


def test_a_gpx_route_reads_when_there_is_no_track_so_the_planner_export_goes_round_trip():
    from routes.route_builder import _build_gpx
    wps = [{'lat': 50.4, 'lng': -4.7}, {'lat': 50.41, 'lng': -4.7}, {'lat': 50.41, 'lng': -4.69}]
    got = planned_routes.from_gpx(_build_gpx('Planned', wps, [10, 20, None]).encode())
    assert got['name'] == 'Planned' and got['sportType'] is None
    assert got['track'] == [[50.4, -4.7, 10.0], [50.41, -4.7, 20.0], [50.41, -4.69, None]]


def test_the_name_falls_back_to_the_file_and_an_empty_file_gives_nothing():
    assert planned_routes.from_gpx(trk(meta=False, name=''), 'Coast to Coast.gpx')['name'] == 'Coast to Coast'
    empty = b'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>x</name></trk></gpx>'
    assert planned_routes.from_gpx(empty, 'x.gpx') is None


def test_a_broken_file_is_read_with_parse_gpx_s_fixes():
    """Points straight in <trk> with no <trkseg>, and a UUID in <number>: Strava's old Android app."""
    text = trk().decode().replace('<trkseg>', '<number>0e1f-uuid</number>').replace('</trkseg>', '')
    assert len(planned_routes.from_gpx(text.encode())['track']) == 50


def test_simplify_keeps_the_corners_and_drops_the_straights():
    line = [[50.4 + i * 0.0001, -4.7, None] for i in range(100)] + [[50.4 + 99 * 0.0001, -4.7 + i * 0.0001, None] for i in range(1, 100)]
    keep = planned_routes.simplify(line, 5)
    assert keep == [0, 99, 198]
    wiggle = [[50.4 + i * 0.0001, -4.7 + (0.0002 if i % 2 else 0), None] for i in range(20)]     # ~14 m either side
    assert len(planned_routes.simplify(wiggle, 5)) == 20
    assert planned_routes.as_waypoints(line)[1] == {'lat': line[99][0], 'lng': -4.7}


def test_clean_rounds_and_drops_standing_still_and_nonsense():
    assert planned_routes.clean([[50.1234567, -4.1, 10.04], [50.1234567, -4.1, 11], [0, 0], ['x', 1], [50.2, -4.1]]) == \
        [[50.123457, -4.1, 10.0], [50.2, -4.1, None]]


# ---------- saving ----------

def test_the_same_name_and_points_are_kept_once_per_rider(db):
    t = planned_routes.from_gpx(trk())['track']
    a = planned_routes.save(db, 1, 'Loop', track=t, source='gpx')
    assert a[1] and planned_routes.save(db, 1, 'Loop', track=t, source='strava') == (a[0], False)
    assert planned_routes.save(db, 1, 'Loop again', track=t)[1]                 # another name: another route
    assert planned_routes.save(db, 1, 'Loop', track=t[:-1])[1]                  # other points: another route
    db.execute("INSERT INTO Rider (id, name) VALUES (2, 'Sam')")
    assert planned_routes.save(db, 2, 'Loop', track=t)[1]                       # another rider's
    row = db.execute('SELECT * FROM PlannedRoute WHERE id=?', [a[0]]).fetchone()
    assert row['source'] == 'gpx' and row['riderId'] == 1 and row['waypoints'] == '[]'
    assert row['distance'] == pytest.approx(planned_routes.distance_m(t), abs=0.1) and row['elevationGain'] == pytest.approx(49, abs=1)


def test_step_4_gives_old_routes_the_owner_and_a_distance(tmp_path):
    path = tmp_path / 'old.db'
    app = Flask('t')
    app.config['DATABASE'] = str(path)
    app.teardown_appcontext(database.close_db)
    with app.app_context():
        database.migrate_db()
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO Rider (id, name, isDefault) VALUES (7, 'Owner', 1)")
    conn.execute('DROP TABLE PlannedRoute')                                    # as it was before step 4
    conn.execute("CREATE TABLE PlannedRoute (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, waypoints TEXT NOT NULL, "
                 "createdAt TEXT DEFAULT (datetime('now')))")
    conn.execute('INSERT INTO PlannedRoute (name, waypoints) VALUES (?, ?)', ['Old', json.dumps([{'lat': 50.4, 'lng': -4.7}, {'lat': 50.41, 'lng': -4.7}])])
    conn.execute("INSERT INTO PlannedRoute (name, waypoints) VALUES ('Broken', 'not json')")
    conn.execute('PRAGMA user_version = 3')
    conn.commit()
    conn.close()
    with app.app_context():
        database.migrate_db()
    conn = sqlite3.connect(path)
    rows = conn.execute('SELECT name, riderId, source, round(distance), track FROM PlannedRoute ORDER BY id').fetchall()
    assert rows == [('Old', 7, 'planner', 1112.0, None), ('Broken', 7, 'planner', 0.0, None)]


# ---------- the Strava export ----------

def strava_zip(routes_csv, files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('activities.csv', 'Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Filename\n')
        z.writestr('routes.csv', 'Route Name,Route Filename\n' + routes_csv)
        for name, data in files:
            z.writestr(name, data)
    buf.seek(0)
    return zipfile.ZipFile(buf)


def run_import(db, z, **opts):
    events = [json.loads(e[len('data: '):]) for e in import_rides._process_strava_export(z, z.namelist(), 1, **opts)]
    db.commit()
    return events[-1]


def test_the_export_s_routes_come_in_once_when_asked_for(db):
    z = strava_zip('Bodmin,routes/1.gpx\nBodmin,routes/2.gpx\nCanal,routes/3.gpx\nGone,routes/9.gpx\n',
                   [('routes/1.gpx', trk()), ('routes/2.gpx', trk()), ('routes/3.gpx', trk(30, 'Canal', 'running'))])
    assert 'routes_created' not in run_import(db, z)                            # off unless ticked
    assert not db.execute('SELECT COUNT(*) FROM PlannedRoute').fetchone()[0]
    done = run_import(db, z, routes=True)
    assert (done['routes_created'], done['routes_existing'], done['routes_unread']) == (2, 1, 1)     # 1 and 2 are the same route
    assert [tuple(r) for r in db.execute("SELECT name, sportType, source, riderId FROM PlannedRoute ORDER BY id")] == \
        [('Bodmin', 'MountainBikeRide', 'strava', 1), ('Canal', 'Run', 'strava', 1)]
    renumbered = strava_zip('Canal,routes/1.gpx\nBodmin,routes/2.gpx\n', [('routes/1.gpx', trk(30, 'Canal', 'running')), ('routes/2.gpx', trk())])
    again = run_import(db, renumbered, routes=True)
    assert (again['routes_created'], again['routes_existing']) == (0, 2)


# ---------- the planner ----------

def test_import_gpx_saves_each_file_and_says_what_it_did_with_the_rest(client):
    files = [(io.BytesIO(trk()), 'a.gpx'), (io.BytesIO(trk()), 'copy of a.gpx'), (io.BytesIO(trk(name='', meta=False, kind=None)), 'Ride two.gpx'),
             (io.BytesIO(b'<gpx xmlns="http://www.topografix.com/GPX/1/1"></gpx>'), 'empty.gpx'), (io.BytesIO(b'not xml at all'), 'junk.gpx')]
    res = client.post('/planner/routes/import', data={'files': files}, content_type='multipart/form-data').get_json()
    assert [r['status'] for r in res] == ['saved', 'exists', 'saved', 'empty', 'unreadable']
    listed = client.get('/planner/routes').get_json()
    assert sorted(r['name'] for r in listed) == ['Bodmin loop', 'Ride two']
    r = next(r for r in listed if r['name'] == 'Bodmin loop')
    assert r['hasTrack'] and r['source'] == 'gpx' and r['count'] == 50 and 1600 < r['distM'] < 1700 and r['gainM'] == pytest.approx(49, abs=1)


def test_a_track_route_exports_its_own_heights_and_reads_back(client, monkeypatch):
    no_network(monkeypatch)
    client.post('/planner/routes/import', data={'files': [(io.BytesIO(trk()), 'a.gpx')]}, content_type='multipart/form-data')
    rid = client.get('/planner/routes').get_json()[0]['id']
    route = client.get(f'/planner/routes/{rid}').get_json()
    assert len(route['track']) == 50 and route['waypoints'] == []
    gpx = client.get(f'/planner/routes/{rid}/export.gpx').data
    assert b'<trkpt lat="50.4" lon="-4.7"><ele>100.0</ele></trkpt>' in gpx
    assert planned_routes.from_gpx(gpx)['track'] == route['track']


def test_editing_a_track_gives_waypoints_and_saving_them_leaves_the_track(client):
    client.post('/planner/routes/import', data={'files': [(io.BytesIO(trk()), 'a.gpx')]}, content_type='multipart/form-data')
    rid = client.get('/planner/routes').get_json()[0]['id']
    wps = client.get(f'/planner/routes/{rid}/waypoints').get_json()['waypoints']
    assert wps == [{'lat': 50.4, 'lng': -4.7}, {'lat': 50.4147, 'lng': -4.7}]     # a straight line: its two ends
    new = client.post('/planner/routes', json={'name': 'Bodmin loop (edited)', 'waypoints': wps}).get_json()
    assert new['id'] != rid
    assert client.get(f'/planner/routes/{rid}').get_json()['track']             # the original stays


def test_save_as_route_from_a_run_and_not_from_zwift(client):
    page = client.get('/rides/run1').get_data(as_text=True)
    assert 'Save as route' in page and 'Save as route' not in client.get('/rides/zw1').get_data(as_text=True)
    r = client.post('/planner/routes/from-activity/run1')
    assert r.status_code == 302 and '/planner/?route=' in r.headers['Location']
    route = client.get('/planner/routes/' + r.headers['Location'].split('=')[1]).get_json()
    assert route['name'] == 'Canal run' and route['source'] == 'activity' and route['sourceId'] == 'run1' and route['sportType'] == 'Run'
    assert len(route['track']) == 40 and route['track'][0] == [51.5, -0.1, 10.0]      # the standing still at the end is one point
    assert client.post('/planner/routes/from-activity/zw1').status_code == 400
    assert client.post('/planner/routes/from-activity/nope').status_code == 404


def test_the_planner_opens_a_route_asked_for(client):
    assert page_data(client.get('/planner/?route=5').get_data(as_text=True), 'plannerData')['openRoute'] == 5
    assert page_data(client.get('/planner/').get_data(as_text=True), 'plannerData')['openRoute'] is None
