"""Activities stored with GPS and time streams out of step (a parser before 0.7.7 kept a time for every second with no GPS fix): counted in the track
summaries, grouped by how they get put right (Garmin's daily check, a friend's own Headwind, importing the file again), listed on the Import page,
and off the list once a file read again puts them right. Throwaway DB."""
import json

import pytest
from flask import Flask

import database
from services import reimport, tracks


def streams(n, extra=0):
    return json.dumps({'latlng': {'data': [[50.5 + i / 100_000, -3.5] for i in range(n)]}, 'time': {'data': list(range(n + extra))}})


@pytest.fixture
def db(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1), (2, 'Martin', 0)")
        d.execute("INSERT INTO Friend (name, url, token, riderId) VALUES ('Martin', 'http://127.0.0.1:9', 't', 2)")
        d.commit()
        yield d


def add(db, aid, st, rider=1, origin=None, day='2026-09-20'):
    db.execute("INSERT INTO Activity (id, name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedTime, rawData, riderId, "
               "streams, originId) VALUES (?, ?, 'Ride', 'Ride', ?, ?, 1000, 600, 600, '{}', ?, ?, ?)",
               [aid, f'Ride {aid}', f'{day}T10:00:00', f'{day}T10:00:00', rider, st, origin])
    db.commit()


def test_the_track_summary_counts_how_far_out_of_step_it_is(db):
    assert tracks.out_of_step(streams(100, 34)) == 34 and tracks.out_of_step(streams(100)) == 0
    assert tracks.out_of_step({'time': {'data': [0, 1]}}) == 0 and tracks.out_of_step('not json') == 0     # no GPS: nothing to be out of step with
    add(db, 'imp_1', streams(100, 34))
    tracks.fill(db)
    assert db.execute("SELECT outOfStep FROM ActivityTrack WHERE activityId='imp_1'").fetchone()[0] == 34


def test_summaries_from_before_the_count_are_made_again(db):
    add(db, 'imp_1', streams(100, 34))
    db.execute('DROP TABLE ActivityTrack')
    db.execute('CREATE TABLE ActivityTrack (activityId TEXT PRIMARY KEY, minLat REAL, maxLat REAL, minLng REAL, maxLng REAL, line TEXT, '
               'lineHd TEXT, cells TEXT)')
    db.execute("INSERT INTO ActivityTrack (activityId) VALUES ('imp_1')")     # summarised before
    tracks.ensure_schema(db)
    assert db.execute('SELECT COUNT(*) FROM ActivityTrack').fetchone()[0] == 0
    assert tracks.fill(db) == 1 and db.execute('SELECT outOfStep FROM ActivityTrack').fetchone()[0] == 34


def test_they_are_grouped_by_how_they_get_put_right(db):
    add(db, 'garmin_1', streams(100, 40))
    add(db, 'wk_1', streams(100, 40), origin='garmin_2')                      # a Garmin workout under the id the old Workout table gave it
    add(db, 'f1_imp_1', streams(100, 40), rider=2)                            # a friend's
    add(db, 'imp_1', streams(100, 973), day='2026-09-21')
    add(db, 'imp_2', streams(100, 5))                                         # timed all the same: a few seconds out at most
    add(db, 'imp_3', streams(100))
    tracks.fill(db)
    got = reimport.out_of_step(db)
    assert {k: [r['id'] for r in v] for k, v in got.items()} == {'garmin': ['garmin_1', 'wk_1'], 'friend': ['f1_imp_1'], 'files': ['imp_1']}


def test_a_file_read_again_takes_it_off_the_list(db):
    add(db, 'imp_1', streams(100, 40))
    tracks.fill(db)
    reimport.ensure_schema(db)
    reimport.propose(db, db.execute("SELECT * FROM Activity WHERE id='imp_1'").fetchone(), {'id': 'imp_1', 'streams': streams(100)}, 'test')
    tracks.fill(db)
    assert reimport.out_of_step(db)['files'] == []


def test_the_import_page_says_which_and_how(tmp_path, monkeypatch):
    import app as app_module
    import config
    from services import credentials

    class _NoThread:
        def __init__(self, *a, **kw): pass
        def start(self): pass
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'app.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        add(db, 'garmin_1', streams(100, 40))
        add(db, 'imp_1', streams(100, 40))
        tracks.fill(db)
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    html = c.get('/import').get_data(as_text=True)
    assert '2 activities left out of segments' in html and 'href="/rides/imp_1"' in html
    assert 'href="/rides/garmin_1"' in html and 'Full re-sync' not in html.split('id="out-of-step"')[1].split('</div>')[0]   # no Garmin set up
