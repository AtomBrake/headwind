"""Goals and friend challenges (services/goals.py). Goals: progress from the activities as they are, by kind of sport, against an even pace.
Challenges: started on one instance, carried to a friend's on the feed as an invitation, joined there, and the friend shows up in the race back on
the first; leaving or deleting reaches the other side on its next complete sync. Throwaway DBs."""
import io
import json
from datetime import date

import pytest
from flask import Flask

import database
from routes import friends
from services import feed_tokens, goals


def make_app(path, rider, other, token_in, token_out, url):
    """An instance whose default rider is `rider`, who follows `other` (reading their feed with token_out) and shares with them (token_in)."""
    app = Flask(__name__)
    app.config['DATABASE'] = str(path)
    app.teardown_appcontext(database.close_db)
    app.register_blueprint(friends.bp)
    with app.app_context():
        database.migrate_db()
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, ?, 1)", [rider])
        d.execute("INSERT INTO FeedToken (name, tokenHash) VALUES (?, ?)", [other, feed_tokens._hash(token_in)])
        d.execute("INSERT INTO Friend (id, name, url, token) VALUES (1, ?, ?, ?)", [other, url, token_out])
        d.commit()
    return app


def ride(db, aid, day, dist=10000, climb=100, sport='Ride', secs=1800, rider=1):
    db.execute("INSERT INTO Activity (id, name, sportType, startDateLocal, distance, movingTime, totalElevationGain, riderId, rawData) "
               "VALUES (?,?,?,?,?,?,?,?,'{}')", [aid, aid, sport, f'{day}T08:00:00', dist, secs, climb, rider])
    db.commit()


@pytest.fixture
def pair(tmp_path, monkeypatch):
    tom = make_app(tmp_path / 'tom.db', 'Tom', 'Alex', 'for-alex', 'for-tom', 'https://alex.example')
    alex = make_app(tmp_path / 'alex.db', 'Alex', 'Tom', 'for-tom', 'for-alex', 'https://tom.example')
    clients = {'tom.example': tom.test_client(), 'alex.example': alex.test_client()}

    def peer(url, headers, timeout):
        host, path = url.split('://', 1)[1].split('/', 1)
        resp = clients[host].get('/' + path, headers=headers)
        assert resp.status_code == 200
        return io.BytesIO(resp.data)
    monkeypatch.setattr(friends, 'open_peer', peer)
    return tom, alex


def on(app, fn):
    with app.app_context():
        d = database.get_db()
        out = fn(d)
        d.commit()
        return out


def sync(app):
    return on(app, lambda d: friends._do_ride_sync(1))


# ── Goals ───────────────────────────────────────────────────────

def test_period_bounds():
    wed = date(2026, 10, 21)
    assert goals.period_bounds('week', wed) == (date(2026, 10, 19), date(2026, 10, 25))
    assert goals.period_bounds('month', wed) == (date(2026, 10, 1), date(2026, 10, 31))
    assert goals.period_bounds('month', date(2026, 12, 5)) == (date(2026, 12, 1), date(2026, 12, 31))
    assert goals.period_bounds('year', wed) == (date(2026, 1, 1), date(2026, 12, 31))


def test_a_weekly_distance_goal_counts_only_its_sport_and_week(pair):
    tom, _ = pair

    def go(d):
        assert goals.add_goal(d, 1, 'distance', 'week', 'ride', '50') is None          # miles: no Settings.units means imperial
        ride(d, 'mon', '2026-10-19', dist=20000)
        ride(d, 'tue', '2026-10-20', dist=20000)
        ride(d, 'run', '2026-10-20', dist=10000, sport='Run')                              # not a ride
        ride(d, 'last', '2026-10-12', dist=90000)                                          # last week: hit it
        return goals.goals(d, 1, today=date(2026, 10, 21))[0]
    g = on(tom, go)
    assert round(g['done']) == 40000 and g['pct'] == round(100 * 40000 / (50 * 1609.344))
    assert g['status'] == 'ahead'                      # by Wednesday night an even pace is 3/7 of 50 = 21.4 mi; 24.9 done
    assert g['days_left'] == 5 and g['history'][-1]['hit'] and g['streak'] == 1


