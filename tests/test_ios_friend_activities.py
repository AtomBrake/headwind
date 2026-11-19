"""Friends' activities in the app's Activities list: GET /api/v1/rides?rider= lists a friend's (or everyone's) beside your own, they open in
detail, and every change from the phone is refused. Another local rider's never shows."""
from io import BytesIO

import database
from tests.test_ios_api import add, jpeg, phone  # noqa: F401  (phone is a fixture)


def befriend(phone):
    """Rider 2 (Sam) is a friend synced to here; rider 3 (Alex) lives here but isn't the phone's."""
    with phone.app_.app_context():
        d = database.get_db()
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (3, 'Alex', 0)")
        d.execute("INSERT INTO Friend (id, name, url, token, riderId, lastSynced) VALUES (1, 'Sam P', 'https://sam.example', 't', 2, '2026-10-20 08:00:00')")
        d.execute("INSERT INTO Friend (id, name, url, token) VALUES (2, 'Not synced yet', 'https://new.example', 't')")
        d.commit()
    add(phone, 'mine', 'Ride', '2026-10-18', dist=20000)
    add(phone, 'sams', 'Run', '2026-10-19', dist=5000, rider=2)
    add(phone, 'alexs', 'Ride', '2026-10-20', dist=30000, rider=3)


def listed(phone, **q):
    r = phone.get('/api/v1/rides', headers=phone.H, query_string=q)
    return r.status_code, r.get_json()


def test_the_list_is_your_own_unless_you_ask(phone):
    befriend(phone)
    code, got = listed(phone)
    assert code == 200 and [i['id'] for i in got['items']] == ['mine']
    assert got['items'][0]['own'] is True and got['items'][0]['rider'] == 'Tom'


def test_a_friends_activities_and_everyones(phone):
    befriend(phone)
    code, got = listed(phone, rider=2)
    assert code == 200 and [(i['id'], i['rider'], i['own']) for i in got['items']] == [('sams', 'Sam P', False)]
    code, got = listed(phone, rider='all')
    assert got['total'] == 2 and [i['id'] for i in got['items']] == ['sams', 'mine'], 'newest first, and never Alex'
    assert listed(phone, rider='all', group='foot')[1]['items'][0]['id'] == 'sams', "the group filter knows a friend's sports"


def test_another_local_riders_isnt_the_phones(phone):
    befriend(phone)
    for who in (3, 99, 'Sam'):
        assert listed(phone, rider=who)[0] == 404, who
    assert listed(phone, rider=1)[0] == 404, 'your own rider is the empty choice, not an id'
    assert phone.get('/api/v1/rides/ride/alexs', headers=phone.H).status_code == 404


def test_friends_lists_the_synced_ones(phone):
    befriend(phone)
    got = phone.get('/api/v1/friends', headers=phone.H).get_json()
    assert got == {'friends': [{'rider_id': 2, 'name': 'Sam P', 'last_synced': '2026-10-20 08:00:00'}]}
    assert phone.get('/api/v1/friends').status_code == 401


def test_a_friends_activity_opens_and_says_whose(phone):
    befriend(phone)
    got = phone.get('/api/v1/rides/workout/sams', headers=phone.H).get_json()
    assert got['id'] == 'sams' and got['own'] is False and got['rider'] == 'Sam P' and got['synced']
    mine = phone.get('/api/v1/rides/ride/mine', headers=phone.H).get_json()
    assert mine['own'] is True and mine['rider'] == 'Tom' and mine['synced'] is None


def test_a_friends_activity_cant_be_changed_from_the_phone(phone):
    befriend(phone)
    H = phone.H
    assert phone.post('/api/v1/rides/workout/sams/sport', headers=H, json={'sport': 'Walk'}).status_code >= 400
    assert phone.post('/api/v1/rides/workout/sams/bike', headers=H, json={'bike_id': None}).status_code >= 400
    assert phone.post('/api/v1/rides/workout/sams/commute', headers=H, json={'commute': True}).status_code >= 400
    assert phone.post('/api/v1/rides/workout/sams/photos', headers=H, content_type='multipart/form-data',
                      data={'file': (BytesIO(jpeg()), 'p.jpg')}).status_code == 404
    assert phone.delete('/api/v1/rides/workout/sams', headers=H).status_code == 404
    with phone.app_.app_context():
        row = database.get_db().execute('SELECT sportType, commute FROM Activity WHERE id=?', ['sams']).fetchone()
    assert row['sportType'] == 'Run' and not row['commute']
