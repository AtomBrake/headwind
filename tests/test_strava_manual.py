"""Manual entries an older Strava import saved unmarked (services/strava_manual): told from the row once at start-up, so an upgraded database
and a fresh import of the same export keep the same activities. Full app, throwaway DB."""
import json

import pytest

import app as app_module
import config
import database
from services import duplicates, strava_manual


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    a = app_module.create_app()
    with a.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Alex', 1)")
        db.commit()
    return a


def _track(secs, speed):
    return json.dumps({'time': {'data': list(range(0, secs + 1, 10))}, 'distance': {'data': [i * speed for i in range(0, secs + 1, 10)]}})


def _add(db, aid, start, dist, elapsed, moving, streams=None):
    db.execute('INSERT INTO Activity (id, name, riderId, sportType, type, startDate, startDateLocal, distance, elapsedTime, movingTime, streams) '
               "VALUES (?, ?, 1, 'Ride', 'Ride', ?, ?, ?, ?, ?, ?)", [aid, f'Ride {aid}', start, start, dist, elapsed, moving, streams])


def _evening(db):
    """25 March 2019: a 2.5 km top-up typed in on Strava "lasting" 15 hours, and the evening's 24 km ride recorded inside it."""
    _add(db, '2241486599', '2019-03-25T19:30:00', 2478.4, 54000, 54000)
    _add(db, '2240645717', '2019-03-25T19:49:18', 24142.0, 7890, 6726, _track(7890, 3.06))


def test_a_manual_entry_is_marked_and_the_ride_inside_it_is_not_a_piece_of_it(app):
    with app.app_context():
        db = database.get_db()
        _evening(db)
        _add(db, '7583442007', '2022-08-04T10:48:51', 45970.2, 21054, 10554)          # a recording Headwind couldn't read: no track, with stops
        db.execute('UPDATE Settings SET stravaManualDone=0')
        db.commit()
        rows = lambda: {r['id']: dict(r) for r in db.execute('SELECT * FROM Activity')}
        assert duplicates.same_ride(rows()['2240645717'], rows()['2241486599'])     # unmarked, the ride looks like a piece of the entry
        res = strava_manual.fix(db)
        assert res == {'marked': 1, 'restored': []}
        assert {i: r['source'] for i, r in rows().items()} == {'2241486599': 'manual', '2240645717': None, '7583442007': None}
        assert not duplicates.same_ride(rows()['2240645717'], rows()['2241486599'])
        assert strava_manual.fix(db) is None                                           # once only


def test_a_manual_entry_set_aside_behind_a_ride_comes_back(app):
    with app.app_context():
        db = database.get_db()
        _evening(db)
        duplicates.park(db, '2241486599', '2240645717', 'Kept the Phone or file recording (has power, has elevation).')
        db.execute('UPDATE Settings SET stravaManualDone=0')
        db.commit()
        res = strava_manual.fix(db)
        assert res['restored'] == [('2241486599', 'Ride 2241486599')]
        assert db.execute("SELECT source FROM Activity WHERE id='2241486599'").fetchone()[0] == 'manual'
        assert db.execute("SELECT status FROM ActivityDuplicate WHERE id='2241486599'").fetchone()[0] == 'kept_both'


def test_a_recording_set_aside_stays_set_aside(app):
    with app.app_context():
        db = database.get_db()
        _add(db, 'whole', '2022-08-04T10:48:51', 45970.2, 21054, 10554)
        _add(db, 'piece', '2022-08-04T10:49:48', 11519.0, 9152, 9152)                  # one duration and no track, but not a Strava id
        duplicates.park(db, 'piece', 'whole', 'a piece of the ride')
        db.execute('UPDATE Settings SET stravaManualDone=0')
        db.commit()
        db.execute("INSERT INTO Activity (id, name, riderId, sportType, startDateLocal, distance, elapsedTime, movingTime) "
                   "VALUES ('555', 'Zwift', 1, 'VirtualRide', '2026-08-03T06:15:00', 20000, 1800, 1800)")       # never stops, so one duration
        db.commit()
        assert strava_manual.fix(db) == {'marked': 0, 'restored': []}
        assert db.execute("SELECT status FROM ActivityDuplicate WHERE id='piece'").fetchone()[0] == 'parked'
        assert db.execute("SELECT source FROM Activity WHERE id='555'").fetchone()[0] is None