def test_on_track_against_an_even_pace(pair):
    tom, _ = pair

    def go(d):
        goals.add_goal(d, 1, 'climb', 'week', 'all', '1000')                              # feet, every sport
        ride(d, 'a', '2026-10-19', climb=150)                                              # 492 ft by Tuesday night: 2/7 of 1000 is 286
        ride(d, 'swim', '2026-10-20', climb=500, sport='Swim')                             # no climbing in the water
        return goals.goals(d, 1, today=date(2026, 10, 20))[0]
    g = on(tom, go)
    assert round(g['done']) == 150 and g['status'] == 'ahead' and g['expected_pct'] == 29
    g = on(tom, lambda d: goals.goals(d, 1, today=date(2026, 10, 24))[0])                 # Saturday: 6/7 is 857 ft, still 492
    assert g['status'] == 'behind' and g['days_left'] == 2


def test_goals_that_cant_be_measured_are_refused(pair):
    tom, _ = pair
    assert on(tom, lambda d: goals.add_goal(d, 1, 'distance', 'week', 'all', '10')).startswith('A distance goal needs one kind of sport')
    assert on(tom, lambda d: goals.add_goal(d, 1, 'climb', 'week', 'swim', '10')) == 'Swims have no climbing.'
    assert on(tom, lambda d: goals.add_goal(d, 1, 'time', 'week', 'ride', 'lots')).startswith('Type the target')
    assert on(tom, lambda d: goals.add_goal(d, 1, 'time', 'week', 'ride', '-3')).startswith('Type the target')
    assert on(tom, lambda d: d.execute('SELECT COUNT(*) FROM Goal').fetchone()[0]) == 0


# ── Challenges over the feed ────────────────────────────────────

def start(app, tokens=None, **form):
    """Start a challenge on `app`, sent to these feed token ids (default: every one that can be invited)."""
    from werkzeug.datastructures import MultiDict
    fields = {'metric': 'climb', 'sport': 'ride', 'startDate': '2026-10-01', 'endDate': '2026-10-31', 'name': 'October climbing', **form}

    def go(d):
        ids = [t['id'] for t in goals.invitable(d)] if tokens is None else tokens
        return goals.start_challenge(d, 1, MultiDict(list(fields.items()) + [('tokens', str(i)) for i in ids]))
    return on(app, go)


def board(app):
    return on(app, lambda d: [(c['name'], c['invitation'], [(s['name'], round(s['value'])) for s in c['standings']])
                              for c in goals.challenges(d, 1, today=date(2026, 10, 20))])


def test_a_challenge_travels_both_ways(pair):
    tom, alex = pair
    on(tom, lambda d: ride(d, 't1', '2026-10-05', climb=300))
    on(tom, lambda d: ride(d, 't0', '2026-09-30', climb=999))           # before it started
    on(alex, lambda d: ride(d, 'm1', '2026-10-06', climb=450))
    assert start(tom) is None

    sync(alex)                                                         # Alex's instance reads Tom's feed: an invitation, Tom in it
    assert board(alex) == [('October climbing', True, [('Tom', 300)])]

    cid = on(alex, lambda d: d.execute('SELECT id FROM Challenge').fetchone()[0])
    on(alex, lambda d: goals.set_joined(d, cid, True))
    assert board(alex) == [('October climbing', False, [('Alex', 450), ('Tom', 300)])]

    sync(tom)                                                            # Tom's reads Alex's: Alex has joined
    assert board(tom) == [('October climbing', False, [('Alex', 450), ('Tom', 300)])]

    on(alex, lambda d: goals.set_joined(d, cid, False))                # Alex leaves
    sync(tom)
    assert board(tom) == [('October climbing', False, [('Tom', 300)])]


def test_a_deleted_challenge_takes_its_invitation_with_it(pair):
    tom, alex = pair
    start(tom)
    sync(alex)
    assert len(board(alex)) == 1
    on(tom, lambda d: goals.delete_challenge(d, d.execute('SELECT id FROM Challenge').fetchone()[0]))
    sync(alex)
    assert board(alex) == []


def test_a_challenge_isnt_offered_to_a_token_that_doesnt_share_rides(pair):
    tom, alex = pair
    on(tom, lambda d: d.execute('UPDATE FeedToken SET shareRides=0'))
    start(tom)
    sync(alex)
    assert board(alex) == []


def test_a_challenge_goes_only_to_the_friends_invited(pair):
    tom, alex = pair
    sam = on(tom, lambda d: d.execute("INSERT INTO FeedToken (name, tokenHash) VALUES ('Sam', ?)", [feed_tokens._hash('for-sam')]).lastrowid)
    assert start(tom, tokens=[]) == 'Pick at least one friend to invite.'
    assert start(tom, tokens=[sam]) is None                              # Sam only
    sync(alex)
    assert board(alex) == []
    lines = [json.loads(x) for x in tom.test_client().get('/api/feed?manifest=1', headers={'X-Feed-Token': 'for-sam'}).get_data(as_text=True).splitlines()]
    assert [x['name'] for x in lines if x['type'] == 'challenge'] == ['October climbing']
    assert on(tom, lambda d: goals.challenges(d, 1)[0]['invited']) == ['Sam']


