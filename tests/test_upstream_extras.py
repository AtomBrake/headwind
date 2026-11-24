"""Photos and faults from upstream's rewrite (services/upstream_extras.py), brought over once at start-up: RidePhoto into ActivityPhoto with
its files under this Headwind's names, RideFault into its activity's notes. A database from upstream's 0.9.1 (tests/fixtures, no rows) with a
few made up here."""
import os
import sqlite3
from pathlib import Path

from flask import Flask

import database
from services import strava_export, upstream_extras

FIXTURES = Path(__file__).parent / 'fixtures'


def _migrate(path):
    app = Flask('t')
    app.config['DATABASE'] = str(path)
    app.teardown_appcontext(database.close_db)
    with app.app_context():
        database.migrate_db()


def _upstream(tmp_path):
    """An upstream 0.9.1 database: a ride on a bike with two photos and a fault, a run with a photo and a fault (no bike), a copy set aside
    with a photo, a photo of a deleted ride, and one whose file is missing."""
    path = tmp_path / 'bike.db'
    conn = sqlite3.connect(path)
    conn.executescript((FIXTURES / 'schema_upstream_0.9.1.sql').read_text(encoding='utf-8'))
    conn.execute("INSERT INTO Settings (id, units) VALUES (1, 'metric')")
    conn.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Sam', 1)")
    conn.execute("INSERT INTO Bike (id, riderId, name) VALUES (1, 1, 'Road bike')")
    for aid, sport, start, bike, notes in (('ride', 'Ride', '2026-11-20T09:00:00', 1, 'Windy'),
                                           ('run', 'Run', '2026-11-22T08:00:00', None, None)):
        conn.execute('INSERT INTO Activity (id, name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedTime, riderId, '
                     'bikeId, notes) VALUES (?,?,?,?,?,?,?,?,?,1,?,?)', [aid, f'Morning {sport}', sport, sport, start, start, 20000, 3600, 3600,
                                                                         bike, notes])
    conn.execute("INSERT INTO ActivityDuplicate (id, primaryId, riderId, source, reason, rowJson) VALUES ('copy', 'ride', 1, 'Garmin', 'a copy', '{}')")
    img = tmp_path / 'rideimg'
    img.mkdir()
    photos = (('ride', 'aaaaaaaaaaa1', 'First'), ('ride', 'aaaaaaaaaaa2', None), ('run', 'aaaaaaaaaaa3', None), ('copy', 'aaaaaaaaaaa4', None),
              ('deleted', 'aaaaaaaaaaa5', None), ('run', 'aaaaaaaaaaa6', None))
    for i, (aid, hexid, caption) in enumerate(photos, 1):
        conn.execute('INSERT INTO RidePhoto (id, rideId, file, lat, lng, caption) VALUES (?,?,?,?,?,?)', [i, aid, f'rp_{hexid}.jpg', 0.5, -30.0, caption])
        if hexid != 'aaaaaaaaaaa6':                                 # its file was never there
            (img / f'rp_{hexid}.jpg').write_bytes(b'full ' + hexid.encode())
            (img / f'rp_{hexid}_t.jpg').write_bytes(b'thumb ' + hexid.encode())
    conn.execute("INSERT INTO RideFault (rideId, riderId, bikeId, category, outcome, minutesLost, description, date, repairedOn) "
                 "VALUES ('ride', 1, 1, 'puncture', 'fixed', 12, 'Rear tyre', '2026-11-20', '2026-11-20')")
    conn.execute("INSERT INTO RideFault (rideId, riderId, category, outcome, description, date) VALUES ('run', 1, 'other', 'ended', 'Shoe split', "
                 "'2026-11-22')")
    conn.commit()
    conn.close()
    return path


