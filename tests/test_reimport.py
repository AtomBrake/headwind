"""Importing a ride that's already saved: the same ride is skipped, a different one waits on the Import page, and the rider's choice is applied
without losing their own edits. Throwaway DB."""
import io
import json
import zipfile

import pytest
from flask import Flask

import database
from routes import import_rides
from services import reimport, sanity

GPX = ('<?xml version="1.0"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>Tour</name><trkseg>'
       + ''.join(f'<trkpt lat="{50.4 + i * 0.0001:.5f}" lon="-4.7"><ele>{50 + i % 5}</ele><time>2026-07-04T09:{i // 60:02d}:{i % 60:02d}Z</time></trkpt>'
                 for i in range(0, 600, 10))
       + '</trkseg></trk></gpx>')
CSV_HEAD = 'Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Moving Time,Elapsed Time,Distance,Filename\n'


@pytest.fixture
def db(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.execute("INSERT INTO Bike (id, riderId, name, kind) VALUES (1, 1, 'Road bike', 'road')")
        d.commit()
        yield d


def strava_zip(rows, files=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('activities.csv', CSV_HEAD + ''.join(rows))
        for name, text in files:
            z.writestr(name, text)
    buf.seek(0)
    return zipfile.ZipFile(buf)


def run_import(db, z):
    events = [json.loads(e[len('data: '):]) for e in import_rides._process_strava_export(z, z.namelist(), 1)]
    db.commit()
    return events[-1]


def test_a_broken_ride_imported_again_waits_for_review_then_is_repaired(db):
    # first import: no readable file, and the CSV distance read 1000x too big (the 0.5.7 bug)
    db.execute("INSERT INTO Activity (id, name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedTime, totalElevationGain, averageSpeed, "
               "streams, rawData, riderId, bikeId, createdAt, updatedAt) VALUES ('20294689368', 'Lanhydrock loop (renamed)', 'Ride', 'Ride', '2026-07-04T09:00:00', "
               "'2026-07-04T10:00:00', 45959500, 590, 600, 0, 77897, '{}', '{}', 1, 1, 'n', 'n')")
    sanity.flag(db, '20294689368')
    db.commit()
    assert 'beyond any ride' in db.execute("SELECT flagReason FROM Activity").fetchone()[0]

    z = strava_zip(['20294689368,"Jul 4, 2026, 9:00:00 AM",Lanhydrock Tour,Ride,600,45.96,590,600,45959.5,activities/1.gpx\n'], [('activities/1.gpx', GPX)])
    done = run_import(db, z)
    assert done['changed'] == 1 and done['imported'] == 0
    assert db.execute("SELECT distance FROM Activity").fetchone()[0] == 45959500           # nothing overwritten yet
    [c] = reimport.pending(db)
    labels = {d['label'] for d in c['diffs']}
    assert {'Distance', 'Recorded data'} <= labels and 'Start' not in labels                 # same start, once both are local time

    assert reimport.resolve(db, '20294689368', 'replace')
    db.commit()
    r = db.execute("SELECT name, bikeId, distance, flagReason, streams FROM Activity").fetchone()
    assert r['name'] == 'Lanhydrock loop (renamed)' and r['bikeId'] == 1                     # the rider's edits stay
    assert r['distance'] < 10000 and r['flagReason'] is None and 'latlng' in json.loads(r['streams'])
    assert reimport.pending(db) == []


def test_the_same_ride_imported_again_is_just_skipped(db):
    z = strava_zip(['77,"Jul 4, 2026, 9:00:00 AM",Tour,Ride,600,1.0,590,600,1000,activities/1.gpx\n'], [('activities/1.gpx', GPX)])
    first = run_import(db, z)
    assert first['imported'] == 1
    again = run_import(db, strava_zip(['77,"Jul 4, 2026, 9:00:00 AM",Tour,Ride,600,1.0,590,600,1000,activities/1.gpx\n'], [('activities/1.gpx', GPX)]))
    assert again['imported'] == 0 and again['changed'] == 0 and again['skipped'] == 1 and reimport.pending(db) == []


def test_fill_only_adds_what_is_missing_and_keep_changes_nothing(db):
    db.execute("INSERT INTO Activity (id, name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedTime, totalElevationGain, averageSpeed, "
               "averageHeartrate, streams, rawData, riderId, createdAt, updatedAt) VALUES ('88', 'Tour', 'Ride', 'Ride', '2026-07-04T09:00:00', '2026-07-04T10:00:00', "
               "6000, 590, 600, 0, 10.2, 140, ?, '{}', 1, 'n', 'n')", [json.dumps({'heartrate': {'data': [140] * 5}})])
    db.commit()
    run_import(db, strava_zip(['88,"Jul 4, 2026, 9:00:00 AM",Tour,Ride,600,1.0,590,600,1000,activities/1.gpx\n'], [('activities/1.gpx', GPX)]))
    assert reimport.resolve(db, '88', 'fill')
    r = db.execute("SELECT distance, averageHeartrate, streams FROM Activity WHERE id='88'").fetchone()
    s = json.loads(r['streams'])
    assert r['distance'] == 6000 and r['averageHeartrate'] == 140                                # saved values kept
    assert 'latlng' in s and s['heartrate']['data'] == [140] * 5                                 # the track added, its own HR kept

    run_import(db, strava_zip(['88,"Jul 4, 2026, 9:00:00 AM",Tour,Ride,600,1.0,590,600,1000,activities/1.gpx\n'], [('activities/1.gpx', GPX)]))
    before = dict(db.execute("SELECT * FROM Activity WHERE id='88'").fetchone())
    assert reimport.resolve(db, '88', 'keep') is False
    assert dict(db.execute("SELECT * FROM Activity WHERE id='88'").fetchone()) == before and reimport.pending(db) == []
    with pytest.raises(ValueError):
        reimport.resolve(db, '88', 'shred')


def test_differences_ignore_what_the_file_does_not_have():
    saved = {'id': 'x', 'distance': 10000, 'movingTime': 1800, 'elapsedTime': 1900, 'totalElevationGain': 100, 'startDateLocal': '2026-07-04T10:00:00',
             'streams': json.dumps({'latlng': {'data': [[1, 2]]}})}
    assert reimport.differences(saved, {'distance': 10040, 'movingTime': 1810, 'totalElevationGain': 105, 'startDateLocal': '2026-07-04T10:01:00'}) == []
    assert reimport.differences(saved, {'distance': None, 'movingTime': 0, 'streams': '{}'}) == []
    assert [d['label'] for d in reimport.differences(saved, {'distance': 12000})] == ['Distance']


def test_import_page_lists_changes_and_applies_a_choice(tmp_path, monkeypatch):
    import app as app_module
    import config
    from services import credentials

    class _NoThread:
        def __init__(self, *a, **kw): pass
        def start(self): pass
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'app.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.setattr('services.mqtt.push_update', lambda *a, **k: None)
    app = app_module.create_app()
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        db.execute("INSERT INTO Activity (id, name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedTime, streams, rawData, riderId, createdAt, updatedAt) "
                   "VALUES ('5', 'Tour', 'Ride', 'Ride', '2026-07-04T09:00:00', '2026-07-04T10:00:00', 45959500, 590, 600, '{}', '{}', 1, 'n', 'n')")
        reimport.propose(db, db.execute("SELECT * FROM Activity").fetchone(), {'distance': 45959.5}, 'Strava export')
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    html = c.get('/import').get_data(as_text=True)
    assert '1 ride differs from what' in html and 'Use import' in html and 'from Strava export' in html
    assert c.post('/import/changes/all/replace').status_code == 302
    with app.app_context():
        assert database.get_db().execute("SELECT distance FROM Activity").fetchone()[0] == 45959.5
    assert 'id="changes"' not in c.get('/import').get_data(as_text=True)
