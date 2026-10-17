"""The friend feed offers only this instance's own riders: a synced friend's rides were shared with us, not re-shareable. Throwaway DB."""
import json

import pytest
from flask import Flask

import database

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
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("UPDATE Settings SET feedToken=? WHERE id=1", [TOKEN])
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
