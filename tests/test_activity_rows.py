"""Every list of activities draws the same row (templates/_activity_row.html): sport icon, name, date, distance, time, and speed or pace by sport.
Full app, throwaway DB."""
import re
from datetime import date, timedelta

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
        db.execute("INSERT INTO Bike (id, riderId, name, kind) VALUES (1, 1, 'Road bike', 'road')")
        db.execute("INSERT INTO Kit (id, riderId, kind, name) VALUES (1, 1, 'shoes', 'Pegasus')")
        for aid, sport, m, secs, bike, kit in (('ride1', 'Ride', 30000, 3600, 1, None), ('run1', 'Run', 10000, 3000, None, 1), ('walk1', 'Walk', 5000, 3600, None, None)):
            db.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDate, startDateLocal, distance, movingTime, elapsedTime, averageSpeed, "
                       "totalElevationGain, bikeId, kitId) VALUES (?,?,?,?,1,?,?,?,?,?,?,50,?,?)",
                       [aid, aid.title(), sport, sport, day, day, m, secs, secs, m / secs, bike, kit])
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _rows(html):
    """{activity id: the text of its row's second line}"""
    return {aid: re.sub(r'<[^>]+>', '', meta) for aid, meta in
            re.findall(r'<div class="act-row" data-pick="([^"]+)">.*?<div class="act-meta">(.*?)</div>', html, re.S)}


RATES = {'ride1': '18.6 mph', 'run1': '8:03 /mi', 'walk1': '19:19 /mi'}      # 30 km/h; 5:00 /km; 12:00 /km


@pytest.mark.parametrize('page, ids', [
    ('/dashboard', {'ride1', 'run1', 'walk1'}),
    ('/activities', {'ride1', 'run1', 'walk1'}),
    ('/activities?q=r', {'ride1', 'run1'}),
    ('/workouts', {'run1', 'walk1'}),
    ('/gear/bike/1', {'ride1'}),
    ('/gear/kit/1', {'run1'}),
    ('/riders/1', {'ride1'}),
])
def test_every_list_shows_the_same_row_with_speed_or_pace_by_sport(client, page, ids):
    rows = _rows(client.get(page).get_data(as_text=True))
    assert set(rows) == ids
    for aid in ids:
        assert RATES[aid] in rows[aid], (page, aid, rows[aid])
        assert re.search(r'\d+(\.\d)? mi · ', rows[aid])                # distance, then time
