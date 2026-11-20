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
from services import streams as _streams

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
               "rawData, riderId, bikeId, createdAt, updatedAt) VALUES ('20294689368', 'Lanhydrock loop (renamed)', 'Ride', 'Ride', '2026-07-04T09:00:00', "
               "'2026-07-04T10:00:00', 45959500, 590, 600, 0, 77897, '{}', 1, 1, 'n', 'n')")
    _streams.save(db, '20294689368', '{}')
    sanity.flag(db, '20294689368')
    db.commit()
    assert 'beyond any ride' in db.execute("SELECT flagReason FROM Activity").fetchone()[0]

    z = strava_zip(['20294689368,"Jul 4, 2026, 9:00:00 AM",Lanhydrock Tour,Ride,6000,45.96,5900,6000,45959.5,activities/1.gpx\n'], [('activities/1.gpx', GPX)])
    done = run_import(db, z)
    assert done['changed'] == 1 and done['imported'] == 0
    assert db.execute("SELECT distance FROM Activity").fetchone()[0] == 45959500           # nothing overwritten yet
    [c] = reimport.pending(db)
    labels = {d['label'] for d in c['diffs']}
    assert {'Distance', 'Recorded data'} <= labels and 'Start' not in labels                 # same start, once both are local time

    assert reimport.resolve(db, '20294689368', 'replace')
    db.commit()
    r = db.execute(f"SELECT name, bikeId, distance, flagReason, {_streams.sql()} FROM Activity").fetchone()
    assert r['name'] == 'Lanhydrock loop (renamed)' and r['bikeId'] == 1                     # the rider's edits stay
    assert r['distance'] == 45959.5 and r['flagReason'] is None and 'latlng' in json.loads(r['streams'])   # Strava's own figure, in metres
    assert reimport.pending(db) == []


def test_the_same_ride_imported_again_is_just_skipped(db):
    z = strava_zip(['77,"Jul 4, 2026, 9:00:00 AM",Tour,Ride,600,1.0,590,600,1000,activities/1.gpx\n'], [('activities/1.gpx', GPX)])
    first = run_import(db, z)
    assert first['imported'] == 1
    again = run_import(db, strava_zip(['77,"Jul 4, 2026, 9:00:00 AM",Tour,Ride,600,1.0,590,600,1000,activities/1.gpx\n'], [('activities/1.gpx', GPX)]))
    assert again['imported'] == 0 and again['changed'] == 0 and again['skipped'] == 1 and reimport.pending(db) == []


def test_fill_only_adds_what_is_missing_and_keep_changes_nothing(db):
    db.execute("INSERT INTO Activity (id, name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedTime, totalElevationGain, averageSpeed, "
               "averageHeartrate, rawData, riderId, createdAt, updatedAt) VALUES ('88', 'Tour', 'Ride', 'Ride', '2026-07-04T09:00:00', '2026-07-04T10:00:00', "
               "6000, 590, 600, 0, 10.2, 140, '{}', 1, 'n', 'n')", [])
    _streams.save(db, '88', json.dumps({'heartrate': {'data': [140] * 5}}))
    db.commit()
    run_import(db, strava_zip(['88,"Jul 4, 2026, 9:00:00 AM",Tour,Ride,600,1.0,590,600,1000,activities/1.gpx\n'], [('activities/1.gpx', GPX)]))
    assert reimport.resolve(db, '88', 'fill')
    r = db.execute(f"SELECT distance, averageHeartrate, {_streams.sql()} FROM Activity WHERE id='88'").fetchone()
    s = json.loads(r['streams'])
    assert r['distance'] == 6000 and r['averageHeartrate'] == 140                                # saved values kept
    assert 'latlng' in s and s['heartrate']['data'] == [140] * 5                                 # the track added, its own HR kept

    run_import(db, strava_zip(['88,"Jul 4, 2026, 9:00:00 AM",Tour,Ride,600,1.0,590,600,1000,activities/1.gpx\n'], [('activities/1.gpx', GPX)]))
    before = dict(db.execute(f"SELECT *, {_streams.sql()} FROM Activity WHERE id='88'").fetchone())
    assert reimport.resolve(db, '88', 'keep') is False
    assert dict(db.execute(f"SELECT *, {_streams.sql()} FROM Activity WHERE id='88'").fetchone()) == before and reimport.pending(db) == []
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
        db.execute("INSERT INTO Activity (id, name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedTime, rawData, riderId, createdAt, updatedAt) "
                   "VALUES ('5', 'Tour', 'Ride', 'Ride', '2026-07-04T09:00:00', '2026-07-04T10:00:00', 45959500, 590, 600, '{}', 1, 'n', 'n')")
        _streams.save(db, '5', '{}')
        reimport.propose(db, db.execute(f"SELECT *, {_streams.sql()} FROM Activity").fetchone(), {'distance': 45959.5}, 'Strava export')
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    html = c.get('/import').get_data(as_text=True)
    assert '1 activity in the import differs from what' in html and 'Use the file' in html and 'from Strava export' in html
    assert 'Fill in gaps</button>' not in html                                      # nothing missing from the saved ride: not offered
    assert c.post('/import/changes/all/fill').status_code == 302
    with app.app_context():
        assert len(reimport.pending(database.get_db())) == 1                        # filling all gaps leaves it to be chosen
    assert c.post('/import/changes/all/replace').status_code == 302
    with app.app_context():
        assert database.get_db().execute("SELECT distance FROM Activity").fetchone()[0] == 45959.5
    assert 'id="changes"' not in c.get('/import').get_data(as_text=True)


