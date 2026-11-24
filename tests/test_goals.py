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
from services import feed_tokens, goals, periods

CAL = periods.Prefs(periods.CALENDAR, 0)              # calendar weeks from Monday: what every install had before the setting


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
        d.execute('INSERT INTO FeedTokenRider (tokenId, riderId) VALUES (1, 1)')
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

def test_a_weekly_distance_goal_counts_only_its_sport_and_week(pair):
    tom, _ = pair

    def go(d):
        assert goals.add_goal(d, 1, 'distance', 'week', 'ride', '50') is None          # miles: no Settings.units means imperial
        ride(d, 'mon', '2026-10-19', dist=20000)
        ride(d, 'tue', '2026-10-20', dist=20000)
        ride(d, 'run', '2026-10-20', dist=10000, sport='Run')                              # not a ride
        ride(d, 'last', '2026-10-12', dist=90000)                                          # last week: hit it
        return goals.goals(d, 1, today=date(2026, 10, 21), p=CAL)[0]
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
        return goals.goals(d, 1, today=date(2026, 10, 20), p=CAL)[0]
    g = on(tom, go)
    assert round(g['done']) == 150 and g['status'] == 'ahead' and g['expected_pct'] == 29
    g = on(tom, lambda d: goals.goals(d, 1, today=date(2026, 10, 24), p=CAL)[0])         # Saturday: 6/7 is 857 ft, still 492
    assert g['status'] == 'behind' and g['days_left'] == 2


def test_a_rolling_weekly_goal_counts_the_past_7_days(pair):
    """On a Monday the week is last Tuesday to today, not today alone; the history is the 7-day blocks before it."""
    tom, _ = pair

    def go(d):
        goals.add_goal(d, 1, 'distance', 'week', 'ride', '50')
        ride(d, 'last-mon', '2026-10-12', dist=90000)                                     # 8 days back: the block before
        ride(d, 'tue', '2026-10-13', dist=30000)                                          # 6 days back: in
        ride(d, 'sun', '2026-10-18', dist=20000)                                          # yesterday: in
        ride(d, 'mon', '2026-10-19', dist=10000)                                          # today, a Monday: in
        return goals.goals(d, 1, today=date(2026, 10, 19), p=periods.Prefs(periods.ROLLING, 0))[0]
    g = on(tom, go)
    assert round(g['done']) == 60000 and g['period_label'] == 'Past 7 days' and g['period_dates'] == '13–19 Oct'
    assert g['days_left'] == 1 and g['rolling'] and g['status'] == 'behind'              # 37.3 mi of 50: no even pace to be ahead of
    assert g['history'][-1]['label'] == '6–12 Oct' and g['history'][-1]['hit'] and g['streak'] == 1


def test_a_rolling_monthly_goal_on_the_1st_includes_last_months_days(pair):
    tom, _ = pair

    def go(d):
        goals.add_goal(d, 1, 'count', 'month', 'all', '3')
        for i, day in enumerate(('2026-10-04', '2026-10-05', '2026-10-20', '2026-10-31', '2026-11-01')):
            ride(d, f'r{i}', day)
        return goals.goals(d, 1, today=date(2026, 11, 1), p=periods.Prefs(periods.ROLLING, 0))[0]
    g = on(tom, go)
    assert g['done'] == 4 and g['status'] == 'done'                                       # 5 Oct to 1 Nov: the 4th is 29 days back
    assert g['period_label'] == 'Past 28 days' and g['title'].endswith('every 28 days')
    g = on(tom, lambda d: goals.goals(d, 1, today=date(2026, 11, 1), p=CAL)[0])
    assert g['done'] == 1 and g['period_label'] == 'November' and g['days_left'] == 30   # the calendar month: the 1st alone


