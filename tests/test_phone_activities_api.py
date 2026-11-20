"""The phone API's /activities paths, beside the older /rides/<kind>/<id> ones the released apps still use: the same answers without a kind,
whatever the sport, and the older paths unchanged."""
from io import BytesIO

import database
from services import tz
from tests.test_ios_api import add, jpeg, phone  # noqa: F401  (phone is a fixture)


def test_ping_says_the_activities_paths_are_there(phone):
    assert phone.get('/api/v1/ping', headers=phone.H).get_json()['api'] == 3


def test_the_list_is_the_same_without_a_kind(phone):
    day = tz.today().isoformat()
    add(phone, 'r1', 'Ride', day, dist=20000)
    add(phone, 'w1', 'Walk', day, dist=3000)
    new = phone.get('/api/v1/activities?limit=10', headers=phone.H).get_json()
    old = phone.get('/api/v1/rides?limit=10', headers=phone.H).get_json()
    assert new['total'] == old['total'] == 2
    assert {i['kind'] for i in old['items']} == {'ride', 'workout'}
    assert all('kind' not in i for i in new['items'])
    assert [{k: v for k, v in i.items() if k != 'kind'} for i in old['items']] == new['items']
    assert [i['id'] for i in phone.get('/api/v1/activities?group=foot', headers=phone.H).get_json()['items']] == ['w1']


def test_one_opens_whatever_its_sport(phone):
    day = tz.today().isoformat()
    add(phone, 'r1', 'Ride', day, dist=20000)
    add(phone, 'w1', 'Walk', day, dist=3000)
    for aid in ('r1', 'w1'):
        new = phone.get(f'/api/v1/activities/{aid}', headers=phone.H)
        assert new.status_code == 200 and new.get_json()['id'] == aid and 'kind' not in new.get_json()
    old = phone.get('/api/v1/rides/ride/w1', headers=phone.H).get_json()                 # a stale kind still finds it, and says the right one
    assert old['kind'] == 'workout'
    assert phone.get('/api/v1/activities/nope', headers=phone.H).status_code == 404
    assert phone.get('/api/v1/rides/run/w1', headers=phone.H).status_code == 400


def test_photos_on_the_activities_path(phone):
    add(phone, 'w1', 'Walk', tz.today().isoformat(), dist=3000)
    add(phone, 'sams', 'Walk', tz.today().isoformat(), dist=3000, rider=2)
    up = lambda aid: phone.post(f'/api/v1/activities/{aid}/photos', headers=phone.H, content_type='multipart/form-data',
                                data={'file': (BytesIO(jpeg()), 'IMG_1.jpg')})
    assert up('sams').status_code == 404
    up('w1')
    pids = [p['id'] for p in up('w1').get_json()['photos']]
    assert phone.post('/api/v1/activities/w1/photos/order', headers=phone.H, json={'ids': pids[::-1]}).status_code == 200
    cap = phone.patch(f'/api/v1/activities/w1/photos/{pids[0]}', headers=phone.H, json={'caption': 'Summit'}).get_json()['photos']
    assert [p['id'] for p in cap] == pids[::-1] and cap[1]['caption'] == 'Summit'
    gone = phone.delete(f'/api/v1/activities/w1/photos/{pids[1]}', headers=phone.H)
    assert gone.status_code == 200 and [p['id'] for p in gone.get_json()['photos']] == [pids[0]]
    assert [p['id'] for p in phone.get('/api/v1/rides/workout/w1', headers=phone.H).get_json()['photos']] == [pids[0]]


def test_sport_bike_and_commute_on_the_activities_path(phone):
    add(phone, 'r1', 'Ride', tz.today().isoformat(), dist=20000)
    add(phone, 'w1', 'Walk', tz.today().isoformat(), dist=3000)
    assert phone.post('/api/v1/activities/r1/commute', headers=phone.H, json={'commute': True}).get_json() == {'id': 'r1', 'commute': True}
    assert phone.post('/api/v1/activities/r1/bike', headers=phone.H, json={'bike_id': None}).get_json() == {'id': 'r1', 'bike_id': None}
    assert phone.post('/api/v1/activities/w1/bike', headers=phone.H, json={'bike_id': None}).status_code == 400   # only rides have one
    assert phone.post('/api/v1/activities/w1/sport', headers=phone.H, json={'sport': 'Run'}).status_code == 200
    assert phone.get('/api/v1/activities/w1', headers=phone.H).get_json()['sport'] == 'Run'
    assert phone.post('/api/v1/activities/sams/commute', headers=phone.H, json={'commute': True}).status_code == 404


def test_a_duplicate_is_resolved_on_either_path(phone):
    add(phone, 'r1', 'Ride', tz.today().isoformat(), dist=20000)
    with phone.app_.app_context():
        d = database.get_db()
        for i in (1, 2):
            d.execute("INSERT INTO ActivityDuplicate (id, primaryId, riderId, status, source, reason, rowJson) VALUES (?, 'r1', 1, 'parked', "
                      "'garmin', 'same start', '{}')", [i])
        d.commit()
    assert phone.post('/api/v1/activities/r1/duplicate/1/keep', headers=phone.H).get_json() == {'ok': True, 'id': 'r1'}
    assert phone.post('/api/v1/rides/ride/r1/duplicate/2/keep', headers=phone.H).get_json() == {'ok': True, 'ride_id': 'r1'}


def test_deleting_on_the_activities_path(phone):
    add(phone, 'r1', 'Ride', tz.today().isoformat(), dist=20000)
    add(phone, 'w1', 'Walk', tz.today().isoformat(), dist=3000)
    add(phone, 'sams', 'Ride', tz.today().isoformat(), dist=20000, rider=2)
    assert phone.delete('/api/v1/activities/sams', headers=phone.H).status_code == 404
    for aid in ('r1', 'w1'):
        assert phone.delete(f'/api/v1/activities/{aid}', headers=phone.H).get_json() == {'deleted': True}
        assert phone.get(f'/api/v1/activities/{aid}', headers=phone.H).status_code == 404
    assert phone.delete('/api/v1/activities/r1', headers=phone.H).status_code == 404


def test_perform_names_the_activity_and_keeps_the_older_keys(phone):
    add(phone, 'r1', 'Ride', tz.today().isoformat(), dist=20000)
    climb = phone.get('/api/v1/perform', headers=phone.H).get_json()['biggest_climbs'][0]
    assert climb['activityId'] == climb['rideId'] == 'r1' and climb['activityName'] == climb['rideName'] == 'r1'
