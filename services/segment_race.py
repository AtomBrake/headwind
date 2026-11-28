"""The segment race ("Mates Race"): a challenge (services/challenges.py) of metric 'segments'. One to five segments of one family and one class
(services/sports.segment_class: 'bike', 'ebike' or 'foot'), each rider's fastest time on each between the first and the last day, and an overall
standing on points by place.

The segments go with the challenge as their shapes (ChallengeSegment), not as ids: our feed sends only our own segments (routes/friends.feed), so
the 'challenge' line carries them, and a friend who joined passes them on to a third rider. Each instance finds its own segment for each shape
(find_local): same family, both ends within TOLERANCE_M, a length within LENGTH_TOL, and a shape that runs along the local one (_shape_gap), so a
sibling with the same ends (services/segments.siblings_of) isn't taken for it. Our own segment first, then a friend's. With none, the shape is
added as a segment of the friend whose line brought it, challengeOnly=1 and matchPending=1: the friend sync's pending pass matches every activity
against it, it is never sent on, it isn't on the Segments page, and it goes when no race refers to it (drop_orphans). If the friend later sends
the same segment as a 'segment' line, routes/friends._store_segment takes that row over (take_over).

Every instance works the standings out itself, from SegmentEffort on the activities it has: our own and the ones friends share. An approximate
(close) effort doesn't count, as it never takes a PR; nor does one of another class (an e-bike ride in a pedal race). A friend on a Headwind from
before the race drops the line (its services/goals.check refuses the metric), so they're never in it.
"""
import json
from datetime import date

from services import sports
from services.segments import (CHECKPOINT_M, TOLERANCE_M, _near, _offsets, _off_line, _path_length_m, _sample_checkpoints, _window, clean_polyline,
                               seg_sport, siblings_of, valid_coord)

