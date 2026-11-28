"""Challenges with friends (services/challenges.py, routes/challenges.py): started on one instance, carried to a friend's on the feed as an
invitation, joined there, and the friend shows up in the race back on the first; leaving or deleting reaches the other side on its next complete
sync. And the page of their own, split from Goals: its old form addresses, its feature switch and the dashboard card. Throwaway DBs."""
import json
from datetime import date

from services import challenges, feed_tokens
from tests.test_goals import client, on, pair, ride, sync      # noqa: F401  (fixtures)


# ── Challenges over the feed ────────────────────────────────────

def start(app, tokens=None, **form):
    """Start a challenge on `app`, sent to these feed token ids (default: every one that can be invited)."""
    from werkzeug.datastructures import MultiDict
    fields = {'metric': 'climb', 'sport': 'ride', 'startDate': '2026-10-01', 'endDate': '2026-10-31', 'name': 'October climbing', **form}

    def go(d):
        ids = [t['id'] for t in challenges.invitable(d)] if tokens is None else tokens
        return challenges.start_challenge(d, 1, MultiDict(list(fields.items()) + [('tokens', str(i)) for i in ids]))
    return on(app, go)


def board(app):
    return on(app, lambda d: [(c['name'], c['invitation'], [(s['name'], round(s['value'])) for s in c['standings']])
                              for c in challenges.challenges(d, 1, today=date(2026, 10, 20))])


def test_a_challenge_travels_both_ways(pair):
    tom, alex = pair
    on(tom, lambda d: ride(d, 't1', '2026-10-05', climb=300))
    on(tom, lambda d: ride(d, 't0', '2026-09-30', climb=999))           # before it started
    on(alex, lambda d: ride(d, 'm1', '2026-10-06', climb=450))
    assert start(tom) is None

    sync(alex)                                                         # Alex's instance reads Tom's feed: an invitation, Tom in it
    assert board(alex) == [('October climbing', True, [('Tom', 300)])]

    cid = on(alex, lambda d: d.execute('SELECT id FROM Challenge').fetchone()[0])
    on(alex, lambda d: challenges.set_joined(d, cid, True))
    assert board(alex) == [('October climbing', False, [('Alex', 450), ('Tom', 300)])]

    sync(tom)                                                            # Tom's reads Alex's: Alex has joined
    assert board(tom) == [('October climbing', False, [('Alex', 450), ('Tom', 300)])]

    on(alex, lambda d: challenges.set_joined(d, cid, False))                # Alex leaves
    sync(tom)
    assert board(tom) == [('October climbing', False, [('Tom', 300)])]


def test_a_deleted_challenge_takes_its_invitation_with_it(pair):
    tom, alex = pair
    start(tom)
    sync(alex)
    assert len(board(alex)) == 1
    on(tom, lambda d: challenges.delete_challenge(d, d.execute('SELECT id FROM Challenge').fetchone()[0]))
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
    assert on(tom, lambda d: challenges.challenges(d, 1)[0]['invited']) == ['Sam']


def test_joining_a_friends_challenge_invites_nobody_else(pair):
    tom, alex = pair
    start(tom)
    sync(alex)
    on(alex, lambda d: challenges.set_joined(d, d.execute('SELECT id FROM Challenge').fetchone()[0], True))
    on(alex, lambda d: d.execute('INSERT INTO FeedTokenRider (tokenId, riderId) VALUES (?, 1)',
                                 [d.execute("INSERT INTO FeedToken (name, tokenHash) VALUES ('Sam', ?)", [feed_tokens._hash('for-sam')]).lastrowid]))
    lines = [json.loads(x) for x in alex.test_client().get('/api/feed?manifest=1', headers={'X-Feed-Token': 'for-sam'}).get_data(as_text=True).splitlines()]
    line = next(x for x in lines if x['type'] == 'challenge')
    assert line['own'] is False and line['creator'] == 'Tom'           # Sam's instance sees Alex is in it...
    assert on(tom, lambda d: challenges.store_from_friend(d, 1, dict(line, uid='0123456789abcdef'), 1)) is None    # ...but a challenge it hasn't got is no invitation


