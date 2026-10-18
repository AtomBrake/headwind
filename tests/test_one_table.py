"""Every sport in one table: an old install's Workout rows move into Activity, the Ride and Workout views split them, and the duplicate check now
compares walks and runs too (a Garmin run and its Strava copy were both kept while they lived in different tables). Throwaway DB."""
import re
import sqlite3

import pytest
from flask import Flask

import database
from services import duplicates, workouts

OLD_WORKOUT = '''CREATE TABLE Workout (
    id TEXT PRIMARY KEY, riderId INTEGER NOT NULL, sport TEXT NOT NULL, name TEXT, startDate TEXT, startDateLocal TEXT NOT NULL,
    distance REAL, movingTime INTEGER, elapsedTime INTEGER, totalElevationGain REAL, averageSpeed REAL, maxSpeed REAL, averageHeartrate REAL,
    calories REAL, steps INTEGER, startLat REAL, startLng REAL, streams TEXT, weatherSummary TEXT, source TEXT,
    createdAt TEXT DEFAULT (datetime('now')), caloriesRaw REAL, originId TEXT)'''


@pytest.fixture
def app(tmp_path):
    a = Flask(__name__)
    a.config['DATABASE'] = str(tmp_path / 't.db')
    with a.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")                # every real install has its settings row
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
        yield a


def ride(db, rid, start_utc, start_local, sport='Ride', dist=30000.0, secs=4000, hr=None):
    db.execute("INSERT INTO Activity (id, name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedTime, averageHeartrate, rawData, riderId)"
               " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', 1)", [rid, f'{sport} {rid}', sport, sport, start_utc, start_local, dist, secs, secs, hr])


def as_old_install(db):
    """Put the database back the way 0.6 left it: Workout a table of its own, the merge and the workout recheck not done."""
    db.execute('DROP VIEW Workout')
    db.execute('DROP VIEW SegActivity')
    db.execute(OLD_WORKOUT)
    db.execute('UPDATE Settings SET workoutDupCheckDone=0 WHERE id=1')
    db.commit()


def test_an_old_install_moves_its_workouts_in_and_its_twins_are_set_aside(app):
    db = database.get_db()
    as_old_install(db)
    ride(db, 'garmin_1', '2026-07-20T16:00:00', '2026-07-20T17:00:00', hr=140)                                 # a ride, stays a ride
    ride(db, '555', '2026-07-26T21:00:00', '2026-07-26T22:00:00', sport='Run', dist=11800.0, secs=4262)       # Strava's copy of the run, saved as a "ride"
    db.execute("INSERT INTO Workout (id, riderId, sport, name, startDate, startDateLocal, distance, movingTime, elapsedTime, averageHeartrate, steps, source)"
               " VALUES ('garmin_2', 1, 'Run', 'Vancouver Running', '2026-07-26T21:00:00', '2026-07-26T14:00:00', 11800, 4262, 4262, 150, 12000, 'garmin')")
    db.execute("INSERT INTO Workout (id, riderId, sport, startDateLocal, distance, movingTime, source) VALUES ('wk_1', 1, 'Walk', '2026-08-01T09:00:00', 3000, 1800, 'android')")
    db.commit()

    database.migrate_db()
    assert db.execute("SELECT type FROM sqlite_master WHERE name='Workout'").fetchone()[0] == 'view'
    assert db.execute('SELECT COUNT(*) FROM WorkoutPreMerge').fetchone()[0] == 2                       # the old table, untouched
    copy = database.get_db().execute('PRAGMA database_list').fetchone()[2] + '.pre-0.7.0'
    old = sqlite3.connect(copy)
    assert old.execute("SELECT type FROM sqlite_master WHERE name='Workout'").fetchone()[0] == 'table'   # the whole database, as 0.6 left it
    assert old.execute('SELECT COUNT(*) FROM Workout').fetchone()[0] == 2 and old.execute('SELECT COUNT(*) FROM Activity').fetchone()[0] == 2
    old.close()
    assert [r[0] for r in db.execute('SELECT id FROM Ride')] == ['garmin_1']
    assert sorted(r[0] for r in db.execute('SELECT id FROM Workout')) == ['garmin_2', 'wk_1']           # the Strava run is a copy of garmin_2: set aside
    w = db.execute("SELECT * FROM Workout WHERE id='garmin_2'").fetchone()
    assert (w['sport'], w['name'], w['steps'], w['source']) == ('Run', 'Vancouver Running', 12000, 'garmin')
    assert tuple(db.execute("SELECT primaryId, status FROM ActivityDuplicate WHERE id='555'").fetchone()) == ('garmin_2', 'parked')
    tasks = [r[0] for r in db.execute('SELECT task FROM TaskLog')]
    assert 'startup:merge_workouts' in tasks and 'startup:workout_duplicates' in tasks

    database.migrate_db()                                                                              # nothing more to do the second time
    assert db.execute('SELECT COUNT(*) FROM Activity').fetchone()[0] == 3


