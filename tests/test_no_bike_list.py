"""Activities with no gear, found and dealt with one by one: the Gear page's count (and one per type) links to the Activities page filtered to
them (gear=none, bike-none, kit-none), which keeps the history tree, a month at a time, with a picker on each row that comes back to the list;
and the calendar lists a picked day's rides so each can get its own bike. The same gear filter finds a bike's or a pair of shoes' activities.
Full app, throwaway DB."""
import re

import pytest

import app as app_module
import config
import database
from services import credentials, gear, kit


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)       # no MQTT / Garmin / friend background loops
    app = app_module.create_app()
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        road = gear.create_bike(db, 1, 'Roadie')
        gear.create_bike(db, 1, 'Mudder', kind='mtb')
        shoes = kit.create(db, 1, 'Trainers', sports_=['Run'])
        for aid, sport, start, bike, kit_id in (
                ('road_am', 'Ride', '2026-05-02T08:00:00', None, None),          # two bikeless rides on one day
                ('mtb_pm', 'MountainBikeRide', '2026-05-02T15:30:00', None, None),
                ('ridden', 'Ride', '2026-05-03T09:00:00', road, None),          # already on a bike
                ('run', 'Run', '2026-05-02T07:00:00', None, None),             # a run with no shoes: never on the bike list
                ('run_shod', 'Run', '2026-05-04T07:00:00', None, shoes),
                ('old_ride', 'Ride', '2025-01-10T10:00:00', None, None)):        # another month: fetched when it's opened
            db.execute("INSERT INTO Activity (id, name, riderId, sportType, type, startDateLocal, distance, movingTime, bikeId, kitId) "
                       "VALUES (?, ?, 1, ?, ?, ?, 20000, 3600, ?, ?)", [aid, aid, sport, sport, start, bike, kit_id])
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    c.ids = {'road': road, 'shoes': shoes}
    return c


def _listed(client, query):
    """The activities drawn with the page (the open month), and the page."""
    html = client.get(f'/activities?{query}').get_data(as_text=True)
    return set(re.findall(r'data-pick="([^"]+)"', html)), html


def _gear_note(client):
    html = client.get('/gear/').get_data(as_text=True)
    m = re.search(r'<strong>(\d+)</strong> activit(?:y has|ies have) no gear</a>', html)
    return (m.group(1) if m else None), html


def test_the_gear_note_counts_every_sport_and_links_to_each_type(client):
    n, html = _gear_note(client)
    assert n == '4', 'two rides and an old one with no bike, and a run with no shoes'
    assert 'href="/activities?gear=none&amp;rider=1"' in html
    types = re.findall(r'<a href="(/activities\?gear=none&amp;rider=1&amp;skip=[^"]+)">\S+ ([\d,]+) ([^<]+)</a>', html)
    assert [(t[2], t[1]) for t in types] == [('Ride', '2'), ('MountainBikeRide', '1'), ('Run', '1')], 'each type, most first'
    run = next(t[0] for t in types if t[2] == 'Run').replace('&amp;', '&')
    assert _listed(client, run.split('?', 1)[1])[0] == {'run'}, "a type's link: that sport alone"


def test_the_no_bike_list_is_the_history_tree_and_each_ride_drops_off_once_it_has_a_bike(client):
    ids, html = _listed(client, 'gear=bike-none')
    assert ids == {'road_am', 'mtb_pm'}, 'the newest month with any opens, with both of the day\'s bikeless rides; not the ridden one or the run'
    assert 'data-history-from="2025-01-01"' in html, 'older months are fetched when opened, a month at a time'
    assert html.count('action="/gear/ride/') == 2, 'a bike picker on each row'
    back = re.search(r'name="back" value="([^"]+)"', html).group(1).replace('&amp;', '&')
    assert back.startswith('/activities?') and 'gear=bike-none' in back

    r = client.post('/gear/ride/mtb_pm/bike', data={'bike': client.ids['road'] + 1, 'back': back})
    assert r.status_code == 302 and r.headers['Location'].endswith(back), 'back to the list, not the ride'
    assert _listed(client, 'gear=bike-none')[0] == {'road_am'}
    assert _gear_note(client)[0] == '3'


def test_a_month_fetched_later_keeps_the_gear_filter_and_its_pickers(client):
    html = client.get('/dashboard/history?gear=bike-none&from=2025-01-01&to=2025-01-31&list=/activities').get_data(as_text=True)
    assert set(re.findall(r'data-pick="([^"]+)"', html)) == {'old_ride'}
    assert 'action="/gear/ride/old_ride/bike"' in html and 'value="/activities?gear=bike-none"' in html
    assert 'gear=bike-none' in re.search(r'class="dash-link"[^>]*|href="([^"]+)" class="dash-link"', html).group(0), 'the day link keeps it too'


