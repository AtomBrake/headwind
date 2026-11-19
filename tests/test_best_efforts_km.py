"""Ride best efforts in kilometres as well as miles (services/best_efforts: BestEffortKm beside BestEffort): both worked out when a ride is saved,
the km ones once for the rides already there (fill_km), each page showing the set the units pick. Full app, throwaway DB, no network."""
import json

import pytest

import app as app_module
import config
import database
from services import best_efforts, credentials


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def _streams(km, mps=8.0):
    """A straight ride of `km` at a steady `mps`, a point every 100 m."""
    n = int(km * 10) + 1
    return json.dumps({'distance': {'data': [i * 100.0 for i in range(n)]}, 'time': {'data': [round(i * 100 / mps) for i in range(n)]},
                       'latlng': {'data': [[51.5 + i * 0.0009, -2.6] for i in range(n)]}})


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        db.execute("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal, distance, movingTime, streams) "
                   "VALUES ('r45', 'Long', 'Ride', 1, '2026-10-01T08:00:00', 45000, 5625, ?)", [_streams(45)])
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _rows(client, table, col):
    with client.application.app_context():
        return [r[0] for r in database.get_db().execute(f'SELECT {col} FROM {table} ORDER BY {col}')]


def test_a_ride_gets_both_sets(client):
    with client.application.app_context():
        db = database.get_db()
        assert best_efforts.save_best_efforts(db, 'r45', '2026-10-01', db.execute("SELECT streams FROM Activity WHERE id='r45'").fetchone()[0]) == 3
        db.commit()
    assert _rows(client, 'BestEffort', 'distanceMi') == [5, 10, 20]               # 45 km is 28 miles
    assert _rows(client, 'BestEffortKm', 'distanceKm') == [5, 10, 20, 40]
    assert best_efforts.compute_best_efforts(_streams(12))[0]['distanceMi'] == 5   # the old shape, for one set


def test_the_rides_already_there_are_filled_in_once(client):
    with client.application.app_context():
        db = database.get_db()
        db.execute('UPDATE Settings SET bestEffortsKmDone=0 WHERE id=1')
        db.commit()
        assert best_efforts.fill_km(db) == 1
        assert best_efforts.fill_km(db) is None                                     # done: the next start does nothing
    assert _rows(client, 'BestEffortKm', 'distanceKm') == [5, 10, 20, 40] and _rows(client, 'BestEffort', 'distanceMi') == []


def test_the_pages_show_the_set_the_units_pick(client):
    with client.application.app_context():
        db = database.get_db()
        best_efforts.save_best_efforts(db, 'r45', '2026-10-01', db.execute("SELECT streams FROM Activity WHERE id='r45'").fetchone()[0])
        db.commit()
    page = client.get('/riders/1').get_data(as_text=True)
    assert '>20 mi</a>' in page and '>40 km</a>' not in page
    client.post('/settings/', data={'units': 'metric'})
    page = client.get('/riders/1').get_data(as_text=True)
    assert '>40 km</a>' in page and '>20 km</a>' in page and '>32 km<' not in page   # round kilometres, not 20 miles converted
    assert '40 km' in client.get('/data').get_data(as_text=True)


def test_removing_a_rides_efforts_clears_both_sets(client):
    with client.application.app_context():
        db = database.get_db()
        best_efforts.save_best_efforts(db, 'r45', '2026-10-01', db.execute("SELECT streams FROM Activity WHERE id='r45'").fetchone()[0])
        best_efforts.delete_for(db, 'activityId=?', ['r45'])
        db.commit()
    assert _rows(client, 'BestEffort', 'distanceMi') == [] and _rows(client, 'BestEffortKm', 'distanceKm') == []
