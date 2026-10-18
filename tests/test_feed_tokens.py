"""One feed token per friend: each is revoked on its own and shares only what it was given (rides, segments, foods, a date
window). The old shared token carries over as one token that shares everything. Throwaway DB."""
import json

import pytest
from flask import Flask

import database
from services import feed_tokens


def _app(tmp_path, legacy=None):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    app.secret_key = 'test'
    app.teardown_appcontext(database.close_db)
    from routes.friends import bp
    app.register_blueprint(bp)
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Rob', 1)")
        for aid, day in (('r_sep', '2026-09-15'), ('r_oct1', '2026-10-01'), ('r_oct9', '2026-10-09')):
            d.execute("INSERT INTO Activity (id, name, riderId, startDateLocal, streams) VALUES (?, 'ride', 1, ?, '{}')", [aid, day + 'T08:00:00'])
        d.execute("INSERT INTO Segment (name, startLat, startLng, endLat, endLng) VALUES ('Hill', 51.0, -1.0, 51.01, -1.01)")
        d.execute("INSERT INTO CustomFood (riderId, name, calories) VALUES (1, 'Flapjack', 400)")
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        if legacy:
            d.execute("UPDATE Settings SET feedToken=? WHERE id=1", [legacy])
        d.commit()
        if legacy:
            database.migrate_db()           # the upgrade: the shared token becomes a FeedToken row
    return app


@pytest.fixture
def app(tmp_path):
    return _app(tmp_path)


def _make(app, name='Sam', **scope):
    form = {'shareRides': '1', 'shareSegments': '1', 'shareFoods': '1'}
    form.update({k: v for k, v in scope.items() if v is not None})
    for k in [k for k, v in scope.items() if v is None]:
        form.pop(k, None)
    resp = app.test_client().post('/friends/tokens', data={'name': name, **form})
    assert resp.status_code == 200
    return resp.get_json()


def _lines(resp, kind):
    return [o for o in map(json.loads, resp.get_data(as_text=True).splitlines()) if o['type'] == kind]


def _get(app, path, token):
    return app.test_client().get(path, headers={'X-Feed-Token': token})


def test_new_token_works_and_only_its_hash_is_stored(app):
    made = _make(app)
    assert made['token'].startswith('hwf_')
    assert [o['id'] for o in _lines(_get(app, '/api/feed', made['token']), 'ride')] == ['r_oct9', 'r_oct1', 'r_sep']
    with app.app_context():
        row = database.query_db('SELECT * FROM FeedToken WHERE id=?', [made['id']], one=True)
        assert made['token'] not in dict(row).values()
        assert row['lastUsedAt']


def test_revoking_one_friend_leaves_the_other(app):
    sam, alex = _make(app, 'Sam'), _make(app, 'Alex')
    app.test_client().post(f"/friends/tokens/{sam['id']}/revoke")
    for path in ('/api/feed', '/api/riders', '/api/foods-feed'):
        assert _get(app, path, sam['token']).status_code == 403
        assert _get(app, path, alex['token']).status_code == 200


def test_date_window_is_inclusive(app):
    t = _make(app, sinceDate='2026-10-01', untilDate='2026-10-08')['token']
    assert [o['id'] for o in _lines(_get(app, '/api/feed', t), 'ride')] == ['r_oct1']
    # combined with the friend's own incremental ?since=
    assert _lines(_get(app, '/api/feed?since=2026-10-02', t), 'ride') == []


def test_reversed_dates_are_swapped(app):
    t = _make(app, sinceDate='2026-10-08', untilDate='2026-10-01')['token']
    assert [o['id'] for o in _lines(_get(app, '/api/feed', t), 'ride')] == ['r_oct1']


def test_segments_only(app):
    t = _make(app, shareRides=None, shareFoods=None)['token']
    resp = _get(app, '/api/feed', t)
    assert _lines(resp, 'meta') and _lines(resp, 'segment') and not _lines(resp, 'ride')
    assert _get(app, '/api/riders', t).get_json() == []


def test_rides_without_segments(app):
    t = _make(app, shareSegments=None)['token']
    resp = _get(app, '/api/feed', t)
    assert not _lines(resp, 'segment') and len(_lines(resp, 'ride')) == 3


def test_foods_off_sends_a_complete_empty_feed(app):
    # complete, so the friend's instance replaces (clears) its copy of our foods instead of keeping a stale one
    t = _make(app, shareFoods=None)['token']
    resp = _get(app, '/api/foods-feed', t)
    assert resp.status_code == 200
    assert _lines(resp, 'food') == [] and _lines(resp, 'end') == [{'type': 'end', 'count': 0}]
    assert _get(app, '/api/food-image/0000.jpg', t).status_code == 403
    on = _make(app, 'Alex')['token']
    assert [f['name'] for f in _lines(_get(app, '/api/foods-feed', on), 'food')] == ['Flapjack']


def test_editing_a_token_changes_what_it_shares(app):
    made = _make(app)
    app.test_client().post(f"/friends/tokens/{made['id']}", data={'shareSegments': '1'})
    resp = _get(app, '/api/feed', made['token'])
    assert _lines(resp, 'segment') and not _lines(resp, 'ride')


def test_old_shared_token_carries_over(tmp_path):
    app = _app(tmp_path, legacy='old-shared-token')
    assert len(_lines(_get(app, '/api/feed', 'old-shared-token'), 'ride')) == 3
    with app.app_context():
        assert database.query_db('SELECT feedToken FROM Settings WHERE id=1', one=True)[0] is None
        rows = database.query_db('SELECT name FROM FeedToken')
        assert [r['name'] for r in rows] == [feed_tokens.LEGACY_NAME]
        database.migrate_db()                                   # a later start-up doesn't add it again
        assert database.query_db('SELECT COUNT(*) FROM FeedToken', one=True)[0] == 1


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def test_friends_page_after_upgrade(tmp_path, monkeypatch):
    """Full app: the old token shows as one row, a new token can be made from the page, and neither is printed on it."""
    import app as app_module
    import config
    from services import credentials
    path = str(tmp_path / 't.db')
    pre = Flask('pre')
    pre.config['DATABASE'] = path
    with pre.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("UPDATE Settings SET feedToken='old-shared-token' WHERE id=1")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Rob', 1)")
        d.commit()
    monkeypatch.setattr(config.Config, 'DATABASE', path)
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    made = c.post('/friends/tokens', data={'name': 'Sam', 'shareRides': '1', 'sinceDate': '2026-01-01'}).get_json()
    html = c.get('/friends').get_data(as_text=True)
    assert feed_tokens.LEGACY_NAME in html and 'Sam' in html and '2026-01-01 – now' in html
    assert 'old-shared-token' not in html and made['token'] not in html
    assert c.get('/api/riders', headers={'X-Feed-Token': 'old-shared-token'}).status_code == 200


def test_a_friends_new_token_can_be_swapped_in(app):
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT INTO Friend (id, name, url, token) VALUES (7, 'Sam', 'https://sam.example', 'old')")
        d.commit()
    c = app.test_client()
    c.post('/friends/7/token', data={'token': ''})                  # cancelled prompt: nothing changes
    c.post('/friends/7/token', data={'token': '  hwf_new  '})
    with app.app_context():
        assert database.query_db('SELECT token FROM Friend WHERE id=7', one=True)[0] == 'hwf_new'