def test_every_sport_with_no_gear_and_a_count_per_type(client):
    ids, html = _listed(client, 'gear=none')
    assert ids == {'road_am', 'mtb_pm', 'run'}
    assert 'action="/gear/ride/road_am/bike"' in html and 'action="/gear/activity/run/kit"' in html, 'a bike for a ride, shoes for a run'
    chips = re.findall(r'class="sport-only( active)?" href="([^"]+)">([^<]+)<', html)
    assert [c[2].split()[-1] for c in chips] == ['4', '2', '1', '1'], 'Every sport, then each type, most first'
    assert chips[0][0] == ' active' and all('gear=none' in c[1] for c in chips)
    assert '&times; Clear' in html and 'href="/activities" class="btn btn-secondary btn-sm">&times; Clear' in html, 'Clear drops the gear filter'


def test_a_gear_filter_with_nothing_left_says_so(client):
    for a in ('road_am', 'mtb_pm', 'old_ride'):
        client.post(f'/gear/ride/{a}/bike', data={'bike': client.ids['road']})
    html = _listed(client, 'gear=bike-none')[1]
    assert 'No activity matches this gear filter' in html and 'No activities yet' not in html


def test_the_ride_page_picker_still_returns_to_the_ride_and_ignores_another_site(client):
    r = client.post('/gear/ride/road_am/bike', data={'bike': client.ids['road']})
    assert r.headers['Location'].endswith('/rides/road_am')
    r = client.post('/gear/ride/road_am/bike', data={'bike': client.ids['road'], 'back': '//evil.example/x'})
    assert r.headers['Location'].endswith('/rides/road_am')


def test_the_gear_filter_finds_a_bikes_rides_and_the_other_sports_with_no_gear(client):
    assert _listed(client, f"gear=bike-{client.ids['road']}")[0] == {'ridden'}
    assert _listed(client, f"gear=kit-{client.ids['shoes']}")[0] == {'run_shod'}
    ids, html = _listed(client, 'gear=kit-none')
    assert ids == {'run'}, 'rides have a bike, not shoes'
    assert 'action="/gear/activity/run/kit"' in html
    assert '&times; Clear' not in _listed(client, 'gear=nonsense')[1], 'a filter it does not know is ignored: the plain history'


def test_the_calendar_lists_a_picked_days_rides_so_each_can_get_its_own_bike(client):
    j = client.get('/gear/api/day-rides?dates=2026-05-02').get_json()
    assert [r['id'] for r in j['rides']] == ['road_am', 'mtb_pm'] and j['total'] == 2, 'rides only, oldest first'
    assert all(r['bike'] is None for r in j['rides'])

    mtb = client.ids['road'] + 1
    assert client.post('/gear/api/ride-bike', json={'ride': 'mtb_pm', 'bike': mtb}).get_json() == {'ok': True}
    assert client.post('/gear/api/ride-bike', json={'ride': 'road_am', 'bike': client.ids['road']}).status_code == 200
    j = client.get('/gear/api/day-rides?dates=2026-05-02').get_json()
    assert {r['id']: r['bike_name'] for r in j['rides']} == {'road_am': 'Roadie', 'mtb_pm': 'Mudder'}, 'one day, two bikes'
    assert 'have no bike yet' not in client.get('/gear/').get_data(as_text=True), 'the note goes once every ride has a bike'

    assert client.post('/gear/api/ride-bike', json={'ride': 'run', 'bike': mtb}).status_code == 404, 'a run never gets a bike'
    assert client.get('/gear/api/day-rides?dates=nope').status_code == 400


def test_only_sports_with_gear_count_as_having_none(client):
    with client.application.app_context():
        db = database.get_db()
        boots = kit.create(db, 1, 'Boots')                       # no default: hikes have gear because one has been in them
        skis = kit.create(db, 1, 'Old skis', kind='skis')
        kit.retire(db, skis)                                     # retired: nothing to put a ski day on any more
        for aid, sport, kit_id in (('hike', 'Hike', None), ('hike_booted', 'Hike', boots), ('swim', 'Swim', None), ('yoga', 'Yoga', None),
                                   ('trail', 'Trail Run', None), ('ski', 'AlpineSki', None), ('ski_old', 'AlpineSki', skis)):
            db.execute("INSERT INTO Activity (id, name, riderId, sportType, type, startDateLocal, distance, movingTime, kitId) "
                       "VALUES (?, ?, 1, ?, ?, '2026-05-06T10:00:00', 5000, 3600, ?)", [aid, aid, sport, sport, kit_id])
        db.commit()
    assert _listed(client, 'gear=kit-none')[0] == {'run', 'hike'}, 'not a swim or yoga with no gear for them, a trail run (shoes are for Run) or a ski day on retired skis'
    assert _gear_note(client)[0] == '5'
    with client.application.app_context():
        db = database.get_db()
        kit.set_defaults(db, client.ids['shoes'], ['Run', 'Trail Run'])
        db.commit()
    assert _listed(client, 'gear=none')[0] == {'road_am', 'mtb_pm', 'run', 'hike', 'trail'}, 'a default for a sport counts it in'
