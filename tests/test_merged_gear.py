"""Merged activities whose two recordings are on different gear (services/merged_gear.py): found from the gear chosen on the copy set aside or
its Strava export, never from a default it was given; settled by using the other's gear or keeping the kept one's. Throwaway DB."""
import json

import pytest
from flask import Flask

import app as app_module
import config
import database
from services import credentials, duplicates, gear, kit, merged_gear, strava_gear


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


def _add(db, aid, sport='Ride', bike=None, bike_auto=None, kit_id=None, kit_auto=None, day='2026-02-10'):
    db.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDate, startDateLocal, distance, movingTime, elapsedTime, bikeId, bikeAuto, kitId, kitAuto) "
               "VALUES (?, ?, ?, ?, 1, ?, ?, 20000, 3600, 3600, ?, ?, ?, ?)",
               [aid, aid, sport, sport, f'{day}T09:00:00Z', f'{day}T09:00:00', bike, bike_auto, kit_id, kit_auto])


def _bikes(db):
    return gear.create_bike(db, 1, 'Amflow'), gear.create_bike(db, 1, 'Charles')


def test_a_bike_chosen_on_the_copy_set_aside_is_listed_and_can_be_used(db):
    amflow, charles = _bikes(db)
    _add(db, 'garmin_1', bike=amflow, bike_auto=amflow)          # the default bike, given automatically
    _add(db, 'imp_2', bike=charles)                              # the phone said Charles
    duplicates.park(db, 'imp_2', 'garmin_1', 'Kept the Garmin recording.')
    [c] = merged_gear.conflicts(db, 1)
    assert (c['id'], c['dupId'], c['ride'], c['kept']['name'], c['other']['name'], c['fromStrava']) == ('garmin_1', 'imp_2', True, 'Amflow', 'Charles', False)
    assert merged_gear.count(db, 1) == 1 and merged_gear.count(db, None) == 0
    assert merged_gear.use_other(db, [c]) == 1
    assert db.execute("SELECT bikeId FROM Activity WHERE id='garmin_1'").fetchone()[0] == charles
    assert merged_gear.conflicts(db, 1) == []


def test_a_default_bike_on_the_copy_says_nothing(db):
    amflow, charles = _bikes(db)
    _add(db, 'imp_1', bike=charles)
    _add(db, 'garmin_2', bike=amflow, bike_auto=amflow)
    duplicates.park(db, 'garmin_2', 'imp_1', 'Kept the phone recording.')
    assert merged_gear.conflicts(db, 1) == []
    assert db.execute("SELECT bikeId FROM ActivityDuplicate WHERE id='garmin_2'").fetchone()[0] is None


def test_the_bike_a_strava_copy_names_is_listed_and_kept_on_request(db):
    amflow, charles = _bikes(db)
    _add(db, 'garmin_1', bike=amflow, bike_auto=amflow)
    _add(db, '1234')                                             # a Strava export ride: its bike is in StravaGear, not on the row
    duplicates.park(db, '1234', 'garmin_1', 'Kept the Garmin recording.')
    strava_gear.ensure_schema(db)
    db.execute("INSERT INTO StravaGear (activityId, gear) VALUES ('1234', 'Charles')")
    db.execute("INSERT INTO StravaBike (riderId, name, status) VALUES (1, 'Charles', 'new')")
    assert merged_gear.conflicts(db, 1) == []                    # not matched to a bike yet: nothing to compare
    db.execute("UPDATE StravaBike SET bikeId=?, status='matched'", [charles])
    [c] = merged_gear.conflicts(db, 1)
    assert c['fromStrava'] and c['other']['name'] == 'Charles'
    assert merged_gear.keep(db, [c]) == 1
    assert merged_gear.conflicts(db, 1) == []
    assert db.execute("SELECT bikeId FROM Activity WHERE id='garmin_1'").fetchone()[0] == amflow


