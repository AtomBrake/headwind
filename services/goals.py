"""Goals and friend challenges: distance, climbing, time or a count of activities, for the sports picked or for all of them.

A goal is the rider's own target for every week, month or year ("100 mi of riding a week", "50,000 ft of climbing this year", "3 rides or runs a
week"), measured from their activities as they are now, so a deleted or re-typed activity moves it straight away. Nothing is stored but the target
and the sports it counts: Goal.sports, a set of keys as favourites have them (services/favourites.parse_set: 'group:ride' for every kind of ride,
'sport:Run' for runs alone), NULL for every sport (stored_keys). Goal.sport, the one group it was before (database._step_17), is still written, as near as one
group gets, for an older Headwind opening the database. A rider has only the goals they set: none to start with.

A challenge is a race between friends over set dates: the most (or first to a target) of one thing. It travels on the friends feed
(routes/friends.feed) as 'challenge' lines, each with a uid made where it was started. One started here goes only to the friends invited, by
their feed token (ChallengeInvite); one joined from a friend goes to every friend we share with, marked as not ours, so the others in it see us in
it but nobody gets an invitation from anyone but the friend who started it. When the starter's feed brings one this instance doesn't have, it is
shown as an invitation; when any friend's feed brings one we have, that friend is in it (ChallengeMember). Every instance works out the standings itself, from its own activities and the ones its friends share with it, so nobody's
numbers are sent twice and a friend whose activities we can't see can't be in the race here. A challenge the friend no longer lists (they left, or
deleted the one they started) loses them on their next complete sync.
"""
import re
import secrets
from datetime import date

from services import sports, units

