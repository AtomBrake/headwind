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
