"""The duplicates the check missed on a real history (the live server against its Strava export, October 2026), and the one it made up: Zwift
races set aside behind their warm-ups when the watch session that held both was set aside (park), empty Garmin recordings beside real rides,
copies that start the same second with very different distances, starts a time zone out, and second recordings longer than half the ride.
Each case is the real one's figures."""
import json
from itertools import permutations

import pytest

import app as app_module
import config
import database
from services import duplicates as dup, sanity


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


def _track(secs, lat=50.70, step=10):
    """A timed GPS track heading north from `lat`, a point every `step` seconds."""
    n = secs // step + 1
    return json.dumps({'time': {'data': [i * step for i in range(n)]}, 'latlng': {'data': [[lat + i * 1e-4, -3.50] for i in range(n)]}})


def _row(aid, start, secs, dist, sport='Ride', local=None, **kw):
    base = {'id': aid, 'name': aid, 'sportType': sport, 'startDate': start, 'startDateLocal': local or start, 'elapsedTime': secs,
            'movingTime': secs, 'distance': dist, 'averageSpeed': dist / secs if secs else 0, 'maxSpeed': None, 'averageHeartrate': None,
            'averageWatts': None, 'averageCadence': None, 'source': None, 'streams': None, 'riderId': 1}
    base.update(kw)
    return base


def _insert(db, row):
    cols = [c for c in row if c != 'source' or row[c] is not None]
    db.execute(f"INSERT INTO Activity ({', '.join(cols)}, type) VALUES ({', '.join('?' * len(cols))}, ?)", [row[c] for c in cols] + [row['sportType']])


def _live(db):
    return {r[0] for r in db.execute('SELECT id FROM Activity')}


def _parked(db):
    return {r[0]: r[1] for r in db.execute("SELECT id, primaryId FROM ActivityDuplicate WHERE status='parked'")}


# ---------- a watch session that held a Zwift warm-up and a race (2 Nov 2021) ----------
SESSION = _row('garmin_7757968309', '2021-11-02T19:11:08', 4028, 36263.0, 'VirtualRide', averageHeartrate=150, averageWatts=200)
WARMUP = _row('6202940946', '2021-11-02T19:11:02', 915, 9794.0, 'VirtualRide', averageWatts=180, streams=_track(915))
RACE = _row('6203201196', '2021-11-02T19:30:11', 2858, 31175.0, 'VirtualRide', averageWatts=250, streams=_track(2858, lat=50.80))


@pytest.mark.parametrize('order', list(permutations((SESSION, WARMUP, RACE))), ids=lambda o: '-'.join(r['id'][:6] for r in o))
def test_a_warm_up_and_a_race_inside_one_watch_session_are_both_kept_whatever_the_order(app, order):
    with app.app_context():
        db = database.get_db()
        for row in order:
            _insert(db, row)
            dup.resolve(db, row['id'])
        assert _live(db) == {WARMUP['id'], RACE['id']}
        assert set(_parked(db)) == {SESSION['id']}


def test_a_race_set_aside_behind_the_session_comes_back_when_the_session_goes(app):
    """How the five races were lost: the race was set aside behind the watch session (the session won, before Zwift's recording did), then the
    warm-up beat the session, and everything behind the session moved behind the warm-up unchecked."""
    with app.app_context():
        db = database.get_db()
        _insert(db, SESSION)
        _insert(db, RACE)
        dup.park(db, RACE['id'], SESSION['id'], 'Kept the Garmin recording (recorded on a Garmin device, has heart rate).')
        _insert(db, WARMUP)
        res = dup.resolve(db, WARMUP['id'])
        assert res['kept'] == WARMUP['id'] and res['parked'] == SESSION['id']
        assert _live(db) == {WARMUP['id'], RACE['id']} and _parked(db) == {SESSION['id']: WARMUP['id']}