METRICS = ('distance', 'climb', 'time', 'count')
METRIC_LABELS = {'distance': 'Distance', 'climb': 'Climbing', 'time': 'Time', 'count': 'Activities'}
PERIODS = ('week', 'month', 'year')
PERIOD_LABELS = {'week': 'a week', 'month': 'a month', 'year': 'a year'}
ROLLING_PERIOD_LABELS = {'month': 'every 28 days'}    # services/periods.ROLLING
GROUPS = ('ride', 'foot', 'swim', 'all')        # services/sports.stat_group, plus every sport together
GROUP_LABELS = {'ride': 'Rides', 'foot': 'On foot', 'swim': 'Swims', 'all': 'Every sport'}
GROUP_ICONS = {'ride': '🚴', 'foot': '🏃', 'swim': '🏊', 'all': '🏅'}
HISTORY = {'week': 8, 'month': 6, 'year': 4}    # past periods shown under a goal
_UID = re.compile(r'^[0-9a-f]{8,40}$')


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS Goal (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        riderId   INTEGER NOT NULL REFERENCES Rider(id),
        metric    TEXT NOT NULL,                  -- METRICS
        period    TEXT NOT NULL,                  -- PERIODS
        sport     TEXT NOT NULL DEFAULT 'all',    -- GROUPS: what an older Headwind counts (_old_group); sports is what counts
        target    REAL NOT NULL,                  -- metres, seconds or a count
        createdAt TEXT DEFAULT (datetime('now')),
        sports    TEXT                            -- services/favourites.parse_set keys, as JSON; NULL: sport's group, 'all' every sport (stored_keys)
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS Challenge (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        uid          TEXT NOT NULL UNIQUE,         -- made where it was started; the same on every instance that has it
        riderId      INTEGER REFERENCES Rider(id), -- the rider here it belongs to
        name         TEXT NOT NULL,
        metric       TEXT NOT NULL,
        sport        TEXT NOT NULL DEFAULT 'all',
        startDate    TEXT NOT NULL,                -- inclusive, local dates
        endDate      TEXT NOT NULL,
        target       REAL,                         -- NULL: the most wins; else the first to it
        mine         INTEGER NOT NULL DEFAULT 0,   -- 1: started here
        joined       INTEGER NOT NULL DEFAULT 0,   -- 1: the rider here is in it (always, for one started here)
        dismissed    INTEGER NOT NULL DEFAULT 0,   -- an invitation the rider turned down
        creatorName  TEXT,                         -- who started it, as their feed named them
        viaFriendId  INTEGER REFERENCES Friend(id),-- whose feed brought it (NULL: started here)
        createdAt    TEXT DEFAULT (datetime('now'))
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS ChallengeMember (
        challengeId INTEGER NOT NULL REFERENCES Challenge(id) ON DELETE CASCADE,
        friendId    INTEGER NOT NULL REFERENCES Friend(id) ON DELETE CASCADE,
        PRIMARY KEY (challengeId, friendId)
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS ChallengeInvite (       -- who a challenge started here goes to: the friends' feed tokens
        challengeId INTEGER NOT NULL REFERENCES Challenge(id) ON DELETE CASCADE,
        tokenId     INTEGER NOT NULL REFERENCES FeedToken(id) ON DELETE CASCADE,
        PRIMARY KEY (challengeId, tokenId)
    )''')


# ── Values: stored in metres, seconds and counts; typed and shown in the rider's units ──

def to_stored(metric, text):
    """A target typed in the rider's units (miles or km, feet or metres, hours, activities) -> what's stored. Raises ValueError on rubbish or
    on a target that isn't above zero."""
    v = float(str(text).replace(',', '').strip())
    if not v > 0 or v > 1e9:
        raise ValueError(text)
    if metric == 'distance':
        return units.to_metres(v)
    if metric == 'climb':
        return v / units.spec()['elevPerM']
    if metric == 'time':
        return v * 3600
    return round(v)


def to_typed(metric, value):
    """The other way, for a form: a stored target as the number the rider would type."""
    if metric == 'distance':
        return round(units.dist(value), 1)
    if metric == 'climb':
        return round(units.elev(value))
    if metric == 'time':
        return round(value / 3600, 1)
    return int(value)


def fmt(metric, value):
    value = value or 0
    if metric == 'distance':
        return units.fmt_dist(value, places=0 if units.dist(value) >= 100 else 1)
    if metric == 'climb':
        return units.fmt_elev(value)
    if metric == 'time':
        h, m = divmod(int(value) // 60, 60)
        return f'{h:,}h {m:02d}m' if h else f'{m}m'
    n = int(value)
    return f"{n:,} activit{'y' if n == 1 else 'ies'}"


def unit_label(metric):
    return {'distance': units.spec()['dist'], 'climb': units.spec()['elev'], 'time': 'hours', 'count': 'activities'}[metric]


def keys_of(sport):
    """What a goal counts, from a set of keys (a list; anything that isn't one dropped), a challenge's group ('ride', 'all') or None (every
    sport): None for every sport, else the list of keys. An empty list stays empty, for check() to refuse."""
    from services import favourites
    if sport is None or sport == 'all':
        return None
    if isinstance(sport, str):
        return [f'group:{sport}'] if sport in GROUPS else []
    return favourites.parse_set(favourites.dump_set(sport))


def stored_keys(row):
    """What a Goal row counts: its sports, or, where they're NULL, its one group, as a goal an older Headwind added has only that (NULL with
    sport 'all' is every sport)."""
    from services import favourites
    if row['sports'] is None:
        return keys_of(row['sport'] if row['sport'] in GROUPS else 'all')
    return favourites.parse_set(row['sports'])


def _old_group(keys):
    """Goal.sport for an older Headwind: the one group every key is in, else 'all'."""
    from services import favourites
    groups = {favourites.group_of(k) for k in keys or ()}
    return groups.pop() if keys and len(groups) == 1 and next(iter(groups)) in GROUPS else 'all'


def _on(sport):
    """' (rides or runs)' for a title, '' for every sport. sport: keys or a challenge's group."""
    from services import favourites
    keys = keys_of(sport)
    return '' if keys is None else f' ({favourites.nouns(keys)})'


def describe(metric, sport, target=None, period=None, mode=None):
    """'100 mi of distance (rides) a week', 'The most climbing', '3 activities (rides or runs) a week', ... sport: a set of keys (keys_of), a
    challenge's group, or None for every sport. mode 'rolling' (services/periods): a month goal is 'every 28 days'."""
    what = {'distance': 'distance', 'climb': 'climbing', 'time': 'time', 'count': 'activities'}[metric]
    on = _on(sport)
    if target is None:
        return f'The most {what}{on}'
    every = ROLLING_PERIOD_LABELS.get(period) if mode == 'rolling' else None    # a week is 7 days either way
    amount = fmt(metric, target) if metric == 'count' else f'{fmt(metric, target)} of {what}'      # '3 activities', not '3 activities of activities'
    return f"{amount}{on}" + (f' {every or PERIOD_LABELS[period]}' if period else '')


def check(metric, sport, period=None):
    """An error text for a combination that can't be measured, else None. sport: a set of keys, a challenge's group, or None for every sport.
    A distance needs sports whose distances add up, one stat group: a swim's metres never add to a ride's miles (services/sport_filter), nor a
    run's to a ride's. There's no climbing in the water."""
    from services import favourites
    if metric not in METRICS or (isinstance(sport, str) and sport not in GROUPS) or (period is not None and period not in PERIODS):
        return 'Pick what to count, the sport and how often.'
    keys = keys_of(sport)
    if keys == []:
        return 'Pick at least one sport, or every sport.'
    groups = {favourites.group_of(k) for k in keys or ()}
    if metric == 'distance' and (keys is None or len(groups) > 1):
        return ('A distance goal needs sports whose distances add up: rides, or runs and walks, not both. A swim’s or a run’s distance '
                'doesn’t add to a ride’s.')
    if metric == 'climb' and keys is not None:
        if groups == {'swim'}:
            return 'Swims have no climbing.'
        if not any(favourites.group_of(k) in ('ride', 'foot') or sports.has_climbing(k.partition(':')[2]) for k in keys):
            return 'None of those sports has climbing.'
    return None


# ── Totals ──

def _rows(db, rider_id, first, last):
    """(day, sportType, distance, movingTime, climb) of the rider's activities from first to last (dates, inclusive)."""
    return db.execute(f'''SELECT date(startDateLocal), sportType, distance, movingTime, {sports.climb_sql()}
                          FROM Activity WHERE riderId=? AND date(startDateLocal) BETWEEN ? AND ?''',
                      [rider_id, first.isoformat(), last.isoformat()]).fetchall()


def _value(metric, row):
    return {'distance': row[2], 'climb': row[4], 'time': row[3], 'count': 1}[metric] or 0


def _counts(keys, sport_type):
    """Whether an activity of this sport counts towards a goal or challenge of these keys (keys_of)."""
    from services import favourites
    return favourites.covers(keys, sport_type)


def total(db, rider_id, metric, sport, first, last):
    keys = keys_of(sport)
    return sum(_value(metric, r) for r in _rows(db, rider_id, first, last) if _counts(keys, r[1]))


# ── Goals ──

def add_goal(db, rider_id, metric, period, sport, target_text):
    """sport: the keys it counts (a list), a group ('ride') or None / 'all' for every sport. Returns an error text, or None once it's saved.
    Commits."""
    from services import favourites
    err = check(metric, sport, period)
    if err:
        return err
    try:
        target = to_stored(metric, target_text)
    except (TypeError, ValueError):
        return f'Type the target as a number of {unit_label(metric)}.'
    keys = keys_of(sport)
    db.execute('INSERT INTO Goal (riderId, metric, period, sport, sports, target) VALUES (?,?,?,?,?,?)',
               [rider_id, metric, period, _old_group(keys), favourites.dump_set(keys), target])
    db.commit()
    return None


def weekly_count(db, rider_id):
    """The rider's goal of a number of activities each week (the first, if they've set more than one): {id, target, keys, nouns ('rides or
    runs', 'activities' for every sport)}, or None when they have none. Home Assistant's weekly activity sensor and its "looking stagnant" status
    count its sports (services/mqtt, services/insights.activity_status)."""
    from services import favourites
    g = db.execute("SELECT id, target, sport, sports FROM Goal WHERE riderId=? AND metric='count' AND period='week' ORDER BY id LIMIT 1",
                   [rider_id]).fetchone() if rider_id is not None else None
    if not g:
        return None
    keys = stored_keys(g)
    return {'id': g['id'], 'target': int(g['target']), 'keys': keys, 'nouns': favourites.nouns(keys, every='activities')}


def delete_goal(db, rider_id, goal_id):
    db.execute('DELETE FROM Goal WHERE id=? AND riderId=?', [goal_id, rider_id])
    db.commit()


def goals(db, rider_id, today=None, p=None):
    """Each of the rider's goals with where it stands: {id, metric, period, sport, target, title, icon, done, pct, expected (where an even pace
    would be by the end of today), status ('done', 'ahead', 'behind'), to_go, per_day (needed each day left, including today), days_left,
    history [{label, value, pct, hit}] oldest first (the periods before this one), streak (periods hit in a row before this one), period_label}.
    A week and a month are the viewer's (services/periods, p: their Prefs): the past 7 and 28 days, whose only day left is today, or calendar
    ones; the history under a goal is the blocks before, of the same kind."""
    from services import periods, tz
    from services.dates import day_month
    today = today or tz.today()
    p = p or periods.resolve(rider_id)
    out = []
    from services import favourites
    for g in db.execute('SELECT * FROM Goal WHERE riderId=? ORDER BY period, sport, metric, id', [rider_id]).fetchall():
        keys = stored_keys(g)
        blocks = periods.blocks(g['period'], HISTORY[g['period']] + 1, p, today)
        now = blocks[-1]
        first, last = now.first, now.last
        rows = _rows(db, rider_id, blocks[0].first, last)
        sums = [0] * len(blocks)
        for r in rows:
            if _counts(keys, r[1]):
                i = periods.find(blocks, date.fromisoformat(r[0]))
                if i is not None:
                    sums[i] += _value(g['metric'], r)
        done, target = sums[-1], g['target']
        days, days_left = now.days, (last - today).days + 1
        expected = target * (days - days_left + 1) / days
        history = [{'label': b.dates, 'short': day_month(b.first) if p.mode == periods.ROLLING and b.kind != 'year' else b.dates, 'value': v, 'fmt': fmt(g['metric'], v),
                    'pct': min(100, round(100 * v / target)), 'hit': v >= target} for b, v in zip(blocks[:-1], sums[:-1])]
        streak = 0
        for h in reversed(history):
            if not h['hit']:
                break
            streak += 1
        out.append({
            'id': g['id'], 'metric': g['metric'], 'period': g['period'], 'sports': keys, 'target': target,
            'title': describe(g['metric'], keys, target, g['period'], p.mode), 'icon': favourites.icons(keys),
            'done': done, 'done_fmt': fmt(g['metric'], done), 'target_fmt': fmt(g['metric'], target),
            'pct': min(100, round(100 * done / target)), 'expected_pct': min(100, round(100 * expected / target)),
            'status': 'done' if done >= target else ('ahead' if done >= expected else 'behind'),
            'to_go_fmt': fmt(g['metric'], max(0, target - done)),
            'per_day_fmt': fmt(g['metric'], max(0, target - done) / days_left) if g['metric'] != 'count' else None,
            'days_left': days_left, 'history': history, 'streak': streak,
            'period_label': now.label, 'period_dates': now.dates, 'rolling': p.mode == periods.ROLLING and g['period'] != 'year',
        })
    return out


# ── Challenges ──

def _date(text):
    try:
        return date.fromisoformat(str(text or '').strip()[:10]).isoformat()
    except ValueError:
        return None


def invitable(db):
    """The feed tokens a challenge can go to: not revoked, and sharing activities (a race needs them). [{id, name}]"""
    return [dict(r) for r in db.execute('SELECT id, name FROM FeedToken WHERE revokedAt IS NULL AND shareActivities=1 ORDER BY name')]


def start_challenge(db, rider_id, form):
    """A challenge started here, from the Goals page's form (name, metric, sport, startDate, endDate, target in the rider's units or blank, and
    `tokens`: the ids of the friends' feed tokens it goes to). Returns an error text, or None. Commits."""
    metric, sport = form.get('metric'), form.get('sport') or 'all'
    err = check(metric, sport)
    if err:
        return err
    can = {t['id'] for t in invitable(db)}
    tokens = {int(t) for t in form.getlist('tokens') if str(t).isdigit() and int(t) in can}
    if can and not tokens:
        return 'Pick at least one friend to invite.'
    first, last = _date(form.get('startDate')), _date(form.get('endDate'))
    if not first or not last:
        return 'Pick the first and last day.'
    if last < first:
        first, last = last, first
    target = None
    if (form.get('target') or '').strip():
        try:
            target = to_stored(metric, form.get('target'))
        except ValueError:
            return f'Type the target as a number of {unit_label(metric)}, or leave it blank for "the most wins".'
    name = (form.get('name') or '').strip()[:80] or describe(metric, sport, target)
    cur = db.execute('''INSERT INTO Challenge (uid, riderId, name, metric, sport, startDate, endDate, target, mine, joined)
                        VALUES (?,?,?,?,?,?,?,?,1,1)''', [secrets.token_hex(8), rider_id, name, metric, sport, first, last, target])
    db.executemany('INSERT INTO ChallengeInvite (challengeId, tokenId) VALUES (?,?)', [(cur.lastrowid, t) for t in sorted(tokens)])
    db.commit()
    return None


def set_joined(db, challenge_id, joined):
    """Join an invitation, leave a friend's challenge, or turn an invitation down (joined False on one never joined). Commits."""
    c = db.execute('SELECT mine, joined FROM Challenge WHERE id=?', [challenge_id]).fetchone()
    if not c or c['mine']:
        return
    db.execute('UPDATE Challenge SET joined=?, dismissed=? WHERE id=?', [1 if joined else 0, 0 if joined else 1, challenge_id])
    db.commit()


def delete_challenge(db, challenge_id):
    """Only one started here: friends drop it from their lists on their next sync (or keep it, if they've joined, without us). Commits."""
    for table in ('ChallengeMember', 'ChallengeInvite'):
        db.execute(f'DELETE FROM {table} WHERE challengeId IN (SELECT id FROM Challenge WHERE id=? AND mine=1)', [challenge_id])
    db.execute('DELETE FROM Challenge WHERE id=? AND mine=1', [challenge_id])
    db.commit()


def _status(c, today):
    if today.isoformat() < c['startDate']:
        return 'upcoming'
    return 'finished' if today.isoformat() > c['endDate'] else 'on'


def challenges(db, rider_id, today=None):
    """The rider's challenges, each with its standings: {id, uid, name, title, icon, status ('upcoming', 'on', 'finished'), mine, joined,
    invitation (a friend's, not joined, not turned down), creator, start, end, days_left, target_fmt, standings [{name, avatar, value, fmt, pct,
    me, done (reached the target)}] best first, leader (the name at the top when anyone has anything), friends_missing (friends in it who have no
    rider here yet: their first sync hasn't finished)}. Invitations turned down are left out."""
    today = today or date.today()
    out = []
    for c in db.execute('SELECT * FROM Challenge WHERE riderId IS ? AND dismissed=0 ORDER BY endDate DESC, id DESC', [rider_id]).fetchall():
        first, last = date.fromisoformat(c['startDate']), date.fromisoformat(c['endDate'])
        people = []
        if c['joined']:
            me = db.execute('SELECT id, name, avatarPath FROM Rider WHERE id=?', [rider_id]).fetchone()
            if me:
                people.append((me['id'], me['name'], me['avatarPath'], True))
        for f in db.execute('''SELECT f.riderId, COALESCE(r.name, f.name) AS name, r.avatarPath FROM ChallengeMember m JOIN Friend f ON f.id = m.friendId
                               LEFT JOIN Rider r ON r.id = f.riderId WHERE m.challengeId=?''', [c['id']]).fetchall():
            people.append((f['riderId'], f['name'], f['avatarPath'], False))
        standings = []
        for rid, name, avatar, is_me in people:
            v = total(db, rid, c['metric'], c['sport'], first, min(last, today)) if rid and first <= today else 0
            standings.append({'name': name, 'avatar': avatar, 'value': v, 'fmt': fmt(c['metric'], v), 'me': is_me,
                              'done': c['target'] is not None and v >= c['target']})
        standings.sort(key=lambda s: -s['value'])
        scale = max([c['target'] or 0] + [s['value'] for s in standings]) or 1
        for s in standings:
            s['pct'] = min(100, round(100 * s['value'] / scale))
        out.append({
            'id': c['id'], 'uid': c['uid'], 'name': c['name'], 'metric': c['metric'], 'sport': c['sport'], 'icon': GROUP_ICONS[c['sport']],
            'title': describe(c['metric'], c['sport']) if c['target'] is None else f"First to {describe(c['metric'], c['sport'], c['target'])}",
            'status': _status(c, today), 'mine': bool(c['mine']), 'joined': bool(c['joined']),
            'invitation': not c['mine'] and not c['joined'], 'creator': c['creatorName'],
            'start': c['startDate'], 'end': c['endDate'], 'days_left': (last - today).days + 1,
            'target_fmt': fmt(c['metric'], c['target']) if c['target'] else None, 'standings': standings,
            'invited': [r[0] for r in db.execute('SELECT t.name FROM ChallengeInvite i JOIN FeedToken t ON t.id = i.tokenId '
                                                 'WHERE i.challengeId=? ORDER BY t.name', [c['id']])] if c['mine'] else [],
            'leader': standings[0]['name'] if standings and standings[0]['value'] > 0 else None,
            'friends_missing': [p[1] for p in people if not p[0]],
        })
    return out


# ── On the friends feed ──

def feed_lines(db, rider, token_id):
    """The 'challenge' lines for a rider's feed, as read with one friend's token: the challenges this rider started and invited that friend to,
    and the ones they joined from a friend. `own` says whether this rider started it."""
    out = []
    for c in db.execute('''SELECT * FROM Challenge c WHERE riderId=? AND joined=1
                           AND (mine=0 OR EXISTS (SELECT 1 FROM ChallengeInvite i WHERE i.challengeId = c.id AND i.tokenId=?))''',
                        [rider['id'], token_id]).fetchall():
        out.append({'type': 'challenge', 'uid': c['uid'], 'name': c['name'], 'metric': c['metric'], 'sport': c['sport'], 'startDate': c['startDate'],
                    'endDate': c['endDate'], 'target': c['target'], 'own': bool(c['mine']),
                    'creator': rider['name'] if c['mine'] else c['creatorName']})
    return out


def store_from_friend(db, friend_id, obj, rider_id):
    """One 'challenge' line from a friend's feed. A challenge we have gets the friend as a member; one we don't is an invitation for rider_id
    (the friend sync gives the instance's owner), but only from the friend who started it (`own`): a friend in someone else's challenge invites nobody.
    Details follow the friend who started it. Returns its uid, or None for a line that isn't valid or isn't for us. Does not commit."""
    uid = str(obj.get('uid') or '')
    metric, sport = obj.get('metric'), obj.get('sport') or 'all'
    first, last = _date(obj.get('startDate')), _date(obj.get('endDate'))
    if not _UID.match(uid) or check(metric, sport) or not first or not last or last < first:
        return None
    try:
        target = float(obj['target']) if obj.get('target') is not None else None
    except (TypeError, ValueError):
        return None
    if target is not None and not 0 < target < 1e12:
        return None
    name = str(obj.get('name') or '').strip()[:80] or describe(metric, sport, target)
    creator = str(obj.get('creator') or '').strip()[:60] or None
    row = db.execute('SELECT id, mine FROM Challenge WHERE uid=?', [uid]).fetchone()
    if row is None and not obj.get('own'):
        return None
    if row is None:
        cur = db.execute('''INSERT INTO Challenge (uid, riderId, name, metric, sport, startDate, endDate, target, creatorName, viaFriendId)
                            VALUES (?,?,?,?,?,?,?,?,?,?)''', [uid, rider_id, name, metric, sport, first, last, target, creator, friend_id])
        cid = cur.lastrowid
    else:
        cid = row['id']
        if obj.get('own') and not row['mine']:          # the one who started it changed it
            db.execute('UPDATE Challenge SET name=?, metric=?, sport=?, startDate=?, endDate=?, target=?, creatorName=? WHERE id=?',
                       [name, metric, sport, first, last, target, creator, cid])
    db.execute('INSERT OR IGNORE INTO ChallengeMember (challengeId, friendId) VALUES (?,?)', [cid, friend_id])
    return uid


def forget_missing(db, friend_id, seen):
    """After a complete sync: the friend is out of every challenge their feed no longer lists, and an invitation that came only from them and was
    never joined goes. Does not commit."""
    seen = list(seen)
    marks = ','.join('?' * len(seen)) or "''"
    db.execute(f'''DELETE FROM ChallengeMember WHERE friendId=? AND challengeId IN (SELECT id FROM Challenge WHERE uid NOT IN ({marks}))''',
               [friend_id, *seen])
    db.execute(f'''DELETE FROM Challenge WHERE mine=0 AND joined=0 AND viaFriendId=? AND uid NOT IN ({marks})
                   AND NOT EXISTS (SELECT 1 FROM ChallengeMember m WHERE m.challengeId = Challenge.id)''', [friend_id, *seen])


def forget_friend(db, friend_id):
    """A friend removed: out of every challenge, their invitations gone. Does not commit."""
    db.execute('DELETE FROM ChallengeMember WHERE friendId=?', [friend_id])
    db.execute('DELETE FROM Challenge WHERE mine=0 AND joined=0 AND viaFriendId=?', [friend_id])
    db.execute('UPDATE Challenge SET viaFriendId=NULL WHERE viaFriendId=?', [friend_id])


def forget_rider(db, rider_id):
    """A rider deleted: their goals and challenges go. Does not commit."""
    db.execute('DELETE FROM Goal WHERE riderId=?', [rider_id])
    for table in ('ChallengeMember', 'ChallengeInvite'):
        db.execute(f'DELETE FROM {table} WHERE challengeId IN (SELECT id FROM Challenge WHERE riderId=?)', [rider_id])
    db.execute('DELETE FROM Challenge WHERE riderId=?', [rider_id])
