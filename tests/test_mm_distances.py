"""Distances an old Strava import stored in millimetres (services/mm_distances): divided by 1,000 once at start-up, before the duplicate checks.
Full app, throwaway DB."""
import json

import pytest

import app as app_module
import config
import database
from services import mm_distances


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


def _add(db, aid, sport, dist, elapsed, moving, avg=0, streams=None):
    db.execute('INSERT INTO Activity (id, name, riderId, sportType, type, startDateLocal, distance, elapsedTime, movingTime, averageSpeed, streams) '
               'VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)',
               [aid, f'{sport} {aid}', sport, sport, '2019-03-25T19:30:00', dist, elapsed, moving, avg, json.dumps(streams) if streams else None])


def test_distances_stored_in_mm_are_divided_and_real_ones_are_kept(app):
    with app.app_context():
        db = database.get_db()
        _add(db, 'manual', 'Ride', 2478390.0, 54000, 54000)                     # a 2.48 km manual entry over 15 h, saved as 2,478 km
        _add(db, 'csv', 'Ride', 45970238.0, 21054, 10554)                       # a FIT that couldn't be read: 45.97 km saved as 45,970 km
        _add(db, 'paddle', 'Water Sport', 18166100.0, 7644, 7233)
        _add(db, 'blip', 'Ride', 11700.0, 41, 37, streams={'distance': {'data': [0.0] * 37}})   # 11.7 m; its track says it never moved
        _add(db, 'real', 'Ride', 40000.0, 4800, 4500, avg=8.9)                  # an ordinary ride
        _add(db, 'glitch', 'Ride', 3000000.0, 3600, 3600, avg=833,              # its own track says 3,000 km: wrong, but not this fault
             streams={'distance': {'data': [0, 1500000.0, 3000000.0]}})
        db.execute('UPDATE Settings SET mmDistancesDone=0')
        db.commit()
        fixed = mm_distances.fix(db)
        assert sorted(f[0] for f in fixed) == ['blip', 'csv', 'manual', 'paddle']
        got = {r[0]: (r[1], r[2]) for r in db.execute('SELECT id, distance, averageSpeed FROM Activity')}
        assert got['manual'][0] == pytest.approx(2478.39) and got['csv'][0] == pytest.approx(45970.238)
        assert got['csv'][1] == pytest.approx(45970.238 / 10554)               # its average speed, which was 0
        assert got['real'] == (40000.0, 8.9) and got['glitch'][0] == 3000000.0
        assert mm_distances.fix(db) is None                                     # once only


def test_the_repair_runs_at_start_up_and_is_reported(app):
    with app.app_context():
        db = database.get_db()
        _add(db, 'csv', 'Ride', 45970238.0, 21054, 10554)
        db.execute('UPDATE Settings SET mmDistancesDone=0')
        db.commit()
        database.migrate_db()
        db = database.get_db()
        assert db.execute("SELECT distance FROM Activity WHERE id='csv'").fetchone()[0] == pytest.approx(45970.238)
        assert db.execute("SELECT COUNT(*) FROM TaskLog WHERE task='startup:mm_distances_all'").fetchone()[0] == 1