def test_a_goal_of_rides_and_runs_counts_both_and_nothing_else(pair):
    tom, _ = pair

    def go(d):
        assert goals.add_goal(d, 1, 'count', 'week', ['group:ride', 'sport:Run'], '3') is None
        ride(d, 'r1', '2026-10-19')
        ride(d, 'r2', '2026-10-20', sport='EBikeRide')          # every kind of ride
        ride(d, 'run', '2026-10-21', sport='Run')
        ride(d, 'walk', '2026-10-21', sport='Walk')             # on foot, but only runs were picked
        ride(d, 'swim', '2026-10-22', sport='Swim')
        return goals.goals(d, 1, today=date(2026, 10, 22), p=CAL)[0]
    g = on(tom, go)
    assert g['done'] == 3 and g['status'] == 'done' and g['sports'] == ['group:ride', 'sport:Run']
    assert g['title'] == '3 activities (rides or runs) a week' and g['icon'] == '🚴🏃'
    stored = on(tom, lambda d: tuple(d.execute('SELECT sport, sports FROM Goal').fetchone()))
    assert stored == ('all', '["group:ride", "sport:Run"]')     # an older Headwind: as near as one group gets


def test_a_distance_goal_of_runs_and_walks_adds_their_distances(pair):
    tom, _ = pair

    def go(d):
        assert goals.add_goal(d, 1, 'distance', 'week', ['sport:Run', 'sport:Walk'], '5') is None
        ride(d, 'run', '2026-10-19', sport='Run', dist=5000)
        ride(d, 'walk', '2026-10-20', sport='Walk', dist=3000)
        ride(d, 'hike', '2026-10-20', sport='Hike', dist=9000)  # on foot too, but not picked
        return goals.goals(d, 1, today=date(2026, 10, 20), p=CAL)[0]
    g = on(tom, go)
    assert round(g['done']) == 8000
    assert on(tom, lambda d: d.execute('SELECT sport FROM Goal').fetchone()[0]) == 'foot'


def test_a_goal_an_older_headwind_added_counts_its_group(pair):
    tom, _ = pair

    def go(d):
        d.execute("INSERT INTO Goal (riderId, metric, period, sport, target) VALUES (1, 'count', 'week', 'foot', 2)")    # no sports
        ride(d, 'ride', '2026-10-19')
        ride(d, 'walk', '2026-10-19', sport='Walk')
        return goals.goals(d, 1, today=date(2026, 10, 19), p=CAL)[0]
    g = on(tom, go)
    assert g['done'] == 1 and g['sports'] == ['group:foot']
    assert on(tom, lambda d: goals.weekly_count(d, 1))['keys'] == ['group:foot']


def test_every_sport_counts_any_sport(pair):
    tom, _ = pair

    def go(d):
        assert goals.add_goal(d, 1, 'time', 'week', None, '1') is None
        ride(d, 'yoga', '2026-10-19', sport='Yoga', secs=1800, dist=0)
        ride(d, 'paddle', '2026-10-19', sport='Paddle', secs=1800)
        return goals.goals(d, 1, today=date(2026, 10, 19), p=CAL)[0]
    g = on(tom, go)
    assert g['done'] == 3600 and g['sports'] is None and g['icon'] == '🏅' and g['title'] == '1h 00m of time a week'


def test_weekly_count_is_the_riders_weekly_goal_of_a_number_of_activities(pair):
    tom, _ = pair
    assert on(tom, lambda d: goals.weekly_count(d, 1)) is None              # none until the rider sets one
    on(tom, lambda d: goals.add_goal(d, 1, 'count', 'month', 'ride', '10'))
    on(tom, lambda d: goals.add_goal(d, 1, 'distance', 'week', 'ride', '50'))
    assert on(tom, lambda d: goals.weekly_count(d, 1)) is None
    on(tom, lambda d: goals.add_goal(d, 1, 'count', 'week', ['group:ride', 'group:swim'], '4'))
    w = on(tom, lambda d: goals.weekly_count(d, 1))
    assert w['target'] == 4 and w['keys'] == ['group:ride', 'group:swim'] and w['nouns'] == 'rides or swims'


