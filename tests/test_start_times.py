"""Imported rides start at the right local time (file and Strava times are UTC), so the Garmin copy of the same ride is recognised as a duplicate;
and the one-off repair of rides already saved an hour early. Throwaway DB."""
import io
import zipfile
from datetime import datetime

import pytest
from flask import Flask

import database
from routes import import_rides
from services import duplicates
from services.parser import _utc_iso
from services.start_times import fix_utc_starts

STREAMS = '{}'


@pytest.fixture
def db(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("UPDATE Settings SET utcStartFixDone=0 WHERE id=1")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
        yield d


def add(db, rid, start_utc, start_local, dist=19500.0, secs=1980, hr=None, sport='VirtualRide'):
    db.execute("INSERT INTO Activity (id, name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedTime, averageHeartrate, streams, rawData, riderId, createdAt, updatedAt)"
               " VALUES (?, 'Zwift - Group Ride', ?, ?, ?, ?, ?, ?, ?, ?, '{}', '{}', 1, 'n', 'n')", [rid, sport, sport, start_utc, start_local, dist, secs, secs, hr])
    db.commit()


def test_file_times_are_marked_utc():
    assert _utc_iso(datetime(2026, 10, 17, 17, 30)) == '2026-10-17T17:30:00+00:00'
    a, b = import_rides._split_start({'startDateLocal': _utc_iso(datetime(2026, 10, 17, 17, 30))})
    assert (a, b) == ('2026-10-17T17:30:00', '2026-10-17T18:30:00')                   # BST: an hour on
    a, b = import_rides._split_start({'startDateLocal': _utc_iso(datetime(2026, 12, 1, 17, 30))})
    assert a == b == '2026-12-01T17:30:00'                                           # GMT: the same


def test_a_strava_export_ride_lands_on_its_garmin_twin(db):
    add(db, 'garmin_1', '2026-10-17T17:30:00', '2026-10-17T18:30:00', hr=150)        # what Garmin gives: real local time
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('activities.csv', 'Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Moving Time,Distance\n'
                                     '555,"Oct 17, 2026, 5:30:00 PM",Zwift - Group Ride,Virtual Ride,1980,1980,19.5\n')
    with zipfile.ZipFile(buf) as z:
        list(import_rides._process_strava_export(z, z.namelist(), 1))
    db.commit()
    assert db.execute("SELECT 1 FROM Activity WHERE id='555'").fetchone() is None        # not a second live ride
    parked = db.execute("SELECT primaryId, status FROM ActivityDuplicate WHERE id='555'").fetchone()
    assert tuple(parked) == ('garmin_1', 'parked')


def test_repair_moves_old_imports_and_sets_their_twins_aside(db):
    add(db, 'garmin_1', '2026-10-17T17:30:00', '2026-10-17T18:30:00', hr=150)
    add(db, '555', '2026-10-17T17:30:00', '2026-10-17T17:30:00')                       # imported before the fix: UTC stored as local
    add(db, 'imp_win', '2026-01-10T09:00:00', '2026-01-10T09:00:00', dist=30000)       # winter: UTC is local, nothing to move
    add(db, 'imp_ok', '2026-07-01T08:00:00', '2026-07-01T09:00:00', dist=25000)         # already right
    add(db, 'man_1', '2026-07-02T10:00:00', '2026-07-02T10:00:00', dist=10000)          # typed in by hand: local already
    res = fix_utc_starts(db)
    assert res == {'moved': 1, 'duplicates': 1, 'ran': True}
    assert db.execute("SELECT 1 FROM Activity WHERE id='555'").fetchone() is None
    assert db.execute("SELECT startDateLocal FROM ActivityDuplicate d JOIN Activity a ON a.id=d.primaryId WHERE d.id='555'").fetchone()[0] == '2026-10-17T18:30:00'
    times = dict(db.execute("SELECT id, startDateLocal FROM Activity").fetchall())
    assert times == {'garmin_1': '2026-10-17T18:30:00', 'imp_win': '2026-01-10T09:00:00', 'imp_ok': '2026-07-01T09:00:00', 'man_1': '2026-07-02T10:00:00'}
    assert fix_utc_starts(db) == {'moved': 0, 'duplicates': 0, 'ran': False}                          # once only


def test_an_import_with_no_twin_just_gets_the_right_time(db):
    add(db, '777', '2026-08-03T06:15:00', '2026-08-03T06:15:00')
    assert fix_utc_starts(db) == {'moved': 1, 'duplicates': 0, 'ran': True}
    assert db.execute("SELECT startDate, startDateLocal FROM Activity WHERE id='777'").fetchone()[:] == ('2026-08-03T06:15:00', '2026-08-03T07:15:00')
