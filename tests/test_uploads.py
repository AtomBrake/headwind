"""One upload path for every activity from the phone and the Watch (services/uploads.py): POST /api/v1/activities takes a ride, another sport
with a track, or a session with no track, keeps its client_id and finds it again by it; POST /api/v1/activities/known says which client ids the
server has, so Apple Health's sync can leave those out. /rides and /workouts are the same door with the older replies."""
from datetime import datetime, timezone
from io import BytesIO

import database
from tests.test_phone_sport_bike import gpx, phone  # noqa: F401  (phone is a fixture)


def send(phone, data, name='Morning.gpx', **fields):
    return phone.post('/api/v1/activities', headers=phone.H, content_type='multipart/form-data',
                      data={'file': (BytesIO(data), name), 'source': 'ios', **fields})


def known(phone, *ids):
    return phone.post('/api/v1/activities/known', headers=phone.H, json={'client_ids': list(ids)}).get_json()['known']


def sql(phone, q, args=()):
    with phone.app_.app_context():
        d = database.get_db()
        rows = d.execute(q, args).fetchall()
        d.commit()
        return [tuple(r) for r in rows]


WALK = gpx('walking', start=datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc), seconds=900, step=0.00001)
SESSION = {'sport': 'Strength', 'start': '2026-10-20T18:30:00+01:00', 'duration_s': 3600, 'source': 'ios'}


def test_ping_says_the_one_path_is_there(phone):
    assert phone.get('/api/v1/ping', headers=phone.H).get_json()['api'] >= 2


def test_a_ride_a_walk_and_a_session_go_through_one_door_and_keep_their_client_id(phone):
    ride = send(phone, gpx(), sport='Ride', client_id='rec-ride', bike_id='2')
    assert ride.status_code == 201, ride.get_json()
    r = ride.get_json()
    assert (r['status'], r['kind']) == ('created', 'ride')
    walk = send(phone, WALK, sport='Walk', client_id='ah_walk').get_json()
    assert (walk['status'], walk['kind']) == ('created', 'workout')
    lift = phone.post('/api/v1/activities', headers=phone.H, json={**SESSION, 'client_id': 'rec-lift'}).get_json()
    assert (lift['status'], lift['kind']) == ('created', 'workout')
    assert sorted(sql(phone, 'SELECT clientId, sportType, source FROM Activity')) == [
        ('ah_walk', 'Walk', 'ios'), ('rec-lift', 'Strength', 'ios'), ('rec-ride', 'EBikeRide', 'ios')]   # bike 2 is an e-bike
    assert sql(phone, 'SELECT bikeId FROM Activity WHERE id=?', [r['id']]) == [(2,)]

    for again in (send(phone, gpx(), sport='Ride', client_id='rec-ride'), send(phone, WALK, sport='Walk', client_id='ah_walk'),
                  phone.post('/api/v1/activities', headers=phone.H, json={**SESSION, 'client_id': 'rec-lift'})):
        assert again.status_code == 200 and again.get_json()['status'] == 'exists'
    assert sql(phone, 'SELECT COUNT(*) FROM Activity') == [(3,)]
    assert known(phone, 'rec-ride', 'ah_walk', 'rec-lift', 'ah_never') == ['rec-ride', 'ah_walk', 'rec-lift']


def test_without_a_sport_the_files_own_decides(phone):
    assert send(phone, gpx(), client_id='a').get_json()['kind'] == 'ride'
    assert send(phone, WALK, client_id='b').get_json()['kind'] == 'workout'


def test_one_sent_before_client_ids_were_kept_is_found_by_its_old_id_and_gets_its_client_id(phone):
    walk = send(phone, WALK, sport='Walk', client_id='ah_old').get_json()
    lift = phone.post('/api/v1/activities', headers=phone.H, json={**SESSION, 'client_id': 'rec-old'}).get_json()
    sql(phone, 'UPDATE Activity SET clientId=NULL')                                     # as an upload from before 0.7.47
    assert known(phone, 'ah_old', 'rec-old') == ['ah_old', 'rec-old']
    assert send(phone, WALK, sport='Walk', client_id='ah_old').get_json() | {'duplicate': None} == {
        'status': 'exists', 'created': False, 'kind': 'workout', 'id': walk['id'], 'duplicate': None}
    phone.post('/api/v1/activities', headers=phone.H, json={**SESSION, 'client_id': 'rec-old'})
    assert sorted(sql(phone, 'SELECT id, clientId FROM Activity')) == sorted([(walk['id'], 'ah_old'), (lift['id'], 'rec-old')])


