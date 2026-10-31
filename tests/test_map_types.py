"""The shared map types: the optional keys in Settings → Maps, the HD export's tile proxy for every layer (services/map_tiles.py), and the
activity page's chart points carrying their place in the streams for the map. Full app, throwaway DB, no network."""
import io
import json
import re
import sqlite3

import polyline
import pytest
from PIL import Image

import app as app_module
import config
import database
from services import credentials, map_tiles, vault


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


N = 600
STREAMS = {'latlng': {'data': [[51.5 + i * 0.0001, -0.12] for i in range(N)]}, 'distance': {'data': [i * 11.1 for i in range(N)]},
           'altitude': {'data': [10 + i % 50 for i in range(N)]}, 'time': {'data': list(range(N))},
           'heartrate': {'data': [120] * N}}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    a = app_module.create_app()
    with a.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        db.execute("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal, distance, movingTime, rawData, streams) "
                   "VALUES ('gps', 'GPS', 'Ride', 1, '2026-10-01T08:00:00', 6650, 600, '{}', ?)", [json.dumps(STREAMS)])
        # an older activity with only the summary polyline for its map
        db.execute("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal, distance, movingTime, rawData, summaryPolyline) "
                   "VALUES ('poly', 'Poly', 'Ride', 1, '2026-10-02T08:00:00', 5000, 600, '{}', ?)",
                   [polyline.encode([(51.5, -0.12), (51.52, -0.12), (51.52, -0.10)])])
        db.commit()
    return a


@pytest.fixture
def client(app):
    c = app.test_client()
    with app.app_context():
        av = credentials.auth_version()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _keys(client):
    return json.loads(re.search(r'window\.MAP_KEYS = (\{.*?\});', client.get('/heatmap').get_data(as_text=True)).group(1))


def test_map_keys_are_sealed_kept_when_blank_and_removable(client):
    assert _keys(client) == {'thunderforest': '', 'os': ''}
    client.post('/settings/maps', data={'thunderforestKey': 'tf-123', 'osMapsKey': 'os-456'})
    stored = sqlite3.connect(config.Config.DATABASE).execute('SELECT thunderforestKey, osMapsKey FROM Settings').fetchone()
    assert all(v.startswith(vault.PREFIX) for v in stored)                  # encrypted in the database
    assert _keys(client) == {'thunderforest': 'tf-123', 'os': 'os-456'}     # and given to the maps as they are
    client.post('/settings/maps', data={'thunderforestKey': '', 'osMapsKey': ''})
    assert _keys(client) == {'thunderforest': 'tf-123', 'os': 'os-456'}     # blank keeps them
    client.post('/settings/maps', data={'thunderforestKey': '', 'osMapsKey': '', 'clear_os': 'on'})
    assert _keys(client) == {'thunderforest': 'tf-123', 'os': ''}


def _png(colour):
    out = io.BytesIO()
    Image.new('RGBA', (256, 256), colour).save(out, 'PNG')
    return out.getvalue()


class _Resp:
    def __init__(self, content, status=200):
        self.content, self.status_code, self.headers = content, status, {'Content-Type': 'image/png'}


def test_tile_proxy_covers_the_new_layers(app, client, monkeypatch):
    got = []

    def fake_get(url, timeout, headers):
        got.append((url, headers['User-Agent']))
        return _Resp(_png((200, 0, 0, 255)))
    monkeypatch.setattr(map_tiles.requests, 'get', fake_get)

    assert client.get('/heatmap/tile/14/8186/5448?layer=cyclosm').status_code == 200
    assert got[-1][0] == 'https://a.tile-cyclosm.openstreetmap.fr/cyclosm/14/8186/5448.png'
    assert 'Headwind' in got[-1][1] and 'github.com' in got[-1][1]          # says who's asking, as the OSM-based servers ask

    # past OpenTopoMap's last zoom (17): the parent tile, enlarged, rather than its "max zoom" picture
    r = client.get('/heatmap/tile/19/261989/174358?layer=opentopo')
    assert r.status_code == 200 and r.mimetype == 'image/png'
    assert got[-1][0] == f'https://a.tile.opentopomap.org/17/{261989 >> 2}/{174358 >> 2}.png'
    assert Image.open(io.BytesIO(r.data)).size == (256, 256)

    # Esri's tile URLs are row before column
    client.get('/heatmap/tile/12/1/2?layer=topo')
    assert got[-1][0].endswith('/World_Topo_Map/MapServer/tile/12/2/1')

    # OS: nothing without a key, then with it; never past the free zooms, never below its first
    n = len(got)
    assert client.get('/heatmap/tile/12/2045/1360?layer=os').status_code == 502 and len(got) == n
    client.post('/settings/maps', data={'osMapsKey': 'os-456'})
    assert client.get('/heatmap/tile/12/2045/1360?layer=os').status_code == 200
    assert got[-1][0] == 'https://api.os.uk/maps/raster/v1/zxy/Outdoor_3857/12/2045/1360.png?key=os-456'
    client.get('/heatmap/tile/18/130944/87040?layer=os')
    assert '/Outdoor_3857/16/32736/21760.png' in got[-1][0]
    n = len(got)
    assert client.get('/heatmap/tile/5/15/10?layer=os').status_code == 502 and len(got) == n

    # Thunderforest's terms forbid proxies: not a layer here at all, and nor is anything unknown
    for name in ('tf_cycle', 'thunderforest', 'nope'):
        assert client.get(f'/heatmap/tile/12/1/2?layer={name}').status_code == 502
    assert len(got) == n


def test_tile_proxy_passes_on_a_failure(client, monkeypatch):
    monkeypatch.setattr(map_tiles.requests, 'get', lambda url, timeout, headers: _Resp(b'', 404))
    assert client.get('/heatmap/tile/14/8186/5448?layer=wmt_mtb').status_code == 502


def _page_json(html, name):
    return json.loads(re.search(name + r' = (.*?);\n', html).group(1))


def test_chart_points_carry_their_place_in_the_streams(client):
    html = client.get('/rides/gps').get_data(as_text=True)
    assert 'COORDS_FROM_STREAM = true' in html
    elev = json.loads(re.search(r"makeElevHrChart\('elevChart', (\{.*?\}), \{", html).group(1))
    assert len(elev['idx']) == len(elev['values']) == len(elev['labels'])
    assert elev['idx'][:3] == [0, 2, 4]                                     # every 2nd of 600 points: at most 300
    assert _page_json(html, 'var dist')[:3] == [0.0, 11.1, 22.2]            # the distance stream, for the distance markers


def test_a_polyline_track_is_matched_by_distance(client):
    html = client.get('/rides/poly').get_data(as_text=True)
    assert 'COORDS_FROM_STREAM = false' in html
    assert _page_json(html, 'var dist') is None                             # worked out from the points, stretched to the 5 km
    assert 'dist.map(function (d) { return d * total / last; })' in html
