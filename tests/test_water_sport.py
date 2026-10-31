"""Strava's "Water Sport" (whitewater kayaking, in one export) is on the water: no climb, no stops cut from its moving time, a boat for an icon,
and nothing added to the dashboard's Total Elevation. A kayak trip can be changed to any sport, not only a ride or one on foot. Full app."""
import json
from datetime import date

import pytest

import app as app_module
import config
import database
from services import credentials, parser, sports


def test_water_sport_is_on_the_water():
    assert sports.on_water('Water Sport') and not sports.has_climbing('Water Sport') and sports.icon('Water Sport') == '🛶'
    assert parser.pick_moving_time(7000, 3000, 7644, 'Water Sport') == 7000          # drifting isn't a stop
    assert parser.pick_moving_time(7000, 3000, 7644, 'Ride') == 3000


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    today = date.today().isoformat()
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("UPDATE Settings SET units='metric' WHERE id=1")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        for aid, sport, climb in (('k', 'Water Sport', 5249), ('r', 'Ride', 300)):
            db.execute("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal, distance, movingTime, elapsedTime, totalElevationGain) "
                       "VALUES (?, ?, ?, 1, ?, 30000, 7000, 7600, ?)", [aid, aid, sport, today + 'T09:00:00', climb])
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def test_a_kayak_trip_adds_no_climb_to_the_dashboard(client):
    html = client.get('/dashboard').get_data(as_text=True)
    assert '300 m' in html and '5,549' not in html and '5,249' not in html


def test_a_kayak_trip_can_be_any_sport(client):
    html = client.get('/rides/k').get_data(as_text=True)
    assert '<option value="Paddle"' in html and '<option value="Ski"' in html and 'Elevation Gain' not in html
