"""Activities both live and set aside as a copy (a Strava export imported before 0.7.11 saved them again): decided again once at start-up
(services/duplicates.repair_live_parked), and an import that can't bring a copy set aside back. Throwaway DB."""
import io
import json
import zipfile

import pytest
from flask import Flask

import database
from routes import import_rides
from services import duplicates, photos


@pytest.fixture
def db(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'A', 1)")
        photos.ensure_schema(d)
        d.commit()
        yield d


def _track(secs, speed):
    return json.dumps({'time': {'data': list(range(0, secs + 1, 5))}, 'distance': {'data': [i * speed for i in range(0, secs + 1, 5)]}})


def _add(db, aid, name, day='2026-01-10', hour=9, dist=12000.0, secs=3600, sport='Ride', hr=None, streams=None, commute=None):
    start = f'{day}T{hour:02d}:00:00'
    db.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDate, startDateLocal, distance, movingTime, elapsedTime, averageSpeed, "
               "averageHeartrate, streams, commute, rawData) VALUES (?,?,?,?,1,?,?,?,?,?,?,?,?,?,'{}')",
               [aid, name, sport, sport, start + 'Z', start, dist, secs, secs, dist / secs, hr, streams, commute])


def _park_stale(db, aid, primary, reason='Kept the Garmin recording (recorded on a Garmin device).'):
    """What the old import left: a parked row for an id that is live again, with the row as it was when it was set aside."""
    db.execute("INSERT INTO ActivityDuplicate (id, primaryId, riderId, source, reason, status, rowJson) VALUES (?,?,1,'Phone or file',?,'parked',?)",
               [aid, primary, reason, json.dumps({'id': aid, 'name': 'Ride', 'riderId': 1})])


def _live(db):
    return sorted(r[0] for r in db.execute('SELECT id FROM Activity'))


def _dups(db):
    return {r['id']: (r['primaryId'], r['status']) for r in db.execute('SELECT id, primaryId, status FROM ActivityDuplicate')}