def test_photos_and_faults_come_over_once(tmp_path):
    path = _upstream(tmp_path)
    _migrate(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    got = [tuple(r) for r in conn.execute('SELECT activityId, filename, caption, position FROM ActivityPhoto ORDER BY id')]
    assert got == [('ride', 'act_aaaaaaaaaaa4.jpg', None, 0),                       # the copy's photo, on the ride it was set aside behind
                   ('ride', 'act_aaaaaaaaaaa1.jpg', 'First', 1), ('ride', 'act_aaaaaaaaaaa2.jpg', None, 2),
                   ('run', 'act_aaaaaaaaaaa3.jpg', None, 0)]
    img = tmp_path / 'rideimg'
    assert (img / 'act_aaaaaaaaaaa1.jpg').read_bytes() == b'full aaaaaaaaaaa1'
    assert (img / 'act_aaaaaaaaaaa1_t.jpg').read_bytes() == b'thumb aaaaaaaaaaa1'
    assert (img / 'rp_aaaaaaaaaaa1.jpg').exists()                                    # upstream's file stays, for the copy kept before the steps
    assert not (img / 'act_aaaaaaaaaaa5.jpg').exists()                               # its ride is gone
    notes = dict(conn.execute('SELECT id, notes FROM Activity').fetchall())
    assert notes['ride'] == ('Windy\n\nFault on a ride: Puncture / flat - Rear tyre - fixed it and carried on - 12 min lost - repaired 2026-11-20')
    assert notes['run'] == ('Fault on a ride: Something else - Shoe split - ride ended early (walked, rescued or got a lift) - not repaired yet')
    assert conn.execute('SELECT upstreamExtrasDone FROM Settings').fetchone()[0] == 1
    task = conn.execute("SELECT result FROM TaskLog WHERE task='startup:upstream_extras'").fetchone()[0]
    assert task.startswith('4 photos on their activities now show here; 2 faults') and '1 photo file was missing' in task
    before = '\n'.join(conn.iterdump())
    conn.close()

    _migrate(path)                                                                   # the second start
    conn = sqlite3.connect(path)
    assert '\n'.join(conn.iterdump()) == before
    conn.close()


def test_a_database_that_isnt_upstreams_has_nothing_to_do(tmp_path):
    path = tmp_path / 'new.db'
    _migrate(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    assert upstream_extras.upstream_tables(conn) == []
    assert not upstream_extras.from_rewrite(conn)
    assert conn.execute('SELECT upstreamExtrasDone FROM Settings').fetchone()[0] == 1


def _app(path):
    app = Flask('t')
    app.config['DATABASE'] = str(path)
    app.teardown_appcontext(database.close_db)
    return app


def _advice(path):
    """[(riderId, reasons)] the Import page would show."""
    with _app(path).app_context():
        return [(a['riderId'], a['reasons']) for a in strava_export.advice(database.get_db(), str(path))]


def test_a_rider_with_a_strava_export_imported_by_the_original_is_asked_to_import_it_again(tmp_path):
    path = _upstream(tmp_path)
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO Activity (id, name, type, sportType, startDate, startDateLocal, distance, riderId) "
                 "VALUES ('19000000001', 'Evening Ride', 'Ride', 'Ride', '2026-07-01T17:00:00', '2026-07-01T17:00:00', 20000, 1)")
    conn.commit()
    conn.close()
    _migrate(path)
    assert _advice(path) == [(1, [strava_export.ORIGINAL_REASON])]
    with _app(path).app_context():
        db = database.get_db()
        strava_export.dismiss(db, 1)                                                 # Not now
        assert strava_export.advice(db, str(path)) == []
        db.execute('UPDATE StravaExportRead SET advised=-1, dismissed=-1')
        strava_export.note_read(db, 1)                                               # imported again
        assert strava_export.advice(db, str(path)) == []


def test_no_advice_without_strava_activities_or_on_this_headwinds_own_database(tmp_path):
    path = _upstream(tmp_path)                                                       # the original's file imports and nothing from Strava
    _migrate(path)
    assert _advice(path) == []
    own = tmp_path / 'own.db'
    _migrate(own)
    conn = sqlite3.connect(own)
    conn.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Sam', 1)")
    conn.execute("INSERT INTO Activity (id, name, sportType, startDateLocal, distance, riderId) VALUES ('19000000001', 'Ride', 'Ride', "
                 "'2026-07-01T17:00:00', 20000, 1)")
    conn.commit()
    conn.close()
    _migrate(own)
    assert _advice(own) == []


def test_upstream_tables_left_alone_are_named_on_the_tasks_page():
    res = {'photos': 1, 'faults': 0, 'missing': 0, 'gone': 0, 'others': ['WeighInVerdict', 'DiarySummary']}
    assert upstream_extras.summary(res) == ('1 photo on its activity now shows here. Not used here, so left as they were: the verdicts on each '
                                            'weigh-in, the food diary summaries.')


def test_an_older_headwind_that_already_moved_it_gets_its_photos_at_the_next_upgrade(tmp_path):
    """A database moved by a Headwind before step 16 has RidePhoto still, untouched, and gets its photos when step 16 arrives."""
    path = _upstream(tmp_path)
    _migrate(path)
    conn = sqlite3.connect(path)
    conn.execute('DELETE FROM ActivityPhoto')
    conn.execute("UPDATE Activity SET notes=NULL")
    conn.execute('ALTER TABLE Settings DROP COLUMN upstreamExtrasDone')
    conn.execute(f'PRAGMA user_version = {[s for s, _ in database.STEPS].index(database._step_16)}')     # the step before it
    conn.commit()
    conn.close()
    for f in (tmp_path / 'rideimg').glob('act_*'):
        os.remove(f)
    _migrate(path)
    conn = sqlite3.connect(path)
    assert conn.execute('SELECT COUNT(*) FROM ActivityPhoto').fetchone()[0] == 4
    assert conn.execute("SELECT notes FROM Activity WHERE id='run'").fetchone()[0].startswith('Fault on a ride: Something else')
