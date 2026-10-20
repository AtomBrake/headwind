"""Start times where each activity happened, and the duplicates that wrong start times hid: Garmin's zoneless times (UTC in both fields), local
time from the zone at the start position, RunKeeper files whose clock was out, speed-sensor pieces of a ride, and what setting a copy aside
carries over. The rows are copied from the real cases that showed it (2011 rides and runs, 2020-2024 sensor pieces)."""
import io
import json
import zipfile
from datetime import datetime, timezone

import pytest
from flask import Flask

import database
from routes import import_rides
from services import duplicates as dup, parser, start_times, tz

GPS = json.dumps({'time': {'data': list(range(0, 7200, 10))}, 'latlng': {'data': [[50.70 + i * 1e-4, -3.50] for i in range(720)]}})


def _row(**kw):
    base = {'id': 'x', 'sportType': 'Ride', 'startDate': None, 'startDateLocal': None, 'elapsedTime': 3600, 'movingTime': 3500, 'distance': 20000.0,
            'averageHeartrate': None, 'averageWatts': None, 'averageCadence': None, 'streams': None, 'riderId': 1}
    base.update(kw)
    return base


# ---------- the zone at a position ----------
def test_zone_at_a_position_and_without_one():
    assert tz.zone_at(50.62, -3.73).key == 'Europe/London'
    assert tz.zone_at(49.28, -123.1).key == 'America/Vancouver'
    assert tz.zone_at(40.0, -30.0).key.startswith('Etc/GMT')                  # at sea
    for lat, lng in ((None, None), (0, 0), ('x', 1), (95, 0)):
        assert tz.zone_at(lat, lng).key == 'Europe/London'                     # the home zone (conftest)
    utc = datetime(2011, 7, 7, 19, 6, 43, tzinfo=timezone.utc)
    assert tz.local_at(utc, 50.62, -3.73) == '2011-07-07T20:06:43'
    assert tz.local_at(utc, 49.28, -123.1) == '2011-07-07T12:06:43'


# ---------- Garmin's zoneless times ----------
def test_garmin_identical_times_are_utc_and_meet_the_strava_copy():
    """garmin_773053310: 2011-07-07T19:06:43 in both fields; Strava 7435692 is 19:06:43 UTC (20:06 BST). Read as UK time the Garmin copy sat an
    hour early, didn't overlap, and both were kept (the Garmin one with no bike)."""
    garmin = _row(id='garmin_773053310', startDate='2011-07-07T19:06:43', startDateLocal='2011-07-07T19:06:43')
    strava = _row(id='7435692', startDate='2011-07-07T19:06:43', startDateLocal='2011-07-07T20:06:43', distance=20300.0)
    assert dup.start_instant(garmin).isoformat() == '2011-07-07T19:06:43+00:00'
    assert dup.same_ride(garmin, strava) and dup.same_ride(strava, garmin)
    other = _row(id='imp_1', startDate='2011-07-07T19:06:43', startDateLocal='2011-07-07T19:06:43')
    assert dup.start_instant(other).isoformat() == '2011-07-07T18:06:43+00:00'     # anything else saved naive in both is still home-local


# ---------- RunKeeper ----------
def _runkeeper(start='2011-07-26T22:20:00Z', name='Running 7/26/11 6:20 pm', creator='RunKeeper - http://www.runkeeper.com', n=60):
    t0 = datetime.fromisoformat(start.replace('Z', '+00:00'))
    pts = ''.join(f'<trkpt lat="{50.72 + i * 1e-4:.5f}" lon="-3.53"><ele>{30 + i % 5}</ele>'
                  f'<time>{datetime.fromtimestamp(t0.timestamp() + i * 10, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>' for i in range(n))
    return (f'<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="{creator}" xmlns="http://www.topografix.com/GPX/1/1">'
            f'<trk><name><![CDATA[{name}]]></name><time>{start}</time><trkseg>{pts}</trkseg></trk></gpx>').encode()


