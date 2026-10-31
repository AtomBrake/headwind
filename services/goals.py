"""Goals and friend challenges: distance, climbing, time or a count of activities, for one kind of sport or for all of them.

A goal is the rider's own target for every week, month or year ("100 mi of riding a week", "50,000 ft of climbing this year"), measured from their
activities as they are now, so a deleted or re-typed activity moves it straight away. Nothing is stored but the target.

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
from datetime import date, timedelta

from services import sports, units

METRICS = ('distance', 'climb', 'time', 'count')
METRIC_LABELS = {'distance': 'Distance', 'climb': 'Climbing', 'time': 'Time', 'count': 'Activities'}
PERIODS = ('week', 'month', 'year')
PERIOD_LABELS = {'week': 'a week', 'month': 'a month', 'year': 'a year'}
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
        sport     TEXT NOT NULL DEFAULT 'all',    -- GROUPS
        target    REAL NOT NULL,                  -- metres, seconds or a count
        createdAt TEXT DEFAULT (datetime('now'))
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


def describe(metric, sport, target=None, period=None):
    """'100 mi of rides a week', 'The most climbing, every sport', ..."""
    what = {'distance': 'distance', 'climb': 'climbing', 'time': 'time', 'count': 'activities'}[metric]
    on = '' if sport == 'all' else f" ({GROUP_LABELS[sport].lower()})"
    if target is None:
        return f'The most {what}{on}'
    return f"{fmt(metric, target)} of {what}{on}" + (f' {PERIOD_LABELS[period]}' if period else '')


def check(metric, sport, period=None):
    """An error text for a combination that can't be measured, else None. A distance needs one kind of sport: a swim's metres never add to a
    ride's miles (services/sport_filter), and there's no climbing in the water."""
    if metric not in METRICS or sport not in GROUPS or (period is not None and period not in PERIODS):
        return 'Pick what to count, the sport and how often.'
    if metric == 'distance' and sport == 'all':
        return 'A distance goal needs one kind of sport: a swim’s distance doesn’t add to a ride’s.'
    if metric == 'climb' and sport == 'swim':
        return 'Swims have no climbing.'
    return None


# ── Totals ──

def _rows(db, rider_id, first, last):
    """(day, sportType, distance, movingTime, climb) of the rider's activities from first to last (dates, inclusive)."""
    return db.execute(f'''SELECT date(startDateLocal), sportType, distance, movingTime, {sports.climb_sql()}
                          FROM Activity WHERE riderId=? AND date(startDateLocal) BETWEEN ? AND ?''',
                      [rider_id, first.isoformat(), last.isoformat()]).fetchall()


def _value(metric, row):
    return {'distance': row[2], 'climb': row[4], 'time': row[3], 'count': 1}[metric] or 0


def _counts(sport, sport_type):
    return sport == 'all' or sports.stat_group(sport_type) == sport


def total(db, rider_id, metric, sport, first, last):
    return sum(_value(metric, r) for r in _rows(db, rider_id, first, last) if _counts(sport, r[1]))


def period_bounds(period, day):
    """(first, last) day of the week (Monday to Sunday), month or year that `day` is in."""
    if period == 'week':
        first = day - timedelta(days=day.weekday())
        return first, first + timedelta(days=6)
    if period == 'month':
        first = day.replace(day=1)
        return first, (first.replace(year=first.year + 1, month=1) if first.month == 12 else first.replace(month=first.month + 1)) - timedelta(days=1)
    return date(day.year, 1, 1), date(day.year, 12, 31)


def _period_label(period, first):
    from services.dates import day_month
    if period == 'week':
        return day_month(first)
    if period == 'month':
        return first.strftime('%b %Y')
    return str(first.year)


# ── Goals ──

