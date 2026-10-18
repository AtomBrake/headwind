"""Garmin activities that aren't rides: the type mapping, the repair of ones an older sync saved as rides, Garmin workouts staying deleted, and top
speeds that were one GPS spike. Throwaway DB, Garmin faked."""
import json

import pytest
from flask import Flask

import database
from services import convert, duplicates, origin, sanity, sport_fix, workouts
from services.garmin import _save_workout, garmin_sport
from services.max_stats import fix_spiky_max_speed

MI = 1609.344


@pytest.fixture
def db(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT INTO Rider(name,isDefault) VALUES ('Tom',1)"); d.commit()
        yield d


def add_ride(db, rid, sport='Ride', name='Activity', dist=20000.0, max_speed=8.0, streams=None, day='2021-07-05', calories=400):
    db.execute("INSERT INTO Activity (id,name,type,sportType,startDate,startDateLocal,distance,movingTime,elapsedTime,totalElevationGain,averageSpeed,maxSpeed,calories,streams,rawData,riderId,createdAt,updatedAt)"
               " VALUES (?,?,?,?,?,?,?,3600,3700,100,?,?,?,?,'{}',1,'n','n')",
               [rid, name, sport, sport, day + 'T09:00:00', day + 'T10:00:00', dist, dist / 3600, max_speed, calories, streams or '{}'])
    sanity.flag(db, rid)
    db.commit()


@pytest.mark.parametrize('key, sport', [
    ('cycling', 'Ride'), ('road_biking', 'Ride'), ('mountain_biking', 'Ride'), ('gravel_cycling', 'Ride'), ('e_bike_mountain', 'Ride'),
    ('indoor_cycling', 'VirtualRide'), ('virtual_ride', 'VirtualRide'),
    ('running', 'Run'), ('trail_running', 'Run'), ('treadmill_running', 'Run'), ('walking', 'Walk'), ('hiking', 'Hike'),
    ('lap_swimming', 'Swim'), ('open_water_swimming', 'Swim'), ('surfing', 'Surf'), ('kayaking', 'Paddle'), ('stand_up_paddleboarding', 'Paddle'),
    ('rowing', 'Row'), ('resort_skiing_snowboarding', 'Ski'), ('golf', 'Golf'), ('rock_climbing', 'Climb'),
    ('motorcycling', 'Other'), ('multi_sport', 'Other'), ('', 'Other'),
])
def test_garmin_types_map_to_our_sports_and_unknown_is_never_a_ride(key, sport):
    assert garmin_sport(key) == sport


class FakeGarmin:
    """get_activities pages newest first, like Garmin's list."""
    def __init__(self, acts):
        self.acts, self.calls = acts, 0

    def get_activities(self, start, limit):
        self.calls += 1
        return self.acts[start:start + limit]


def test_check_lists_the_wrong_sports_and_apply_moves_them(db):
    add_ride(db, 'garmin_1', name='Pool Swimming', dist=140, calories=210)        # flagged as a 140 m "ride"
    add_ride(db, 'garmin_2', name='Exeter Mountain Biking')
    add_ride(db, 'garmin_3', name='Trail run', dist=8000)
    add_ride(db, 'garmin_4', name='Zwift', day='2021-07-04')
    add_ride(db, 'garmin_5', name='Surfing', dist=1, day='2021-06-20')
    add_ride(db, 'imp_9')                                                           # not from Garmin: never touched
    assert sanity.flagged(db, 1)[0]['isBlip']
    keys = {'1': 'lap_swimming', '2': 'mountain_biking', '3': 'trail_running', '4': 'indoor_cycling', '5': 'surfing'}
    api = FakeGarmin([{'activityId': int(k), 'activityType': {'typeKey': v}, 'startTimeLocal': '2021-07-05 10:00:00'} for k, v in keys.items()])

    res = sport_fix.scan(db, api, 1)
    assert res == {'checked': 5, 'found': 5, 'proposed': 4}
    assert {p['rideId']: p['newSport'] for p in sport_fix.pending(db, 1)} == {'garmin_1': 'Swim', 'garmin_3': 'Run', 'garmin_4': 'VirtualRide', 'garmin_5': 'Surf'}

    res = sport_fix.apply(db, 1, ['garmin_1', 'garmin_3', 'garmin_4'])               # garmin_5 left as it is
    assert res == {'changed': 3, 'failed': 0, 'kept': 1}
    swim = db.execute("SELECT * FROM Workout WHERE sport='Swim'").fetchone()
    assert swim and swim['calories'] == 210                                        # the watch's calories, not a walking estimate
    assert db.execute("SELECT COUNT(*) FROM Workout WHERE sport='Run'").fetchone()[0] == 1
    assert db.execute("SELECT sportType FROM Activity WHERE id='garmin_4'").fetchone()[0] == 'VirtualRide'
    assert not db.execute("SELECT 1 FROM Activity WHERE id IN ('garmin_1','garmin_3')").fetchone()
    assert duplicates.is_deleted(db, 'garmin_1')                                   # a Garmin re-sync won't bring the swim back as a ride
    assert all(f['id'] != 'garmin_1' for f in sanity.flagged(db, 1))                # and it's off the "looks wrong" list
    assert origin.link(swim['id'], swim['originId'])['url'] == 'https://connect.garmin.com/modern/activity/1'    # still links to Garmin

    sport_fix.scan(db, api, 1)
    assert sport_fix.pending(db, 1) == []                                          # the one left alone isn't suggested again


def test_check_stops_paging_once_past_the_oldest_garmin_ride(db):
    add_ride(db, 'garmin_7', day='2026-10-01')
    from datetime import date, timedelta
    acts = [{'activityId': 1000 + i, 'activityType': {'typeKey': 'cycling'}, 'startTimeLocal': f'{date(2026, 10, 30) - timedelta(days=i // 3)} 10:00:00'}
            for i in range(300)]                                                   # three a day, newest first: the 100th is 27 September
    api = FakeGarmin(acts)
    sport_fix.scan(db, api, 1)
    assert api.calls == 1                                                          # the first page already reaches back before 1 October


def test_a_garmin_workout_saves_with_its_own_sport_and_stays_deleted(db):
    parsed = {'distance': 1500.0, 'movingTime': 1800, 'elapsedTime': 2000, 'calories': 300, 'averageSpeed': 0.8, 'streams': '{}'}
    _save_workout(db, 'garmin_42', 1, 'Swim', 'Pool Swimming', '2026-10-01T07:00:00Z', '2026-10-01T08:00:00', parsed, 1.2)
    w = db.execute("SELECT sport, calories, source FROM Workout WHERE id='garmin_42'").fetchone()
    assert tuple(w) == ('Swim', 300, 'garmin')
    assert workouts.delete(db, 'garmin_42', 1)
    assert duplicates.is_deleted(db, 'garmin_42')


def test_top_speed_spike_is_recomputed_and_the_flag_cleared(db):
    speeds = [5.0 + (i % 7) for i in range(600)]
    speeds[300] = 61.0                                                             # one GPS jump: 137 mph
    streams = json.dumps({'velocity_smooth': {'data': speeds}, 'time': {'data': list(range(600))}})
    add_ride(db, 'garmin_8', name='Forest of Dean Mountain Biking', max_speed=61.0, streams=streams)
    add_ride(db, 'garmin_9', max_speed=55.0)                                       # no streams to recompute from: left alone
    assert 'GPS glitch' in (db.execute("SELECT flagReason FROM Activity WHERE id='garmin_8'").fetchone()[0] or '')
    assert fix_spiky_max_speed(db) == 1
    r = db.execute("SELECT maxSpeed, flagReason FROM Activity WHERE id='garmin_8'").fetchone()
    assert r['maxSpeed'] == 11.0 and r['flagReason'] is None
    assert db.execute("SELECT maxSpeed FROM Activity WHERE id='garmin_9'").fetchone()[0] == 55.0


def test_sync_puts_a_swim_in_workouts_and_a_ride_in_rides_with_a_sane_top_speed(db, monkeypatch):
    import io
    import zipfile
    from services import garmin, parser, weather
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('1_ACTIVITY.fit', b'fit')

    class Api(FakeGarmin):
        class ActivityDownloadFormat:
            ORIGINAL = 'original'
        def download_activity(self, aid, dl_fmt=None):
            return buf.getvalue()

    acts = [{'activityId': 11, 'activityName': 'Pool Swimming', 'activityType': {'typeKey': 'lap_swimming'}, 'startTimeLocal': '2026-10-02 08:00:00', 'distance': 1500},
            {'activityId': 12, 'activityName': 'Forest of Dean Mountain Biking', 'activityType': {'typeKey': 'mountain_biking'}, 'startTimeLocal': '2026-10-01 10:00:00', 'distance': 30000}]
    monkeypatch.setattr(garmin, '_client', lambda e, p: Api(acts))
    parsed = {'distance': 30000.0, 'movingTime': 7200, 'elapsedTime': 7500, 'averageSpeed': 4.2, 'maxSpeed': 14.0, 'calories': 900,
              'streams': json.dumps({'velocity_smooth': {'data': [4.0, 61.0, 5.0]}})}         # the stream has a spike; the parser's max doesn't
    monkeypatch.setattr(parser, 'parse_fit', lambda b: dict(parsed))
    monkeypatch.setattr(weather, 'fetch_weather', lambda *a, **k: None)
    db.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)'); db.commit()

    events = list(garmin.sync_garmin_activities('e', 'p', 1))
    assert events[-1]['imported'] == 2
    assert db.execute("SELECT sport FROM Workout WHERE id='garmin_11'").fetchone()[0] == 'Swim'
    assert not db.execute("SELECT 1 FROM Activity WHERE id='garmin_11'").fetchone()
    assert db.execute("SELECT maxSpeed FROM Activity WHERE id='garmin_12'").fetchone()[0] == 14.0

    db.execute('UPDATE Settings SET garminActivitySyncDate=NULL WHERE id=1'); db.commit()
    assert list(garmin.sync_garmin_activities('e', 'p', 1))[-1]['imported'] == 0          # a full re-sync adds neither again