MAX_SEGMENTS = 5
POINTS = (10, 8, 6, 5, 4, 3, 2, 1)       # by place on each segment; ninth and lower score nothing
LENGTH_TOL = 0.05                        # a local segment's length within this share of the sent one's
SHAPE_APART_M = 20                       # two shapes are one line while neither runs further than this from the other ...
SHAPE_RUN_M = 20                         # ... for more than this far in a row. A sibling runs 25-40 m away for hundreds of metres
CLASS_FAMILY = {'bike': 'ride', 'ebike': 'ride', 'foot': 'foot'}      # a race's class, and the segments (and Challenge.sport) it has


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS ChallengeSegment (
        challengeId    INTEGER NOT NULL REFERENCES Challenge(id) ON DELETE CASCADE,
        position       INTEGER NOT NULL,             -- 1 to MAX_SEGMENTS
        segmentId      INTEGER REFERENCES Segment(id) ON DELETE SET NULL,   -- the local one it was matched to (find_local); NULL: not yet
        sourceSegId    INTEGER,                      -- the segment's id on the instance whose line brought it, when it is that one's own
        sourceFriendId INTEGER REFERENCES Friend(id),-- ... and that friend (NULL: picked here)
        name           TEXT NOT NULL,                -- the shape as it was sent, so the race can find its segment again
        startLat       REAL NOT NULL,
        startLng       REAL NOT NULL,
        endLat         REAL NOT NULL,
        endLng         REAL NOT NULL,
        distanceM      REAL,
        elevationGainM REAL,
        polyline       TEXT,
        family         TEXT NOT NULL,
        leaderRiderId  INTEGER,                      -- who held the top spot when last checked (notify_leaders), so each change is sent once
        leaderSecs     INTEGER,
        PRIMARY KEY (challengeId, position)
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS ChallengeSeen (       -- the boards as a rider last saw them, for the page's "new" marks
        challengeId INTEGER NOT NULL REFERENCES Challenge(id) ON DELETE CASCADE,
        riderId     INTEGER NOT NULL,
        board       TEXT NOT NULL,                   -- {"position": {"riderId": secs}}
        seenAt      TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (challengeId, riderId)
    )''')


def check(seg_class):
    """An error text for a class a race can't have, else None."""
    return None if seg_class in CLASS_FAMILY else 'Pick a bike, an e-bike or on foot.'


# ── Shapes ──

def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) < 1e9 else None


def clean(obj):
    """A segment as a 'challenge' line or the start form sends it, checked: {name, startLat, startLng, endLat, endLng, distanceM, elevationGainM,
    polyline (JSON text or None), family, sourceSegId}, or None for one with impossible ends or no length."""
    if not isinstance(obj, dict):
        return None
    s = valid_coord(obj.get('startLat'), obj.get('startLng'))
    e = valid_coord(obj.get('endLat'), obj.get('endLng'))
    shape = clean_polyline(obj.get('polyline'))
    dist = _num(obj.get('distanceM'))
    if dist is None and shape:
        dist = _path_length_m(shape)
    if not s or not e or not dist or dist <= 0:
        return None
    src = obj.get('id')
    return {'name': str(obj.get('name') or 'Segment').strip()[:80] or 'Segment', 'startLat': s[0], 'startLng': s[1], 'endLat': e[0],
            'endLng': e[1], 'distanceM': dist, 'elevationGainM': _num(obj.get('elevationGainM')),
            'polyline': json.dumps(shape) if shape else None, 'family': seg_sport({'sport': obj.get('family') or obj.get('sport')}),
            'sourceSegId': src if isinstance(src, int) and not isinstance(src, bool) else None}


def _longest_apart(offsets):
    run = best = prev = 0.0
    for step, off in offsets:
        run = run + step if off > SHAPE_APART_M and prev > SHAPE_APART_M else 0.0
        best = max(best, run)
        prev = off
    return best


def _shape_gap(a, b):
    """The mean distance in metres of shape a from shape b (lists of [lat, lng]) when they're one line, else None. One line: a's checkpoints
    within CHECKPOINT_M of b, and neither runs further than SHAPE_APART_M from the other for more than SHAPE_RUN_M (a sibling, the other way
    down the same hill 25-40 m off, passes the checkpoints but not that)."""
    if any(_off_line(p[0], p[1], b) > CHECKPOINT_M for p in _sample_checkpoints(json.dumps(a))):
        return None
    ab, ba = _offsets(a, 0, len(a) - 1, b), _offsets(b, 0, len(b) - 1, a)
    if _longest_apart(ab) > SHAPE_RUN_M or _longest_apart(ba) > SHAPE_RUN_M:
        return None
    length = sum(step for step, _ in ab)
    return sum(step * off for step, off in ab) / length if length else 0.0


def _same(sent, local, pool):
    """How far apart (a sort key, lower is nearer) when the local segment row is the sent shape, else None. A sent shape with no line is only
    the local one when that has no siblings (nothing to tell them apart by)."""
    if seg_sport(local) != sent['family']:
        return None
    if _near(_window(sent['startLat'], sent['startLng'], TOLERANCE_M), local['startLat'], local['startLng'], TOLERANCE_M) is None \
            or _near(_window(sent['endLat'], sent['endLng'], TOLERANCE_M), local['endLat'], local['endLng'], TOLERANCE_M) is None:
        return None
    if not local['distanceM'] or abs(local['distanceM'] - sent['distanceM']) > LENGTH_TOL * sent['distanceM']:
        return None
    mine, theirs = clean_polyline(sent['polyline']), clean_polyline(local['polyline'])
    if not mine:
        return 0.0 if not siblings_of(local, pool) else None
    if not theirs:
        return None
    return _shape_gap(mine, theirs)


def find_local(db, sent):
    """The id of the local segment that is this sent shape (clean), or None: ours first, then a friend's, then one already here only for a
    race; the nearest shape of those."""
    w = _window(sent['startLat'], sent['startLng'], TOLERANCE_M)
    near = db.execute("SELECT * FROM Segment WHERE startLat BETWEEN ? AND ? AND startLng BETWEEN ? AND ? AND COALESCE(sport, 'ride') = ?",
                      [w[0] - w[2], w[0] + w[2], w[1] - w[3], w[1] + w[3], sent['family']]).fetchall()
    best = None
    for s in near:
        gap = _same(sent, s, near)
        if gap is None:
            continue
        key = (2 if s['challengeOnly'] else 1 if s['friendId'] else 0, gap, s['id'])
        if best is None or key < best:
            best = key
    return best[2] if best else None


def take_over(db, friend_id, sent, source_id):
    """routes/friends._store_segment, for a friend's segment line it hasn't seen: the id of a segment here only for a race that is this one
    (its own row, by the id the race line gave, or any by shape), made an ordinary segment of theirs; None when there's none. Does not commit."""
    row = db.execute('SELECT id FROM Segment WHERE challengeOnly=1 AND friendId=? AND sourceSegId=?', [friend_id, source_id]).fetchone()
    sid = row[0] if row else None
    if sid is None:
        w = _window(sent['startLat'], sent['startLng'], TOLERANCE_M)
        near = db.execute("SELECT * FROM Segment WHERE startLat BETWEEN ? AND ? AND startLng BETWEEN ? AND ? AND COALESCE(sport, 'ride') = ?",
                          [w[0] - w[2], w[0] + w[2], w[1] - w[3], w[1] + w[3], sent['family']]).fetchall()
        hits = sorted((g, s['id']) for s in near if s['challengeOnly'] for g in [_same(sent, s, near)] if g is not None)
        sid = hits[0][1] if hits else None
    if sid is None:
        return None
    db.execute('UPDATE Segment SET challengeOnly=0, friendId=?, sourceSegId=? WHERE id=?', [friend_id, source_id, sid])
    return sid


def set_segments(db, challenge_id, shapes, friend_id=None):
    """The race's segments, from the start form or a friend's line (friend_id: whose): shapes in order, each clean(). A position whose shape is
    the same as before keeps the segment it was matched to. Then resolve(). Does not commit."""
    old = {r['position']: r for r in db.execute('SELECT * FROM ChallengeSegment WHERE challengeId=?', [challenge_id])}
    keys = ('name', 'startLat', 'startLng', 'endLat', 'endLng', 'distanceM', 'elevationGainM', 'polyline', 'family')
    for pos, s in enumerate(shapes, 1):
        was = old.pop(pos, None)
        same = was is not None and all(was[k] == s[k] for k in keys if k != 'name')
        if same:
            db.execute('UPDATE ChallengeSegment SET name=?, sourceSegId=COALESCE(?, sourceSegId) WHERE challengeId=? AND position=?',
                       [s['name'], s['sourceSegId'], challenge_id, pos])
            continue
        db.execute('DELETE FROM ChallengeSegment WHERE challengeId=? AND position=?', [challenge_id, pos])
        db.execute(f'''INSERT INTO ChallengeSegment (challengeId, position, sourceSegId, sourceFriendId, {', '.join(keys)})
                       VALUES (?,?,?,?,{','.join('?' * len(keys))})''', [challenge_id, pos, s['sourceSegId'], friend_id, *(s[k] for k in keys)])
    for pos in old:
        db.execute('DELETE FROM ChallengeSegment WHERE challengeId=? AND position=?', [challenge_id, pos])
    resolve(db, challenge_id, friend_id)
    drop_orphans(db)


def resolve(db, challenge_id, friend_id=None):
    """Find each of the race's segments here that hasn't got one (new, or the one it had has gone): find_local, else a segment added for the
    race (challengeOnly), of the friend whose line brought it (friend_id, else the friend the shape came from). Its first leader is noted
    without a notification. Returns the ids of the segments added, which need matching against every activity (the friend sync's pending pass
    does it for a friend's; the caller for one with no friend). Does not commit."""
    added = []
    if friend_id:
        # One kept with no friend (theirs went): this friend has the race, so it's theirs now, and their sync matches it
        db.execute('''UPDATE Segment SET friendId=?, matchPending=1 WHERE challengeOnly=1 AND friendId IS NULL
                      AND id IN (SELECT segmentId FROM ChallengeSegment WHERE challengeId=?)''', [friend_id, challenge_id])
    for cs in db.execute('''SELECT cs.* FROM ChallengeSegment cs LEFT JOIN Segment s ON s.id = cs.segmentId
                            WHERE cs.challengeId=? AND s.id IS NULL''', [challenge_id]).fetchall():
        sent = dict(cs)
        sid = find_local(db, sent)
        if sid is None:
            fid = friend_id or cs['sourceFriendId']
            if fid and not db.execute('SELECT 1 FROM Friend WHERE id=?', [fid]).fetchone():
                fid = None
            src = cs['sourceSegId'] if fid and fid == cs['sourceFriendId'] else None
            sid = db.execute('''INSERT INTO Segment (name, startLat, startLng, endLat, endLng, distanceM, elevationGainM, polyline, sport, friendId,
                                                     sourceSegId, matchPending, challengeOnly) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)''',
                             [cs['name'], cs['startLat'], cs['startLng'], cs['endLat'], cs['endLng'], cs['distanceM'], cs['elevationGainM'],
                              cs['polyline'], cs['family'], fid, src, 1 if fid else 0]).lastrowid
            added.append(sid)
        db.execute('UPDATE ChallengeSegment SET segmentId=? WHERE challengeId=? AND position=?', [sid, challenge_id, cs['position']])
    if added:
        unfriended = [s for s in added if db.execute('SELECT friendId FROM Segment WHERE id=?', [s]).fetchone()[0] is None]
        if unfriended:
            from routes.segments import queue_scan           # no friend sync will match these: the worker does
            queue_scan(db, unfriended)
    return added


def drop_orphans(db):
    """Delete the segments here only for a race that no race refers to any more (one turned down doesn't), and their efforts. Does not commit."""
    gone = [r[0] for r in db.execute('''SELECT id FROM Segment WHERE challengeOnly=1 AND id NOT IN (
                                          SELECT cs.segmentId FROM ChallengeSegment cs JOIN Challenge c ON c.id = cs.challengeId
                                          WHERE cs.segmentId IS NOT NULL AND c.dismissed=0)''')]
    if gone:
        marks = ','.join('?' * len(gone))
        db.execute(f'DELETE FROM SegmentEffort WHERE segmentId IN ({marks})', gone)
        db.execute(f'UPDATE ChallengeSegment SET segmentId=NULL WHERE segmentId IN ({marks})', gone)
        db.execute(f'DELETE FROM Segment WHERE id IN ({marks})', gone)
    return gone


def forget(db, where, args):
    """The race parts of the challenges `where` picks (SQL on Challenge), before they're deleted. Does not commit."""
    for table in ('ChallengeSegment', 'ChallengeSeen'):
        db.execute(f'DELETE FROM {table} WHERE challengeId IN (SELECT id FROM Challenge WHERE {where})', args)


def line_segments(db, challenge_id, zones=None):
    """A race's segments for its 'challenge' line, the fields a 'segment' line has, plus position. `id` only on one that is the sender's own
    (sent as a segment line too), so the friend can tell their copy of it later. One that starts or ends in the sender's privacy zones (a
    Hider) is left out, as the segment lines leave it out."""
    out = []
    for cs in db.execute('''SELECT cs.*, s.friendId, s.challengeOnly FROM ChallengeSegment cs LEFT JOIN Segment s ON s.id = cs.segmentId
                            WHERE cs.challengeId=? ORDER BY cs.position''', [challenge_id]):
        if zones and (zones.inside(cs['startLat'], cs['startLng']) or zones.inside(cs['endLat'], cs['endLng'])):
            continue
        own = cs['segmentId'] is not None and cs['friendId'] is None and not cs['challengeOnly']
        out.append({'position': cs['position'], **({'id': cs['segmentId']} if own else {}), 'name': cs['name'], 'startLat': cs['startLat'],
                    'startLng': cs['startLng'], 'endLat': cs['endLat'], 'endLng': cs['endLng'], 'distanceM': cs['distanceM'],
                    'elevationGainM': cs['elevationGainM'], 'polyline': cs['polyline'], 'family': cs['family'],
                    'sport': 'run' if cs['family'] == 'foot' else 'ride'})
    return out


# ── Picking segments to race ──

def pickable(db, rider_id):
    """The segments the start form offers: our own and friends', not ones here only for a race, and not one that starts or ends in the rider's
    privacy zones. [{id, name, family, distanceM, elevationGainM, friend}] by family, then name."""
    from services import privacy_zones
    zones = privacy_zones.hider(db, rider_id)
    out = []
    for s in db.execute('''SELECT s.id, s.name, COALESCE(s.sport, 'ride') AS family, s.distanceM, s.elevationGainM, s.startLat, s.startLng,
                                  s.endLat, s.endLng, f.name AS friend FROM Segment s LEFT JOIN Friend f ON f.id = s.friendId
                           WHERE COALESCE(s.challengeOnly, 0) = 0 ORDER BY family, s.name COLLATE NOCASE, s.id'''):
        if zones and (zones.inside(s['startLat'], s['startLng']) or zones.inside(s['endLat'], s['endLng'])):
            continue
        out.append({k: s[k] for k in ('id', 'name', 'family', 'distanceM', 'elevationGainM', 'friend')})
    return out


def picked(db, rider_id, ids, seg_class):
    """The shapes for a race of these segment ids (in the order picked), or an error text. 1 to MAX_SEGMENTS of them, all of the class's
    family, none in the rider's privacy zones, none here only for a race."""
    from services import privacy_zones
    if check(seg_class):
        return check(seg_class)
    ids = list(dict.fromkeys(ids))
    if not ids:
        return 'Pick at least one segment.'
    if len(ids) > MAX_SEGMENTS:
        return f'A race has at most {MAX_SEGMENTS} segments.'
    zones = privacy_zones.hider(db, rider_id)
    out = []
    for sid in ids:
        s = db.execute('SELECT * FROM Segment WHERE id=? AND COALESCE(challengeOnly, 0) = 0', [sid]).fetchone()
        if not s:
            return 'One of those segments has gone. Pick again.'
        if seg_sport(s) != CLASS_FAMILY[seg_class]:
            return ('A race on foot needs segments on foot.' if seg_class == 'foot' else 'A race on a bike needs ride segments.')
        if zones and (zones.inside(s['startLat'], s['startLng']) or zones.inside(s['endLat'], s['endLng'])):
            return f'“{s["name"]}” starts or ends in one of your privacy zones, so it can’t go to friends.'
        shape = clean({**dict(s), 'family': seg_sport(s), 'id': None})
        if not shape:
            return f'“{s["name"]}” has no length to race.'
        out.append(shape)
    return out


# ── Standings ──

def _riders_sql(n):
    return ','.join('?' * n)


def boards(db, c, people, today=None):
    """The race's segments with each rider's best time, and the overall standing. c: the Challenge row; people: [(riderId, name, avatar, me)].
    {segments: [{position, id (the local segment), name, distanceM, elevationGainM, shape, board: [{rider_id, name, avatar, me, secs, date,
    activity_id, activity_name, place, points}], leader}], overall: [{rider_id, name, avatar, me, points, wins, secs, done, place}]}.
    A rider with no riderId yet (their first sync hasn't finished) isn't on it."""
    today = today or date.today()
    last = min(c['endDate'], today.isoformat())
    riders = {p[0]: p for p in people if p[0]}
    keep = sports.class_sql(c['segClass'])
    segs = []
    for cs in db.execute('SELECT * FROM ChallengeSegment WHERE challengeId=? ORDER BY position', [c['id']]).fetchall():
        board = []
        if cs['segmentId'] and riders and c['startDate'] <= last:
            seen = set()
            for e in db.execute(f'''
                SELECT e.elapsedSecs, e.activityDate, e.startSecs, a.id AS activityId, a.name AS activityName, a.riderId
                FROM SegmentEffort e JOIN SegActivity a ON a.id = e.activityId LEFT JOIN Bike b ON b.id = a.bikeId
                WHERE e.segmentId=? AND COALESCE(e.approx, 0) = 0 AND a.riderId IN ({_riders_sql(len(riders))})
                  AND date(a.startDateLocal) BETWEEN ? AND ? AND {keep}
                ORDER BY e.elapsedSecs, e.activityDate, COALESCE(e.startSecs, 0), e.id''',
                    [cs['segmentId'], *riders, c['startDate'], last]):
                if e['riderId'] in seen:
                    continue                                    # their faster lap (or the same time, set earlier) is in already
                seen.add(e['riderId'])
                rid, name, avatar, me = riders[e['riderId']]
                place = len(board) + 1
                board.append({'rider_id': rid, 'name': name, 'avatar': avatar, 'me': me, 'secs': e['elapsedSecs'], 'date': e['activityDate'],
                              'activity_id': e['activityId'], 'activity_name': e['activityName'], 'place': place,
                              'points': POINTS[place - 1] if place <= len(POINTS) else 0})
        segs.append({'position': cs['position'], 'id': cs['segmentId'], 'name': cs['name'], 'distanceM': cs['distanceM'],
                     'elevationGainM': cs['elevationGainM'], 'shape': clean_polyline(cs['polyline']),
                     'start': [cs['startLat'], cs['startLng']], 'end': [cs['endLat'], cs['endLng']], 'board': board,
                     'leader': board[0] if board else None, 'leader_was': (cs['leaderRiderId'], cs['leaderSecs'])})
    overall = {rid: {'rider_id': rid, 'name': p[1], 'avatar': p[2], 'me': p[3], 'points': 0, 'wins': 0, 'secs': 0, 'done': 0}
               for rid, p in riders.items()}
    for s in segs:
        for row in s['board']:
            o = overall[row['rider_id']]
            o['points'] += row['points']
            o['wins'] += row['place'] == 1
            o['secs'] += row['secs']
            o['done'] += 1
    table = sorted(overall.values(), key=lambda o: (-o['points'], -o['wins'], o['secs'] if o['done'] else float('inf'), o['name'] or ''))
    for i, o in enumerate(table, 1):
        o['place'] = i
    return {'segments': segs, 'overall': table}


# ── What's new since the rider last looked ──

def snapshot(race):
    return {str(s['position']): {str(r['rider_id']): r['secs'] for r in s['board']} for s in race['segments']}


def mark_new(db, challenge_id, rider_id, race):
    """Mark the times that are new since the rider last saw the race (ChallengeSeen): a rider not on that segment's board then, or with
    another time. Nothing is new the first time they look. Returns how many."""
    row = db.execute('SELECT board FROM ChallengeSeen WHERE challengeId=? AND riderId=?', [challenge_id, rider_id]).fetchone()
    try:
        seen = json.loads(row[0]) if row else None
    except (TypeError, ValueError):
        seen = None
    n = 0
    for s in race['segments']:
        was = (seen or {}).get(str(s['position'])) or {}
        for r in s['board']:
            r['new'] = seen is not None and was.get(str(r['rider_id'])) != r['secs']
            n += r['new']
    return n


def seen(db, challenge_id, rider_id, race):
    """The race as the rider has now seen it. Commits."""
    db.execute('''INSERT INTO ChallengeSeen (challengeId, riderId, board, seenAt) VALUES (?,?,?,datetime('now'))
                  ON CONFLICT(challengeId, riderId) DO UPDATE SET board=excluded.board, seenAt=excluded.seenAt''',
               [challenge_id, rider_id, json.dumps(snapshot(race), separators=(',', ':'))])
    db.commit()


# ── Notifications ──

def fmt_secs(secs):
    """12:34 or 1:02:03, as the pages' fmt_duration shows a segment time."""
    h, rem = divmod(int(secs or 0), 3600)
    m, s = divmod(rem, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


def notify_leaders(db, send=True, today=None, challenge_id=None):
    """Each segment of the races that are on and that the rider here is in: when its top spot has a new holder (or the holder a new time), the
    change is noted on ChallengeSegment and, with send, sent as a notification (services/notify), once. A segment whose leader was never
    noted (a race just started or joined, a segment new to it) is noted without one; one noted with nobody on it notifies its first leader.
    challenge_id: that race alone. Returns the texts sent. Never raises; does not commit (a caller in the middle of an import commits
    it with the rest)."""
    out = []
    try:
        from services import challenges
        today = today or date.today()
        rows = db.execute('''SELECT * FROM Challenge WHERE metric='segments' AND joined=1 AND dismissed=0 AND endDate >= ?
                             AND (? IS NULL OR id=?)''', [today.isoformat(), challenge_id, challenge_id]).fetchall()
        for c in rows:
            race = boards(db, c, challenges.people(db, c), today)
            for s in race['segments']:
                lead = s['leader']
                now = (lead['rider_id'], lead['secs']) if lead else (None, 0)       # (None, 0): noted, nobody on it yet
                was = tuple(s['leader_was'])
                if now == was:
                    continue
                db.execute('UPDATE ChallengeSegment SET leaderRiderId=?, leaderSecs=? WHERE challengeId=? AND position=?',
                           [now[0], now[1], c['id'], s['position']])
                if lead and was != (None, None) and lead['rider_id'] != was[0]:
                    out.append((c, s, lead))
        if send and out:
            from services import external_url, notify
            base = external_url.get()
            for c, s, lead in out:
                notify.send_notification(f'{c["name"]}: {"you" if lead["me"] else lead["name"]} took {s["name"]}',
                                         f'{fmt_secs(lead["secs"])}, the fastest on {s["name"]} now.',
                                         f'{base}/challenges/{c["id"]}' if base else None)
    except Exception:
        import logging
        logging.getLogger(__name__).warning('Checking the segment races for new leaders failed', exc_info=True)
    return [f'{c["name"]}: {lead["name"]} took {s["name"]}' for c, s, lead in out]
