"""Ride best times are read through the Ride view and the rider: BestEffort holds rows for anything with a track, so a fast walk (a GPS that
jumped, a lift, a car) is never a ride's best 5 miles, on the phone's Perform tab or in the AI's achievements. Throwaway DB."""
import json

import pytest
from flask import Flask

import database
from routes import api_v1
from services import context
from services.best_efforts import save_best_efforts


@pytest.fixture
def app(tmp_path):
    a = Flask(__name__)
    a.config['DATABASE'] = str(tmp_path / 't.db')
    a.register_blueprint(api_v1.bp)                     # the device-token check is the app's, not the blueprint's
    with a.app_context():
        database.migrate_db()
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'A', 1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (2, 'B', 0)")
        db.commit()
    return a


def _add(db, aid, sport, speed, day, rider=1):
    """12 miles at a steady `speed` (m/s), with a track, and its best times worked out as every import does."""
    secs = int(12 * 1609.344 / speed)
    streams = json.dumps({'time': {'data': list(range(0, secs + 1, 5))}, 'distance': {'data': [i * speed for i in range(0, secs + 1, 5)]}})
    db.execute("INSERT INTO Activity (id, name, type, sportType, riderId, startDateLocal, distance, movingTime, elapsedTime, streams) "
               "VALUES (?,?,?,?,?,?,?,?,?,?)", [aid, f'{sport} {aid}', sport, sport, rider, f'{day}T09:00:00', secs * speed, secs, secs, streams])
    save_best_efforts(db, aid, day, streams)
    db.commit()


def test_a_fast_walk_is_not_a_ride_best_time(app):
    with app.app_context():
        db = database.get_db()
        _add(db, 'walk', 'Walk', 28.0, '2026-09-01')    # about 100 km/h: a track that went wrong
        _add(db, 'ride', 'Ride', 8.0, '2026-09-02')
        _add(db, 'theirs', 'Ride', 12.0, '2026-09-03', rider=2)
        _add(db, 'newer', 'Ride', 9.0, '2026-09-04')
        assert db.execute("SELECT COUNT(*) FROM BestEffort WHERE activityId='walk'").fetchone()[0] == 2     # kept on purpose
        best = {e['distanceMi']: e['rideId'] for e in app.test_client().get('/api/v1/perform').get_json()['best_efforts']}
        assert best == {5: 'newer', 10: 'newer'}       # not the walk, not the other rider's faster ride
        said = context._build_achievement_context('newer', '2026-09-04')
        assert said.count('from 2 Sep 2026') == 2, said  # the rider's own earlier ride, not the walk on the 1st or B's ride on the 3rd
        assert context._build_achievement_context('walk', '2026-09-01') == ''      # a walk sets no ride achievements
