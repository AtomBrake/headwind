"""An activity's sport when its sources disagree: two recordings of it that say different sports (services/merged_sport.py), listed and settled
by taking the other's sport or keeping the kept one's; a Garmin activity saved with another sport than the type Garmin last listed for it,
proposed at start with no call to Garmin (sport_fix.from_seen); and a ride on an e-bike chosen for it being an e-bike ride (gear.ebike_sport).
Throwaway DB, no network."""
import json

import pytest
from flask import Flask

import app as app_module
import config
import database
from services import convert, credentials, duplicates, gear, merged_sport, sport_fix


@pytest.fixture
def db(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
        yield d


def _add(db, aid, sport='Ride', bike=None, bike_auto=None, day='2026-02-10', rider=1):
    db.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDate, startDateLocal, distance, movingTime, elapsedTime, bikeId, bikeAuto) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, 20000, 3600, 3600, ?, ?)",
               [aid, aid, sport, sport, rider, f'{day}T09:00:00Z', f'{day}T09:00:00', bike, bike_auto])


def _sport(db, aid, col='sportType'):
    return db.execute(f'SELECT {col} FROM Activity WHERE id=?', [aid]).fetchone()[0]


# ---------- two recordings, two sports ----------
def test_a_garmin_ride_kept_over_a_strava_e_bike_ride_is_flagged_and_takes_it(db):
    _add(db, 'garmin_1', 'Ride')
    _add(db, '1234', 'EBikeRide')                        # Strava's "E-Bike Ride", under Headwind's name since the start-up rename
    duplicates.park(db, '1234', 'garmin_1', 'Kept the Garmin recording.')
    [c] = merged_sport.conflicts(db, 1)
    assert (c['id'], c['dupId'], c['other'], c['keptBy'], c['otherBy'], c['pair']) == ('garmin_1', '1234', 'EBikeRide', 'Garmin', 'Strava', ('Ride', 'EBikeRide'))
    assert merged_sport.count(db, 1) == 1 and merged_sport.count(db, None) == 0
    assert merged_sport.use_other(db, [c]) == (1, [])
    assert _sport(db, 'garmin_1') == 'EBikeRide'
    assert merged_sport.conflicts(db, 1) == []
    assert [d['id'] for d in duplicates.parked_for(db, 'garmin_1')] == ['1234']      # the Strava recording is still set aside


def test_the_other_way_round_strava_kept_over_a_garmin_ride(db):
    _add(db, '1234', 'EBikeRide')
    _add(db, 'garmin_1', 'Ride')
    duplicates.park(db, 'garmin_1', '1234', 'Kept the Strava recording.')
    [c] = merged_sport.conflicts(db, 1)
    assert (c['keptBy'], c['otherBy'], c['other']) == ('Strava', 'Garmin', 'Ride')
    assert merged_sport.use_other(db, [c])[0] == 1
    assert _sport(db, '1234') == 'Ride'


def test_keeping_the_kept_sport_stops_it_being_listed(db):
    _add(db, 'garmin_1', 'MountainBikeRide')
    _add(db, '1234', 'EBikeRide')                        # the Stumpy Evo: Strava is the one that's wrong
    duplicates.park(db, '1234', 'garmin_1', 'Kept the Garmin recording.')
    found = merged_sport.conflicts(db, 1)
    assert merged_sport.keep(db, found) == 1
    assert merged_sport.conflicts(db, 1) == []
    assert _sport(db, 'garmin_1') == 'MountainBikeRide'


@pytest.mark.parametrize('kept, other', [('VirtualRide', 'Virtual Ride'), ('Surf', 'Workout'), ('Paddle', 'Other'), ('Ride', 'Ride'), ('Ride', None)])
def test_one_sport_in_two_spellings_or_a_copy_that_says_nothing_is_not_listed(db, kept, other):
    _add(db, 'garmin_1', kept)
    _add(db, '1234', other)
    duplicates.park(db, '1234', 'garmin_1', 'Kept the Garmin recording.')
    assert merged_sport.conflicts(db, 1) == []


def test_a_sport_headwind_has_no_name_for_is_taken_as_strava_has_it(db):
    _add(db, 'garmin_1', 'Surf')
    _add(db, '1234', 'Windsurf')
    duplicates.park(db, '1234', 'garmin_1', 'Kept the Garmin recording.')
    assert merged_sport.use_other(db, merged_sport.conflicts(db, 1))[0] == 1
    assert _sport(db, 'garmin_1') == 'Windsurf'
    with pytest.raises(ValueError):                      # picked by hand, a sport is still one of Headwind's
        convert.change_sport(db, None, 'garmin_1', 'Windsurf ')


def test_a_ride_that_becomes_a_run_keeps_the_copy_that_said_so(db):
    _add(db, 'garmin_1', 'Ride')
    _add(db, '1234', 'Run')
    duplicates.park(db, '1234', 'garmin_1', 'Kept the Garmin recording.')
    assert merged_sport.use_other(db, merged_sport.conflicts(db, 1)) == (1, [])
    assert _sport(db, 'garmin_1') == 'Run'
    assert [d['id'] for d in duplicates.parked_for(db, 'garmin_1')] == ['1234']