def _park_phone_copy(db, under, day='2024-05-30'):
    """The same session arriving again from a phone / file import, set aside under the Garmin one."""
    add_ride(db, 'imp_hiit', dist=0.0, day=day)
    duplicates.park(db, 'imp_hiit', under, 'Kept the Garmin recording.')
    db.commit()


def test_apply_moves_a_ride_with_a_copy_set_aside_and_throws_the_copy_away(db):
    add_ride(db, 'garmin_20', name='HIIT', dist=0.0, day='2024-05-30')
    _park_phone_copy(db, 'garmin_20')
    api = FakeGarmin([{'activityId': 20, 'activityType': {'typeKey': 'hiit'}, 'startTimeLocal': '2024-05-30 10:00:00'}])
    sport_fix.scan(db, api, 1)
    assert [p['parked'] for p in sport_fix.pending(db, 1)] == [1]                  # the review list says a copy goes with it

    assert sport_fix.apply(db, 1, ['garmin_20']) == {'changed': 1, 'failed': 0, 'kept': 0}
    assert db.execute("SELECT sport FROM Workout").fetchone()[0] == 'Other'
    assert not db.execute("SELECT 1 FROM Activity").fetchone()
    d = db.execute("SELECT status, rowJson FROM ActivityDuplicate WHERE id='imp_hiit'").fetchone()
    assert tuple(d) == ('discarded', '{}')
    assert duplicates.exists_anywhere(db, 'imp_hiit')                              # a re-import can't bring the copy back as a ride