def test_a_ride_from_the_older_path_gets_its_client_id_when_it_comes_again(phone):
    old = phone.post('/api/v1/rides', headers=phone.H, content_type='multipart/form-data', data={'file': (BytesIO(gpx()), 'Ride.gpx')}).get_json()
    assert old['status'] == 'imported' and old['imported'] == 1 and old['ride']['id']                # the reply the released apps read
    assert known(phone, 'ah_ride') == []
    again = send(phone, gpx(), sport='Ride', client_id='ah_ride').get_json()
    assert (again['status'], again['id']) == ('exists', old['ride']['id'])
    assert known(phone, 'ah_ride') == ['ah_ride']
    retry = phone.post('/api/v1/rides', headers=phone.H, content_type='multipart/form-data', data={'file': (BytesIO(gpx()), 'Ride.gpx')}).get_json()
    assert (retry['status'], retry['imported'], retry['skipped'], retry['ride']['id']) == ('skipped', 0, 1, old['ride']['id'])


def test_the_older_workouts_path_keeps_its_reply(phone):
    r = phone.post('/api/v1/workouts', headers=phone.H, content_type='multipart/form-data',
                   data={'file': (BytesIO(WALK), 'Walk.gpx'), 'sport': 'Walk', 'client_id': 'w1', 'steps': '1200'})
    assert r.status_code == 201 and r.get_json()['status'] == 'created'
    w = r.get_json()['workout']
    assert (w['sport'], w['steps'], w['source']) == ('Walk', 1200, 'android')                       # an older Android app sends no source
    again = phone.post('/api/v1/workouts', headers=phone.H, content_type='multipart/form-data',
                       data={'file': (BytesIO(WALK), 'Walk.gpx'), 'sport': 'Walk', 'client_id': 'w1'})
    assert again.status_code == 200 and again.get_json()['status'] == 'exists' and again.get_json()['workout']['id'] == w['id']
    assert phone.post('/api/v1/workouts', headers=phone.H, json={}).status_code == 400


def test_one_set_aside_behind_another_recording_is_known_and_stands_as_that_one(phone):
    walk = send(phone, WALK, sport='Walk', client_id='ah_dup').get_json()
    with phone.app_.app_context():
        d = database.get_db()
        w = d.execute('SELECT startDate, startDateLocal, distance, movingTime FROM Activity WHERE id=?', [walk['id']]).fetchone()
        d.execute("INSERT INTO Activity (id, riderId, type, sportType, name, startDate, startDateLocal, distance, movingTime, elapsedTime, "
                  "averageHeartrate, rawData) VALUES ('garmin_5', 1, 'Walk', 'Walk', 'Walk', ?, ?, ?, ?, ?, 100, '{}')",
                  [w['startDate'], w['startDateLocal'], w['distance'], w['movingTime'], w['movingTime']])
        from services import duplicates
        assert duplicates.resolve(d, 'garmin_5')['parked'] == walk['id']                           # the Garmin recording wins
        d.commit()
    assert known(phone, 'ah_dup') == ['ah_dup']
    again = send(phone, WALK, sport='Walk', client_id='ah_dup').get_json()
    assert (again['status'], again['id']) == ('exists', 'garmin_5')


def test_a_deleted_one_is_known_so_a_sync_leaves_it_out_but_sending_it_brings_it_back(phone):
    walk = send(phone, WALK, sport='Walk', client_id='ah_gone').get_json()
    assert phone.delete(f"/api/v1/workouts/{walk['id']}", headers=phone.H).status_code == 200
    assert known(phone, 'ah_gone') == ['ah_gone']
    back = send(phone, WALK, sport='Walk', client_id='ah_gone').get_json()
    assert back['status'] == 'created' and sql(phone, 'SELECT clientId FROM Activity') == [('ah_gone',)]


def test_known_asks_about_a_list_of_ids_only(phone):
    ask = lambda body: phone.post('/api/v1/activities/known', headers=phone.H, json=body)
    assert ask({}).status_code == 400 and ask({'client_ids': 'ah_x'}).status_code == 400
    assert ask({'client_ids': ['x'] * 501}).status_code == 400
    assert ask({'client_ids': [None, '', 5, ' ']}).get_json() == {'known': []}


def test_another_riders_client_id_is_not_this_ones(phone):
    send(phone, WALK, sport='Walk', client_id='ah_mine')
    sql(phone, 'UPDATE Activity SET riderId=2')
    assert known(phone, 'ah_mine') == []


def test_a_session_that_cant_be_kept_is_a_400_saying_why(phone):
    r = phone.post('/api/v1/activities', headers=phone.H, json={'sport': 'Ride', 'date': '2999-01-01', 'duration_s': 60, 'distance_m': 1})
    assert r.status_code == 400 and r.get_json() == {'error': 'that is in the future'}


