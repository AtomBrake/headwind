"""Zwift maps: a virtual ride is drawn over its Zwift world's map (services/zwift), on its own page and on the heatmap, and the heatmap leaves
virtual rides out unless asked (the Zwift rides switch: out, in or only). Full app, throwaway DB."""
import json
import re

import pytest

import app as app_module
import config
import database
from services import credentials, sports, zwift


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def _streams(lat0, lng0):
    return json.dumps({'latlng': {'data': [[lat0 + i * 0.0002, lng0 + i * 0.0002] for i in range(60)]}})


RIDES = (('road', 'Ride', 51.50, -0.12),                    # a real ride in London: inside Zwift's London box, but not a Zwift ride
         ('watopia', 'VirtualRide', -11.70, 166.95),
         ('makuri', 'Virtual Ride', -10.80, 165.82),        # Strava's spelling
         ('zlondon', 'VirtualRide', 51.49, -0.12),
         ('nowhere', 'VirtualRide', 10.0, 10.0))           # another platform's made-up place: no world, the normal map


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        for aid, sport, lat0, lng0 in RIDES:
            db.execute("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal, distance, movingTime, rawData, streams) "
                       "VALUES (?, ?, ?, 1, '2026-10-01T08:00:00', 20000, 3600, '{}', ?)", [aid, aid, sport, _streams(lat0, lng0)])
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def test_world_of_a_track_box():
    assert zwift.world_of(-11.70, -11.65, 166.93, 166.97)['slug'] == 'watopia'
    assert zwift.world_of(-10.40, -10.37, 165.79, 165.81)['slug'] == 'crit-city'
    assert zwift.world_of(51.49, 51.51, -0.15, -0.07)['slug'] == 'london'
    assert zwift.world_of(51.40, 51.60, -0.30, 0.10) is None            # bigger than the world: a real ride across London
    assert zwift.world_of(None, None, None, None) is None
    assert len({w['slug'] for w in zwift.WORLDS}) == len(zwift.WORLDS)


def test_virtual_sports():
    assert sports.is_virtual('VirtualRide') and sports.is_virtual('Virtual Ride') and sports.is_virtual('VirtualRun')
    assert not sports.is_virtual('Ride') and not sports.is_virtual(None)


def _data(client, **args):
    d = client.get('/heatmap/data', query_string=args).get_json()
    assert d['count'] == len(d['tracks']) == len(d['riders']) == len(d['worlds'])
    return d


def test_heatmap_leaves_virtual_rides_out_unless_asked(client):
    assert _data(client)['worlds'] == [None]                             # the real ride only
    assert sorted(w or '' for w in _data(client, virtual='in')['worlds']) == ['', '', 'london', 'makuri-islands', 'watopia']
    only = _data(client, virtual='only')
    assert only['count'] == 4 and sorted(w or '' for w in only['worlds']) == ['', 'london', 'makuri-islands', 'watopia']


def test_heatmap_page_has_the_zwift_switch(client):
    html = client.get('/heatmap').get_data(as_text=True)
    assert 'id="virtualFilter"' in html
    sport_menu = re.search(r'id="sportFilter".*?</select>', html, re.S).group(0)
    assert 'Virtual' not in sport_menu                                   # the switch covers them
    worlds = json.loads(re.search(r'var ZWIFT_WORLDS = (.*);', html).group(1))
    assert worlds['watopia']['madeUp'] and not worlds['london']['madeUp']


def test_no_zwift_switch_without_virtual_rides(client):
    with client.application.app_context():
        db = database.get_db()
        db.execute(f"DELETE FROM Activity WHERE {sports.virtual_sql()}")
        db.commit()
    assert 'id="virtualFilter"' not in client.get('/heatmap').get_data(as_text=True)


def test_ride_page_draws_the_world(client):
    html = client.get('/rides/watopia').get_data(as_text=True)
    assert '/heatmap/zwift/watopia.png' in html and 'L.imageOverlay' in html
    assert '/heatmap/zwift/london.png' in client.get('/rides/zlondon').get_data(as_text=True)
    for plain in ('road', 'nowhere'):                                    # a real ride in London, and a virtual one in no Zwift world
        assert '/heatmap/zwift/' not in client.get(f'/rides/{plain}').get_data(as_text=True), plain


def test_world_map_is_fetched_once(client, monkeypatch):
    calls = []

    class _Resp:
        status_code = 200
        content = b'\x89PNG fake'

    def fake_get(url, **kw):
        calls.append(url)
        return _Resp()

    monkeypatch.setattr(zwift, '_images', {})
    monkeypatch.setattr(zwift.requests, 'get', fake_get)
    for _ in range(2):
        r = client.get('/heatmap/zwift/watopia.png')
        assert r.status_code == 200 and r.data == b'\x89PNG fake' and r.mimetype == 'image/png'
    assert calls == ['https://cdn.zwift.com/static/images/maps/MiniMap_Watopia_2.png']
    assert client.get('/heatmap/zwift/atlantis.png').status_code == 404