def test_live_copies_set_aside_are_decided_again_once(db):
    # A: Garmin's made-up name, the Strava copy has the rider's name, a photo and the commute tick. Garmin's recording wins, with all of that.
    _add(db, 'garmin_1', 'London Cycling', streams=_track(3600, 3.4))
    _add(db, '111', 'Box Hill loop', hr=140, commute=1, streams=_track(3600, 3.4))
    db.execute("INSERT INTO BestEffort (activityId, activityDate, distanceMi, elapsedSecs) VALUES ('111', '2026-01-10', 5, 2400)")
    db.execute("INSERT INTO ActivityPhoto (activityId, filename, sourceKey) VALUES ('111', 'act_1.jpg', 'strava:media/1.jpg')")
    _park_stale(db, '111', 'garmin_1')
    # B: a converted ski day with a generic name, behind which the Strava day with heart rate was set aside: now the Strava day wins, and a copy
    # set aside behind the converted one follows it
    _add(db, 'wk_b', 'Morning Ski', day='2026-01-11', sport='AlpineSki')
    _add(db, '222', "Alpe d'Huez day 2", day='2026-01-11', sport='AlpineSki', hr=120)
    _park_stale(db, '222', 'wk_b')
    _park_stale(db, '333', 'wk_b')                         # not live: only its parked row
    # C: no longer the same ride (it starts three hours later): both kept
    _add(db, 'garmin_4', 'Commute', day='2026-01-12')
    _add(db, '444', 'Evening commute', day='2026-01-12', hour=12)
    _park_stale(db, '444', 'garmin_4')
    # D: the rider chose the other recording: that choice stands, whatever the scores
    _add(db, 'garmin_5', 'Ride', day='2026-01-13')
    _add(db, '555', 'Hill reps', day='2026-01-13', hr=150)
    _park_stale(db, '555', 'garmin_5', duplicates.CHOSEN)
    # E: set aside behind an activity since deleted: stays live, as its own
    _add(db, '666', 'Solo', day='2026-01-14')
    _park_stale(db, '666', 'gone')
    # F: thrown away, then imported again: the stale row goes; one not live is still remembered
    _add(db, '777', 'Back again', day='2026-01-15')
    db.execute("INSERT INTO ActivityDuplicate (id, primaryId, riderId, status, rowJson) VALUES ('777', 'x', 1, 'discarded', '{}')")
    db.execute("INSERT INTO ActivityDuplicate (id, primaryId, riderId, status, rowJson) VALUES ('888', 'x', 1, 'discarded', '{}')")
    db.execute('UPDATE Settings SET liveParkedFixDone=0')
    db.commit()

    res = duplicates.repair_live_parked(db)
    assert res['ran'] and res['orphans'] == 1 and res['discarded'] == 1 and res['apart'] == [('444', 'garmin_4')]
    assert sorted((k, p) for k, p, _ in res['decided']) == [('222', 'wk_b'), ('garmin_1', '111'), ('garmin_5', '555')]
    assert _live(db) == ['222', '444', '666', '777', 'garmin_1', 'garmin_4', 'garmin_5']
    assert _dups(db) == {'111': ('garmin_1', 'parked'), 'wk_b': ('222', 'parked'), '333': ('222', 'parked'), '555': ('garmin_5', 'parked'),
                         '888': ('x', 'discarded')}

    a = db.execute("SELECT * FROM Activity WHERE id='garmin_1'").fetchone()
    assert (a['name'], a['commute']) == ('Box Hill loop', 1)
    assert json.loads(db.execute("SELECT rowJson FROM ActivityDuplicate WHERE id='111'").fetchone()[0])['name'] == 'Box Hill loop'   # as it is now
    assert db.execute("SELECT activityId FROM ActivityPhoto").fetchone()[0] == 'garmin_1'
    assert {r[0] for r in db.execute('SELECT activityId FROM BestEffort')} == {'garmin_1'}           # worked out for the one kept, gone with the copy
    assert db.execute("SELECT reason FROM ActivityDuplicate WHERE id='555'").fetchone()[0] == duplicates.CHOSEN

    assert duplicates.repair_live_parked(db)['ran'] is False        # once only


CSV_HEAD = 'Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Filename,Moving Time,Distance\n'


def _strava_zip(*rows):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('activities.csv', CSV_HEAD + ''.join(rows))
    buf.seek(0)
    return zipfile.ZipFile(buf)


def test_an_import_never_brings_a_copy_set_aside_back(db):
    _add(db, 'garmin_1', 'Box Hill loop')
    db.commit()
    db.execute("INSERT INTO ActivityDuplicate (id, primaryId, riderId, reason, status, rowJson) VALUES ('111', 'garmin_1', 1, 'x', 'parked', ?)",
               [json.dumps({'id': '111', 'name': 'Box Hill loop'})])
    db.execute("INSERT INTO ActivityDuplicate (id, primaryId, riderId, status, rowJson) VALUES ('222', '', 1, 'discarded', '{}')")
    db.commit()
    z = _strava_zip('111,"Jan 10, 2026, 9:00:00 AM",Box Hill loop,Ride,3600,12,activities/111.gpx,3600,12000.0\n',     # recordings (a file),
                    '222,"Jan 11, 2026, 9:00:00 AM",Thrown away,Ride,3600,12,activities/222.gpx,3600,12000.0\n')    # not manual entries
    for _ in range(2):                                     # and importing the same export again changes nothing
        done = [json.loads(e[len('data: '):]) for e in import_rides._process_strava_export(z, z.namelist(), 1)][-1]
        db.commit()
        assert done['imported'] == 0
        assert _live(db) == ['garmin_1']
        assert _dups(db) == {'111': ('garmin_1', 'parked'), '222': ('', 'discarded')}