def test_a_friends_bad_challenge_line_is_ignored(pair):
    _, alex = pair
    bad = [{'uid': 'x'}, {'uid': 'abcdef0123', 'metric': 'distance', 'sport': 'all', 'startDate': '2026-10-01', 'endDate': '2026-10-31'},
           {'uid': 'abcdef0123', 'metric': 'climb', 'sport': 'ride', 'startDate': 'soon', 'endDate': '2026-10-31'},
           {'uid': 'abcdef0123', 'metric': 'climb', 'sport': 'ride', 'startDate': '2026-10-01', 'endDate': '2026-10-31', 'target': 'lots'}]
    assert on(alex, lambda d: [challenges.store_from_friend(d, 1, dict(o, own=True), 1) for o in bad]) == [None] * 4
    assert on(alex, lambda d: d.execute('SELECT COUNT(*) FROM Challenge').fetchone()[0]) == 0


def test_removing_a_friend_removes_their_invitations(pair):
    tom, alex = pair
    start(tom)
    sync(alex)
    on(alex, lambda d: challenges.forget_friend(d, 1))
    assert board(alex) == []


# ── The page ───────────────────────────────────────────────────────────

def test_starting_a_challenge_from_the_page(client):
    r = client.post('/challenges', data={'metric': 'time', 'sport': 'all', 'startDate': date.today().isoformat(),
                                               'endDate': date.today().isoformat(), 'target': ''})
    assert r.status_code == 302 and r.headers['Location'].endswith('/challenges')
    html = client.get('/challenges').get_data(as_text=True)
    assert 'The most time' in html and 'Tom' in html and 'Nobody reads your feed yet' in html
    assert 'The most time' in client.get('/dashboard').get_data(as_text=True)


def test_a_form_from_before_the_move_still_lands(client):
    """A Goals page left open from before the move posts to /goals/challenges...: 308 sends the same form on to the new address."""
    r = client.post('/goals/challenges', data={'metric': 'time', 'sport': 'all', 'startDate': '2026-10-01', 'endDate': '2026-10-31'})
    assert r.status_code == 308 and r.headers['Location'].endswith('/challenges')
    r = client.post('/goals/challenges', data={'metric': 'time', 'sport': 'all', 'startDate': '2026-10-01', 'endDate': '2026-10-31'},
                    follow_redirects=True)
    assert r.status_code == 200 and 'The most time' in r.get_data(as_text=True)
    r = client.post('/goals/challenges/1/delete', data={'rider': '1'})
    assert r.status_code == 308 and r.headers['Location'].endswith('/challenges/1/delete')
    client.post('/goals/challenges/1/delete', data={'rider': '1'}, follow_redirects=True)
    assert 'No challenges yet' in client.get('/challenges').get_data(as_text=True)


def test_goals_and_challenges_have_a_page_each(client):
    client.post('/goals/add', data={'metric': 'count', 'sport': 'ride', 'period': 'week', 'target': '3'})
    client.post('/challenges', data={'metric': 'climb', 'sport': 'ride', 'startDate': date.today().isoformat(), 'endDate': date.today().isoformat()})
    goals_page, page = client.get('/goals').get_data(as_text=True), client.get('/challenges').get_data(as_text=True)
    assert '3 activities (rides) a week' in goals_page and 'The most climbing' not in goals_page and 'Start a challenge' not in goals_page
    assert 'The most climbing' in page and '3 activities (rides) a week' not in page and 'Add a goal' not in page
    assert 'href="/challenges"' in page and 'href="/goals"' in page            # both in the sidebar


def _switch(client, *off):
    from services import features
    r = client.post('/settings/features', data={'on': [n for n in features.NAMES if n not in off]})
    assert r.status_code == 302


def test_challenges_switch_off_on_their_own(client):
    client.post('/goals/add', data={'metric': 'count', 'sport': 'ride', 'period': 'week', 'target': '3'})
    client.post('/challenges', data={'metric': 'climb', 'sport': 'ride', 'startDate': date.today().isoformat(), 'endDate': date.today().isoformat()})
    _switch(client, 'challenges')
    r = client.get('/challenges')
    assert r.status_code == 403 and 'turned off' in r.get_data(as_text=True)
    page = client.get('/dashboard').get_data(as_text=True)
    assert 'href="/challenges"' not in page and 'The most climbing' not in page and '3 activities (rides) a week' in page
    assert client.get('/goals').status_code == 200

    _switch(client, 'goals')                                                   # and the other way round: the card is the Challenges one
    assert client.get('/goals').status_code == 403
    page = client.get('/dashboard').get_data(as_text=True)
    assert 'card-title">Challenges<' in page and 'The most climbing' in page and '3 activities (rides) a week' not in page
    assert 'href="/goals"' not in page
