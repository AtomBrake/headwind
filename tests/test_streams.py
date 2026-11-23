"""Streams in ActivityStream, compressed (services/streams.py, database step 2): they round-trip, go with their activity, drop its track summary
and tell friends when they change, and an older database's move across loses nothing and doesn't send every activity to every friend again."""
import json
import sqlite3
from pathlib import Path

import pytest
from flask import Flask

import database
from services import duplicates, recently_deleted, streams

FIXTURES = Path(__file__).parent / 'fixtures'
TRACK = {'time': {'data': list(range(50))}, 'latlng': {'data': [[51.5 + i * 1e-4, -0.12] for i in range(50)]},
         'distance': {'data': [i * 11.1 for i in range(50)]}}


@pytest.fixture
def app(tmp_path):
    a = Flask(__name__)
    a.config['DATABASE'] = str(tmp_path / 't.db')
    a.teardown_appcontext(database.close_db)
    with a.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
        yield a


def add(db, aid, track=TRACK, **cols):
    row = {'id': aid, 'name': aid, 'type': 'Ride', 'sportType': 'Ride', 'riderId': 1, 'startDateLocal': '2026-10-01T09:00:00',
           'startDate': '2026-10-01T08:00:00', 'distance': 550.0, 'movingTime': 49, 'elapsedTime': 49, 'rawData': '{}', **cols}
    db.execute(f"INSERT INTO Activity ({','.join(row)}) VALUES ({','.join('?' * len(row))})", list(row.values()))
    streams.save(db, aid, track)
    db.commit()


def test_they_round_trip_compressed_and_empty_ones_are_none(app):
    db = database.get_db()
    add(db, 'a')
    assert streams.load(db, 'a') == TRACK
    raw = db.execute("SELECT format, data FROM ActivityStream WHERE activityId='a'").fetchone()
    assert raw[0] == streams.FORMAT and len(raw[1]) < len(json.dumps(TRACK)) / 2
    assert json.loads(db.execute(f"SELECT {streams.sql()} FROM Activity WHERE id='a'").fetchone()['streams']) == TRACK
    assert json.loads(db.execute(f"SELECT x.id, {streams.sql('x')} FROM Activity x").fetchone()['streams']) == TRACK
    for empty in (None, '', 'null', '{}', {}):
        streams.save(db, 'a', empty)
        assert streams.load(db, 'a') == {} and streams.load_json(db, 'a') is None
        assert not db.execute(f"SELECT 1 FROM Activity WHERE {streams.has_sql()}").fetchone()
    assert 'streams' not in {r[1] for r in db.execute('PRAGMA table_info(Activity)')}


def test_has_sql_can_ask_for_one_stream(app):
    db = database.get_db()
    add(db, 'gps')
    add(db, 'indoor', track={'time': {'data': [0, 1]}, 'watts': {'data': [200, 210]}})
    ids = lambda **kw: [r[0] for r in db.execute(f'SELECT id FROM Activity WHERE {streams.has_sql(**kw)} ORDER BY id')]
    assert ids() == ['gps', 'indoor'] and ids(key='latlng') == ['gps'] and ids(key='watts') == ['indoor']


def test_they_go_with_their_activity(app):
    db = database.get_db()
    add(db, 'a')
    db.execute("UPDATE Activity SET id='b' WHERE id='a'")
    assert streams.load(db, 'b') == TRACK and streams.load(db, 'a') == {}
    db.execute("DELETE FROM Activity WHERE id='b'")
    assert db.execute('SELECT COUNT(*) FROM ActivityStream').fetchone()[0] == 0


def test_a_change_drops_the_track_summary_and_tells_friends(app):
    from services import tracks
    db = database.get_db()
    add(db, 'a')
    db.execute("UPDATE Activity SET updatedAt='2026-01-01 00:00:00' WHERE id='a'")
    tracks.fill(db)
    assert db.execute("SELECT 1 FROM ActivityTrack WHERE activityId='a'").fetchone()
    streams.save(db, 'a', TRACK)                                       # the same streams: nothing happens
    assert db.execute("SELECT updatedAt FROM Activity WHERE id='a'").fetchone()[0] == '2026-01-01 00:00:00'
    streams.save(db, 'a', {**TRACK, 'heartrate': {'data': [120] * 50}})
    assert not db.execute("SELECT 1 FROM ActivityTrack WHERE activityId='a'").fetchone()
    assert db.execute("SELECT updatedAt FROM Activity WHERE id='a'").fetchone()[0] > '2026-01-01 00:00:00'


