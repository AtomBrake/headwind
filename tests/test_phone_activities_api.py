"""The phone API's /activities paths: the same answers whatever the sport, with no kind. The older /rides and /workouts paths, and the
/rides/<kind>/<id> ones under them, are gone and answer 404."""
from io import BytesIO

import database
from services import tz
from tests.test_ios_api import add, jpeg, phone  # noqa: F401  (phone is a fixture)


def test_ping_says_the_activities_paths_are_there(phone):
    assert phone.get('/api/v1/ping', headers=phone.H).get_json()['api'] == 3


def test_the_list_has_every_sport_and_no_kind(phone):
    day = tz.today().isoformat()
    add(phone, 'r1', 'Ride', day, dist=20000)
    add(phone, 'w1', 'Walk', day, dist=3000)
    new = phone.get('/api/v1/activities?limit=10', headers=phone.H).get_json()
    assert new['total'] == 2 and {i['id'] for i in new['items']} == {'r1', 'w1'}
    assert all('kind' not in i for i in new['items'])
    assert [i['id'] for i in phone.get('/api/v1/activities?group=foot', headers=phone.H).get_json()['items']] == ['w1']


def test_one_opens_whatever_its_sport(phone):
    day = tz.today().isoformat()
    add(phone, 'r1', 'Ride', day, dist=20000)
    add(phone, 'w1', 'Walk', day, dist=3000)
    for aid in ('r1', 'w1'):
        new = phone.get(f'/api/v1/activities/{aid}', headers=phone.H)
        assert new.status_code == 200 and new.get_json()['id'] == aid and 'kind' not in new.get_json()
    assert phone.get('/api/v1/activities/nope', headers=phone.H).status_code == 404


def test_the_older_paths_are_gone(phone):
    """Upstream's Android app's paths: every one answers 404 now, with a good token, for an activity that is there."""
    from tests.test_uploads import gpx
    day = tz.today().isoformat()
    add(phone, 'r1', 'Ride', day, dist=20000)
    add(phone, 'w1', 'Walk', day, dist=3000)
    upload = lambda: {'file': (BytesIO(gpx()), 'Ride.gpx')}
    gone = [
        phone.post('/api/v1/rides', headers=phone.H, content_type='multipart/form-data', data=upload()),
        phone.post('/api/v1/workouts', headers=phone.H, content_type='multipart/form-data', data=upload()),
        phone.get('/api/v1/rides', headers=phone.H),
        phone.get('/api/v1/rides?limit=10', headers=phone.H),
        phone.get('/api/v1/workouts', headers=phone.H),
        phone.delete('/api/v1/workouts/w1', headers=phone.H),
    ]
    for kind, aid in (('ride', 'r1'), ('workout', 'w1')):
        base = f'/api/v1/rides/{kind}/{aid}'
        gone += [
            phone.get(base, headers=phone.H),
            phone.delete(base, headers=phone.H),
            phone.post(f'{base}/photos', headers=phone.H, content_type='multipart/form-data', data={'file': (BytesIO(jpeg()), 'IMG_1.jpg')}),
            phone.post(f'{base}/photos/order', headers=phone.H, json={'ids': []}),
            phone.patch(f'{base}/photos/1', headers=phone.H, json={'caption': 'x'}),
            phone.delete(f'{base}/photos/1', headers=phone.H),
            phone.post(f'{base}/sport', headers=phone.H, json={'sport': 'Run'}),
            phone.post(f'{base}/bike', headers=phone.H, json={'bike_id': None}),
            phone.post(f'{base}/commute', headers=phone.H, json={'commute': True}),
        ]
    gone.append(phone.post('/api/v1/rides/ride/r1/duplicate/1/keep', headers=phone.H))
    assert [r.status_code for r in gone] == [404] * len(gone)
    # ...and nothing they were sent changed anything
    assert {i['id'] for i in phone.get('/api/v1/activities', headers=phone.H).get_json()['items']} == {'r1', 'w1'}
    w1 = phone.get('/api/v1/activities/w1', headers=phone.H).get_json()
    assert w1['sport'] == 'Walk' and w1['commute'] is False and w1['photos'] == []


