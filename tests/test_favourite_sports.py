"""Favourite sports (services/favourites.py): picked in Settings → Display, each one a sidebar item under Activities that opens the list with only that
sport or group, by what it keeps (group=ride, only=Run: services/sport_filter.py) so a sport first done later joins in. Full app, throwaway DB."""
import re
from datetime import date

import pytest

import app as app_module
import config
import database
from services import credentials, favourites


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def _add(db, aid, sport, day='2026-10-01'):
    db.execute("INSERT INTO Activity (id, name, riderId, sportType, startDateLocal, distance, movingTime) VALUES (?, ?, 1, ?, ?, 10000, 3600)",
               [aid, aid, sport, f'{day}T08:00:00'])


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        for aid, sport in (('road', 'Ride'), ('zwift', 'VirtualRide'), ('run', 'Run'), ('walk', 'Walk'), ('swim', 'Swim'), ('yoga', 'Yoga')):
            _add(db, aid, sport)
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _sidebar(html):
    return re.findall(r'<a href="([^"]+)" class="nav-item nav-sub ?(active)?">\s*<span class="nav-emoji"[^>]*>[^<]*</span> ([^<]+?)\s*</a>', html)


def _listed(html):
    return set(re.findall(r'href="/activities/(\w+)"', html))


def _saved(client):
    with client.application.app_context():
        return favourites.parse(database.get_db().execute('SELECT favouriteSports FROM Settings WHERE id=1').fetchone()[0])


def _pick(client, *keys):
    return client.post('/settings/', data={'favouritesShown': '1', 'favourite': list(keys), 'units': 'imperial'})


def test_the_choices_are_the_groups_then_each_sport(client):
    page = client.get('/settings/').get_data(as_text=True)
    keys = re.findall(r'name="favourite" value="([^"]+)"', page)
    assert keys[:3] == ['group:ride', 'group:foot', 'group:swim']
    assert {'sport:Ride', 'sport:VirtualRide', 'sport:Run', 'sport:Walk', 'sport:Swim', 'sport:Yoga'} == set(keys[3:])


def test_a_favourite_adds_its_item_and_opens_only_that_sport(client):
    assert _sidebar(client.get('/dashboard').get_data(as_text=True)) == []
    assert _pick(client, 'group:ride', 'sport:Run').status_code == 302
    html = client.get('/dashboard').get_data(as_text=True)
    assert _sidebar(html) == [('/activities?group=ride', '', 'Cycling'), ('/activities?only=Run', '', 'Run')]
    rides = client.get('/activities?group=ride').get_data(as_text=True)
    assert _listed(rides) == {'road', 'zwift'}
    assert _sidebar(rides)[0][1] == 'active' and not re.search(r'class="nav-item active">\s*<svg[^>]*>.*?</svg> Activities', rides, re.S)
    assert _listed(client.get('/activities?only=Run').get_data(as_text=True)) == {'run'}                # runs without the walks
    for more in ('q=road', 'power=1', 'sort=distance', 'only=Run'):                                  # another filter on: not highlighted
        assert _sidebar(client.get(f'/activities?group=ride&{more}').get_data(as_text=True))[0][1] == '', more
    assert _sidebar(client.get('/activities?group=ride&q=&power=&commute=only').get_data(as_text=True))[0][1] == 'active'   # empty fields


def test_a_sport_first_done_later_joins_its_group(client):
    _pick(client, 'group:ride')
    with client.application.app_context():
        db = database.get_db()
        _add(db, 'gravel', 'GravelRide', day='2026-10-02')
        db.commit()
    assert _listed(client.get('/activities?group=ride').get_data(as_text=True)) == {'road', 'zwift', 'gravel'}


def test_links_on_a_favourites_list_keep_saying_what_it_keeps(client):
    html = client.get('/activities?group=ride').get_data(as_text=True)
    assert 'name="group" value="ride" data-keep' in html                  # the search form keeps it until a box is changed
    assert 'skip=Run' not in html
    assert 'href="/activities?group=foot"' in html                        # the "Only on foot" shortcut says what it keeps too


def test_removing_a_favourite_takes_the_item_away_and_junk_is_dropped(client):
    _pick(client, 'group:ride', 'sport:Run')
    _pick(client, 'sport:Run', 'group:nonsense', 'other:thing', 'sport:Run')
    assert _saved(client) == ['sport:Run']
    assert [l for _, _, l in _sidebar(client.get('/dashboard').get_data(as_text=True))] == ['Run']
    client.post('/settings/', data={'units': 'metric'})                   # another card of the page: the favourites stay
    assert _saved(client) == ['sport:Run']
    _pick(client)
    assert _sidebar(client.get('/dashboard').get_data(as_text=True)) == []


def test_the_phone_app_gets_them_from_ping(client):
    _pick(client, 'group:foot', 'sport:Swim')
    from routes import api_v1
    with client.application.test_request_context('/api/v1/ping'):          # the view itself: the device token check is tested elsewhere
        body = api_v1.ping().get_json()
    assert body['favourite_sports'] == [{'label': 'On foot', 'icon': '🏃', 'group': 'foot'}, {'label': 'Swim', 'icon': '🏊', 'sport': 'Swim'}]