def test_start_up_brings_back_the_races_already_lost_and_runs_once(app):
    with app.app_context():
        db = database.get_db()
        for row in (SESSION, WARMUP, RACE):
            _insert(db, row)
        dup.park(db, SESSION['id'], WARMUP['id'], 'Kept the Zwift (or other app) recording.')
        # the state on the server: the race behind the warm-up, as the old park left it
        db.execute("INSERT INTO ActivityDuplicate (id, primaryId, riderId, reason, status, rowJson) VALUES (?, ?, 1, 'Kept the Garmin recording.', "
                   "'parked', ?)", [RACE['id'], WARMUP['id'], json.dumps(RACE)])
        db.execute('DELETE FROM Activity WHERE id=?', [RACE['id']])
        db.execute('UPDATE Settings SET dupMatchFixDone=0')
        db.commit()
        res = dup.recheck_matching(db)
        assert res['ran'] and [i for i, _ in res['back']] == [RACE['id']] and res['merged'] == []
        assert _live(db) == {WARMUP['id'], RACE['id']}
        assert not dup.recheck_matching(db)['ran']


def test_a_new_database_has_the_start_up_check_done(app):
    with app.app_context():
        assert database.get_db().execute('SELECT dupMatchFixDone FROM Settings').fetchone()[0] == 1


# ---------- recordings with nothing in them ----------
RIDE = _row('garmin_9607269927', '2022-09-14T16:46:29', 7467, 13329.1, averageHeartrate=140, streams=_track(7467))
EMPTY = _row('garmin_9729741781', '2022-09-14T17:31:21', 3600, 0.0, averageSpeed=0.0, maxSpeed=0.0)


def test_an_empty_recording_beside_a_real_ride_is_set_aside_whatever_its_length():
    assert dup.is_empty(EMPTY) and not dup.is_empty(RIDE)
    assert dup.same_ride(RIDE, EMPTY) and dup.same_ride(EMPTY, RIDE)          # 48% of the ride: longer than a piece may be
    for existing, new in ((RIDE, EMPTY), (EMPTY, RIDE)):
        winner, loser, reason = dup.pick_winner(existing, new)
        assert winner is RIDE and 'nothing in it' in reason
    assert not dup.same_ride(RIDE, dict(EMPTY, startDate='2022-09-14T18:50:00'))          # mostly after the ride
    assert not dup.same_ride(RIDE, dict(EMPTY, startDate='2022-09-14T18:50:00'), fragments=False)
    for something in ({'distance': 5.0}, {'averageHeartrate': 90}, {'averageWatts': 120}, {'maxSpeed': 1.2}, {'streams': _track(60)},
                      {'sportType': 'Other'}, {'sportType': None}, {'source': 'manual'}):
        assert not dup.is_empty(dict(EMPTY, **something))                    # something recorded, or a sport with no distance to record


def test_an_empty_recording_is_found_by_a_ride_imported_after_it(app):
    with app.app_context():
        db = database.get_db()
        _insert(db, EMPTY)
        _insert(db, RIDE)
        assert dup.resolve(db, RIDE['id'])['parked'] == EMPTY['id']


def test_an_empty_recording_beside_nothing_is_flagged_to_delete(app):
    with app.app_context():
        db = database.get_db()
        _insert(db, EMPTY)
        _insert(db, _row('garmin_9720136853', '2022-10-03T10:00:00', 3600, 0.0, 'Other'))             # a PT session: nothing to record
        assert sanity.flag(db, EMPTY['id']) == sanity.EMPTY
        assert sanity.flag(db, 'garmin_9720136853') is None
        assert sanity.blip_ids(db, 1) == [EMPTY['id']]


