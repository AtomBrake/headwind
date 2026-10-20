"""A Strava export's moving time is Strava's (rawData.stravaMoving), and the start-up repairs that work moving time out from the track
(services/moving_time) leave it alone. Found on a new install whose second start cut 167 of them. Full app, throwaway DB."""
import io
import json
import zipfile

import pytest

import app as app_module
import config
import database
from routes import import_rides
from services import moving_time

# 600 s on the track, moving all the way (1.1 m/s): the track's moving time is about 590 s
GPX = ('<?xml version="1.0"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>Tour</name><trkseg>'
       + ''.join(f'<trkpt lat="{50.4 + i * 0.0001:.5f}" lon="-4.7"><ele>50</ele><time>2026-07-04T09:{i // 60:02d}:{i % 60:02d}Z</time></trkpt>'
                 for i in range(0, 600, 10))
       + '</trkseg></trk></gpx>')
CSV_HEAD = 'Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Moving Time,Elapsed Time,Distance,Filename\n'
# Strava's 900 s is "well over" the track's (repair_paused would cut it); its 200 s is under half (repair would raise it)
ROWS = ['101,"Jul 4, 2026, 9:00:00 AM",Uplift day,Ride,900,0.66,900,900,660,activities/101.gpx\n',
        '102,"Jul 5, 2026, 9:00:00 AM",Lap timer,Ride,600,0.66,200,600,660,activities/102.gpx\n']


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    return app_module.create_app()


def _zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('activities.csv', CSV_HEAD + ''.join(ROWS))
        z.writestr('activities/101.gpx', GPX)
        z.writestr('activities/102.gpx', GPX.replace('2026-07-04', '2026-07-05'))
    buf.seek(0)
    return zipfile.ZipFile(buf)


def _import(db):
    z = _zip()
    done = [json.loads(e[len('data: '):]) for e in import_rides._process_strava_export(z, z.namelist(), 1)][-1]
    db.commit()
    return done


def _moving(db):
    return {r['id']: r['movingTime'] for r in db.execute('SELECT id, movingTime FROM Activity')}


def test_a_new_install_imports_an_export_and_the_next_start_changes_nothing(app):
    from services import credentials
    client = app.test_client()
    with app.app_context(), client.session_transaction() as sess:
        sess['logged_in'], sess['av'] = True, credentials.auth_version()
    client.post('/setup?step=1', data={'riders[]': 'Tom'})
    client.post('/setup?step=2', data={'units': 'metric'})
    with app.app_context():
        db = database.get_db()
        assert _import(db)['imported'] == 2
        before = {r['id']: tuple(r) for r in db.execute('SELECT id, movingTime, averageSpeed, distance FROM Activity')}
        assert {k: v[1] for k, v in before.items()} == {'101': 900, '102': 200}
        database.migrate_db()                               # the second start
        assert {r['id']: tuple(r) for r in db.execute('SELECT id, movingTime, averageSpeed, distance FROM Activity')} == before
        s = db.execute('SELECT * FROM Settings WHERE id=1').fetchone()
        assert s['units'] == 'metric' and all(s[f] == 1 for f in database._REPAIR_FLAGS)
        assert db.execute("SELECT COUNT(*) FROM TaskLog WHERE task LIKE 'startup:%'").fetchone()[0] == 0


def test_the_repairs_leave_stravas_moving_time_alone(app):
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        _import(db)
        assert {json.loads(r[0]).get('stravaMoving') for r in db.execute('SELECT rawData FROM Activity')} == {900, 200}
        db.execute('UPDATE Settings SET movingTimeFixDone=0, movingTimePausedDone=0')
        assert moving_time.repair(db) == {'ran': True, 'fixed': []}
        assert moving_time.repair_paused(db) == {'ran': True, 'fixed': []}
        assert _moving(db) == {'101': 900, '102': 200}


def test_an_older_import_with_the_files_moving_time_is_still_repaired(app):
    """Saved before Strava's moving time was kept (or changed since): nothing says it's Strava's, so the repairs go on as before."""
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        _import(db)
        db.execute("UPDATE Activity SET rawData='{}' WHERE id='101'")                            # an older import: no record of Strava's
        db.execute("UPDATE Activity SET movingTime=150 WHERE id='102'")                         # no longer Strava's 200
        db.execute('UPDATE Settings SET movingTimeFixDone=0, movingTimePausedDone=0')
        assert [f[0] for f in moving_time.repair(db)['fixed']] == ['102']
        assert [f[0] for f in moving_time.repair_paused(db)['fixed']] == ['101']
        assert 580 <= _moving(db)['101'] <= 600 and 580 <= _moving(db)['102'] <= 600


def test_importing_again_marks_stravas_moving_time_on_a_ride_saved_before(app):
    """A ride from an import before 0.7.13 has Strava's moving time but no record of it: importing the export again records it, beside what its
    rawData already held."""
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        _import(db)
        db.execute("""UPDATE Activity SET rawData='{"other": 1}'""")
        db.execute('DELETE FROM ImportSeen')                                                      # read the files again, as a new release would
        db.commit()
        _import(db)
        raw = {r['id']: json.loads(r['rawData']) for r in db.execute('SELECT id, rawData FROM Activity')}
        assert raw['101']['stravaMoving'] == 900 and raw['102']['stravaMoving'] == 200
        assert raw['101']['other'] == raw['102']['other'] == 1
