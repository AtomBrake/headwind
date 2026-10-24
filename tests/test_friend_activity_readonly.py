"""A friend's activity (synced through their feed) is only shown here: its page has no controls for changing it, and every route that changes an
activity refuses one (services/friend_rides.py). Full app, throwaway DB."""
import json

import pytest

import app as app_module
import config
import database
from services import credentials

TRACK = json.dumps({'latlng': {'data': [[51.5 + i * 1e-4, -2.6] for i in range(50)]}, 'time': {'data': list(range(0, 500, 10))},
                    'altitude': {'data': [10.0] * 50}})
CONTROLS = ('id="typeCard"', 'id="commuteBox"', 'id="rideNotes"', 'id="kudosCard"', 'id="scanBtn"', 'id="wxSelect"', 'Add photos',
            '/delete"', 'name="bike"')


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.setattr('services.mqtt.push_update', lambda *a, **k: None)
    monkeypatch.setattr('services.mqtt.push_update_nutrition', lambda *a, **k: None)
    app = app_module.create_app()
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1), (2, 'Sam', 0)")
        db.execute("INSERT INTO Friend (id, name, url, token, riderId, lastSynced) VALUES (1, 'Sam', 'https://sam.example', 't', 2, '2026-10-20 08:00:00')")
        db.execute("INSERT INTO Bike (id, riderId, name, kind) VALUES (1, 1, 'Road bike', 'road'), (2, 2, 'A bike for Sam', 'road')")
        db.execute("INSERT INTO Kit (id, riderId, name, kind) VALUES (1, 2, 'Shoes for Sam', 'shoes')")
        for aid, rider, sport in (('r1', 1, 'Ride'), ('f1_r1', 2, 'Ride'), ('f1_w1', 2, 'Run')):
            db.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDate, startDateLocal, distance, movingTime, elapsedTime, streams, "
                       "flagReason, rawData, updatedAt) VALUES (?, 'Morning', ?, ?, ?, '2026-10-19T07:00:00', '2026-10-19T08:00:00', 20000, 3600, 3600, ?, "
                       "'only 45 m long', '{}', '2026-10-20 08:00:00')", [aid, sport, sport, rider, TRACK])
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def row(client, aid):
    with client.application.app_context():
        r = database.get_db().execute('SELECT * FROM Activity WHERE id=?', [aid]).fetchone()
        return dict(r) if r else None


def test_a_friends_ride_page_says_whose_it_is_and_offers_no_changes(client):
    page = client.get('/rides/f1_r1').get_data(as_text=True)
    assert "Sam's ride" in page and 'their instance' in page
    assert [c for c in CONTROLS if c in page] == []
    assert 'This ride looks wrong' not in page          # the flag's buttons dismiss or delete it
    assert 'id="map"' in page and '/rides/f1_r1/gpx' in page      # what's read-only stays


def test_a_friends_run_page_offers_no_gear(client):
    page = client.get('/rides/f1_w1').get_data(as_text=True)
    assert "Sam's activity" in page
    assert 'id="kitCard"' not in page and '/workouts/f1_w1/delete' not in page


def test_your_own_ride_page_still_has_every_control(client):
    page = client.get('/rides/r1').get_data(as_text=True)
    assert [c for c in CONTROLS if c not in page] == []
    assert 'id="friendCard"' not in page


@pytest.mark.parametrize('path, data', [
    ('/rides/f1_r1/delete', {}),
    ('/rides/f1_r1/sport', {'sport': 'EBikeRide'}),
    ('/rides/f1_r1/commute', {'commute': '1'}),
    ('/rides/f1_r1/notes', {'notes': 'mine now'}),
    ('/rides/f1_r1/weather', {'condition': 'Rain'}),
    ('/rides/f1_r1/flag/dismiss', {}),
    ('/rides/f1_r1/scan', {}),
    ('/rides/f1_r1/photos', {}),
    ('/rides/f1_r1/kudos', {}),
])
def test_changing_a_friends_ride_is_refused(client, path, data):
    before = row(client, 'f1_r1')
    assert client.post(path, data=data).status_code == 403
    assert row(client, 'f1_r1') == before


def test_a_bike_or_kit_on_a_friends_activity_is_refused(client):
    client.post('/gear/ride/f1_r1/bike', data={'bike': 2})
    client.post('/gear/activity/f1_w1/kit', data={'kit': 1})
    assert row(client, 'f1_r1')['bikeId'] is None
    assert row(client, 'f1_w1')['kitId'] is None


def test_a_segment_from_a_friends_ride_is_refused(client):
    r = client.post('/segments/create', data={'name': 'Hill', 'startLat': 51.5, 'startLng': -2.6, 'endLat': 51.504, 'endLng': -2.6,
                                              'distanceM': 450, 'activityId': 'f1_r1'})
    assert r.status_code == 403


def test_a_bulk_action_skips_a_friends_activities_and_says_so(client):
    r = client.post('/rides/bulk', data={'action': 'rename', 'id': ['r1', 'f1_r1', 'f1_w1'], 'name': 'Renamed', 'back': '/dashboard'},
                    follow_redirects=True)
    assert row(client, 'r1')['name'] == 'Renamed'
    assert row(client, 'f1_r1')['name'] == row(client, 'f1_w1')['name'] == 'Morning'
    assert "2 are friends&#39; activities, changed only on their instance." in r.get_data(as_text=True)
    client.post('/rides/bulk', data={'action': 'delete', 'id': ['f1_r1'], 'back': '/dashboard'})
    assert row(client, 'f1_r1')


def test_the_bulk_type_change_skips_a_friends_activities(client):
    client.post('/rides/bulk-sport', data={'sport': 'EBikeRide', 'ids': 'r1,f1_r1', 'back': '/dashboard'})
    assert row(client, 'r1')['sportType'] == 'EBikeRide'
    assert row(client, 'f1_r1')['sportType'] == 'Ride'