def test_changing_one_ride_by_hand_still_asks_to_settle_its_copy_first(db):
    from services import convert
    add_ride(db, 'garmin_21', dist=0.0, day='2024-05-30')
    _park_phone_copy(db, 'garmin_21')
    with pytest.raises(ValueError, match='set aside'):
        convert.change_sport(db, 'ride', 'garmin_21', 'Other')


@pytest.mark.parametrize('aid, origin_id, url', [
    ('garmin_123', None, 'https://connect.garmin.com/modern/activity/123'),
    ('4567890', None, 'https://www.strava.com/activities/4567890'),                 # a Strava export keeps Strava's id
    ('conv_garmin_123', None, 'https://connect.garmin.com/modern/activity/123'),
    ('wk_0123456789abcdef', '4567890', 'https://www.strava.com/activities/4567890'),
    ('imp_0123456789abcd', None, None), ('f2_99', None, None), ('man_abc', None, None), ('garmin_x', None, None),
])
def test_link_to_where_it_came_from(aid, origin_id, url):
    assert (origin.link(aid, origin_id) or {}).get('url') == url


def test_a_ride_from_garmin_and_strava_links_to_both(db):
    add_ride(db, 'garmin_123')
    add_ride(db, '4567890')
    add_ride(db, 'imp_0123456789abcd')
    duplicates.park(db, '4567890', 'garmin_123', 'same ride')
    duplicates.park(db, 'imp_0123456789abcd', 'garmin_123', 'same ride')
    assert [l['name'] for l in origin.links(db, 'garmin_123')] == ['Garmin', 'Strava']
    duplicates.discard(db, '4567890')                                              # gone from here, still on Strava
    assert [l['url'] for l in origin.links(db, 'garmin_123')] == ['https://connect.garmin.com/modern/activity/123', 'https://www.strava.com/activities/4567890']
    assert duplicates.swap(db, 'imp_0123456789abcd')
    assert sorted(l['name'] for l in origin.links(db, 'imp_0123456789abcd')) == ['Garmin', 'Strava']     # the merged ones follow the main recording


def test_a_ride_changed_to_a_run_and_back_keeps_its_strava_link(db):
    add_ride(db, '4567890', dist=8000)
    wid = convert.change_sport(db, 'ride', '4567890', 'Run')['id']
    assert db.execute('SELECT originId FROM Workout WHERE id=?', [wid]).fetchone()[0] == '4567890'
    aid = convert.change_sport(db, 'workout', wid, 'Ride')['id']
    assert db.execute('SELECT originId FROM Activity WHERE id=?', [aid]).fetchone()[0] == '4567890'


def test_workouts_converted_before_the_origin_was_kept_are_matched_up(db):
    add_ride(db, 'garmin_7', dist=8000)
    wid = convert.change_sport(db, 'ride', 'garmin_7', 'Run')['id']
    db.execute('UPDATE Workout SET originId=NULL'); db.commit()                    # as an older version left it
    assert origin.backfill(db) == 1
    assert db.execute('SELECT originId FROM Workout WHERE id=?', [wid]).fetchone()[0] == 'garmin_7'
