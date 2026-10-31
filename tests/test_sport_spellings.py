"""One sport, one spelling: Strava's "Virtual Ride", "E-Bike Ride", ... are saved as Headwind's VirtualRide, EBikeRide, ... (sports.canonical), by the
Strava import, by a friend's sync and, for activities already saved, by a start-up repair (services/sport_fix.fix_spellings). Before, a rider with
both a Strava import and a Garmin sync saw "Indoor ride" twice in the sport filter."""
import pytest
from flask import Flask
from werkzeug.datastructures import MultiDict

import database
from routes import friends
from services import sport_fix, sports, tasks
from services.sport_filter import SportFilter
from tests.test_strava_gear import row, run_import


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


def add(db, aid, sport):
    db.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDateLocal, distance, movingTime, rawData) "
               "VALUES (?, ?, ?, ?, 1, '2026-10-01T08:00:00', 20000, 3600, '{}')", [aid, aid, sport, sport])


def sport_of(db, aid):
    return tuple(db.execute('SELECT sportType, type FROM Activity WHERE id=?', [aid]).fetchone())


def test_canonical():
    assert [sports.canonical(s) for s in ('Virtual Ride', 'Virtual Run', 'E-Bike Ride', 'Mountain Bike Ride', 'Gravel Ride')] == \
        ['VirtualRide', 'VirtualRun', 'EBikeRide', 'MountainBikeRide', 'GravelRide']
    assert [sports.canonical(s) for s in ('VirtualRide', 'Ride', 'Trail Run', 'E-Mountain Bike Ride', '', None)] == \
        ['VirtualRide', 'Ride', 'Trail Run', 'E-Mountain Bike Ride', '', None]          # no name of Headwind's for these: kept as they are
    for strava, ours in sports.STRAVA_NAMES.items():                                       # the same sport to every test that reads one
        assert (sports.is_ride(strava), sports.is_virtual(strava), sports.is_ebike(strava), sports.segment_family(strava), sports.stat_group(strava)) == \
               (sports.is_ride(ours), sports.is_virtual(ours), sports.is_ebike(ours), sports.segment_family(ours), sports.stat_group(ours))


def test_activities_already_saved_take_headwinds_name_and_the_filter_lists_each_sport_once(db):
    for aid, sport in (('strava_z', 'Virtual Ride'), ('garmin_z', 'VirtualRide'), ('strava_e', 'E-Bike Ride'), ('strava_vr', 'Virtual Run'),
                       ('strava_trail', 'Trail Run'), ('road', 'Ride')):
        add(db, aid, sport)
    db.commit()
    assert [s for s, _ in SportFilter(db, 1, MultiDict()).sports].count('Virtual Ride') == 1
    assert sport_fix.fix_spellings(db) == {'Virtual Ride': 1, 'E-Bike Ride': 1, 'Virtual Run': 1}
    assert sport_of(db, 'strava_z') == sport_of(db, 'garmin_z') == ('VirtualRide', 'VirtualRide')
    assert sport_of(db, 'strava_e') == ('EBikeRide', 'EBikeRide') and sport_of(db, 'strava_vr') == ('VirtualRun', 'VirtualRun')
    assert sport_of(db, 'strava_trail') == ('Trail Run', 'Trail Run')
    assert dict(SportFilter(db, 1, MultiDict()).sports)['VirtualRide'] == 2
    labels = [sports.label(s) for s, _ in SportFilter(db, 1, MultiDict()).sports]
    assert len(labels) == len(set(labels))
    assert sport_fix.fix_spellings(db) == {}                                              # nothing left: the next start does nothing


def test_the_start_up_repair_runs_and_says_what_it_did(db):
    add(db, 'strava_z', 'Virtual Ride'); add(db, 'strava_z2', 'Virtual Ride'); db.commit()
    database.migrate_db()
    assert sport_of(db, 'strava_z') == ('VirtualRide', 'VirtualRide')
    rec = tasks.last(db, 'startup:strava_spellings')
    assert rec and '2 Virtual Ride → VirtualRide (Indoor ride)' in rec['result']


def test_the_strava_import_saves_headwinds_name(db):
    run_import(db, [row('z', 'Oct 17, 2026', 'Virtual Ride'), row('e', 'Oct 16, 2026', 'E-Bike Ride'), row('t', 'Oct 15, 2026', 'Trail Run', km=8)])
    assert sport_of(db, 'z') == ('VirtualRide', 'VirtualRide') and sport_of(db, 'e') == ('EBikeRide', 'EBikeRide')
    assert sport_of(db, 't') == ('Trail Run', 'Trail Run')


def test_a_friend_on_an_older_headwind_is_saved_with_headwinds_name_and_not_changed_on_every_sync(db):
    obj = {'id': '6631286820', 'name': 'Zwift', 'sportType': 'Virtual Ride', 'startDateLocal': '2026-10-01T08:00:00', 'distance': 20000}
    aid, kind = friends._store_ride(db, 1, 1, obj)
    assert kind == 'new' and sport_of(db, aid) == ('VirtualRide', 'VirtualRide')
    assert friends._store_ride(db, 1, 1, obj)[1] is None