def test_runkeeper_clock_is_put_right_from_the_track_name():
    """Strava 37089330: the file says 22:20 UTC, the name 6:20 pm (BST), so the run started at 17:20 UTC. The id stays the file's own."""
    act = parser.parse_gpx(_runkeeper())
    assert act['startDateLocal'] == '2011-07-26T17:20:00+00:00'
    assert act['clockShiftedFrom'] == '2011-07-26T22:20:00+00:00'
    plain = parser.parse_gpx(_runkeeper(creator='Garmin Connect'))
    assert plain['startDateLocal'] == '2011-07-26T22:20:00+00:00' and 'clockShiftedFrom' not in plain
    assert act['id'] == plain['id']


@pytest.mark.parametrize('name', ['Running 7/26/11 11:20 pm',            # it agrees with the file
                                  'Running 7/26/11 6:47 pm',             # not a whole number of hours out
                                  'Morning run',                         # no time in the name
                                  'Running 7/20/11 6:20 pm'])            # six days out: not a clock error
def test_runkeeper_is_left_alone_unless_the_gap_is_whole_hours(name):
    assert 'clockShiftedFrom' not in parser.parse_gpx(_runkeeper(name=name))


# ---------- pieces of a ride ----------
def test_a_speed_sensor_piece_inside_a_ride_is_set_aside_under_it():
    ride = _row(id='9001', startDate='2022-05-01T09:00:00', startDateLocal='2022-05-01T10:00:00', elapsedTime=7200, movingTime=6800,
                distance=45000.0, streams=GPS)
    piece = _row(id='garmin_5', startDate='2022-05-01T09:40:00', startDateLocal='2022-05-01T09:40:00', elapsedTime=900, movingTime=900,
                 distance=0.0, averageHeartrate=120)
    wheel = dict(piece, distance=6200.0)                                        # only the wheel's distance, still no GPS
    for p in (piece, wheel):
        assert dup.fragment_of(p, ride) and dup.same_ride(ride, p)
        for existing, new in ((ride, p), (p, ride)):
            winner, loser, reason = dup.pick_winner(existing, new)
            assert winner is ride and loser is p and 'piece' in reason and '15-minute' in reason
    assert not dup.fragment_of(dict(piece, elapsedTime=4000, movingTime=4000), ride)            # more than half the ride
    assert not dup.fragment_of(dict(piece, startDate='2022-05-01T10:58:00'), ride)              # runs on well past its end
    assert not dup.fragment_of(dict(piece, sportType='Walk'), ride)                             # a walk is never a piece of a ride


def test_a_piece_with_its_own_gps_must_be_where_the_ride_was():
    ride = _row(id='9001', startDate='2022-05-01T09:00:00', startDateLocal='2022-05-01T10:00:00', elapsedTime=7200, distance=45000.0, streams=GPS)
    with_gps = lambda lat: json.dumps({'time': {'data': list(range(0, 1800, 10))}, 'latlng': {'data': [[lat + i * 1e-4, -3.50] for i in range(180)]}})
    # the ride's second 2400 is at 50.724: a track that starts there is the same ride; one 30 km away (a device left recording till the next
    # ride) is not
    near = _row(id='garmin_6', startDate='2022-05-01T09:40:00', startDateLocal='2022-05-01T10:40:00', elapsedTime=1800, distance=2000.0,
                streams=with_gps(50.724))
    assert dup.fragment_of(near, ride)
    assert not dup.fragment_of(dict(near, streams=with_gps(51.0)), ride)
    # Zwift inside the watch's indoor ride: Zwift's recording is kept
    watch = _row(id='garmin_7', sportType='VirtualRide', startDate='2022-01-01T18:00:00', startDateLocal='2022-01-01T18:00:00', elapsedTime=4000,
                 distance=0.0, averageHeartrate=140)
    zwift = _row(id='zw_1', sportType='VirtualRide', startDate='2022-01-01T18:05:00', startDateLocal='2022-01-01T18:05:00', elapsedTime=1900, movingTime=1900,
                 distance=20000.0, averageWatts=200, streams=GPS)
    assert dup.same_ride(watch, zwift) and dup.pick_winner(watch, zwift)[0] is zwift