def one_moment(points=5, at='2026-11-03T07:30:00Z', last=None):
    """Apple Health's route for a workout that recorded none: one stale location, at the same moment, over and over."""
    times = [at] * (points - 1) + [last or at]
    pts = ''.join(f'<trkpt lat="51.5000000" lon="-0.1000000"><ele>10.0</ele><time>{t}</time></trkpt>' for t in times)
    return (f'<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" creator="Headwind iOS" xmlns="http://www.topografix.com/GPX/1/1">'
            f'<trk><name>Workout</name><type>walking</type><trkseg>{pts}</trkseg></trk></gpx>').encode()


def nothing_stored(phone):
    return sql(phone, 'SELECT COUNT(*) FROM Activity') == [(0,)] and sql(phone, 'SELECT COUNT(*) FROM ActivityDuplicate') == [(0,)]


REFUSED = {'error': 'The recording has no distance and no time: nothing was recorded'}


def test_a_track_that_is_one_moment_is_refused_through_every_door_and_nothing_is_stored(phone):
    old = lambda path, cid: phone.post(f'/api/v1/{path}', headers=phone.H, content_type='multipart/form-data',
                                       data={'file': (BytesIO(one_moment()), 'Workout.gpx'), 'client_id': cid, 'source': 'ios'})
    for r in (send(phone, one_moment(), sport='Walk', client_id='ah_w'), send(phone, one_moment(), sport='Ride', client_id='ah_r'),
              send(phone, one_moment(), client_id='ah_any'), old('rides', 'ah_old_r'), old('workouts', 'ah_old_w')):
        assert (r.status_code, r.get_json()) == (422, REFUSED)
    assert nothing_stored(phone)
    assert known(phone, 'ah_w', 'ah_r', 'ah_any', 'ah_old_r', 'ah_old_w') == []


def test_one_point_or_one_moment_written_two_ways_is_refused_too(phone):
    for data in (one_moment(points=1), one_moment(last='2026-11-03T07:30:00.000Z'), one_moment(at='2026-11-03t07:30:00z')):
        r = send(phone, data, sport='Walk', client_id='ah_x')
        assert (r.status_code, r.get_json()) == (422, REFUSED)
    assert nothing_stored(phone)


def test_a_refused_one_can_come_again_as_a_timed_session(phone):
    assert send(phone, one_moment(), sport='Walk', client_id='ah_later').status_code == 422
    r = phone.post('/api/v1/activities', headers=phone.H, json={**SESSION, 'sport': 'Walk', 'distance_m': 3000, 'client_id': 'ah_later'})
    assert r.status_code == 201 and r.get_json()['created']
    assert known(phone, 'ah_later') == ['ah_later']


def test_a_short_real_track_is_still_stored(phone):
    two = lambda kind, hour: gpx(kind, start=datetime(2026, 11, 3, hour, 30, tzinfo=timezone.utc), seconds=2, step=0.0001).replace(
        b':01Z', b':05Z')                                                                           # two points, 5 s and 11 m apart
    assert b'07:30:05Z' in two('walking', 7) and b'07:30:01Z' not in two('walking', 7)
    walk = send(phone, two('walking', 7), sport='Walk', client_id='ah_short')
    assert walk.status_code == 201 and walk.get_json()['created'], walk.get_json()
    ride = phone.post('/api/v1/rides', headers=phone.H, content_type='multipart/form-data',
                      data={'file': (BytesIO(two('cycling', 17)), 'Ride.gpx'), 'client_id': 'rec_short', 'source': 'ios'})
    assert ride.status_code == 200 and ride.get_json()['imported'] == 1, ride.get_json()          # the older path's reply
    assert known(phone, 'ah_short', 'rec_short') == ['ah_short', 'rec_short']
    assert sql(phone, 'SELECT COUNT(*) FROM Activity WHERE elapsedTime > 0') == [(2,)]


def test_the_check_reads_only_plain_gpx_times():
    from services.uploads import _no_time
    assert _no_time(one_moment()) and _no_time(one_moment().replace(b'<trkpt', b'<g:trkpt').replace(b'</trkpt', b'</g:trkpt'))
    assert not _no_time(gpx(seconds=2))
    assert not _no_time(gpx(seconds=1).replace(b'<time>', b'<x>').replace(b'</time>', b'</x>'))     # no times: the parsers say why
    assert not _no_time(one_moment().replace(b'2026-11-03T07:30:00Z', b'yesterday'))              # unreadable: the parsers say why
    assert not _no_time(b'\x0e\x10\x00\x00\x00\x00\x00\x00.FIT' + b'\x00' * 20)                       # a FIT file
