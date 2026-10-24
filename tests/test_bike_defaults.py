"""A default bike per kind of ride, and for commutes (gear.pick_bike, BikeDefault), with the rider's default bike for every other ride; the same
for shoes and other kit (KitDefault, kit.COMMUTE). Gear given automatically follows a change of sport or commute tick (gear.regear); gear
chosen by hand stays. Past activities can be put on their defaults (apply_defaults). Then the one gear page and form for bikes and kit.
Throwaway DB, no network."""
import pytest
from flask import Flask

import app as app_module
import config
import database
from services import convert, credentials, gear, kit, sports


@pytest.fixture
def db(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT INTO Rider(name,isDefault) VALUES ('Rob',1)")
        d.commit()
        yield d


def add(db, aid, sport='Ride', commute=None, bike=None, day='2026-05-02', stamp=True):
    db.execute("INSERT INTO Activity (id, name, riderId, sportType, type, startDateLocal, distance, movingTime, commute, bikeId) "
               "VALUES (?, ?, 1, ?, ?, ?, 20000, 3600, ?, ?)", [aid, aid, sport, sport, f'{day}T09:00:00', commute, bike])
    if stamp:
        gear.on_ride_added(db, aid)


def got(db, aid, col='bikeId'):
    return db.execute(f'SELECT {col} FROM Activity WHERE id=?', [aid]).fetchone()[0]


@pytest.fixture
def bikes(db):
    road = gear.create_bike(db, 1, 'Road bike')                       # the first bike: every other ride's
    mtb = gear.create_bike(db, 1, 'Stumpjumper', kind='mtb')
    hybrid = gear.create_bike(db, 1, 'Hybrid', kind='commuter')
    ebike = gear.create_bike(db, 1, 'Turbo Vado', kind='ebike')
    gear.set_bike_defaults(db, mtb, ['MountainBikeRide', 'Mountain Bike Ride'])     # Strava's spelling is the same kind
    gear.set_default_for(db, 1, kit.COMMUTE, hybrid)
    gear.set_default_for(db, 1, 'EBikeRide', ebike)
    db.commit()
    return {'road': road, 'mtb': mtb, 'hybrid': hybrid, 'ebike': ebike}


def test_each_kind_of_ride_gets_its_bike_and_anything_else_the_default(db, bikes):
    add(db, 'mtb', 'MountainBikeRide')
    add(db, 'strava_mtb', 'Mountain Bike Ride')
    add(db, 'zwift', 'VirtualRide')                                    # no default of its own
    add(db, 'commute', 'Ride', commute=1)
    add(db, 'ecommute', 'EBikeRide', commute=1)                        # a commute goes on the commute bike whatever its sport
    add(db, 'ebike', 'EBikeRide')
    assert [got(db, a) for a in ('mtb', 'strava_mtb', 'zwift', 'commute', 'ecommute', 'ebike')] == \
        [bikes['mtb'], bikes['mtb'], bikes['road'], bikes['hybrid'], bikes['hybrid'], bikes['ebike']]
    assert got(db, 'mtb', 'bikeAuto') == bikes['mtb'], 'remembered as given automatically'
    assert gear.bike_defaults_of(db, bikes['road']) == [gear.ANY] and gear.bike_defaults_of(db, bikes['mtb']) == ['MountainBikeRide']


def test_a_retired_bike_is_skipped_and_its_defaults_go(db, bikes):
    gear.archive_bike(db, bikes['mtb'])
    assert gear.get_bike(db, bikes['mtb'])['retiredOn'], 'kept when, as kit does'
    add(db, 'mtb', 'MountainBikeRide')
    assert got(db, 'mtb') == bikes['road']
    assert 'MountainBikeRide' not in gear.bike_defaults(db, 1)
    with pytest.raises(ValueError):
        gear.set_bike_defaults(db, bikes['mtb'], ['GravelRide'])
    gear.archive_bike(db, bikes['mtb'], False)
    assert gear.get_bike(db, bikes['mtb'])['retiredOn'] is None


def test_no_default_at_all_leaves_a_ride_with_none_but_marks_it_automatic(db):
    add(db, 'r1')
    assert got(db, 'r1') is None and got(db, 'r1', 'bikeAuto') == 0
    hybrid = gear.create_bike(db, 1, 'Hybrid')
    gear.set_default(db, 1, None)
    gear.set_default_for(db, 1, kit.COMMUTE, hybrid)
    db.execute("UPDATE Activity SET commute=1 WHERE id='r1'")
    assert gear.regear(db, 'r1') and got(db, 'r1') == hybrid, 'a commute tick after it arrived (a Strava export ticks it later)'


def test_a_commute_tick_moves_an_automatic_bike_but_not_a_chosen_one(db, bikes):
    add(db, 'auto')
    add(db, 'chosen')
    gear.set_ride_bike(db, 'chosen', bikes['mtb'])                     # picked by hand
    for a in ('auto', 'chosen'):
        db.execute('UPDATE Activity SET commute=1 WHERE id=?', [a])
        gear.regear(db, a)
    assert got(db, 'auto') == bikes['hybrid'] and got(db, 'chosen') == bikes['mtb']
    db.execute("UPDATE Activity SET commute=0 WHERE id='auto'")
    assert gear.regear(db, 'auto') and got(db, 'auto') == bikes['road'], 'unticked: back to the default'


def test_a_bike_from_a_strava_export_or_the_phone_is_never_moved(db, bikes):
    add(db, 'strava', stamp=False)                                     # a ride that names its Strava bike: no default stamped
    add(db, 'phone', bike=bikes['mtb'])                                # the phone said which bike
    for a in ('strava', 'phone'):
        db.execute('UPDATE Activity SET commute=1 WHERE id=?', [a])
        assert not gear.regear(db, a)
    assert got(db, 'strava') is None and got(db, 'phone') == bikes['mtb']


def test_changing_the_sport_follows_the_rules(db, bikes):
    add(db, 'r')
    assert got(db, 'r') == bikes['road']
    convert.change_sport(db, 'ride', 'r', 'MountainBikeRide')
    assert got(db, 'r') == bikes['mtb']
    convert.change_sport(db, 'ride', 'r', 'EBikeRide')
    assert got(db, 'r') == bikes['ebike'] and sports.class_of(db, 'r') == 'ebike'


def test_the_commute_tick_on_the_web_and_in_bulk_picks_again(tmp_path, monkeypatch):
    class _NoThread:
        def __init__(self, *a, **kw): pass
        def start(self): pass
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'w.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        road = gear.create_bike(d, 1, 'Road')
        hybrid = gear.create_bike(d, 1, 'Hybrid')
        gear.set_default_for(d, 1, kit.COMMUTE, hybrid)
        add(d, 'a')
        add(d, 'b')
        d.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    assert c.post('/rides/a/commute', data={'commute': '1'}).status_code == 204
    c.post('/rides/bulk', data={'action': 'commute', 'commute': '1', 'ids': 'b'})
    with app.app_context():
        d = database.get_db()
        assert got(d, 'a') == hybrid and got(d, 'b') == hybrid and road


def test_apply_to_past_rides_previews_then_moves_only_what_it_should(db, bikes):
    add(db, 'old_none', 'MountainBikeRide', stamp=False)               # from before: no bike
    add(db, 'old_road', 'MountainBikeRide', bike=bikes['road'], stamp=False)      # from before: on the old default, maybe by hand
    add(db, 'auto', 'Ride', stamp=True)
    gear.set_default_for(db, 1, 'Ride', None)                          # (a no-op: plain rides follow every other ride's bike)
    gear.set_default(db, 1, bikes['hybrid'])                          # every other ride now goes on the hybrid
    plan = gear.apply_defaults(db, 1)
    assert plan == {bikes['mtb']: {'none': 1, 'auto': 0, 'other': 1}, bikes['hybrid']: {'none': 0, 'auto': 1, 'other': 0}}
    assert got(db, 'old_none') is None, 'a preview changes nothing'
    gear.apply_defaults(db, 1, dry_run=False)
    assert [got(db, a) for a in ('old_none', 'old_road', 'auto')] == [bikes['mtb'], bikes['road'], bikes['hybrid']]
    gear.apply_defaults(db, 1, include_chosen=True, dry_run=False)
    assert got(db, 'old_road') == bikes['mtb'] and got(db, 'old_road', 'bikeAuto') == bikes['mtb']


def test_kit_has_a_commute_default_and_follows_the_same_rules(db):
    road = kit.create(db, 1, 'Road shoes', sports_=['Run'])
    trail = kit.create(db, 1, 'Trail shoes', sports_=['TrailRun', 'Hike'])
    commute = kit.create(db, 1, 'Commute shoes', sports_=[kit.COMMUTE])
    add(db, 'run', 'Run')
    add(db, 'crun', 'Run', commute=1)
    assert got(db, 'run', 'kitId') == road and got(db, 'crun', 'kitId') == commute and got(db, 'run', 'kitAuto') == road
    convert.change_sport(db, 'workout', 'run', 'Hike')
    assert got(db, 'run', 'kitId') == trail
    kit.set_activity_kit(db, 'crun', road)                             # by hand
    db.execute("UPDATE Activity SET commute=0 WHERE id='crun'")
    assert not gear.regear(db, 'crun') and got(db, 'crun', 'kitId') == road
    assert kit.defaults_of(db, commute) == [kit.COMMUTE]


def test_kit_apply_and_assign_by_date(db):
    shoes = kit.create(db, 1, 'Shoes')
    add(db, 'r1', 'Run', stamp=False)
    add(db, 'r2', 'Run', day='2025-01-01', stamp=False)
    add(db, 'w1', 'Walk', stamp=False)
    assert kit.assign(db, 1, shoes, ['Run'], '2026-01-01', '2026-12-31', dry_run=True) == {'matched': 1, 'changed': 1}
    kit.assign(db, 1, shoes, ['Run'], '2000-01-01', '2026-12-31')
    assert got(db, 'r1', 'kitId') == shoes and got(db, 'r2', 'kitId') == shoes and got(db, 'w1', 'kitId') is None
    boots = kit.create(db, 1, 'Boots')
    kit.set_default_for(db, 1, 'Walk', boots)
    assert kit.apply_defaults(db, 1) == {boots: {'none': 1, 'auto': 0, 'other': 0}}


def test_garmin_keeps_mountain_and_gravel_rides(db):
    from services.garmin import garmin_sport
    assert garmin_sport('mountain_biking') == 'MountainBikeRide' and garmin_sport('gravel_cycling') == 'GravelRide'
    assert garmin_sport('road_biking') == 'Ride' and garmin_sport('e_bike_mountain') == 'EBikeRide'
    assert sports.label('MountainBikeRide') == 'Mountain bike ride' and sports.is_ride('GravelRide')


def test_a_strava_bikes_default_sports_seed_its_defaults(db):
    from services import strava_gear
    db.execute("INSERT INTO StravaBike (riderId, name, sports) VALUES (1, 'Stumpy', 'Mountain Bike Ride|Ride')")
    gear.create_bike(db, 1, 'Road')
    strava_gear.save(db, 1, {'Stumpy': {'match': 'new', 'kind': 'mtb'}})
    stumpy = db.execute("SELECT id FROM Bike WHERE name='Stumpy'").fetchone()[0]
    assert gear.bike_defaults(db, 1) == {'MountainBikeRide': stumpy}, 'a plain Ride is left to the default bike'


# ---------- the one gear page and form ----------
@pytest.fixture
def client(tmp_path, monkeypatch):
    class _NoThread:
        def __init__(self, *a, **kw): pass
        def start(self): pass
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'p.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        road = gear.create_bike(d, 1, 'Roadie')
        shoes = kit.create(d, 1, 'Trainers', sports_=['Run'])
        add(d, 'ride1', 'Ride')
        add(d, 'mtb1', 'MountainBikeRide', bike=road)
        add(d, 'run1', 'Run')
        d.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    c.app_, c.ids = app, {'road': road, 'shoes': shoes}
    return c


def test_bike_and_kit_pages_share_their_sections(client):
    for url, noun in ((f"/gear/bike/{client.ids['road']}", 'rides'), (f"/gear/kit/{client.ids['shoes']}", 'activities')):
        html = client.get(url).get_data(as_text=True)
        for part in ('class="gear-head"', 'Distance on Headwind', 'Moving time', 'Distance by year', f'Assign {noun} to', f'Recent {noun}',
                     'Default for</span>', 'gear_assign_range.js', 'Retire it instead to keep its history'):
            assert part in html, (url, part)
    bike = client.get(f"/gear/bike/{client.ids['road']}").get_data(as_text=True)
    assert 'Parts on this bike' in bike and 'By sport' in bike, 'a bike ridden as two kinds of ride'
    assert 'Parts on this bike' not in client.get(f"/gear/kit/{client.ids['shoes']}").get_data(as_text=True)
    for url in ('/gear/bike/new', f"/gear/bike/{client.ids['road']}/edit", '/gear/kit/new', f"/gear/kit/{client.ids['shoes']}/edit"):
        html = client.get(url).get_data(as_text=True)
        assert 'Default for new' in html and 'name="photo"' in html and 'value="Commute"' in html, url


def test_the_gear_page_saves_defaults_and_applies_them(client):
    html = client.get('/gear/').get_data(as_text=True)
    assert 'Defaults for new activities' in html and 'name="bike_MountainBikeRide"' in html and 'name="kit_Run"' in html
    mtb = None
    with client.app_.app_context():
        mtb = gear.create_bike(database.get_db(), 1, 'Mudder', kind='mtb')
        database.get_db().commit()
    r = client.post('/gear/defaults', data={'rider': '1', 'bike_MountainBikeRide': str(mtb), 'bike_Commute': '', 'kit_Run': str(client.ids['shoes'])})
    assert r.status_code == 302
    html = client.get('/gear/').get_data(as_text=True)
    assert 'Past activities' in html and 'on other gear, maybe chosen by hand' in html
    client.post('/gear/defaults/apply', data={'rider': '1', 'include_chosen': '1'})
    with client.app_.app_context():
        assert got(database.get_db(), 'mtb1') == mtb


def test_saving_the_bike_form_sets_its_defaults(client):
    r = client.post('/gear/bike/save', data={'rider': '1', 'name': 'Gravel', 'kind': 'gravel', 'defaults': '1', 'sport': ['GravelRide', kit.COMMUTE]})
    bid = int(r.headers['Location'].rstrip('/').split('/')[-1])
    with client.app_.app_context():
        assert gear.bike_defaults_of(database.get_db(), bid) == [kit.COMMUTE, 'GravelRide']
    client.post('/gear/bike/save', data={'id': str(client.ids['road']), 'name': 'Roadie', 'kind': 'road', 'defaults': '1'})
    with client.app_.app_context():
        assert gear.bike_defaults_of(database.get_db(), client.ids['road']) == [], 'unticking every other ride leaves no default bike'


def test_the_phone_bike_list_says_what_each_bike_is_for(client):
    with client.app_.app_context():
        d = database.get_db()
        gear.set_default_for(d, 1, kit.COMMUTE, client.ids['road'])
        d.commit()
        from routes.api_v1 import _bikes
        assert _bikes(1) == [{'id': client.ids['road'], 'name': 'Roadie', 'kind': 'road', 'is_default': True, 'default_for': [kit.COMMUTE]}]
