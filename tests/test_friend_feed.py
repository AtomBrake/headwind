"""The friend feed offers only this instance's own riders: a synced friend's rides were shared with us, not re-shareable. Throwaway DB."""
import json

import pytest
from flask import Flask

import database
from services import feed_tokens
from services import streams as _streams

TOKEN = 'feed-token-abc'


@pytest.fixture
def client(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    app.teardown_appcontext(database.close_db)
    from routes.friends import bp
    app.register_blueprint(bp)
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT INTO FeedToken (name, tokenHash) VALUES ('Friend', ?)", [feed_tokens._hash(TOKEN)])
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Rob', 1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (2, 'Sam', 0)")       # a second rider living here
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (3, 'Alice', 0)")     # created by syncing a friend
        d.execute("INSERT INTO Friend (name, url, token, riderId) VALUES ('Alice', 'https://alice.example', 't', 3)")
        d.execute('INSERT INTO FeedTokenRider (tokenId, riderId) SELECT 1, id FROM Rider')     # even ticked, Alice isn't ours to share
        for aid, rid in (('own1', 1), ('sam1', 2), ('f1_alice1', 3)):
            d.execute("INSERT INTO Activity (id, name, riderId, startDateLocal) VALUES (?, 'ride', ?, '2026-10-01T08:00:00')", [aid, rid])
            _streams.save(d, aid, '{}')
        d.commit()
    return app.test_client()


def _rides(resp):
    return [o['id'] for o in map(json.loads, resp.get_data(as_text=True).splitlines()) if o['type'] == 'ride']


def test_rider_list_leaves_out_synced_friends(client):
    names = [r['name'] for r in client.get('/api/riders', headers={'X-Feed-Token': TOKEN}).get_json()]
    assert names == ['Rob', 'Sam']


def test_feed_serves_own_riders(client):
    assert _rides(client.get('/api/feed', headers={'X-Feed-Token': TOKEN})) == ['own1']
    assert _rides(client.get('/api/feed?rider=sam', headers={'X-Feed-Token': TOKEN})) == ['sam1']


def test_feed_never_reshares_a_friends_rides(client):
    resp = client.get('/api/feed?rider=Alice', headers={'X-Feed-Token': TOKEN})
    assert resp.status_code == 200
    assert _rides(resp) == []


def _lines(resp, kind):
    return [o for o in map(json.loads, resp.get_data(as_text=True).splitlines()) if o['type'] == kind]


def _dated(client, aid, utc, local):
    with client.application.app_context():
        d = database.get_db()
        d.execute("INSERT INTO Activity (id, name, sportType, riderId, startDate, startDateLocal, distance, movingTime, elapsedTime, rawData, updatedAt) "
                  "VALUES (?, 'ride', 'Ride', 1, ?, ?, 20000, 3600, 3600, '{}', '2026-10-01 09:00:00')", [aid, utc, local])
        _streams.save(d, aid, '{}')
        d.commit()


@pytest.fixture
def future(client):
    """Rob's 2106 ride (a device clock reset to 1970, wrapped round), and two that are only ahead of the clock here: one recorded in New Zealand,
    its local time tomorrow, and one saved with no zone, 14 hours on."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    at = lambda h: (now + timedelta(hours=h)).strftime('%Y-%m-%dT%H:%M:%S')
    _dated(client, 'avinox', '2106-02-08T23:46:37+00:00', '2106-02-08T23:46:37')
    _dated(client, 'kiwi', at(-1) + 'Z', at(12))
    _dated(client, 'naive', at(14), at(14))
    return client


def test_a_start_that_hasnt_happened_is_left_out_of_the_feed(future):
    H = {'X-Feed-Token': TOKEN}
    assert sorted(_rides(future.get('/api/feed', headers=H))) == ['kiwi', 'naive', 'own1'], 'only the impossible one is held back'
    manifest = _lines(future.get('/api/feed?manifest=1', headers=H), 'manifest')[0]['rides']
    assert sorted(r[0] for r in manifest) == ['kiwi', 'naive', 'own1'], 'so a friend who already has it deletes it'
    assert _rides(future.get('/api/feed?ids=avinox,own1', headers=H)) == ['own1'], 'nor sent when asked for by id'
    assert 'avinox' not in _rides(future.get('/api/feed?since=2026-01-01', headers=H))


def test_dismissing_the_flag_doesnt_share_it(future):
    from services import sanity
    with future.application.app_context():
        d = database.get_db()
        sanity.flag(d, 'avinox')
        sanity.dismiss(d, 'avinox')
        d.commit()
    assert 'avinox' not in _rides(future.get('/api/feed', headers={'X-Feed-Token': TOKEN}))


def test_once_its_date_is_fixed_it_goes_out_as_new(future):
    from services import sanity
    with future.application.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("UPDATE Activity SET startLat=51.5, startLng=-0.12 WHERE id='avinox'")
        assert sanity.set_start(d, 'avinox', '2026-10-02T08:00') is None
        d.commit()
    H = {'X-Feed-Token': TOKEN}
    manifest = dict(map(tuple, _lines(future.get('/api/feed?manifest=1', headers=H), 'manifest')[0]['rides']))
    assert 'avinox' in manifest and manifest['avinox'] > '2026-10-01 09:00:00', 'its updatedAt is new, so a friend fetches it'
    ride = next(r for r in _lines(future.get('/api/feed?ids=avinox', headers=H), 'ride'))
    assert ride['startDateLocal'] == '2026-10-02T08:00:00'


FEED_ENDPOINTS =['/api/riders', '/api/feed', '/api/foods-feed', '/api/food-image/0000.jpg']


@pytest.mark.parametrize('path', FEED_ENDPOINTS)
def test_wrong_or_missing_token_is_refused(client, path):
    assert client.get(path).status_code == 403
    assert client.get(path, headers={'X-Feed-Token': 'wrong'}).status_code == 403
    assert client.get(path, headers={'X-Feed-Token': TOKEN + 'x'}).status_code == 403
    assert client.get(path, headers={'X-Feed-Token': 'café'}).status_code == 403     # non-ASCII must not 500


@pytest.mark.parametrize('path', FEED_ENDPOINTS)
def test_token_in_query_string_is_not_accepted(client, path):
    # it would land in proxy access logs; friend instances send the header
    assert client.get(path + '?token=' + TOKEN).status_code == 403


def test_empty_token_never_matches(client):
    assert client.get('/api/feed', headers={'X-Feed-Token': ''}).status_code == 403


def test_second_sync_of_a_friend_waits_its_turn(monkeypatch):
    """Two syncs of one friend at once only fight over SQLite's write lock (and lock out everything else), so the second
    is refused while the first runs, and allowed again once it's done."""
    import threading
    from routes import friends
    started, release = threading.Event(), threading.Event()

    def slow(fid):
        started.set()
        release.wait(5)
        return 3, None
    monkeypatch.setattr(friends, '_do_sync_once', slow)
    first = []
    t = threading.Thread(target=lambda: first.append(friends._do_sync(7)))
    t.start()
    assert started.wait(5)
    assert friends._do_sync(7) == (0, 'Already syncing')
    release.set()
    t.join(5)
    assert first == [(3, None)]
    monkeypatch.setattr(friends, '_do_sync_once', lambda fid: (1, None))
    assert friends._do_sync(7) == (1, None)