def test_quality_counts_an_altitude_track():
    flat = _row(id='garmin_772924371', streams=json.dumps({'latlng': {'data': [[50.7, -3.5]] * 600}}))
    hilly = _row(id='garmin_2375551000', streams=json.dumps({'latlng': {'data': [[50.7, -3.5]] * 600}, 'altitude': {'data': [30.0] * 600}}))
    assert dup.quality(hilly)[0] > dup.quality(flat)[0]
    assert dup.pick_winner(flat, hilly)[0] is hilly


# ---------- the database ----------
@pytest.fixture
def db(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    monkeypatch.setattr('services.weather.fetch_weather', lambda *a, **k: None)
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.execute("INSERT INTO Bike (id, riderId, name) VALUES (9, 1, 'Road bike')")
        d.execute("INSERT INTO Kit (id, riderId, kind, name) VALUES (3, 1, 'shoes', 'Pegasus')")
        d.commit()
        yield d


def _add(db, act_id, start, local, sport='Ride', dist=20000.0, secs=3600, **cols):
    vals = dict(id=act_id, name=act_id, type=sport, sportType=sport, startDate=start, startDateLocal=local, distance=dist, movingTime=secs,
                elapsedTime=secs, riderId=1, rawData='{}', **cols)
    db.execute(f"INSERT INTO Activity ({','.join(vals)}) VALUES ({','.join('?' * len(vals))})", list(vals.values()))
    db.commit()


def _live(db):
    return sorted(r[0] for r in db.execute('SELECT id FROM Activity'))


def test_setting_a_run_aside_carries_its_shoes(db):
    _add(db, '7435700', '2011-07-09T10:00:00', '2011-07-09T11:00:00', sport='Run', dist=8000.0, kitId=3)
    _add(db, 'garmin_1', '2011-07-09T10:00:00', '2011-07-09T11:00:00', sport='Run', dist=8000.0, averageHeartrate=150)
    res = dup.resolve(db, 'garmin_1')
    assert res['kept'] == 'garmin_1' and res['parked'] == '7435700'
    assert db.execute("SELECT kitId FROM Activity WHERE id='garmin_1'").fetchone()[0] == 3


def test_copies_set_aside_under_a_copy_follow_it_when_it_is_set_aside(db):
    """garmin_2375… kept, Strava 37089330 set aside under it; then garmin_2375… is set aside under garmin_772…: the Strava copy moves too, so
    its Strava shoes (services/strava_gear._rides follows primaryId to a live activity) still reach the run kept."""
    _add(db, 'garmin_2375551000', '2011-07-26T17:20:00', '2011-07-26T18:20:00', sport='Run', dist=8000.0)
    _add(db, '37089330', '2011-07-26T17:20:00', '2011-07-26T18:20:00', sport='Run', dist=8000.0)
    _add(db, 'garmin_772924371', '2011-07-26T17:20:00', '2011-07-26T18:20:00', sport='Run', dist=8000.0)
    dup.park(db, '37089330', 'garmin_2375551000', 'test')
    dup.park(db, 'garmin_2375551000', 'garmin_772924371', 'test')
    rows = dict(db.execute("SELECT id, primaryId FROM ActivityDuplicate").fetchall())
    assert rows == {'37089330': 'garmin_772924371', 'garmin_2375551000': 'garmin_772924371'}


def test_fix_local_zones_on_the_real_cases(db):
    # 1. a Garmin ride with no zone (UTC in both fields) and its Strava copy, which has the bike: one ride, on the bike, at 20:06 BST
    _add(db, 'garmin_773053310', '2011-07-07T19:06:43', '2011-07-07T19:06:43', averageHeartrate=140, startLat=50.62, startLng=-3.73,
         weatherSummary='Clear, 18°C', weatherCode=0)
    _add(db, '7435692', '2011-07-07T19:06:43', '2011-07-07T20:06:43', dist=20300.0, bikeId=9, startLat=50.62, startLng=-3.73)
    # 2. a Strava walk in Vancouver saved at London time; its weather goes, a condition the rider picked stays
    _add(db, '9100', '2016-08-01T22:10:00', '2016-08-01T23:10:00', sport='Walk', dist=3900.0, startLat=49.28, startLng=-123.1,
         weatherSummary='Rain, 15°C', weatherCode=61)
    _add(db, '9101', '2016-08-02T22:10:00', '2016-08-02T23:10:00', sport='Walk', dist=3000.0, startLat=49.28, startLng=-123.1,
         weatherSummary='Snow, 15°C', weatherCode=71, weatherSource='manual')
    # 3. a speed-sensor piece (0 m, no GPS) inside a ride on the bike
    _add(db, '8000', '2022-05-01T09:00:00', '2022-05-01T10:00:00', dist=45000.0, secs=7200, bikeId=9, startLat=50.7, startLng=-3.5, streams=GPS)
    _add(db, 'garmin_5', '2022-05-01T09:40:00', '2022-05-01T10:40:00', dist=0.0, secs=900, averageHeartrate=120)
    # 4. typed in by hand, and a friend's: never touched
    _add(db, 'man_1', '2016-08-03T10:00:00', '2016-08-03T10:00:00', startLat=49.28, startLng=-123.1)
    db.execute("INSERT INTO Rider (id, name) VALUES (2, 'Friend')")
    db.execute("INSERT INTO Friend (name, url, riderId) VALUES ('Friend', 'http://x', 2)")
    _add(db, 'garmin_99', '2011-07-07T19:06:43', '2011-07-07T19:06:43')
    db.execute("UPDATE Activity SET riderId=2 WHERE id='garmin_99'")
    db.execute('UPDATE Settings SET localZoneFixDone=0'); db.commit()      # a new database starts with the repair done

    res = start_times.fix_local_zones(db)
    assert res['ran'] and res['duplicates'] == 1 and res['fragments'] == 1
    assert _live(db) == ['8000', '9100', '9101', 'garmin_773053310', 'garmin_99', 'man_1']
    g = db.execute("SELECT startDate, startDateLocal, bikeId, weatherSummary FROM Activity WHERE id='garmin_773053310'").fetchone()
    assert tuple(g) == ('2011-07-07T19:06:43', '2011-07-07T20:06:43', 9, None)
    w = db.execute("SELECT startDateLocal, weatherSummary FROM Activity WHERE id='9100'").fetchone()
    assert tuple(w) == ('2016-08-01T15:10:00', None)
    assert db.execute("SELECT startDateLocal, weatherSummary FROM Activity WHERE id='9101'").fetchone()[1] == 'Snow, 15°C'
    assert db.execute("SELECT startDateLocal FROM Activity WHERE id='man_1'").fetchone()[0] == '2016-08-03T10:00:00'
    assert db.execute("SELECT startDateLocal FROM Activity WHERE id='garmin_99'").fetchone()[0] == '2011-07-07T19:06:43'
    reason = db.execute("SELECT primaryId, reason FROM ActivityDuplicate WHERE id='garmin_5'").fetchone()
    assert reason[0] == '8000' and 'piece' in reason[1]
    assert start_times.fix_local_zones(db) == {'ran': False}                      # once only


def test_import_puts_local_time_where_the_activity_started(db):
    act = parser.parse_gpx(_runkeeper(creator='phone', name='Vancouver walk').replace(b'lat="50.', b'lat="49.').replace(b'lon="-3.53"', b'lon="-123.1"'))
    assert import_rides._split_start(act) == ('2011-07-26T22:20:00', '2011-07-26T15:20:00')


# ---------- RunKeeper through a Strava export ----------
CSV_HEAD = 'Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Filename,Moving Time,Distance\n'


def _export(dist_m):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('activities.csv', CSV_HEAD + f'37089330,"Jul 26, 2011, 10:20:00 PM",Evening Run,Run,590,{dist_m / 1000:.2f},activities/37089330.gpx,590,{dist_m}\n')
        z.writestr('activities/37089330.gpx', _runkeeper())
    buf.seek(0)
    return zipfile.ZipFile(buf)


def test_strava_export_puts_runkeeper_copies_on_the_right_time(db):
    """The Garmin re-upload of the RunKeeper file (garmin_2375…) took the wrong time and holds the shoes; Garmin's older copy (garmin_772…,
    UTC in both fields, no elevation) had it right. Importing the export again moves the re-upload to 17:20 UTC, where it meets the old copy
    and the Strava one: one run is left, the one with elevation and the shoes."""
    act = parser.parse_gpx(_runkeeper())
    dist = act['distance']
    _add(db, 'garmin_2375551000', '2011-07-26T22:20:00', '2011-07-26T23:20:00', sport='Run', dist=dist, secs=590, kitId=3,
         streams=act['streams'], startLat=50.72, startLng=-3.53)
    flat = json.loads(act['streams']); flat.pop('altitude', None)
    _add(db, 'garmin_772924371', '2011-07-26T17:20:00', '2011-07-26T17:20:00', sport='Run', dist=dist, secs=590,
         streams=json.dumps(flat), startLat=50.72, startLng=-3.53)
    z = _export(round(dist, 1))
    events = [json.loads(e[len('data: '):]) for e in import_rides._process_strava_export(z, z.namelist(), 1)]
    db.commit()
    assert events[-1]['errors'] == 0
    assert _live(db) == ['garmin_2375551000']
    kept = db.execute("SELECT startDate, startDateLocal, kitId FROM Activity WHERE id='garmin_2375551000'").fetchone()
    assert tuple(kept) == ('2011-07-26T17:20:00', '2011-07-26T18:20:00', 3)
    parked = dict(db.execute("SELECT id, primaryId FROM ActivityDuplicate WHERE status='parked'").fetchall())
    assert parked == {'garmin_772924371': 'garmin_2375551000', '37089330': 'garmin_2375551000'}


def test_strava_export_does_not_bring_back_a_copy_set_aside(db):
    """Set aside under the Garmin copy (here by "use the other recording"): importing the export again, read anew after a release, leaves it so."""
    act = parser.parse_gpx(_runkeeper(creator='phone', name='Evening Run'))
    _add(db, 'garmin_1', '2011-07-26T22:20:00', '2011-07-26T23:20:00', sport='Run', dist=act['distance'], secs=590)
    _add(db, '37089330', '2011-07-26T22:20:00', '2011-07-26T23:20:00', sport='Run', dist=act['distance'], secs=590, averageHeartrate=150,
         streams=act['streams'])
    dup.park(db, '37089330', 'garmin_1', 'You chose to use the other recording.'); db.commit()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('activities.csv', CSV_HEAD + f'37089330,"Jul 26, 2011, 10:20:00 PM",Evening Run,Run,590,1.00,activities/37089330.gpx,590,{act["distance"]}\n')
        z.writestr('activities/37089330.gpx', _runkeeper(creator='phone', name='Evening Run'))
    buf.seek(0)
    z = zipfile.ZipFile(buf)
    list(import_rides._process_strava_export(z, z.namelist(), 1)); db.commit()
    assert _live(db) == ['garmin_1']
    assert db.execute("SELECT primaryId FROM ActivityDuplicate WHERE id='37089330'").fetchone()[0] == 'garmin_1'


# ---------- Garmin sync ----------
def test_garmin_sync_reads_zoneless_times_as_utc(tmp_path, monkeypatch):
    from tests.test_garmin_sync import FakeAPI
    from services import garmin
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT INTO Rider(name) VALUES ('r')"); d.commit()
        monkeypatch.setattr('services.parser.parse_fit', lambda b: {'distance': 10000, 'movingTime': 1800, 'elapsedTime': 1800, 'streams': None})
        monkeypatch.setattr('services.weather.fetch_weather', lambda *a, **k: None)
        acts = [{'activityId': 936556469, 'activityType': {'typeKey': 'cycling'}, 'startTimeLocal': '2011-07-09 10:59:00',
                 'startTimeGMT': '2011-07-09 10:59:00', 'distance': 10000, 'activityName': 'Lustleigh', 'startLatitude': 50.62, 'startLongitude': -3.73}]
        monkeypatch.setattr(garmin, '_client', lambda e, p: FakeAPI(acts, ()))
        list(garmin.sync_garmin_activities('e', 'p', 1))
        row = d.execute("SELECT startDate, startDateLocal FROM Activity WHERE id='garmin_936556469'").fetchone()
        assert tuple(row) == ('2011-07-09T10:59:00', '2011-07-09T11:59:00')


# ---------- weather ----------
def test_weather_backfill_covers_every_sport_with_a_position(db, monkeypatch):
    from services import weather
    _add(db, 'w1', '2016-08-01T22:10:00', '2016-08-01T15:10:00', sport='Walk', startLat=49.28, startLng=-123.1)
    _add(db, 'w2', '2016-08-02T22:10:00', '2016-08-02T15:10:00', sport='Run')                     # no position: nothing to look up
    asked = []
    monkeypatch.setattr(weather, 'fetch_weather', lambda lat, lng, local, streams=None: asked.append((lat, local)) or None)
    weather._FAILED.clear()
    weather.backfill_missing(db, pause=0)
    assert asked == [(49.28, '2016-08-01T15:10:00')]


def test_a_short_ride_just_after_another_is_not_a_piece_of_it():
    """5 Nov 2016: a 210 s ride, then a 30 s one 52 s after it ended. Inside the 120 s slack, but they don't overlap at all."""
    first = _row(id='766408885', startDate='2016-11-05T11:54:18', startDateLocal='2016-11-05T11:54:18', elapsedTime=210, movingTime=210, distance=953.0)
    then = _row(id='766410274', startDate='2016-11-05T11:58:40', startDateLocal='2016-11-05T11:58:40', elapsedTime=30, movingTime=30, distance=203.0)
    assert not dup.fragment_of(then, first) and not dup.same_ride(first, then)


def test_a_piece_with_half_the_distance_never_wins_over_the_whole_ride():
    """29 Nov 2025: 'Who greased the leaves?' (74 min, 9.8 km, heart rate) inside the e-bike's 'Morning Mountain Bike Ride' (2 h 45, 19.7 km).
    The piece is the better recording, but keeping it would lose 10 km of riding."""
    whole = _row(id='16602099234', sportType='E-Bike Ride', startDate='2025-11-29T09:47:27', startDateLocal='2025-11-29T09:47:27', elapsedTime=9880,
                 movingTime=6761, distance=19680.0, averageWatts=184, streams=GPS)
    piece = _row(id='16599742639', sportType='E-Bike Ride', startDate='2025-11-29T09:51:19', startDateLocal='2025-11-29T09:51:19', elapsedTime=4443,
                 movingTime=3324, distance=9794.0, averageWatts=148, averageHeartrate=103, streams=GPS)
    assert dup.same_ride(whole, piece)
    winner, _, reason = dup.pick_winner(piece, whole)
    assert winner is whole and '50% of its distance' in reason


def test_virtual_rides_keep_the_home_clock():
    """Zwift's track is in Watopia (the Solomon Islands' zone) or New York; the rider was at home."""
    utc = datetime(2026, 10, 17, 17, 0, 19, tzinfo=timezone.utc)
    assert tz.local_at(utc, -11.64, 166.95, 'Virtual Ride') == '2026-10-17T18:00:19'
    assert tz.local_at(utc, -11.64, 166.95, 'VirtualRide') == '2026-10-17T18:00:19'
    assert tz.local_at(utc, -11.64, 166.95, 'Ride') == '2026-10-18T04:00:19'


def test_a_piece_may_run_on_after_the_ride():
    """Canonteign, 3 Aug 2022: the phone app's piece (18 min, no GPS) went on 125 s after the watch was stopped."""
    ride = _row(id='garmin_9332269082', startDate='2022-08-03T17:32:48', startDateLocal='2022-08-03T18:32:48', elapsedTime=6514, movingTime=5000,
                distance=20000.0, streams=GPS)
    piece = _row(id='garmin_9729740985', startDate='2022-08-03T19:05:27', startDateLocal='2022-08-03T20:05:27', elapsedTime=1080, movingTime=1080,
                 distance=0.0)
    assert dup.fragment_of(piece, ride) and dup.pick_winner(piece, ride)[0] is ride
    assert not dup.fragment_of(dict(piece, startDate='2022-08-03T19:20:00'), ride)        # mostly after it


@pytest.mark.parametrize('watch, zwift', [
    # TdZ Stage 8, 4 Feb 2022: the watch's 45.2 km, Zwift's 56.4 km; Zwift started 9 minutes in
    (dict(startDate='2022-02-04T17:51:36', elapsedTime=5763, distance=45202.0), dict(startDate='2022-02-04T18:00:27', elapsedTime=5232, distance=56379.0)),
    # The Zwift Big Spin, 4 Mar 2025: 22.1 km and 26.0 km, 45 s apart
    (dict(startDate='2025-03-04T18:29:37', elapsedTime=2798, distance=22089.0), dict(startDate='2025-03-04T18:30:22', elapsedTime=2866, distance=26019.0)),
])
def test_a_watch_indoor_ride_and_its_zwift_copy_pair_whatever_their_distances(watch, zwift):
    w = _row(id='garmin_8240214546', sportType='VirtualRide', startDateLocal=watch['startDate'], movingTime=watch['elapsedTime'],
             averageHeartrate=140, **watch)
    z = _row(id='6631286820', sportType='Virtual Ride', startDateLocal=zwift['startDate'], movingTime=zwift['elapsedTime'], averageWatts=210,
             streams=GPS, **zwift)
    assert dup.same_ride(w, z) and dup.same_ride(z, w)
    for existing, new in ((w, z), (z, w)):                                         # Zwift's recording is kept, though the watch's is a Garmin
        winner, _, reason = dup.pick_winner(existing, new)
        assert winner is z and 'Zwift' in reason


def test_zwift_rides_inside_a_watch_session_are_kept_and_the_session_goes():
    """18 Jan 2022: one watch session (74 min, 34 km) held a Zwift warm-up and a race."""
    watch = _row(id='garmin_8146807976', sportType='VirtualRide', startDate='2022-01-18T18:55:00', startDateLocal='2022-01-18T18:55:00',
                 elapsedTime=4411, movingTime=4411, distance=34085.0, averageHeartrate=150)
    warmup = _row(id='6544804586', sportType='Virtual Ride', startDate='2022-01-18T19:05:47', startDateLocal='2022-01-18T19:05:47',
                  elapsedTime=1364, movingTime=1364, distance=14813.0, averageWatts=180, streams=GPS)
    assert dup.same_ride(watch, warmup) and dup.pick_winner(watch, warmup)[0] is warmup


def test_a_zwift_copy_with_no_distance_does_not_win():
    watch = _row(id='garmin_1', sportType='VirtualRide', startDate='2022-02-04T18:00:00', startDateLocal='2022-02-04T18:00:00', elapsedTime=3600,
                 movingTime=3600, distance=30000.0, averageHeartrate=140)
    broken = dict(watch, id='6631', sportType='Virtual Ride', distance=0.0, averageHeartrate=None, streams=GPS)
    assert dup.pick_winner(broken, watch)[0] is watch


def test_virtual_rides_still_need_the_same_start_and_length():
    a = _row(sportType='VirtualRide', startDate='2022-02-04T18:00:00', startDateLocal='2022-02-04T18:00:00', elapsedTime=3600, movingTime=3600,
             distance=30000.0)
    assert not dup.same_ride(a, dict(a, startDate='2022-02-04T18:15:00', startDateLocal='2022-02-04T18:15:00', distance=20000.0))   # 15 min later
    assert not dup.same_ride(a, dict(a, elapsedTime=2600, movingTime=2600, distance=20000.0))                                    # 28% shorter
    assert not dup.same_ride(a, dict(a, sportType='Ride', distance=20000.0))                                                     # one outdoors