def test_a_friends_activity_is_not_listed(db):
    db.execute("INSERT INTO Rider (id, name) VALUES (2, 'Martin')")
    db.execute("INSERT INTO Friend (name, url, riderId) VALUES ('Martin', 'http://127.0.0.1:9', 2)")
    _add(db, 'garmin_1', 'Ride', rider=2)
    _add(db, '1234', 'EBikeRide', rider=2)
    duplicates.park(db, '1234', 'garmin_1', 'Kept the Garmin recording.')
    assert merged_sport.conflicts(db) == []


def test_copies_set_aside_before_the_sport_column_get_it_from_their_row(db):
    _add(db, 'garmin_1', 'Ride')
    _add(db, '1234', 'EBikeRide')
    duplicates.park(db, '1234', 'garmin_1', 'Kept the Garmin recording.')
    db.execute('ALTER TABLE ActivityDuplicate DROP COLUMN sportChecked')
    db.execute('ALTER TABLE ActivityDuplicate DROP COLUMN sportType')
    duplicates.ensure_schema(db)
    assert db.execute("SELECT sportType FROM ActivityDuplicate WHERE id='1234'").fetchone()[0] == 'EBikeRide'
    assert len(merged_sport.conflicts(db, 1)) == 1


def test_groups_put_the_same_difference_together_biggest_first(db):
    for i, (kept, other) in enumerate([('Ride', 'EBikeRide'), ('Ride', 'EBikeRide'), ('Other', 'Yoga')]):
        day = f'2026-02-1{i}'
        _add(db, f'garmin_{i}', kept, day=day)
        _add(db, f'12{i}', other, day=day)
        duplicates.park(db, f'12{i}', f'garmin_{i}', 'Kept the Garmin recording.')
    g = merged_sport.groups(merged_sport.conflicts(db, 1))
    assert [(x['kept'], x['other'], len(x['rows'])) for x in g] == [('Ride', 'EBikeRide', 2), ('Other', 'Yoga', 1)]


# ---------- Garmin's type, without asking Garmin ----------
def _seen(db, gid, type_key):
    from services import garmin_changes
    garmin_changes.ensure_schema(db)
    db.execute('INSERT INTO GarminSeen (garminId, summary) VALUES (?, ?)', [gid, json.dumps({'name': 'Ride', 'typeKey': type_key})])


def test_an_e_bike_ride_saved_as_a_ride_is_proposed_from_what_garmin_listed(db, monkeypatch):
    from services import garmin
    monkeypatch.setattr(garmin, '_client', lambda *a, **k: pytest.fail('Garmin was asked'), raising=False)
    _add(db, 'garmin_1', 'Ride')
    _add(db, 'garmin_2', 'Ride', day='2026-02-11')
    _add(db, 'garmin_3', 'EBikeRide', day='2026-02-12')
    _seen(db, '1', 'e_bike_fitness')
    _seen(db, '2', 'cycling')
    _seen(db, '3', 'e_bike_mountain')
    assert sport_fix.from_seen(db) == {1: 1}
    [p] = sport_fix.pending(db, 1)
    assert (p['rideId'], p['oldSport'], p['newSport'], p['typeKey']) == ('garmin_1', 'Ride', 'EBikeRide', 'e_bike_fitness')
    assert sport_fix.count(db, 1) == 1
    assert sport_fix.from_seen(db) == {}                 # proposed once, not again at every start
    assert sport_fix.apply(db, 1, ['garmin_1'])['changed'] == 1
    assert _sport(db, 'garmin_1') == 'EBikeRide' and sport_fix.count(db, 1) == 0


def test_a_proposal_kept_or_made_stale_is_not_offered(db):
    _add(db, 'garmin_1', 'Ride')
    _add(db, 'garmin_2', 'Ride', day='2026-02-11')
    _seen(db, '1', 'e_bike_fitness')
    _seen(db, '2', 'mountain_biking')
    sport_fix.from_seen(db)
    sport_fix.apply(db, 1, [])                           # nothing ticked: both kept as they are
    assert sport_fix.from_seen(db) == {} and sport_fix.count(db, 1) == 0
    db.execute('DELETE FROM SportFix')
    sport_fix.from_seen(db)
    convert.change_sport(db, None, 'garmin_1', 'EBikeRide')      # changed some other way meanwhile
    sport_fix.from_seen(db)
    assert [p['rideId'] for p in sport_fix.pending(db, 1)] == ['garmin_2']


# ---------- a ride on an e-bike ----------
@pytest.fixture
def bikes(db):
    return gear.create_bike(db, 1, 'Roadie'), gear.create_bike(db, 1, 'Amflow', kind='ebike')