def test_goals_that_cant_be_measured_are_refused(pair):
    tom, _ = pair
    assert on(tom, lambda d: goals.add_goal(d, 1, 'distance', 'week', 'all', '10')).startswith('A distance goal needs sports whose distances add up')
    assert on(tom, lambda d: goals.add_goal(d, 1, 'distance', 'week', ['group:ride', 'sport:Run'], '10')).startswith('A distance goal needs')
    assert on(tom, lambda d: goals.add_goal(d, 1, 'climb', 'week', ['sport:Swim'], '10')) == 'Swims have no climbing.'
    assert on(tom, lambda d: goals.add_goal(d, 1, 'climb', 'week', ['sport:Kitesurf'], '10')) == 'None of those sports has climbing.'
    assert on(tom, lambda d: goals.add_goal(d, 1, 'count', 'week', [], '3')).startswith('Pick at least one sport')
    assert on(tom, lambda d: goals.add_goal(d, 1, 'count', 'week', ['nonsense'], '3')).startswith('Pick at least one sport')
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
    on(tom, lambda d: d.execute('UPDATE FeedToken SET shareActivities=0'))
    start(tom)
    sync(alex)
    assert board(alex) == []


def test_a_challenge_goes_only_to_the_friends_invited(pair):
    tom, alex = pair
    sam = on(tom, lambda d: d.execute("INSERT INTO FeedToken (name, tokenHash) VALUES ('Sam', ?)", [feed_tokens._hash('for-sam')]).lastrowid)
    on(tom, lambda d: d.execute('INSERT INTO FeedTokenRider (tokenId, riderId) VALUES (?, 1)', [sam]))
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
    on(alex, lambda d: d.execute('INSERT INTO FeedTokenRider (tokenId, riderId) VALUES (?, 1)',
                                 [d.execute("INSERT INTO FeedToken (name, tokenHash) VALUES ('Sam', ?)", [feed_tokens._hash('for-sam')]).lastrowid]))
    lines = [json.loads(x) for x in alex.test_client().get('/api/feed?manifest=1', headers={'X-Feed-Token': 'for-sam'}).get_data(as_text=True).splitlines()]
    line = next(x for x in lines if x['type'] == 'challenge')
    assert line['own'] is False and line['creator'] == 'Tom'           # Sam's instance sees Alex is in it...
    assert on(tom, lambda d: goals.store_from_friend(d, 1, dict(line, uid='0123456789abcdef'), 1)) is None    # ...but a challenge it hasn't got is no invitation


def test_a_friends_bad_challenge_line_is_ignored(pair):
    _, alex = pair
    bad = [{'uid': 'x'}, {'uid': 'abcdef0123', 'metric': 'distance', 'sport': 'all', 'startDate': '2026-10-01', 'endDate': '2026-10-31'},
           {'uid': 'abcdef0123', 'metric': 'climb', 'sport': 'ride', 'startDate': 'soon', 'endDate': '2026-10-31'},
           {'uid': 'abcdef0123', 'metric': 'climb', 'sport': 'ride', 'startDate': '2026-10-01', 'endDate': '2026-10-31', 'target': 'lots'}]
    assert on(alex, lambda d: [goals.store_from_friend(d, 1, dict(o, own=True), 1) for o in bad]) == [None] * 4
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
    r = client.post('/goals/add', data={'metric': 'distance', 'every': '1', 'period': 'week', 'target': '100'})
    assert 'error=' in r.headers['Location']
    r = client.post('/goals/add', data={'metric': 'count', 'period': 'week', 'target': '3'})          # nothing ticked
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


def test_the_goal_form_takes_any_set_of_sports(client):
    html = client.get('/goals').get_data(as_text=True)
    for key in ('group:ride', 'group:foot', 'group:swim', 'sport:Ride'):    # the groups even before any run or swim, and the sports the rider has
        assert f'value="{key}"' in html
    r = client.post('/goals/add', data={'metric': 'count', 'period': 'week', 'target': '3', 'sports': ['group:ride', 'sport:Run']})
    assert r.status_code == 302 and 'error' not in r.headers['Location']
    r = client.post('/goals/add', data={'metric': 'time', 'period': 'month', 'target': '20', 'every': '1', 'sports': ['group:ride']})
    assert 'error' not in r.headers['Location']                      # Every sport wins over a sport left ticked
    html = client.get('/goals').get_data(as_text=True)
    assert '3 activities (rides or runs) a week' in html and '20h 00m of time' in html