def test_fill_in_gaps_is_offered_only_for_what_the_saved_ride_lacks(db):
    db.execute("INSERT INTO Activity (id, name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedTime, rawData, riderId, createdAt, updatedAt) "
               "VALUES ('6', 'Tour', 'Ride', 'Ride', '2026-07-04T09:00:00', '2026-07-04T10:00:00', 45959, 590, 600, '{}', 1, 'n', 'n')")
    reimport.propose(db, db.execute("SELECT * FROM Activity").fetchone(),
                     {'distance': 45959, 'movingTime': 900, 'averageHeartrate': 140, 'maxHeartrate': 170, 'calories': 300}, 'Garmin')
    [c] = reimport.pending(db)
    assert c['fills'] == ['heart rate', 'calories'] and c['sportType'] == 'Ride'     # moving time is there already: a difference, not a gap
    assert reimport.fill_adds({**{k: 1 for k in reimport.FILL_LABELS}, 'streams': 1}, {'streams': '{}'},
                              [{'label': 'Recorded data', 'old': 'GPS, altitude', 'new': 'GPS, altitude, heart rate'}]) == ['heart rate']


def _saved_track(db, ride_id):
    s = json.loads(_streams.load_json(db, ride_id))
    return s['time']['data'], s['distance']['data'], s['latlng']['data']


def test_a_ride_cropped_on_strava_keeps_only_the_window_strava_kept(db):
    # the file runs 09:00:00 to 09:09:50; on Strava the ride starts at 09:02 and lasts 3 minutes
    z = strava_zip(['55,"Jul 4, 2026, 9:02:00 AM",Cropped,Ride,180,0.33,170,180,333.0,activities/1.gpx\n'], [('activities/1.gpx', GPX)])
    assert run_import(db, z)['imported'] == 1
    t, d, ll = _saved_track(db, '55')
    assert t[0] == 0 and t[-1] == 180 and d[0] == 0 and len(ll) == len(t) == 19
    assert abs(ll[0][0] - (50.4 + 120 * 0.0001)) < 1e-6                                        # the file's point at 09:02:00
    r = db.execute("SELECT distance, movingTime, elapsedTime, startLat FROM Activity WHERE id='55'").fetchone()
    assert (r['distance'], r['movingTime'], r['elapsedTime']) == (333.0, 170, 180) and abs(r['startLat'] - ll[0][0]) < 1e-9


def test_a_clock_that_is_out_is_not_taken_for_a_crop(db):
    # Strava's start an hour before the file's (a device that wrote local time as UTC): the window doesn't fit the recording, so nothing is cut
    z = strava_zip(['56,"Jul 4, 2026, 8:00:00 AM",Clock,Ride,590,0.66,590,590,660.0,activities/1.gpx\n'], [('activities/1.gpx', GPX)])
    run_import(db, z)
    t, _, _ = _saved_track(db, '56')
    assert len(t) == 60 and t[-1] == 590


def test_importing_again_after_a_crop_on_strava_offers_the_cropped_track(db):
    run_import(db, strava_zip(['57,"Jul 4, 2026, 9:00:00 AM",Whole,Ride,590,0.66,590,590,660.0,activities/1.gpx\n'], [('activities/1.gpx', GPX)]))
    done = run_import(db, strava_zip(['57,"Jul 4, 2026, 9:02:00 AM",Whole,Ride,180,0.33,170,180,333.0,activities/1.gpx\n'], [('activities/1.gpx', GPX)]))
    assert done['changed'] == 1
    [c] = reimport.pending(db)
    track = next(x for x in c['diffs'] if x['label'] == 'Track')
    assert track['old'] == '9:50 recorded' and track['new'] == '3:00 recorded'
    assert reimport.resolve(db, '57', 'replace')
    db.commit()
    assert _saved_track(db, '57')[0][-1] == 180