def test_a_ride_put_on_an_e_bike_becomes_an_e_bike_ride_and_goes_back_off_it(db, bikes):
    road, ebike = bikes
    _add(db, 'r1', 'MountainBikeRide')
    gear.set_ride_bike(db, 'r1', ebike)
    assert (_sport(db, 'r1'), _sport(db, 'r1', 'sportBeforeBike')) == ('EBikeRide', 'MountainBikeRide')
    gear.set_ride_bike(db, 'r1', road)
    assert (_sport(db, 'r1'), _sport(db, 'r1', 'sportBeforeBike')) == ('MountainBikeRide', None)


def test_a_default_e_bike_given_automatically_says_nothing(db, bikes):
    road, ebike = bikes
    gear.set_default(db, 1, ebike)
    _add(db, 'r1', 'Ride')
    gear.on_ride_added(db, 'r1')
    assert db.execute("SELECT bikeId FROM Activity WHERE id='r1'").fetchone()[0] == ebike
    assert _sport(db, 'r1') == 'Ride'
    gear.apply_defaults(db, 1, dry_run=False)
    assert _sport(db, 'r1') == 'Ride'


def test_an_indoor_ride_on_an_e_bike_stays_indoor(db, bikes):
    _add(db, 'r1', 'VirtualRide')
    gear.set_ride_bike(db, 'r1', bikes[1])
    assert _sport(db, 'r1') == 'VirtualRide'


def test_a_bike_made_an_e_bike_makes_its_rides_e_bike_rides_and_back(db, bikes):
    road, _ = bikes
    _add(db, 'r1', 'Ride', bike=road)                    # chosen
    _add(db, 'r2', 'Ride', bike=road, bike_auto=road, day='2026-02-11')     # its default
    gear.update_bike(db, road, kind='ebike')
    assert (_sport(db, 'r1'), _sport(db, 'r2')) == ('EBikeRide', 'Ride')
    gear.update_bike(db, road, kind='road')
    assert (_sport(db, 'r1'), _sport(db, 'r2')) == ('Ride', 'Ride')


def test_a_sport_changed_by_hand_is_not_undone_off_the_e_bike(db, bikes):
    road, ebike = bikes
    _add(db, 'r1', 'Ride')
    gear.set_ride_bike(db, 'r1', ebike)
    convert.change_sport(db, None, 'r1', 'GravelRide')
    convert.change_sport(db, None, 'r1', 'EBikeRide')
    gear.set_ride_bike(db, 'r1', road)
    assert _sport(db, 'r1') == 'EBikeRide'


def test_rides_already_on_an_e_bike_are_made_e_bike_rides_once(db, bikes):
    road, ebike = bikes
    _add(db, 'r1', 'Ride', bike=ebike)                   # from before Headwind told a chosen bike from a default: counts as chosen
    _add(db, 'r2', 'Ride', bike=ebike, bike_auto=ebike, day='2026-02-11')
    _add(db, 'r3', 'Ride', bike=road, day='2026-02-12')
    db.execute('UPDATE Settings SET ebikeSportDone=0')
    res = gear.ebike_rides(db)
    assert res['ran'] and res['changed'] == [('r1', 'r1', 'Ride', '2026-02-10T09:00:00')]
    assert [_sport(db, i) for i in ('r1', 'r2', 'r3')] == ['EBikeRide', 'Ride', 'Ride']
    assert gear.ebike_rides(db) == {'ran': False, 'changed': []}


# ---------- the pages ----------
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
        for i in range(2):
            day = f'2026-02-1{i}'
            _add(d, f'garmin_{i}', 'Ride', day=day)
            _add(d, f'12{i}', 'EBikeRide', day=day)
            duplicates.park(d, f'12{i}', f'garmin_{i}', 'Kept the Garmin recording.')
        d.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    c.app_ = app
    return c


def test_the_activity_page_says_so_and_takes_the_other_sport(client):
    page = client.get('/rides/garmin_0').get_data(as_text=True)
    assert 'Different sport:' in page and 'Strava says <strong>E-bike ride</strong>' in page and 'Garmin says <strong>Ride</strong>' in page
    r = client.post('/import/sports/120/other', data={'back': '/rides/garmin_0'})
    assert r.status_code == 302 and r.headers['Location'].endswith('/rides/garmin_0')
    assert 'Different sport:' not in client.get('/rides/garmin_0').get_data(as_text=True)


def test_the_import_page_lists_them_and_settles_a_whole_kind_at_once(client):
    page = client.get('/import').get_data(as_text=True)
    assert '2 activities recorded twice with different sports' in page and 'Use E-bike ride for all 2' in page
    assert 'Sports to check' in client.get('/dashboard').get_data(as_text=True)
    r = client.post('/import/sports/all/other', data={'kept': 'Ride', 'other': 'EBikeRide'})
    assert r.status_code == 302
    with client.app_.app_context():
        d = database.get_db()
        assert [x[0] for x in d.execute("SELECT sportType FROM Activity WHERE id LIKE 'garmin_%' ORDER BY id")] == ['EBikeRide', 'EBikeRide']
    assert 'recorded twice with different sports' not in client.get('/import').get_data(as_text=True)