def test_a_run_is_checked_by_its_shoes(db):
    road, trail = kit.create(db, 1, 'Road shoes'), kit.create(db, 1, 'Trail shoes')
    _add(db, 'garmin_1', sport='Run', kit_id=road, kit_auto=road)
    _add(db, 'imp_2', sport='Run', kit_id=trail)
    duplicates.park(db, 'imp_2', 'garmin_1', 'Kept the Garmin recording.')
    [c] = merged_gear.conflicts(db, 1)
    assert not c['ride'] and (c['kept']['name'], c['other']['name']) == ('Road shoes', 'Trail shoes')
    merged_gear.use_other(db, [c])
    assert db.execute("SELECT kitId FROM Activity WHERE id='garmin_1'").fetchone()[0] == trail


def test_gear_since_deleted_is_left_out(db):
    amflow, charles = _bikes(db)
    _add(db, 'garmin_1', bike=amflow)
    _add(db, 'imp_2', bike=charles)
    duplicates.park(db, 'imp_2', 'garmin_1', 'Kept the Garmin recording.')
    gear.delete_bike(db, charles)
    assert merged_gear.conflicts(db, 1) == []


def test_copies_set_aside_before_the_upgrade_get_their_chosen_gear(db):
    amflow, charles = _bikes(db)
    _add(db, 'garmin_1', bike=amflow, bike_auto=amflow)
    for col in ('bikeId', 'kitId', 'gearChecked'):
        db.execute(f'ALTER TABLE ActivityDuplicate DROP COLUMN {col}')
    rows = {'imp_2': {'id': 'imp_2', 'bikeId': charles, 'bikeAuto': None}, 'imp_3': {'id': 'imp_3', 'bikeId': charles, 'bikeAuto': charles},
            'imp_4': {'id': 'imp_4', 'bikeId': charles, 'bikeAuto': amflow}}
    for aid, row in rows.items():
        db.execute("INSERT INTO ActivityDuplicate (id, primaryId, riderId, status, rowJson) VALUES (?, 'garmin_1', 1, 'parked', ?)", [aid, json.dumps(row)])
    db.execute("INSERT INTO ActivityDuplicate (id, primaryId, riderId, status, rowJson) VALUES ('imp_5', 'garmin_1', 1, 'parked', 'not json')")
    duplicates.ensure_schema(db)
    got = {r[0]: r[1] for r in db.execute('SELECT id, bikeId FROM ActivityDuplicate')}
    assert got == {'imp_2': charles, 'imp_3': None, 'imp_4': charles, 'imp_5': None}     # imp_3's Charles was a default; imp_4's was changed by hand
    assert sorted(c['dupId'] for c in merged_gear.conflicts(db, 1)) == ['imp_2', 'imp_4']


# ---- the pages ----
class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        amflow, charles = _bikes(d)
        _add(d, 'garmin_1', bike=amflow, bike_auto=amflow)
        _add(d, 'imp_2', bike=charles)
        duplicates.park(d, 'imp_2', 'garmin_1', 'Kept the Garmin recording.')
        d.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    c.bikes = (amflow, charles)
    c.app = app
    return c


def test_the_ride_page_dashboard_and_gear_page_point_at_the_difference(client):
    ride = client.get('/rides/garmin_1').get_data(as_text=True)
    assert 'Different bike:' in ride and 'Use Charles' in ride and 'Amflow is right' in ride
    assert 'Gear to check' in client.get('/dashboard').get_data(as_text=True)
    assert '/gear/merged' in client.get('/gear/').get_data(as_text=True)
    page = client.get('/gear/merged').get_data(as_text=True)
    assert 'Use Charles' in page and 'for all 1' in page


def test_using_the_other_bike_from_the_ride_page_goes_back_to_it(client):
    r = client.post('/gear/merged/imp_2/other', data={'back': '/rides/garmin_1'})
    assert r.status_code == 302 and r.headers['Location'].endswith('/rides/garmin_1')
    with client.app.app_context():
        assert database.get_db().execute("SELECT bikeId FROM Activity WHERE id='garmin_1'").fetchone()[0] == client.bikes[1]
    assert 'Different bike:' not in client.get('/rides/garmin_1').get_data(as_text=True)


def test_leaving_them_all_as_they_are(client):
    r = client.post('/gear/merged/all/kept')
    assert r.status_code == 302 and 'left+on+the+gear' in r.headers['Location']
    assert 'Nothing to check' in client.get('/gear/merged').get_data(as_text=True)
    assert 'Gear to check' not in client.get('/dashboard').get_data(as_text=True)
