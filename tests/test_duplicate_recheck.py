"""Duplicate decisions that come out the same however the activities arrived: a tie in quality broken by the recordings themselves
(duplicates._tie_break), and copies set aside behind an activity checked again when an import's figures change it (duplicates.recheck_parked,
from reimport.resolve). Full app, throwaway DB."""
import json

import pytest

import app as app_module
import config
import database
from services import duplicates, reimport


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
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Alex', 1)")
        db.commit()
    return a


def _track(n):
    return json.dumps({'latlng': {'data': [[50.7 + i * 1e-5, -3.5] for i in range(n)]}, 'time': {'data': list(range(n))}})


def _row(aid, dist, pts=0, **cols):
    return {'id': aid, 'name': aid, 'sportType': 'Ride', 'startDate': '2020-06-12T19:11:54', 'startDateLocal': '2020-06-12T20:11:54',
            'distance': dist, 'movingTime': 1400, 'elapsedTime': 1800, 'averageHeartrate': None, 'averageWatts': 95, 'averageCadence': None,
            'source': None, 'streams': _track(pts) if pts else None, **cols}


def test_a_tie_keeps_the_same_recording_whichever_came_first():
    # 12 June 2020: a phone and a bike computer, both with power; the bike computer's 6.0 km against the phone's 5.5 km
    phone, computer = _row('3604465245', 5495, 1700), _row('3604374659', 6066, 1539)
    assert duplicates.quality(phone)[0] == duplicates.quality(computer)[0]
    for existing, new in ((phone, computer), (computer, phone)):
        winner, loser, reason = duplicates.pick_winner(existing, new)
        assert (winner['id'], loser['id']) == ('3604374659', '3604465245') and 'the longer of the two' in reason
    a, b = _row('a', 6000, 1600), _row('b', 6000, 1500)                    # the same distance: the more detailed track
    assert duplicates.pick_winner(b, a)[0]['id'] == 'a' and duplicates.pick_winner(a, b)[0]['id'] == 'a'
    first, again = _row('255438415', 19173, 1375), _row('16745255996', 19173, 1375)      # one file uploaded twice: the original
    assert duplicates.pick_winner(again, first)[0]['id'] == '255438415' and duplicates.pick_winner(first, again)[0]['id'] == '255438415'


def _add(db, aid, local, dist, elapsed, moving):
    db.execute('INSERT INTO Activity (id, name, riderId, sportType, type, startDate, startDateLocal, distance, elapsedTime, movingTime) '
               "VALUES (?, ?, 1, 'Ride', 'Ride', ?, ?, ?, ?, ?)", [aid, aid, local, local, dist, elapsed, moving])


def test_strava_elapsed_time_brings_back_the_ride_a_device_left_running_had_swallowed(app):
    # 31 December 2020: "OTHER" from 17:57, whose file ran on to 21:21 (Strava's, trimmed, ends 19:56), and the 19:59 "Evening Ride"
    with app.app_context():
        db = database.get_db()
        _add(db, 'other', '2020-12-31T17:57:01', 10215, 12243, 7222)
        _add(db, 'evening', '2020-12-31T19:59:10', 5258, 3144, 1448)
        _add(db, 'chosen', '2020-12-31T18:30:00', 4000, 1500, 1400)       # set aside by the rider: stays, whatever the times say
        rows = {r['id']: dict(r) for r in db.execute('SELECT * FROM Activity')}
        assert duplicates.same_ride(rows['evening'], rows['other'])        # inside the file's 3 h 24 min: taken for a piece of it
        duplicates.park(db, 'evening', 'other', 'Kept the whole ride: the other recording is only a 52-minute piece of it.')
        duplicates.park(db, 'chosen', 'other', duplicates.CHOSEN)
        db.execute("INSERT INTO ImportChange (rideId, riderId, rideName, source, diffs, act) VALUES ('other', 1, 'OTHER', 'Strava export', '[]', ?)",
                   [json.dumps({'elapsedTime': 7152, 'movingTime': 4473})])
        db.commit()
        assert reimport.resolve(db, 'other', 'replace')                     # "use the import" on the Import page
        db.commit()
        live = {r[0] for r in db.execute('SELECT id FROM Activity')}
        assert live == {'other', 'evening'}
        assert [tuple(r) for r in db.execute('SELECT id, status FROM ActivityDuplicate')] == [('chosen', 'parked')]


def test_a_copy_that_is_still_the_same_ride_stays_set_aside(app):
    with app.app_context():
        db = database.get_db()
        _add(db, 'whole', '2022-08-04T10:48:51', 45970, 21054, 10554)
        _add(db, 'piece', '2022-08-04T10:49:48', 11519, 9152, 9152)
        duplicates.park(db, 'piece', 'whole', 'Kept the whole ride.')
        db.execute("INSERT INTO ImportChange (rideId, riderId, rideName, source, diffs, act) VALUES ('whole', 1, 'whole', 'Strava export', '[]', ?)",
                   [json.dumps({'elapsedTime': 21051})])
        db.commit()
        assert reimport.resolve(db, 'whole', 'replace')
        assert db.execute("SELECT status FROM ActivityDuplicate WHERE id='piece'").fetchone()[0] == 'parked'
