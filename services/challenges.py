"""Challenges with friends: a race over set dates, the most (or first to a target) of distance, climbing, time or activities, for one group of
sports (services/goals.GROUPS). They have their own page (routes/challenges.py) and feature switch, 'challenges' (services/features.py); they
used to be the second half of the Goals page. The values, the titles and the totals are the goals' own (services/goals).

A challenge travels on the friends feed (routes/friends.feed) as 'challenge' lines, each with a uid made where it was started. One started here
goes only to the friends invited, by their feed token (ChallengeInvite); one joined from a friend goes to every friend we share with, marked as
not ours, so the others in it see us in it but nobody gets an invitation from anyone but the friend who started it. When the starter's feed
brings one this instance doesn't have, it is shown as an invitation; when any friend's feed brings one we have, that friend is in it
(ChallengeMember). Every instance works out the standings itself, from its own activities and the ones its friends share with it, so nobody's
numbers are sent twice and a friend whose activities we can't see can't be in the race here. A challenge the friend no longer lists (they left, or
deleted the one they started) loses them on their next complete sync.

The feed and the sync carry challenges whether or not the switch is on: it hides the page and the dashboard's rows, and switching it back on finds
every race as up to date as the activities are.
"""
import re
import secrets
from datetime import date

from services.goals import GROUP_ICONS, check, describe, fmt, to_stored, total, unit_label

_UID = re.compile(r'^[0-9a-f]{8,40}$')


def ensure_schema(db):
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


def _date(text):
    try:
        return date.fromisoformat(str(text or '').strip()[:10]).isoformat()
    except ValueError:
        return None


def invitable(db):
    """The feed tokens a challenge can go to: not revoked, and sharing activities (a race needs them). [{id, name}]"""
    return [dict(r) for r in db.execute('SELECT id, name FROM FeedToken WHERE revokedAt IS NULL AND shareActivities=1 ORDER BY name')]


def start_challenge(db, rider_id, form):
    """A challenge started here, from the Challenges page's form (name, metric, sport, startDate, endDate, target in the rider's units or blank,
    and `tokens`: the ids of the friends' feed tokens it goes to). Returns an error text, or None. Commits."""
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
    """A rider deleted: their challenges go. Does not commit."""
    for table in ('ChallengeMember', 'ChallengeInvite'):
        db.execute(f'DELETE FROM {table} WHERE challengeId IN (SELECT id FROM Challenge WHERE riderId=?)', [rider_id])
    db.execute('DELETE FROM Challenge WHERE riderId=?', [rider_id])
