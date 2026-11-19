"""Each feed token shares only the riders ticked for it: a new token just the default rider unless more are ticked, a rider
added later none, and tokens from before the choice every rider they shared then. Throwaway DB."""
import json

import pytest

import database
from services import feed_tokens
from tests.test_feed_tokens import _app, _get, _lines


@pytest.fixture
def app(tmp_path):
    app = _app(tmp_path)
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (2, 'Kim', 0)")             # a second rider living here
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (3, 'Alice', 0)")           # created by syncing a friend
        d.execute("INSERT INTO Friend (name, url, token, riderId) VALUES ('Alice', 'https://alice.example', 't', 3)")
        d.execute("INSERT INTO Activity (id, name, riderId, startDateLocal, streams) VALUES ('kim1', 'run', 2, '2026-10-02T08:00:00', '{}')")
        d.execute("INSERT INTO Activity (id, name, riderId, startDateLocal, streams) VALUES ('f1_a1', 'ride', 3, '2026-10-02T08:00:00', '{}')")
        d.commit()
    return app


def _make(app, riders=None, **form):
    data = {'name': 'Sam', 'shareRides': '1', 'shareSegments': '1', 'shareFoods': '1', **form}
    if riders is not None:
        data.update(ridersChosen='1', rider=[str(r) for r in riders])
    return app.test_client().post('/friends/tokens', data=data).get_json()


def _names(app, token):
    return [r['name'] for r in _get(app, '/api/riders', token).get_json()]


def _feed(app, token, query=''):
    lines = list(map(json.loads, _get(app, '/api/feed' + query, token).get_data(as_text=True).splitlines()))
    return {k: [o for o in lines if o['type'] == k] for k in ('meta', 'ride', 'manifest', 'end')}


def test_a_new_token_shares_the_default_rider_unless_others_are_ticked(app):
    plain = _make(app)['token']
    assert _names(app, plain) == ['Rob']
    both = _make(app, riders=[1, 2])['token']
    assert _names(app, both) == ['Rob', 'Kim']
    assert [o['id'] for o in _feed(app, both, '?rider=kim')['ride']] == ['kim1']


def test_a_rider_not_shared_is_missing_and_their_feed_is_empty(app):
    t = _make(app, riders=[1])['token']
    assert 'Kim' not in _names(app, t)
    got = _feed(app, t, '?rider=Kim')
    assert got['ride'] == [] and got['meta'][0]['name'] is None and got['end']
    got = _feed(app, t, '?rider=Kim&manifest=1')
    assert got['manifest'] == [{'type': 'manifest', 'rides': []}]          # a friend who had Kim's rides lets them go


def test_the_default_rider_can_be_left_out(app):
    t = _make(app, riders=[2])['token']
    assert _names(app, t) == ['Kim']
    got = _feed(app, t)
    assert got['ride'] == [] and got['meta'][0]['name'] is None


def test_none_ticked_shares_no_rider(app):
    t = _make(app, riders=[], shareRides='1')['token']
    assert _names(app, t) == []
    assert _feed(app, t)['ride'] == []
    assert _lines(_get(app, '/api/feed', t), 'segment')                      # segments are still shared


def test_a_friends_rider_is_never_shared_even_if_asked_for(app):
    t = _make(app, riders=[1, 2, 3])['token']
    assert _names(app, t) == ['Rob', 'Kim']
    assert _feed(app, t, '?rider=Alice')['ride'] == []
    with app.app_context():
        assert [r['riders'] for r in feed_tokens.tokens()] == [[1, 2]]


def test_editing_the_riders(app):
    made = _make(app, riders=[1])
    app.test_client().post(f"/friends/tokens/{made['id']}", data={'shareRides': '1', 'ridersChosen': '1', 'rider': ['2']})
    assert _names(app, made['token']) == ['Kim']
    app.test_client().post(f"/friends/tokens/{made['id']}", data={'shareRides': '1', 'ridersChosen': '1'})
    assert _names(app, made['token']) == []


def test_a_rider_added_later_isnt_shared(app):
    t = _make(app, riders=[1, 2])['token']
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (4, 'Jo', 0)")
        d.commit()
    assert _names(app, t) == ['Rob', 'Kim']


def test_tokens_from_before_keep_every_rider(app):
    t = _make(app, riders=[1])['token']
    with app.app_context():
        d = database.get_db()
        d.execute("UPDATE FeedToken SET revokedAt=datetime('now') WHERE id=1")
        old = feed_tokens.PREFIX + 'from-before'
        d.execute("INSERT INTO FeedToken (name, tokenHash) VALUES ('Old', ?)", [feed_tokens._hash(old)])
        d.execute('DROP TABLE FeedTokenRider')                  # as an install from before riders were chosen
        d.commit()
        database.migrate_db()
    assert _names(app, old) == ['Rob', 'Kim']                   # every rider of ours, not the friend's
    assert _get(app, '/api/riders', t).status_code == 403


def test_the_app_can_choose_riders(app):
    from routes import api_v1
    app.register_blueprint(api_v1.bp)
    c = app.test_client()
    made = c.post('/api/v1/friends/tokens', json={'name': 'Sam', 'riders': [2], 'server_url': 'https://h.example'}).get_json()
    assert _names(app, made['token']) == ['Kim']
    made = c.post('/api/v1/friends/tokens', json={'name': 'Sam', 'server_url': 'https://h.example'}).get_json()
    assert _names(app, made['token']) == ['Rob']


def test_deleting_a_rider_takes_them_off_every_token(app):
    _make(app, riders=[1, 2])
    with app.app_context():
        feed_tokens.forget_rider(database.get_db(), 2)
        assert [r['riders'] for r in feed_tokens.tokens()] == [[1]]
