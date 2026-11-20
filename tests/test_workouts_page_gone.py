"""The Workouts page went into the Activities page: /workouts lands there with the rides left out, a walk's page links back to Activities and is
deleted and re-typed through the same routes as a ride, and an activity is added by hand from the Activities page. Full app, throwaway DB."""
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

import app as app_module
import config
import database
from services import credentials


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)       # no MQTT / Garmin / friend background loops
    app = app_module.create_app()
    day = (date.today() - timedelta(days=1)).isoformat() + 'T08:00:00'
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (2, 'Kim', 0)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (3, 'Sam', 0)")                   # synced from a friend
        db.execute("INSERT INTO Friend (name, url, token, riderId) VALUES ('Sam', 'https://sam.example', 't', 3)")
        for aid, sport in (('ride1', 'Ride'), ('ebike1', 'EBikeRide'), ('walk1', 'Walk'), ('run1', 'Run')):
            db.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDate, startDateLocal, distance, movingTime, elapsedTime, calories) "
                       "VALUES (?,?,?,?,1,?,?,5000,3600,3600,300)", [aid, aid.title(), sport, sport, day, day])
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _sports(client):
    with client.application.app_context():
        return dict(database.get_db().execute('SELECT id, sportType FROM Activity').fetchall())


def test_workouts_lands_on_activities_with_the_rides_left_out(client):
    r = client.get('/workouts?q=wa&from=2020-01-01')
    url = urlsplit(r.headers['Location'])
    assert r.status_code == 302 and url.path == '/activities'
    assert parse_qs(url.query) == {'q': ['wa'], 'from': ['2020-01-01'], 'skip': ['EBikeRide', 'Ride']}
    page = client.get(r.headers['Location']).get_data(as_text=True)
    assert 'data-pick="walk1"' in page and 'data-pick="ride1"' not in page
    assert parse_qs(urlsplit(client.get('/workouts?sport=Run').headers['Location']).query) == {'sport': ['Run']}
    assert 'href="/workouts"' not in page, 'not in the sidebar'


def test_a_walk_links_back_to_activities_and_uses_the_ride_routes(client):
    page = client.get('/activities/walk1').get_data(as_text=True)
    assert '<a href="/activities">Activities</a>' in page
    assert 'action="/activities/walk1/delete"' in page and 'action="/activities/walk1/sport"' in page

    r = client.post('/activities/walk1/sport', data={'sport': 'Run'})
    assert r.headers['Location'].endswith('/activities/walk1') and _sports(client)['walk1'] == 'Run'
    r = client.post('/activities/run1/sport', data={'sport': 'Ride'})                 # and on to a ride
    assert r.headers['Location'].endswith('/activities/run1') and _sports(client)['run1'] == 'Ride'

    client.get('/activities?q=walk')
    r = client.post('/activities/walk1/delete')
    assert r.headers['Location'] == '/activities?q=walk', 'back to the list it was opened from'
    assert 'walk1' not in _sports(client)
    with client.application.app_context():
        assert database.get_db().execute("SELECT COUNT(*) FROM ActivityDuplicate WHERE id='walk1'").fetchone()[0] == 1


def test_an_activity_added_by_hand_on_the_activities_page(client):
    page = client.get('/activities').get_data(as_text=True)
    assert 'action="/activities/new"' in page and '1,200 kcal' in page
    form = {'sport': 'Run', 'date': (date.today() - timedelta(days=2)).isoformat(), 'time': '07:00', 'hours': '0', 'minutes': '40', 'distance': '5', 'unit': 'km'}
    r = client.post('/activities/new', data=form)
    assert r.status_code == 302 and r.headers['Location'] == '/activities'
    with client.application.app_context():
        row = database.get_db().execute("SELECT riderId, distance, movingTime FROM Activity WHERE sportType='Run' AND id NOT IN ('run1')").fetchone()
    assert tuple(row) == (1, 5000, 2400)

    r = client.post('/activities/new', data=dict(form, rider='2'))               # added from Kim's list: Kim's
    assert r.headers['Location'] == '/activities?rider=2'
    with client.application.app_context():
        assert database.get_db().execute("SELECT COUNT(*) FROM Activity WHERE riderId=2").fetchone()[0] == 1

    r = client.post('/activities/new', data=dict(form, date='2999-01-01'))
    assert 'error=' in r.headers['Location']
    assert 'Could not add that: that is in the future' in client.get(r.headers['Location']).get_data(as_text=True)


def test_a_friends_list_offers_no_form_and_refuses_one(client):
    assert 'action="/activities/new"' not in client.get('/activities?rider=3').get_data(as_text=True)
    r = client.post('/activities/new', data={'rider': '3', 'sport': 'Run', 'date': date.today().isoformat(), 'minutes': '30', 'distance': '5'})
    assert 'error=' in r.headers['Location']
    with client.application.app_context():
        assert database.get_db().execute("SELECT COUNT(*) FROM Activity WHERE riderId=3").fetchone()[0] == 0