def add_goal(db, rider_id, metric, period, sport, target_text):
    """Returns an error text, or None once it's saved. Commits."""
    err = check(metric, sport, period)
    if err:
        return err
    try:
        target = to_stored(metric, target_text)
    except (TypeError, ValueError):
        return f'Type the target as a number of {unit_label(metric)}.'
    db.execute('INSERT INTO Goal (riderId, metric, period, sport, target) VALUES (?,?,?,?,?)', [rider_id, metric, period, sport, target])
    db.commit()
    return None


def delete_goal(db, rider_id, goal_id):
    db.execute('DELETE FROM Goal WHERE id=? AND riderId=?', [goal_id, rider_id])
    db.commit()


def goals(db, rider_id, today=None):
    """Each of the rider's goals with where it stands: {id, metric, period, sport, target, title, icon, done, pct, expected (where an even pace
    would be by the end of today), status ('done', 'ahead', 'behind'), to_go, per_day (needed each day left, including today), days_left,
    history [{label, value, pct, hit}] oldest first (the periods before this one), streak (periods hit in a row before this one), period_label}."""
    today = today or date.today()
    out = []
    for g in db.execute('SELECT * FROM Goal WHERE riderId=? ORDER BY period, sport, metric', [rider_id]).fetchall():
        first, last = period_bounds(g['period'], today)
        n_hist = HISTORY[g['period']]
        starts = [first]
        for _ in range(n_hist):
            starts.insert(0, period_bounds(g['period'], starts[0] - timedelta(days=1))[0])
        rows = _rows(db, rider_id, starts[0], last)
        sums = dict.fromkeys(starts, 0)
        for r in rows:
            if _counts(g['sport'], r[1]):
                d = date.fromisoformat(r[0])
                sums[period_bounds(g['period'], d)[0]] += _value(g['metric'], r)
        done, target = sums[first], g['target']
        days, days_left = (last - first).days + 1, (last - today).days + 1
        expected = target * (days - days_left + 1) / days
        history = [{'label': _period_label(g['period'], s), 'value': sums[s], 'fmt': fmt(g['metric'], sums[s]),
                    'pct': min(100, round(100 * sums[s] / target)), 'hit': sums[s] >= target} for s in starts[:-1]]
        streak = 0
        for h in reversed(history):
            if not h['hit']:
                break
            streak += 1
        out.append({
            'id': g['id'], 'metric': g['metric'], 'period': g['period'], 'sport': g['sport'], 'target': target,
            'title': describe(g['metric'], g['sport'], target, g['period']), 'icon': GROUP_ICONS[g['sport']],
            'done': done, 'done_fmt': fmt(g['metric'], done), 'target_fmt': fmt(g['metric'], target),
            'pct': min(100, round(100 * done / target)), 'expected_pct': min(100, round(100 * expected / target)),
            'status': 'done' if done >= target else ('ahead' if done >= expected else 'behind'),
            'to_go_fmt': fmt(g['metric'], max(0, target - done)),
            'per_day_fmt': fmt(g['metric'], max(0, target - done) / days_left) if g['metric'] != 'count' else None,
            'days_left': days_left, 'history': history, 'streak': streak,
            'period_label': {'week': 'This week', 'month': first.strftime('%B'), 'year': str(first.year)}[g['period']],
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
    return [dict(r) for r in db.execute('SELECT id, name FROM FeedToken WHERE revokedAt IS NULL AND shareRides=1 ORDER BY name')]


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


def store_from_friend(db, friend_id, obj):
    """One 'challenge' line from a friend's feed. A challenge we have gets the friend as a member; one we don't is an invitation for the
    instance's own rider (the default one), but only from the friend who started it (`own`): a friend in someone else's challenge invites nobody.
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
        owner = db.execute('SELECT id FROM Rider WHERE isDefault=1').fetchone()
        cur = db.execute('''INSERT INTO Challenge (uid, riderId, name, metric, sport, startDate, endDate, target, creatorName, viaFriendId)
                            VALUES (?,?,?,?,?,?,?,?,?,?)''', [uid, owner[0] if owner else None, name, metric, sport, first, last, target, creator, friend_id])
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
