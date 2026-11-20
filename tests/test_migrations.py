"""Numbered database steps (database.STEPS, PRAGMA user_version): every database reaches the latest step, once; a newer one is refused; a step
that fails changes nothing. tests/fixtures holds two schemas, no rows: upstream's 0.5.3 database, and every table as a database at step 1 had
it when the steps were numbered (regenerate it only by hand, never to make test_a_database_at_step_1_gets_what_a_new_one_has pass)."""
import sqlite3
from pathlib import Path

import pytest
from flask import Flask

import config
import database

FIXTURES = Path(__file__).parent / 'fixtures'


def _migrate(path):
    app = Flask('t')
    app.config['DATABASE'] = str(path)
    app.teardown_appcontext(database.close_db)
    with app.app_context():
        database.migrate_db()


def _from_sql(path, name, version):
    conn = sqlite3.connect(path)
    conn.executescript((FIXTURES / name).read_text())
    conn.execute(f'PRAGMA user_version = {version}')
    conn.commit()
    conn.close()


def _schema(path):
    """{table: {column: type}} and the names of the indexes, triggers and views, and the step."""
    conn = sqlite3.connect(path)
    try:
        objs = conn.execute("SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        tables = {n: {r[1]: r[2] for r in conn.execute(f'PRAGMA table_info("{n}")')} for t, n in objs if t == 'table'}
        others = {(t, n) for t, n in objs if t != 'table' and not n.startswith('sqlite_autoindex')}
        return tables, others, conn.execute('PRAGMA user_version').fetchone()[0]
    finally:
        conn.close()


def _missing(path, fresh):
    """What a new database has that this one hasn't: tables, columns, indexes, triggers, views."""
    tables, others, _ = _schema(path)
    want_tables, want_others, _ = _schema(fresh)
    gone = [t for t in want_tables if t not in tables]
    cols = [f'{t}.{c}' for t, cs in want_tables.items() if t in tables for c in cs if c not in tables[t]]
    return gone + cols + sorted(f'{t} {n}' for t, n in want_others - others)


@pytest.fixture
def fresh(tmp_path):
    path = tmp_path / 'fresh.db'
    _migrate(path)
    return path


def test_a_new_database_has_every_step(fresh):
    assert _schema(fresh)[2] == database.LATEST


def test_running_again_changes_nothing(fresh):
    before = '\n'.join(sqlite3.connect(fresh).iterdump())
    _migrate(fresh)
    assert '\n'.join(sqlite3.connect(fresh).iterdump()) == before


def test_an_upstream_0_5_database_reaches_the_latest_step(tmp_path, fresh):
    old = tmp_path / 'old.db'
    _from_sql(old, 'schema_upstream_0.5.3.sql', 0)
    conn = sqlite3.connect(old)
    conn.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'A', 1)")
    conn.execute("INSERT INTO Activity (id, name, type, startDateLocal, distance, streams, riderId) "
                 "VALUES ('1', 'Morning Ride', 'Ride', '2024-05-01T08:00:00', 20000, '{\"time\": {\"data\": [0, 1]}}', 1)")
    conn.execute("INSERT INTO Workout (id, riderId, sport, name, startDateLocal, distance) VALUES ('w1', 1, 'Run', 'Lunch Run', '2024-05-02T12:00:00', 5000)")
    conn.commit()
    conn.close()
    _migrate(old)
    assert _schema(old)[2] == database.LATEST
    assert _missing(old, fresh) == []
    conn = sqlite3.connect(old)
    assert sorted(r[0] for r in conn.execute('SELECT name FROM Activity')) == ['Lunch Run', 'Morning Ride']


def test_a_database_at_step_1_gets_what_a_new_one_has(tmp_path, fresh):
    """A database that has had step 1 never runs it again: a table or column added to it reaches new databases only. Put it in a new step."""
    old = tmp_path / 'step1.db'
    _from_sql(old, 'schema_step_1.sql', 1)
    _migrate(old)
    missing = _missing(old, fresh)
    assert not missing, (f'A database already past step 1 does not get {missing}. Add them in a new step at the end of database.STEPS, not to an '
                         'earlier step (or, for a service\'s own table, in its ensure_schema with a check for the column, as the others do).')


def test_step_3_keeps_the_settings_a_build_before_the_steps_added(tmp_path):
    """A database that ran main between 0.7.42 and the numbered steps has step 3's columns already, and its choices in them, at step 0."""
    old = tmp_path / 'main.db'
    _from_sql(old, 'schema_step_1.sql', 0)
    conn = sqlite3.connect(old)
    conn.execute("ALTER TABLE Settings ADD COLUMN favouriteSports TEXT")
    conn.execute("ALTER TABLE Settings ADD COLUMN tempUnit TEXT DEFAULT 'C'")
    conn.execute("ALTER TABLE Settings ADD COLUMN bestEffortsKmDone INTEGER DEFAULT 0")
    conn.execute("""INSERT INTO Settings (id, favouriteSports, tempUnit) VALUES (1, '["group:ride"]', 'F')""")
    conn.execute("INSERT INTO Activity (id, name, startDateLocal) VALUES ('1', 'Ride', '2026-11-01T08:00:00')")
    conn.commit()
    conn.close()
    _migrate(old)
    conn = sqlite3.connect(old)
    assert conn.execute('SELECT favouriteSports, tempUnit FROM Settings').fetchone() == ('["group:ride"]', 'F')
    assert conn.execute('PRAGMA user_version').fetchone()[0] == database.LATEST