def test_a_crop_takes_stravas_climb_and_top_speed_even_a_climb_of_nothing(db):
    """Like "A Cracking Ride": 7 hours recorded, 27:33 kept on Strava, 0.61 km, 0 m climbed, 29.2 km/h top speed."""
    head = 'Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Moving Time,Elapsed Time,Distance,Elevation Gain,Max Speed,Filename\n'

    def zip_of(row):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('activities.csv', head + row)
            z.writestr('activities/1.gpx', GPX)
        buf.seek(0)
        return zipfile.ZipFile(buf)

    run_import(db, zip_of('58,"Jul 4, 2026, 9:00:00 AM",Cracking,Ride,590,0.66,590,590,660.0,12.0,9.0,activities/1.gpx\n'))
    run_import(db, zip_of('58,"Jul 4, 2026, 9:02:00 AM",Cracking,Ride,180,0.33,110,180,333.0,0,8.1,activities/1.gpx\n'))
    assert reimport.resolve(db, '58', 'replace')
    db.commit()
    r = db.execute("SELECT distance, movingTime, elapsedTime, totalElevationGain, maxSpeed FROM Activity WHERE id='58'").fetchone()
    assert (r['distance'], r['movingTime'], r['elapsedTime'], r['totalElevationGain'], r['maxSpeed']) == (333.0, 110, 180, 0, 8.1)


def test_a_gap_in_the_recording_is_not_taken_for_a_crop(db):
    # Strava leaves a stopped device's gap out of its elapsed time: 180 s here for a 590 s recording, but its distance is the whole track's
    whole = round(sum(__import__('services.best_efforts', fromlist=['x'])._haversine(50.4 + i * 0.0001, -4.7, 50.4 + (i + 10) * 0.0001, -4.7)
                      for i in range(0, 590, 10)), 1)
    run_import(db, strava_zip([f'59,"Jul 4, 2026, 9:00:00 AM",Gap,Ride,180,0.65,170,180,{whole},activities/1.gpx\n'], [('activities/1.gpx', GPX)]))
    t, _, _ = _saved_track(db, '59')
    assert len(t) == 60 and t[-1] == 590


def test_a_later_start_on_strava_is_always_a_crop(db):
    # Strava's distance said nothing useful (0.0 km in the export), but the start moved: that is a crop
    run_import(db, strava_zip(['60,"Jul 4, 2026, 9:02:00 AM",Late,Ride,180,0,170,180,0,activities/1.gpx\n'], [('activities/1.gpx', GPX)]))
    assert _saved_track(db, '60')[0][-1] == 180


def test_a_crop_to_the_end_of_a_session_that_ran_on_past_its_last_record_is_made():
    """Alpe d'Huez, 13 Mar 2025: the watch's session ran 32 s past its last record, and Strava's crop kept from 625 s in to the session's end.
    Taken for a clock that was out, the whole day was kept under the crop's start, 625 s late, and never matched the watch's own copy."""
    from datetime import datetime, timezone
    from services.parser import crop
    t = list(range(0, 591, 10))
    act = {'startDateLocal': '2026-07-04T09:00:00+00:00', 'elapsedTime': 622, 'streams': json.dumps({'time': {'data': t}})}
    cut = crop(act, datetime(2026, 7, 4, 9, 2, tzinfo=timezone.utc), 502)
    assert cut.get('cropped') and json.loads(cut['streams'])['time']['data'] == [x - 120 for x in t if x >= 120]
    assert not crop(act, datetime(2026, 7, 4, 9, 2, tzinfo=timezone.utc), 560).get('cropped')        # past the session's end: a clock out


def test_a_paused_recording_is_not_taken_for_a_crop(db):
    """A bike park day: the recording paused for each uplift, so the track jumps from the bottom to the top. Strava leaves the pause out of
    its elapsed time and the jump out of its distance; that is not a crop."""
    pts = [(s, 50.4 + s * 0.00002) for s in range(0, 300, 10)] + [(s, 50.5 + (s - 1500) * 0.00002) for s in range(1500, 1800, 10)]
    gpx = ('<?xml version="1.0"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
           + ''.join(f'<trkpt lat="{lat:.6f}" lon="-4.7"><time>2026-07-04T09:{s // 60:02d}:{s % 60:02d}Z</time></trkpt>' for s, lat in pts)
           + '</trkseg></trk></gpx>')
    ridden = 2 * 29 * 10 * 0.00002 * 111_195          # both runs, not the jump between them
    run_import(db, strava_zip([f'61,"Jul 4, 2026, 9:00:00 AM",BPW,Ride,590,0.13,580,590,{ridden:.1f},activities/1.gpx\n'], [('activities/1.gpx', gpx)]))
    t, _, _ = _saved_track(db, '61')
    assert t[-1] == 1790