def test_the_same_id_in_both_tables_keeps_the_activity_row(app):
    db = database.get_db()
    as_old_install(db)
    ride(db, 'garmin_3', '2026-07-20T16:00:00', '2026-07-20T17:00:00', sport='Swim', dist=1500.0)
    db.execute("INSERT INTO Workout (id, riderId, sport, startDateLocal, distance, movingTime, source) VALUES ('garmin_3', 1, 'Swim', '2026-07-20T17:00:00', 1400, 1800, 'garmin')")
    db.commit()
    database.migrate_db()
    assert db.execute("SELECT distance FROM Activity WHERE id='garmin_3'").fetchone()[0] == 1500.0
    assert db.execute("SELECT distance FROM WorkoutPreMerge WHERE id='garmin_3'").fetchone()[0] == 1400.0


def test_a_garmin_walk_lands_on_its_strava_copy(app, monkeypatch):
    from services import garmin
    db = database.get_db()
    ride(db, '777', '2026-07-26T22:10:00', '2026-07-26T23:10:00', sport='Walk', dist=3900.0, secs=3689)
    db.commit()
    parsed = {'distance': 3900.0, 'movingTime': 3689, 'elapsedTime': 3689, 'averageHeartrate': 105, 'calories': 250}
    garmin._save_workout(db, 'garmin_9', 1, 'Walk', 'Vancouver Walking', '2026-07-26T22:10:00', '2026-07-26T15:10:00', parsed, 2.0)
    db.commit()
    assert [r[0] for r in db.execute('SELECT id FROM Workout')] == ['garmin_9']
    assert tuple(db.execute("SELECT primaryId, status FROM ActivityDuplicate WHERE id='777'").fetchone()) == ('garmin_9', 'parked')


def test_a_phone_walk_that_was_set_aside_is_not_saved_again(app, monkeypatch):
    db = database.get_db()
    gpx = ('<?xml version="1.0"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
           + ''.join(f'<trkpt lat="{49.27 + i * 1e-4}" lon="-123.12"><time>2026-07-26T22:{10 + i // 60:02d}:{i % 60:02d}Z</time></trkpt>' for i in range(0, 1800, 10))
           + '</trkseg></trk></gpx>').encode()
    monkeypatch.setattr('services.weather.fetch_weather', lambda *a, **k: None)
    w, created = workouts.save_from_gpx(1, gpx, sport='Walk', client_id='c-1')
    assert created
    ride(db, 'garmin_5', '2026-07-26T22:10:00', '2026-07-26T15:10:00', sport='Walk', dist=w['distance'], secs=w['movingTime'], hr=100)
    db.commit()
    assert duplicates.resolve(db, 'garmin_5')['parked'] == w['id']                                      # the Garmin recording wins
    db.commit()
    again, created = workouts.save_from_gpx(1, gpx, sport='Walk', client_id='c-1')                      # the phone retries the upload
    assert not created and again['id'] == 'garmin_5' and again['sport'] == 'Walk'
    assert db.execute('SELECT COUNT(*) FROM Activity').fetchone()[0] == 1


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def test_the_history_shows_every_sport_and_can_leave_some_out(tmp_path, monkeypatch):
    import app as app_module
    import config
    from services import credentials
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'full.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)       # no MQTT / Garmin / friend background loops
    full = app_module.create_app()
    with full.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        ride(db, 'r1', '2026-07-20T16:00:00', '2026-07-20T17:00:00')
        ride(db, 'w1', '2026-07-21T15:00:00', '2026-07-21T16:00:00', sport='Walk', dist=4000.0)
        db.execute("UPDATE Activity SET name=NULL WHERE id='w1'")
        db.commit()
        av = credentials.auth_version()
    c = full.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    page = c.get('/dashboard').get_data(as_text=True)
    assert '/rides/r1' in page and '/rides/w1' in page and 'Afternoon walk' in page                   # a walk with no name gets one
    assert 'data-sport value="Walk" checked' in page and 'data-sport value="Ride" checked' in page      # every sport included to start with
    page = c.get('/dashboard?skip=Walk').get_data(as_text=True)
    assert '/rides/r1' in page and '/rides/w1' not in page
    assert re.search(r'data-sport value="Walk"\s+onchange', page) and 'data-sport value="Ride" checked' in page and 'Tick all' in page    # the left-out one is unticked
