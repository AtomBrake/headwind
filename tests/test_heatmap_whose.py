"""The heatmap's Whose filter: the owner's rides by default, one friend's (or another rider's) on their own, or everyone's together, with
whose each track is so the page can colour them. Full app, throwaway DB."""
import json
import re

import pytest

import app as app_module
import config
import database
from services import credentials


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def _streams(lat0):
    return json.dumps({'latlng': {'data': [[lat0 + i * 0.0001, -0.12] for i in range(60)]}})


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)       # no MQTT / Garmin / friend background loops
    app = app_module.create_app()
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1), (2, 'Rachel', 0), (3, 'Quiet', 0)")
        db.execute("INSERT INTO Friend (id, name, url, riderId) VALUES (1, 'Rachel', 'http://example.invalid', 2), "
                   "(2, 'Quiet', 'http://example.invalid', 3)")
        for aid, rider, sport, lat0 in (('mine1', 1, 'Ride', 51.5), ('mine2', 1, 'Ride', 51.6), ('run', 1, 'Run', 51.7),
                                        ('f2_a', 2, 'Ride', 52.5), ('f2_b', 2, 'EBikeRide', 52.6)):
            db.execute("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal, distance, movingTime, rawData, streams) "
                       "VALUES (?, ?, ?, ?, '2026-10-01T08:00:00', 20000, 3600, '{}', ?)", [aid, aid, sport, rider, _streams(lat0)])
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _data(client, **args):
    d = client.get('/heatmap/data', query_string=args).get_json()
    assert d['count'] == len(d['tracks']) == len(d['riders'])
    return d


def test_mine_by_default_one_friend_or_everyone(client):
    assert _data(client)['riders'] == [1, 1]                             # the owner's rides only: not the friend's, and not the run
    assert _data(client, who='2')['riders'] == [2, 2]
    assert sorted(_data(client, who='all')['riders']) == [1, 1, 2, 2]
    assert _data(client, who='all', sport='ebike')['riders'] == [2]      # the other filters still apply
    assert _data(client, who='3')['count'] == 0
    hd = _data(client, who='all', hd='1')
    assert sorted(hd['riders']) == [1, 1, 2, 2]                          # the HD export's tracks are tagged too


def test_the_page_offers_the_owner_and_friends_with_rides(client):
    html = client.get('/heatmap').get_data(as_text=True)
    assert 'id="whoFilter"' in html
    friends = re.search(r'<optgroup label="Friends">(.*?)</optgroup>', html).group(1)
    assert 'Rachel' in friends and 'Quiet' not in friends              # a friend with nothing to draw isn't offered
    people = json.loads(re.search(r'var PEOPLE = (.*);', html).group(1))
    assert [p['name'] for p in people] == ['Tom', 'Rachel']


def test_no_picker_without_anyone_else(client):
    with client.application.app_context():
        db = database.get_db()
        db.execute("DELETE FROM Activity WHERE riderId = 2")
        db.commit()
    assert 'id="whoFilter"' not in client.get('/heatmap').get_data(as_text=True)