def test_joining_a_friends_challenge_invites_nobody_else(pair):
    tom, alex = pair
    start(tom)
    sync(alex)
    on(alex, lambda d: goals.set_joined(d, d.execute('SELECT id FROM Challenge').fetchone()[0], True))
    on(alex, lambda d: d.execute("INSERT INTO FeedToken (name, tokenHash) VALUES ('Sam', ?)", [feed_tokens._hash('for-sam')]))
    lines = [json.loads(x) for x in alex.test_client().get('/api/feed?manifest=1', headers={'X-Feed-Token': 'for-sam'}).get_data(as_text=True).splitlines()]
    line = next(x for x in lines if x['type'] == 'challenge')
    assert line['own'] is False and line['creator'] == 'Tom'           # Sam's instance sees Alex is in it...
    assert on(tom, lambda d: goals.store_from_friend(d, 1, dict(line, uid='0123456789abcdef'))) is None    # ...but a challenge it hasn't got is no invitation


def test_a_friends_bad_challenge_line_is_ignored(pair):
    _, alex = pair
    bad = [{'uid': 'x'}, {'uid': 'abcdef0123', 'metric': 'distance', 'sport': 'all', 'startDate': '2026-10-01', 'endDate': '2026-10-31'},
           {'uid': 'abcdef0123', 'metric': 'climb', 'sport': 'ride', 'startDate': 'soon', 'endDate': '2026-10-31'},
           {'uid': 'abcdef0123', 'metric': 'climb', 'sport': 'ride', 'startDate': '2026-10-01', 'endDate': '2026-10-31', 'target': 'lots'}]
    assert on(alex, lambda d: [goals.store_from_friend(d, 1, dict(o, own=True)) for o in bad]) == [None] * 4
    assert on(alex, lambda d: d.execute('SELECT COUNT(*) FROM Challenge').fetchone()[0]) == 0


def test_removing_a_friend_removes_their_invitations(pair):
    tom, alex = pair
    start(tom)
    sync(alex)
    on(alex, lambda d: goals.forget_friend(d, 1))
    assert board(alex) == []


# ── The pages ───────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    import app as app_module
    import config
    from services import credentials

    class _NoThread:
        def __init__(self, *a, **kw): pass
        def start(self): pass
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'web.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    a = app_module.create_app()
    with a.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("UPDATE Settings SET units='metric' WHERE id=1")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        ride(d, 'today', date.today().isoformat(), dist=12000, climb=200)
        av = credentials.auth_version()
    c = a.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def test_goals_page_adds_shows_and_deletes_a_goal(client):
    assert 'No goals yet' in client.get('/goals').get_data(as_text=True)
    assert 'Goals &rarr;' not in client.get('/dashboard').get_data(as_text=True)          # no card on the dashboard until there's a goal
    r = client.post('/goals/add', data={'metric': 'distance', 'sport': 'ride', 'period': 'week', 'target': '100'})
    assert r.status_code == 302 and 'error' not in r.headers['Location']
    html = client.get('/goals').get_data(as_text=True)
    assert '100 km of distance (rides) a week' in html and '<strong>12.0 km</strong> of 100 km' in html
    assert '100 km of distance (rides) a week' in client.get('/dashboard').get_data(as_text=True)
    r = client.post('/goals/add', data={'metric': 'distance', 'sport': 'all', 'period': 'week', 'target': '100'})
    assert 'error=' in r.headers['Location']
    client.post('/goals/1/delete', data={'rider': '1'})
    assert 'No goals yet' in client.get('/goals').get_data(as_text=True)


def test_starting_a_challenge_from_the_page(client):
    r = client.post('/goals/challenges', data={'metric': 'time', 'sport': 'all', 'startDate': date.today().isoformat(),
                                               'endDate': date.today().isoformat(), 'target': ''})
    assert r.status_code == 302 and r.headers['Location'].endswith('#challenges')
    html = client.get('/goals').get_data(as_text=True)
    assert 'The most time' in html and 'Tom' in html and 'Nobody reads your feed yet' in html
    assert 'The most time' in client.get('/dashboard').get_data(as_text=True)