# ---------- the same start ----------
def test_two_recordings_that_start_the_same_second_are_one_whatever_the_distances():
    """"Walk in the dark to see the planets": 31.2 km on Garmin (GPS jumps), 1.7 km on Strava."""
    garmin = _row('garmin_5998508292', '2020-12-24T16:42:24', 5653, 31171.5, 'Walk', averageHeartrate=95)
    strava = _row('4513468214', '2020-12-24T16:42:24', 3193, 1717.1, 'Walk')
    assert dup.same_ride(garmin, strava) and dup.same_ride(strava, garmin)
    assert not dup.same_ride(garmin, dict(strava, startDate='2020-12-24T16:43:30'))          # a minute apart: the distances must agree
    zwift = dict(strava, sportType='VirtualRide')                            # virtual rides keep their own rule
    assert not dup.same_ride(dict(garmin, sportType='VirtualRide'), zwift)


# ---------- a start a time zone out ----------
STRAVA_RUN = _row('135020695', '2014-04-28T02:56:23', 6384, 10779.5, 'Run', local='2014-04-28T14:56:23', streams=_track(6384, lat=-44.94))
PHONE_ROW = _row('wk_00a06a64b2d62d48', '2014-04-28T01:56:23', 6384, 10779.5, 'Row', local='2014-04-28T13:56:23', streams=_track(6384, lat=-44.94))


def test_one_recording_an_hour_out_is_the_same_activity():
    """"Arrowtown" (saved as a row) and Strava's "Sawpit Gully & New Chum Track": the same 10,780 m and 6,384 s, exactly an hour apart."""
    assert dup.clock_shift(PHONE_ROW, STRAVA_RUN) == 3600 and dup.clock_shift(STRAVA_RUN, PHONE_ROW) == -3600
    assert dup.same_ride(PHONE_ROW, STRAVA_RUN)
    assert not dup.same_ride(PHONE_ROW, dict(STRAVA_RUN, distance=10500.0))                          # 2.6% further
    assert not dup.same_ride(PHONE_ROW, dict(STRAVA_RUN, elapsedTime=6500, movingTime=6500))         # two minutes longer
    assert not dup.same_ride(PHONE_ROW, dict(STRAVA_RUN, startDate='2014-04-28T03:06:23'))           # 70 minutes: not a clock's mistake
    assert not dup.same_ride(PHONE_ROW, dict(STRAVA_RUN, streams=None))                              # nothing to show it's one recording


def test_two_rides_of_one_commute_at_one_pace_are_not_a_clock_mistake():
    """1 May 2018: "St. Leonards - Pinhoe" at 07:15 and at 16:59, 18,049 m and 17,984 m, both on the Garmin."""
    am = _row('garmin_2665330748', '2018-05-01T06:15:10', 2400, 18048.6, averageHeartrate=140, streams=_track(2400))
    pm = _row('garmin_2668120060', '2018-05-01T15:59:28', 2410, 17983.5, averageHeartrate=140, streams=_track(2410))
    assert not dup.same_ride(am, pm)                                         # two Garmin recordings: Garmin's UTC is right on both
    phone = dict(pm, id='imp_1', streams=_track(2410, lat=50.703))           # ...and from a phone, 300 m off the morning's line throughout
    assert not dup.same_ride(am, phone)


def test_the_activity_kept_takes_the_start_whose_time_zone_is_known(app):
    """A RunKeeper run on Strava, its time saved with no zone (22:20, read as UK time), and a file of it that knows it started at 17:20 UTC."""
    runkeeper = _row('37089330', '2011-07-26T22:20:00', 3047, 10137.0, 'Run', averageHeartrate=150, streams=_track(3047))
    file = _row('imp_7', '2011-07-26T17:20:00', 3031, 10135.0, 'Run', local='2011-07-26T18:20:00', streams=_track(3031))
    with app.app_context():
        db = database.get_db()
        _insert(db, runkeeper)
        _insert(db, file)
        res = dup.resolve(db, 'imp_7')
        assert res['kept'] == '37089330' and 'time zone' in res['reason']
        assert tuple(db.execute("SELECT startDate, startDateLocal FROM Activity WHERE id='37089330'").fetchone()) == ('2011-07-26T17:20:00', '2011-07-26T18:20:00')


