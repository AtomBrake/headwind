"""Looking at a recording that was set aside as a duplicate: on its own and side by side with the kept one. Full app, throwaway DB."""
import json

import pytest

import app as app_module
import config
import database
from services import credentials, duplicates


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def _streams(hr, mins=60, gps=False):
    s = {'time': {'data': [i * 60 for i in range(mins)]}, 'heartrate': {'data': [hr] * mins}}
    if gps:
        s['latlng'] = {'data': [[50.7 + i * 1e-4, -3.5] for i in range(mins)]}
    return json.dumps(s)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        for aid, hr, gps in (('garmin_1', 140, False), ('imp_2', 103, True)):
            db.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDateLocal, distance, movingTime, elapsedTime, averageHeartrate, streams) "
                       "VALUES (?, ?, 'Ride', 'Ride', 1, '2024-05-30T10:00:00', 0, 3602, 3602, ?, ?)", [aid, aid, hr, _streams(hr, gps=gps)])
        duplicates.park(db, 'imp_2', 'garmin_1', 'Kept the Garmin recording.')
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def test_ride_page_links_to_the_set_aside_recording(client):
    html = client.get('/rides/garmin_1').get_data(as_text=True)
    assert '/rides/garmin_1/duplicate/imp_2' in html and '/rides/garmin_1/duplicate/imp_2?compare=1' in html


def test_view_shows_only_the_set_aside_recording(client):
    r = client.get('/rides/garmin_1/duplicate/imp_2')
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert '103 bpm' in html and '140 bpm' not in html
    assert 'id="dupMap"' in html                                                     # it has a GPS track


def test_compare_shows_both_side_by_side(client):
    html = client.get('/rides/garmin_1/duplicate?compare=1').get_data(as_text=True)      # no id: the first one set aside
    assert '140 bpm' in html and '103 bpm' in html
    assert 'dup-differs' in html                                                      # the heart rates differ, so that row is marked


def test_unknown_or_unrelated_recording_is_not_found(client):
    assert client.get('/rides/garmin_1/duplicate/nope').status_code == 404
    assert client.get('/rides/imp_2/duplicate').status_code == 404


def test_a_zwift_ride_is_drawn_over_its_world(client):
    """The kept recording is a Zwift ride and the set-aside one (a watch's copy) a plain Ride: both are drawn over Watopia, not satellite tiles."""
    with app_module.create_app().app_context():
        db = database.get_db()
        db.execute("UPDATE Activity SET sportType='VirtualRide' WHERE id='garmin_1'")
        row = json.loads(db.execute("SELECT rowJson FROM ActivityDuplicate WHERE id='imp_2'").fetchone()[0])
        row['streams'] = json.dumps({'time': {'data': [0, 60]}, 'latlng': {'data': [[-11.65, 166.95], [-11.66, 166.96]]}})
        db.execute("UPDATE ActivityDuplicate SET rowJson=? WHERE id='imp_2'", [json.dumps(row)])
        db.commit()
    for url in ('/rides/garmin_1/duplicate/imp_2', '/rides/garmin_1/duplicate/imp_2?compare=1'):
        html = client.get(url).get_data(as_text=True)
        assert '/heatmap/zwift/watopia.png' in html and 'arcgisonline' not in html


def test_a_real_ride_keeps_the_satellite_map(client):
    html = client.get('/rides/garmin_1/duplicate/imp_2?compare=1').get_data(as_text=True)
    assert 'arcgisonline' in html and 'imageOverlay' not in html