def test_step_5_compresses_the_streams_of_copies_set_aside_and_of_imports_waiting(tmp_path):
    """Kept in their JSON as text until step 5: out into a streams column of their own, compressed, the rest of the row as it was."""
    import json
    from services import streams
    old = tmp_path / 'step1.db'
    _from_sql(old, 'schema_step_1.sql', 1)
    track = json.dumps({'time': {'data': list(range(500))}})
    row = {'id': 'imp_1', 'name': 'Morning Ride', 'distance': 20000, 'streams': track}
    conn = sqlite3.connect(old)
    conn.execute("INSERT INTO Activity (id, name, startDateLocal) VALUES ('1', 'Ride', '2026-11-01T08:00:00')")
    for i in range(database._HEAVY_BATCH + 3):          # more than one batch
        conn.execute("INSERT INTO ActivityDuplicate (id, primaryId, riderId, status, rowJson) VALUES (?, '1', 1, 'parked', ?)",
                     [f'imp_{i}', json.dumps({**row, 'id': f'imp_{i}'})])
    conn.execute("INSERT INTO ActivityDuplicate (id, primaryId, riderId, status, rowJson) VALUES ('gone', '', 1, 'deleted', '{}')")
    conn.execute("INSERT INTO ActivityDuplicate (id, primaryId, riderId, status, rowJson) VALUES ('bad', '1', 1, 'parked', 'not json')")
    conn.execute("INSERT INTO ImportChange (rideId, riderId, diffs, act) VALUES ('1', 1, '[]', ?)", [json.dumps({'distance': 21000, 'streams': track})])
    conn.commit()
    conn.close()
    _migrate(old)
    conn = sqlite3.connect(old)
    kept = dict(((i, (j, s)) for i, j, s in conn.execute('SELECT id, rowJson, streams FROM ActivityDuplicate')))
    assert streams.together(*kept['imp_0']) == {**row, 'id': 'imp_0'} and streams.together(*kept[f'imp_{database._HEAVY_BATCH + 2}'])['streams'] == track
    assert 'streams' not in json.loads(kept['imp_0'][0]) and len(kept['imp_0'][1]) < len(track) / 2
    assert kept['gone'] == ('{}', None) and kept['bad'] == ('not json', None)
    act, data = conn.execute('SELECT act, streams FROM ImportChange').fetchone()
    assert json.loads(act) == {'distance': 21000} and streams.unpack(data) == track


def test_a_newer_database_is_refused_and_left_alone(fresh, monkeypatch):
    conn = sqlite3.connect(fresh)
    conn.execute(f'PRAGMA user_version = {database.LATEST + 1}')
    conn.commit()
    conn.close()
    before = '\n'.join(sqlite3.connect(fresh).iterdump())
    with pytest.raises(database.SchemaTooNew, match='newer Headwind'):
        _migrate(fresh)
    assert '\n'.join(sqlite3.connect(fresh).iterdump()) == before

    import app as app_module
    monkeypatch.setattr(config.Config, 'DATABASE', str(fresh))
    monkeypatch.setattr(app_module.threading, 'Thread', lambda *a, **kw: type('T', (), {'start': lambda s: None})())
    with pytest.raises(database.SchemaTooNew):
        app_module.create_app()


def test_a_step_that_fails_changes_nothing(fresh, monkeypatch):
    def broken(db):
        db.execute('CREATE TABLE Half (x)')
        db.execute("INSERT INTO Rider (name) VALUES ('half')")
        raise RuntimeError('stopped')

    monkeypatch.setattr(database, 'STEPS', database.STEPS + ((broken, False),))
    monkeypatch.setattr(database, 'LATEST', database.LATEST + 1)
    with pytest.raises(RuntimeError, match='stopped'):
        _migrate(fresh)
    tables, _, version = _schema(fresh)
    assert version == database.LATEST - 1 and 'Half' not in tables
    assert not sqlite3.connect(fresh).execute("SELECT 1 FROM Rider WHERE name='half'").fetchone()


def test_a_step_that_cant_be_undone_keeps_a_copy_first(fresh, monkeypatch):
    from version import __version__

    def one_way(db):
        db.execute('CREATE TABLE OneWay (x)')

    monkeypatch.setattr(database, 'STEPS', database.STEPS + ((one_way, True),))
    monkeypatch.setattr(database, 'LATEST', database.LATEST + 1)
    _migrate(fresh)
    copy = Path(f'{fresh}.pre-{__version__}')
    assert copy.exists()
    tables, _, version = _schema(copy)
    assert version == database.LATEST - 1 and 'OneWay' not in tables
    assert 'OneWay' in _schema(fresh)[0]


def test_the_command_migrates_and_refuses_a_newer_database(tmp_path, monkeypatch):
    path = tmp_path / 'cmd.db'
    monkeypatch.setattr(config.Config, 'DATABASE', str(path))
    assert database.main(['migrate']) == 0
    assert _schema(path)[2] == database.LATEST
    conn = sqlite3.connect(path)
    conn.execute(f'PRAGMA user_version = {database.LATEST + 1}')
    conn.commit()
    conn.close()
    assert database.main(['migrate']) == 1
    assert database.main([]) == 2


def test_a_backup_from_a_newer_headwind_is_not_restored(fresh):
    from services import backup
    conn = sqlite3.connect(fresh)
    conn.execute(f'PRAGMA user_version = {database.LATEST + 1}')
    conn.commit()
    conn.close()
    with pytest.raises(backup.BackupError, match='newer Headwind'):
        backup.prepare(str(fresh))
