"""The iPhone app's sport and bike choice: e-bike GPX types, the bike list in /ping, a chosen bike on upload, and changing a ride's bike."""
from datetime import datetime, timedelta, timezone

import pytest

import database
from services.parser import _map_sport


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def gpx(kind='cycling', start=datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc), seconds=120, step=0.00005):
    """A short straight track, as the app's GPXWriter writes it."""
    pts = ''.join(f'<trkpt lat="{51.5 + i * step:.7f}" lon="-0.1000000"><ele>10.0</ele>'
                  f'<time>{(start + timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>' for i in range(seconds))
    return (f'<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="Headwind iOS" xmlns="http://www.topografix.com/GPX/1/1">'
            f'<trk><name>Morning Ride</name><type>{kind}</type><trkseg>{pts}</trkseg></trk></gpx>').encode()


@pytest.fixture
def phone(tmp_path, monkeypatch):
    import app as app_module
    import config
    from services import credentials
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'app.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.setattr('services.weather.fetch_weather', lambda *a, **k: None)
    app = app_module.create_app()
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (2, 'Sam', 0)")
        d.executemany("INSERT INTO Bike (id, riderId, name, kind, archived) VALUES (?,?,?,?,?)",
                      [(1, 1, 'Roadie', 'road', 0), (2, 1, 'Zappy', 'ebike', 0), (3, 1, 'Old one', 'mtb', 1), (4, 2, "Sam's", 'road', 0)])
        d.execute('UPDATE Rider SET defaultBikeId=1 WHERE id=1')
        d.commit()
        av = credentials.auth_version()
    web = app.test_client()
    with web.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    token = web.post('/phones/create', json={'name': 'iPhone', 'server_url': 'https://h.example'}).get_json()['token']
    c = app.test_client()
    c.app_, c.H = app, {'Authorization': 'Bearer ' + token}
    return c


def upload(phone, data, **fields):
    from io import BytesIO
    return phone.post('/api/v1/rides', headers=phone.H, content_type='multipart/form-data',
                      data={'file': (BytesIO(data), 'Morning Ride.gpx'), **fields})


def activity(phone, rid):
    with phone.app_.app_context():
        return dict(database.get_db().execute('SELECT sportType, bikeId FROM Activity WHERE id=?', [rid]).fetchone())


def test_ebike_gpx_types():
    assert {_map_sport(t) for t in ('ebike', 'E-Bike', 'e_bike', 'EBikeRide')} == {'EBikeRide'}
    assert _map_sport('cycling') == 'Ride'


def test_ping_lists_the_riders_bikes(phone):
    bikes = phone.get('/api/v1/ping', headers=phone.H).get_json()['bikes']
    assert bikes == [{'id': 1, 'name': 'Roadie', 'kind': 'road', 'is_default': True},
                     {'id': 2, 'name': 'Zappy', 'kind': 'ebike', 'is_default': False}]      # not the archived one, not Sam's


def test_upload_without_a_bike_gets_the_default(phone):
    r = upload(phone, gpx())
    assert r.status_code == 200 and r.get_json()['status'] == 'imported'
    assert activity(phone, r.get_json()['ride']['id']) == {'sportType': 'Ride', 'bikeId': 1}


def test_upload_on_a_chosen_bike_and_as_an_ebike_ride(phone):
    r = upload(phone, gpx('ebike'), bike_id='2')
    assert activity(phone, r.get_json()['ride']['id']) == {'sportType': 'EBikeRide', 'bikeId': 2}


def test_a_bike_that_isnt_available_falls_back_to_the_default(phone):
    for n, bad in enumerate(('3', '4', '99', 'abc')):                                  # archived, another rider's, gone, nonsense
        r = upload(phone, gpx(start=datetime(2026, 10, 1 + n, 8, 0, tzinfo=timezone.utc)), bike_id=bad)
        assert r.status_code == 200 and activity(phone, r.get_json()['ride']['id'])['bikeId'] == 1


def test_change_a_rides_bike(phone):
    rid = upload(phone, gpx()).get_json()['ride']['id']
    r = phone.post(f'/api/v1/rides/ride/{rid}/bike', json={'bike_id': 2}, headers=phone.H)
    assert r.status_code == 200 and r.get_json() == {'id': rid, 'bike_id': 2} and activity(phone, rid)['bikeId'] == 2
    assert phone.post(f'/api/v1/rides/ride/{rid}/bike', json={'bike_id': None}, headers=phone.H).get_json()['bike_id'] is None
    assert activity(phone, rid)['bikeId'] is None
    for bad in (3, 4, True, 'x'):
        assert phone.post(f'/api/v1/rides/ride/{rid}/bike', json={'bike_id': bad}, headers=phone.H).status_code == 400
    assert phone.post('/api/v1/rides/ride/nope/bike', json={'bike_id': 1}, headers=phone.H).status_code == 404
    assert phone.post(f'/api/v1/rides/ride/{rid}/bike', json={'bike_id': 1}).status_code == 401


def test_walks_have_no_bike(phone):
    from io import BytesIO
    r = phone.post('/api/v1/workouts', headers=phone.H, content_type='multipart/form-data',
                   data={'file': (BytesIO(gpx('walking', step=0.00001)), 'Morning Walk.gpx'), 'sport': 'Walk', 'client_id': 'abc', 'source': 'ios'})
    assert r.status_code == 201
    wid = r.get_json()['workout']['id']
    assert activity(phone, wid) == {'sportType': 'Walk', 'bikeId': None}
    with phone.app_.app_context():
        assert database.get_db().execute('SELECT source FROM Activity WHERE id=?', [wid]).fetchone()[0] == 'ios'
    assert phone.post(f'/api/v1/rides/workout/{wid}/bike', json={'bike_id': 1}, headers=phone.H).status_code == 400