# ---------- pieces longer than half the ride ----------
def test_a_second_recording_longer_than_half_the_ride_is_a_piece_when_its_track_follows():
    """"Monmouthshire Cycling" (3 h 05 m, 21.7 km) inside "FoD Day 2 - Staunton" (4 h 32 m, 31.6 km): 68% of it."""
    whole = _row('garmin_7904178835', '2021-12-02T09:56:48', 16329, 31630.7, averageHeartrate=120, streams=_track(16329))
    piece = _row('garmin_7941020020', '2021-12-02T10:39:41', 11100, 21719.2, averageHeartrate=120,
                 streams=json.dumps({'time': {'data': list(range(0, 11101, 10))}, 'latlng': {'data': [[50.70 + (2573 + i * 10) / 10 * 1e-4, -3.50] for i in range(1111)]}}))
    assert dup.fragment_of(piece, whole) and dup.same_ride(whole, piece)
    assert dup.pick_winner(piece, whole)[0] is whole
    assert not dup.fragment_of(dict(piece, streams=_track(11100, lat=51.0)), whole)                # somewhere else
    assert not dup.fragment_of(piece, dict(whole, streams=None))                                   # a track on one side proves nothing
    assert not dup.fragment_of(dict(piece, startDate='2021-12-02T13:00:00'), whole)               # runs on past its end
    assert not dup.fragment_of(dict(piece, sportType='Walk'), whole)                               # another sport


def test_zwift_longer_than_half_a_watch_session_is_kept_over_it():
    """11 Jan 2022: Zwift's 30-minute warm-up inside the watch's 52 minutes."""
    zwift = _row('6508139881', '2022-01-11T18:43:27', 1816, 11752.0, 'VirtualRide', averageWatts=180, streams=_track(1816))
    watch = _row('garmin_8100935383', '2022-01-11T18:43:32', 3111, 13446.0, 'VirtualRide', averageHeartrate=140, averageWatts=180)
    assert dup.same_ride(watch, zwift) and dup.pick_winner(watch, zwift)[0] is zwift


def test_a_copy_whose_figures_are_impossible_loses_whatever_recorded_it():
    """"Walk in the dark to see the planets" (24 Dec 2020): Garmin's GPS made 1.7 km into 31.2 km, 33 km/h on foot. Strava's copy has a 115 km/h
    spike of its own, but its distance and time are right."""
    garmin = _row('garmin_5998508292', '2020-12-24T16:42:24', 5653, 31171.5, 'Walk', movingTime=3389, averageSpeed=9.1978, maxSpeed=29.998,
                  totalElevationGain=385.0, averageHeartrate=87.0, averageCadence=50, streams=_track(5653))
    strava = _row('4513468214', '2020-12-24T16:42:24', 3193, 1717.1, 'Walk', movingTime=1873, averageSpeed=0.9168, maxSpeed=31.9,
                  totalElevationGain=100.0, averageHeartrate=93.6, averageCadence=47.2, streams=_track(3193))
    assert dup.same_ride(garmin, strava)
    for existing, new in ((garmin, strava), (strava, garmin)):
        winner, loser, reason = dup.pick_winner(existing, new)
        assert winner is strava and 'Garmin one looks wrong' in reason and 'not possible walking' in reason
    assert dup.pick_winner(strava, dict(garmin, flagDismissed=1))[0]['id'] == garmin['id']        # the rider said it's right
    wrong_too = dict(strava, distance=31000.0, averageSpeed=16.5)
    assert dup.pick_winner(wrong_too, garmin)[0] is garmin                                         # both wrong: the better recording, as before
    sane = dict(garmin, distance=1717.1, averageSpeed=0.9168, totalElevationGain=100.0)
    for fault in ({'maxSpeed': 40.0}, {'averageHeartrate': 250}, {'maxHeartrate': 260}, {'calories': 20000}):
        assert dup.pick_winner(strava, dict(sane, **fault))[0]['id'] == garmin['id']               # a spike or a sensor fault: totals still right
