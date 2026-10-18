"""Picking many activities on a list and acting on them at once (services/bulk.py, /rides/bulk*), and the GPX export's times. Full app, throwaway DB."""
import io
import json
import zipfile

import pytest

import app as app_module
import config
import database
from services import credentials, duplicates
from services.sports import RIDE_SQL

TRACK = json.dumps({'latlng': {'data': [[51.5 + i * 1e-4, -2.6] for i in range(50)]}, 'time': {'data': list(range(0, 500, 10))},
                    'altitude': {'data': [10.0] * 50}})


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    pushed = []
    monkeypatch.setattr('services.mqtt.push_update', lambda *a, **k: pushed.append('ride'))
    monkeypatch.setattr('services.mqtt.push_update_nutrition', lambda *a, **k: pushed.append('workout'))
    app = app_module.create_app()
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1), (2, 'Sam', 0)")
        db.execute("INSERT INTO Bike (id, riderId, name, kind) VALUES (1, 1, 'Road bike', 'road'), (2, 2, 'Sam''s bike', 'road')")
        for i in range(1, 5):
            db.execute("INSERT INTO Activity (id, name, sportType, riderId, startDate, startDateLocal, distance, movingTime, elapsedTime, streams, flagReason) "
                       "VALUES (?, 'Ride', 'Ride', 1, ?, ?, 20000, 3600, 3600, ?, ?)",
                       [f'r{i}', f'2026-07-0{i}T07:00:00', f'2026-07-0{i}T08:00:00', TRACK, 'only 45 m long' if i == 4 else None])
        db.execute("INSERT INTO Activity (id, riderId, sportType, startDateLocal, distance, movingTime, source) VALUES ('wk1', 1, 'Walk', '2026-07-05T09:00:00', 3000, 1800, 'android')")
        db.execute("INSERT INTO Activity (id, riderId, sportType, startDateLocal, distance, movingTime, source) VALUES ('garmin_9', 1, 'Swim', '2026-07-06T09:00:00', 1500, 1800, 'garmin')")
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    c.pushed = pushed
    return c


def q(client, sql, args=()):
    with client.application.app_context():
        return database.get_db().execute(sql, args).fetchall()


def bulk(client, action, ids, **form):
    return client.post('/rides/bulk', data={'action': action, 'id': ids, 'back': '/dashboard', **form})


def test_delete_mixes_rides_and_workouts_and_refreshes_once(client):
    r = bulk(client, 'delete', ['r1', 'r2', 'wk1', 'garmin_9', 'nope'])
    assert r.status_code == 302 and r.headers['Location'].endswith('/dashboard')
    assert [x[0] for x in q(client, 'SELECT id FROM Activity ORDER BY id')] == ['r3', 'r4']
    assert q(client, f'SELECT COUNT(*) FROM Activity WHERE NOT {RIDE_SQL}')[0][0] == 0
    with client.application.app_context():
        db = database.get_db()
        assert duplicates.is_deleted(db, 'r1') and duplicates.is_deleted(db, 'garmin_9')     # a re-sync won't bring them back
    assert client.pushed.count('ride') == 1 and client.pushed.count('workout') == 1
    with client.session_transaction() as s:
        assert 'Deleted 4 activities. 1 could not be changed.' in str(s.get('_flashes'))


def test_change_type_bike_rider_rename_and_flags(client):
    bulk(client, 'sport', ['r1', 'wk1'], sport='VirtualRide')
    assert q(client, "SELECT sportType FROM Activity WHERE id='r1'")[0][0] == 'VirtualRide'
    assert q(client, "SELECT COUNT(*) FROM Activity WHERE sportType='VirtualRide'")[0][0] == 2          # the walk became an indoor ride

    bulk(client, 'bike', ['r2', 'r3'], bike='1')
    assert {x[0] for x in q(client, "SELECT bikeId FROM Activity WHERE id IN ('r2','r3')")} == {1}
    bulk(client, 'bike', ['r2'], bike='2')                                                            # Sam's bike: not Tom's ride
    assert q(client, "SELECT bikeId FROM Activity WHERE id='r2'")[0][0] == 1

    bulk(client, 'rider', ['r3'], rider='2')
    assert tuple(q(client, "SELECT riderId, bikeId FROM Activity WHERE id='r3'")[0]) == (2, None)

    bulk(client, 'rename', ['r2', 'r3'], name='  Commute  ')
    assert {x[0] for x in q(client, "SELECT name FROM Activity WHERE id IN ('r2','r3')")} == {'Commute'}

    bulk(client, 'dismiss', ['r4'])
    assert tuple(q(client, "SELECT flagReason, flagDismissed FROM Activity WHERE id='r4'")[0]) == (None, 1)


def test_bad_input_changes_nothing(client):
    bulk(client, 'sport', ['r1'], sport='Quidditch')
    bulk(client, 'rider', ['r1'], rider='99')
    bulk(client, 'rename', ['r1'], name='  ')
    bulk(client, 'explode', ['r1'])
    assert tuple(q(client, "SELECT sportType, riderId, name FROM Activity WHERE id='r1'")[0]) == ('Ride', 1, 'Ride')


def test_download_is_a_zip_of_gpx_files_in_utc(client):
    r = client.post('/rides/bulk/download', data={'id': ['r1', 'r2', 'wk1']})
    assert r.status_code == 200 and r.mimetype == 'application/zip'
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert sorted(z.namelist()) == ['2026-07-01_Ride.gpx', '2026-07-02_Ride.gpx']          # the walk has no track
    gpx = z.read('2026-07-01_Ride.gpx').decode()
    assert '<time>2026-07-01T07:00:00Z</time>' in gpx                                     # 08:00 BST is 07:00 UTC, not 08:00Z


def test_options_and_the_lists_offer_select_mode(client):
    d = client.get('/rides/bulk/options').get_json()
    assert [r['name'] for r in d['riders']] == ['Tom', 'Sam'] and d['riders'][0]['bikes'] == [{'id': 1, 'name': 'Road bike'}]
    assert {'value': 'VirtualRide', 'label': 'Indoor ride'} in d['sports']
    for url, row in (('/dashboard', 'data-history-from="2026-07-01"'), ('/workouts', 'data-pick="wk1"'), ('/riders/1', 'data-pick="r1"')):
        html = client.get(url).get_data(as_text=True)
        assert 'data-pick-toggle' in html and row in html and 'id="bulkBar"' in html, url
    # The dashboard draws only the open month; July's rows come from /dashboard/history when it is opened, ready to pick.
    html = client.get('/dashboard/history?from=2026-07-01&to=2026-07-31').get_data(as_text=True)
    assert 'data-pick="r1"' in html and 'data-pick="wk1"' in html
