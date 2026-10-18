"""The friend feed offers only this instance's own riders: a synced friend's rides were shared with us, not re-shareable. Throwaway DB."""
import json

import pytest
from flask import Flask

import database
from services import feed_tokens

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
        for aid, rid in (('own1', 1), ('sam1', 2), ('f1_alice1', 3)):
            d.execute("INSERT INTO Activity (id, name, riderId, startDateLocal, streams) VALUES (?, 'ride', ?, '2026-10-01T08:00:00', '{}')", [aid, rid])
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


FEED_ENDPOINTS = ['/api/riders', '/api/feed', '/api/foods-feed', '/api/food-image/0000.jpg']


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