def test_deleted_restored_and_parked_ones_keep_their_streams(app):
    db = database.get_db()
    add(db, 'a')
    duplicates.delete_activity(db, 'a')
    db.commit()
    assert streams.load(db, 'a') == {}
    assert recently_deleted.restore(db, 'a') == 'a'
    assert streams.load(db, 'a') == TRACK
    add(db, 'b', track={'time': {'data': [0, 1, 2]}})
    duplicates.park(db, 'b', 'a', 'test')
    db.commit()
    kept = db.execute("SELECT rowJson, streams FROM ActivityDuplicate WHERE id='b'").fetchone()
    assert streams.load(db, 'b') == {} and 'streams' not in json.loads(kept['rowJson'])         # compressed beside the row, not in it
    assert json.loads(streams.unpack(kept['streams'])) == {'time': {'data': [0, 1, 2]}}
    duplicates.swap(db, 'b')
    db.commit()
    assert streams.load(db, 'b') == {'time': {'data': [0, 1, 2]}} and streams.load(db, 'a') == {}


def _old_database(path):
    """A database as step 1 left it (tests/fixtures/schema_step_1.sql), with two activities whose streams are in Activity.streams."""
    conn = sqlite3.connect(path)
    conn.executescript((FIXTURES / 'schema_step_1.sql').read_text(encoding='utf-8'))
    conn.execute('PRAGMA user_version = 1')
    conn.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
    for aid, st in (('gps', json.dumps(TRACK)), ('none', '{}')):
        conn.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDateLocal, streams, updatedAt) "
                     "VALUES (?, ?, 'Ride', 'Ride', 1, '2026-10-01T09:00:00', ?, '2026-01-01 00:00:00')", [aid, aid, st])
    conn.commit()
    conn.close()


def test_an_older_database_moves_its_streams_across_once(tmp_path):
    from version import __version__
    path = tmp_path / 'old.db'
    _old_database(path)
    a = Flask(__name__)
    a.config['DATABASE'] = str(path)
    a.teardown_appcontext(database.close_db)
    with a.app_context():
        database.migrate_db()
        db = database.get_db()
        assert db.execute('PRAGMA user_version').fetchone()[0] == database.LATEST
        assert 'streams' not in {r[1] for r in db.execute('PRAGMA table_info(Activity)')}
        assert streams.load(db, 'gps') == TRACK and streams.load(db, 'none') == {}
        assert [r[0] for r in db.execute('SELECT updatedAt FROM Activity')] == ['2026-01-01 00:00:00'] * 2    # no friend fetches them again
    copy = sqlite3.connect(f'{path}.pre-{__version__}')
    assert copy.execute('PRAGMA user_version').fetchone()[0] == 1
    assert json.loads(copy.execute("SELECT streams FROM Activity WHERE id='gps'").fetchone()[0]) == TRACK


def test_a_backup_from_before_the_move_restores(tmp_path):
    from services import backup
    path = tmp_path / 'backup.db'
    _old_database(path)
    backup.prepare(str(path))
    conn = sqlite3.connect(path)
    streams.register(conn)
    assert json.loads(conn.execute(f"SELECT {streams.sql()} FROM Activity WHERE id='gps'").fetchone()[0]) == TRACK


def test_a_friends_feed_still_sends_them_as_text(app):
    from routes.friends import _store_ride
    db = database.get_db()
    obj = {'id': 'x1', 'name': 'Their ride', 'type': 'ride', 'sportType': 'Ride', 'startDateLocal': '2026-10-02T09:00:00', 'streams': json.dumps(TRACK)}
    assert _store_ride(db, 7, 1, obj) == ('f7_x1', 'new')
    assert streams.load(db, 'f7_x1') == TRACK
    assert _store_ride(db, 7, 1, obj) == ('f7_x1', None)                 # the same again: nothing changed
    assert _store_ride(db, 7, 1, {**obj, 'streams': '{}'}) == ('f7_x1', 'changed')
    assert _store_ride(db, 7, 1, {**obj, 'streams': None}) == ('f7_x1', None)   # none and empty are the same