def test_upload_replies_have_no_kind(phone):
    from tests.test_uploads import gpx
    r = phone.post('/api/v1/activities', headers=phone.H, content_type='multipart/form-data',
                   data={'file': (BytesIO(gpx()), 'Ride.gpx'), 'sport': 'Ride', 'client_id': 'k1'})
    assert r.status_code == 201 and set(r.get_json()) == {'status', 'created', 'id', 'duplicate'}


def test_overview_sends_the_groups_and_not_the_ride_totals(phone):
    add(phone, 'r1', 'Ride', tz.today().isoformat(), dist=20000)
    o = phone.get('/api/v1/overview', headers=phone.H).get_json()
    assert set(o) == {'rider', 'recovery', 'groups', 'weekly_all', 'periods'}
    assert [g['key'] for g in o['groups']] == ['ride'] and o['groups'][0]['totals']['all']['distance_m'] == 20000


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
    assert [p['id'] for p in phone.get('/api/v1/activities/w1', headers=phone.H).get_json()['photos']] == [pids[0]]


def test_sport_bike_and_commute_on_the_activities_path(phone):
    add(phone, 'r1', 'Ride', tz.today().isoformat(), dist=20000)
    add(phone, 'w1', 'Walk', tz.today().isoformat(), dist=3000)
    assert phone.post('/api/v1/activities/r1/commute', headers=phone.H, json={'commute': True}).get_json() == {'id': 'r1', 'commute': True}
    assert phone.post('/api/v1/activities/r1/bike', headers=phone.H, json={'bike_id': None}).get_json() == {'id': 'r1', 'bike_id': None}
    assert phone.post('/api/v1/activities/w1/bike', headers=phone.H, json={'bike_id': None}).status_code == 400   # only rides have one
    assert phone.post('/api/v1/activities/w1/sport', headers=phone.H, json={'sport': 'Run'}).status_code == 200
    assert phone.get('/api/v1/activities/w1', headers=phone.H).get_json()['sport'] == 'Run'
    assert phone.post('/api/v1/activities/sams/commute', headers=phone.H, json={'commute': True}).status_code == 404


def test_a_duplicate_is_resolved(phone):
    add(phone, 'r1', 'Ride', tz.today().isoformat(), dist=20000)
    with phone.app_.app_context():
        d = database.get_db()
        for i in (1, 2):
            d.execute("INSERT INTO ActivityDuplicate (id, primaryId, riderId, status, source, reason, rowJson) VALUES (?, 'r1', 1, 'parked', "
                      "'garmin', 'same start', '{}')", [i])
        d.commit()
    assert phone.post('/api/v1/activities/r1/duplicate/1/keep', headers=phone.H).get_json() == {'ok': True, 'id': 'r1'}
    assert phone.post('/api/v1/activities/r1/duplicate/2/discard', headers=phone.H).get_json() == {'ok': True, 'id': 'r1'}


def test_deleting_on_the_activities_path(phone):
    add(phone, 'r1', 'Ride', tz.today().isoformat(), dist=20000)
    add(phone, 'w1', 'Walk', tz.today().isoformat(), dist=3000)
    add(phone, 'sams', 'Ride', tz.today().isoformat(), dist=20000, rider=2)
    assert phone.delete('/api/v1/activities/sams', headers=phone.H).status_code == 404
    for aid in ('r1', 'w1'):
        assert phone.delete(f'/api/v1/activities/{aid}', headers=phone.H).get_json() == {'deleted': True}
        assert phone.get(f'/api/v1/activities/{aid}', headers=phone.H).status_code == 404
    assert phone.delete('/api/v1/activities/r1', headers=phone.H).status_code == 404


def test_perform_names_the_activity(phone):
    add(phone, 'r1', 'Ride', tz.today().isoformat(), dist=20000)
    climb = phone.get('/api/v1/perform', headers=phone.H).get_json()['biggest_climbs'][0]
    assert climb == {'activityId': 'r1', 'activityName': 'r1', 'elevM': climb['elevM'], 'date': climb['date']}
