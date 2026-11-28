"""A live tracking link: while a rider records, a link that anyone they send it to opens in a browser, with no account, to see where they
are, the track so far, and the distance, time and speed or pace (GET /live/<token>, routes/live_share.py).

The phone starts a share for the recording in progress (POST /api/v1/live/share) and keeps posting /api/v1/live, which carries the
recording's id (`recording`), as it did before for Home Assistant (services/live.py). Each reading for that recording is kept on the share
(its last one) and, thinned to a point every THIN_S seconds or THIN_M metres, as the track so far (LivePoint), both in the database: a
reading posted to one web process shows on a page another serves, and a restart mid-ride loses nothing.

A share ends when the recording does (an idle reading), and its link works for AFTER_END_S more, then expires. One that hears nothing for
SILENT_S expires too (a phone that died). Stopping a share revokes it at once. The worker deletes an expired or revoked share's points
(sweep): the saved activity is the record. An unknown, revoked or expired token all read as None, so the page can't tell a guess from a
link that has ended.

What the page shows is only this share's: the sport, the figures, the track, and the rider's first name. Points within HIDE_START_M of
where the share's track began are never shown, nor the position while it's there, so the link doesn't show where the ride started (home,
usually) or where it came back to. Nor anything inside the rider's privacy zones (services/privacy_zones.py).

The token is stored as a SHA-256 hash, for looking it up, and sealed (services/vault.py), for giving the link to the phone again when it
asks for the share it already has.

When a share starts, the link goes by email to each of the rider's contacts ticked for live links (services/contacts.py), from here rather
than the phone: a Watch on its own has no way to send it, and nobody need tap anything. Once per share, never again when the phone is given
the running one. It's sent by the worker (SEND_JOB), so a slow mail server doesn't hold up the phone's request; the phone reads how it went
from the share (recipients), asking again until nobody is left at "sending".

A share can follow one of the rider's saved routes (PlannedRoute, services/planned_routes.py), named when it starts. The share keeps its own
copy of the route's line, simplified (route_copy), so renaming, editing or deleting the route doesn't change a running link, and the copy
goes with the points. Each reading is matched to the line near the last match, at the place nearest where the rider should be by now
(_follow), so a loop or an out-and-back that passes the same road twice doesn't jump ahead or back; that gives the distance done and to go, and the finish time at the recent
moving speed (_moving_speed: stops don't count). Off the line, the page says so and keeps the last figures. The line is drawn only when
the rider chose to show it (showRoute): the figures are shown either way, as they say how far away the end is but not where. A route
usually starts and ends at home, so the line is cut around both ends (each a HIDE_START_M circle moved a random way off it, as a privacy
zone is) and inside the rider's privacy zones, and the rider's own position and track aren't shown inside those circles either."""
import hashlib
import ipaddress
import json
import math
import random
import re
import secrets
import time
from urllib.parse import urlsplit

from services import contacts, jobs, vault

PREFIX = 'hwl_'
AFTER_END_S = 3600          # the link works for an hour after the recording ends
SILENT_S = 6 * 3600         # and a share that has heard nothing for this long has ended too
NO_SIGNAL_S = 90            # the page says "No signal since ..." after this long without a reading (services/live.IDLE_AFTER_S)
THIN_S = 10                 # a track point at most every THIN_S seconds ...
THIN_M = 25                 # ... or as soon as the rider is THIN_M metres on
MIN_MOVE_M = 5              # and not while standing still
HIDE_START_M = 300          # nothing shown this close to where the track began
MAX_POINTS = 20_000         # a day at THIN_S
MAX_SENT_TRACK = 5_000      # points the phone may send with a share started mid-recording
MAX_ROUTE_POINTS = 5_000    # a followed route's line, simplified until it has at most this many
ON_ROUTE_M = 50             # a reading this close to the route's line is on it
OFF_AFTER = 2               # and this many readings in a row further off are off it
AHEAD_M = 2_000             # a reading is matched first within this far ahead of the last match ...
BEHIND_M = 100              # ... and this far behind it (GPS wanders; the rider turns round)
RECENT_S = 600              # the finish time is at the moving speed of the last ten minutes
MOVING_MPS = 0.5            # slower than this between two points is stopped


SETTINGS_PATH = '/settings#address'
_HOME_SUFFIXES = ('.local', '.lan', '.home', '.home.arpa', '.internal', '.localdomain')


def _home_only(host):
    """Whether an address can only be reached at home (or on this machine): localhost, a private or link-local address, a .local name."""
    host = (host or '').strip('[]').lower()
    if not host or host == 'localhost' or host.endswith('.localhost') or host.endswith(_HOME_SUFFIXES) or '.' not in host and ':' not in host:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip in ipaddress.ip_network('100.64.0.0/10')


def link_base():
    """(address, None): the outside address the links start with (services/external_url.py). (None, why) when there's none anyone the rider
    sends a link to could open: none saved, not https, or one that only works at home."""
    from services import external_url
    url = external_url.get()
    if not url:
        return None, 'Headwind has no outside address, so nobody away from home could open the link. Set one in Settings → Outside address.'
    host = urlsplit(url).hostname
    if _home_only(host):
        return None, (f'The outside address ({host}) only works at home, so nobody you send the link to could open it. Set the address '
                      'Headwind is reached on from outside in Settings → Outside address.')
    if not url.startswith('https://'):
        return None, ('The outside address is not https://, and a link to it would send where you are unencrypted. Set the https address in '
                      'Settings → Outside address.')
    return url, None


def link(base, token):
    return f'{base}/live/{token}'


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def ensure_schema(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS LiveShare (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            riderId     INTEGER NOT NULL,
            tokenHash   TEXT NOT NULL UNIQUE,
            sealedToken TEXT,                       -- vault.seal of the token, to give the link to the phone again
            recording   TEXT NOT NULL DEFAULT '',   -- the phone's id for the recording ('' from an app that sends none)
            sport       TEXT,
            deviceId    INTEGER,                    -- the phone that started it (DeviceToken.id)
            createdAt   REAL NOT NULL,              -- epoch seconds, as the rest
            reading     TEXT,                       -- JSON: the last reading for this recording (services/live.clean)
            readingAt   REAL,
            startLat    REAL,                       -- where its track began (HIDE_START_M)
            startLng    REAL,
            endedAt     REAL,
            expiresAt   REAL NOT NULL,
            revokedAt   REAL
        )''')
    have = {r[1] for r in db.execute('PRAGMA table_info(LiveShare)').fetchall()}
    for col, defn in (('routeId', 'INTEGER'),               # the saved route it follows, as it was named (PlannedRoute.id)
                      ('showRoute', 'INTEGER NOT NULL DEFAULT 0'),  # whether the page draws the route
                      ('routeLine', 'TEXT'),                # JSON [[lat, lng, metres along], ...]: the share's own copy of the line
                      ('routeHide', 'TEXT'),                # JSON: the circles cut round its ends, as privacy zones ({lat, lng, radiusM, bearing, shift})
                      ('routeAt', 'REAL'),                  # metres along the line of the last reading on it
                      ('routeSeg', 'INTEGER'),              # and the part of the line it was on
                      ('routeMiss', 'INTEGER NOT NULL DEFAULT 0')):  # readings in a row off the line
        if col not in have:
            db.execute(f'ALTER TABLE LiveShare ADD COLUMN {col} {defn}')
    db.execute('CREATE INDEX IF NOT EXISTS idx_liveshare_rider ON LiveShare(riderId, recording)')
    db.execute('''
        CREATE TABLE IF NOT EXISTS LivePoint (
            shareId INTEGER NOT NULL,
            ts      REAL NOT NULL,
            lat     REAL NOT NULL,
            lng     REAL NOT NULL
        )''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_livepoint_share ON LivePoint(shareId, ts)')


def _metres(a_lat, a_lng, b_lat, b_lng):
    """Haversine distance in metres."""
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lng - a_lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6_371_000 * math.asin(min(1.0, math.sqrt(h)))


def recording_id(value):
    """The phone's recording id as kept: a short string, or '' for none."""
    return str(value or '').strip()[:64]


def _live_sql(now):
    return f'revokedAt IS NULL AND expiresAt > {float(now)!r}'


def open_share(db, rider_id, recording, now=None):
    """The rider's share of this recording that is still running (not ended, revoked or expired), or None."""
    now = time.time() if now is None else now
    return db.execute(f'SELECT * FROM LiveShare WHERE riderId=? AND recording=? AND endedAt IS NULL AND {_live_sql(now)} '
                      'ORDER BY id DESC LIMIT 1', [rider_id, recording_id(recording)]).fetchone()


def token_of(row):
    """The token of a share, or None when this server's key can't open it (a database restored elsewhere)."""
    return vault.unseal(row['sealedToken']) if row and row['sealedToken'] else None


def start(db, rider_id, recording, sport=None, device_id=None, track=None, now=None, route=None, show_route=None, rng=random):
    """Start sharing this recording, or find the share of it that is already running. Returns (row, token, created); token is None for one
    already running whose token can't be opened. `track`: the points recorded before the share began, [[lat, lng, epoch s], ...], kept
    thinned as the start of its track. `route`: the id of the rider's saved route being followed, copied onto the share (route_copy); one
    that isn't theirs, or is gone, is left out. A running share given a route when it has none takes it, and `show_route` (whether the page
    draws it) when it's given. Commits."""
    now = time.time() if now is None else now
    recording = recording_id(recording)
    row = open_share(db, rider_id, recording, now)
    if row:
        changed = False
        if route is not None and not row['routeLine']:
            changed = _attach_route(db, row['id'], rider_id, route, rng)
        if show_route is not None and bool(show_route) != bool(row['showRoute']):
            db.execute('UPDATE LiveShare SET showRoute=? WHERE id=?', [1 if show_route else 0, row['id']])
            changed = True
        if changed:
            db.commit()
            row = db.execute('SELECT * FROM LiveShare WHERE id=?', [row['id']]).fetchone()
        return row, token_of(row), False
    token = PREFIX + secrets.token_urlsafe(24)
    cur = db.execute('INSERT INTO LiveShare (riderId, tokenHash, sealedToken, recording, sport, deviceId, createdAt, expiresAt, showRoute) '
                     'VALUES (?,?,?,?,?,?,?,?,?)', [rider_id, _hash(token), vault.seal(token), recording, (sport or '')[:20] or None,
                                                    device_id, now, now + SILENT_S, 1 if show_route else 0])
    share_id = cur.lastrowid
    sent = _clean_track(track)[-MAX_SENT_TRACK:]
    for p in sent:
        _add_point(db, share_id, p[0], p[1], p[2])
    if route is not None:
        _attach_route(db, share_id, rider_id, route, rng, sent)
    # The reading that came before the share, if it's this recording's: the page has something to show at once
    last = db.execute('SELECT reading, ts FROM LiveReading WHERE riderId=?', [rider_id]).fetchone()
    if last:
        c = json.loads(last['reading'])
        if c.get('state') == 'riding' and recording_id(c.get('recording')) == recording and now - last['ts'] < NO_SIGNAL_S:
            _take(db, db.execute('SELECT * FROM LiveShare WHERE id=?', [share_id]).fetchone(), c, last['ts'])
    db.commit()
    return db.execute('SELECT * FROM LiveShare WHERE id=?', [share_id]).fetchone(), token, True


def route_copy(db, rider_id, route_id, rng=random):
    """The share's copy of one of the rider's saved routes: (line, hide), line [[lat, lng, metres along], ...] simplified to at most
    MAX_ROUTE_POINTS (planned_routes.simplify), hide the circles cut round its start and finish, as privacy zones (privacy_zones.circle):
    HIDE_START_M moved a random way off each end, made larger by as much, so the cut doesn't draw a circle round the door. None when the
    route isn't the rider's, is gone, or has fewer than two points."""
    from services import planned_routes, privacy_zones
    try:
        route_id = int(route_id)
    except (TypeError, ValueError):
        return None
    r = db.execute('SELECT track, waypoints FROM PlannedRoute WHERE id=? AND riderId IS ?', [route_id, rider_id]).fetchone()
    if not r:
        return None
    try:
        raw = json.loads(r['track']) if r['track'] else [[w['lat'], w['lng']] for w in json.loads(r['waypoints'] or '[]')]
    except (TypeError, ValueError, KeyError):
        return None
    pts = [[p[0], p[1]] for p in planned_routes.clean(raw)]
    if len(pts) < 2:
        return None
    tol = planned_routes.SIMPLIFY_M
    keep = planned_routes.simplify(pts, tol)
    while len(keep) > MAX_ROUTE_POINTS:
        tol *= 2
        keep = planned_routes.simplify(pts, tol)
    line, along = [], 0.0
    for i in keep:
        lat, lng = pts[i]
        if line:
            along += _metres(line[-1][0], line[-1][1], lat, lng)
        line.append([lat, lng, round(along, 1)])
    hide = [{'lat': p[0], 'lng': p[1], 'radiusM': HIDE_START_M, 'bearing': rng.uniform(0, 360), 'shift': rng.uniform(*privacy_zones.SHIFT)}
            for p in (pts[0], pts[-1])]
    return line, hide


def _attach_route(db, share_id, rider_id, route_id, rng=random, track=()):
    """Copy the route onto the share, and match the track it has so far to it, in order. Returns whether there was a route. Does not commit."""
    got = route_copy(db, rider_id, route_id, rng)
    if not got:
        return False
    line, hide = got
    db.execute('UPDATE LiveShare SET routeId=?, routeLine=?, routeHide=?, routeAt=NULL, routeSeg=NULL, routeMiss=0 WHERE id=?',
               [int(route_id), json.dumps(line, separators=(',', ':')), json.dumps(hide), share_id])
    if track:
        share = db.execute('SELECT * FROM LiveShare WHERE id=?', [share_id]).fetchone()
        state = _route_state(share)
        for p in track:
            state = _follow(line, state, p[0], p[1])
        _save_route_state(db, share_id, state)
    return True


def _route_state(share):
    return {'at': share['routeAt'], 'seg': share['routeSeg'], 'miss': share['routeMiss'] or 0}


def _save_route_state(db, share_id, state):
    db.execute('UPDATE LiveShare SET routeAt=?, routeSeg=?, routeMiss=? WHERE id=?', [state['at'], state['seg'], state['miss'], share_id])


def _near(line, i, lat, lng):
    """(metres from the position to part i of the line, metres along the line of the nearest point of it)."""
    a, b = line[i], line[i + 1]
    kx = 111_320.0 * math.cos(math.radians(lat))
    ax, ay = (a[1] - lng) * kx, (a[0] - lat) * 111_320.0
    bx, by = (b[1] - lng) * kx, (b[0] - lat) * 111_320.0
    dx, dy = bx - ax, by - ay
    ll = dx * dx + dy * dy
    t = 0.0 if not ll else max(0.0, min(1.0, -(ax * dx + ay * dy) / ll))
    return math.hypot(ax + t * dx, ay + t * dy), a[2] + t * (b[2] - a[2])


def _point_at(line, seg, at):
    """The position at metres `at` along part `seg` of the line."""
    a, b = line[seg], line[seg + 1]
    t = 0.0 if b[2] == a[2] else max(0.0, min(1.0, (at - a[2]) / (b[2] - a[2])))
    return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])


def _match(line, lat, lng, first, last, expect=None):
    """The place on parts first..last of the line within ON_ROUTE_M of the position that is nearest `expect` metres along (where the rider
    should be by now), or, with no expect, the first along. Where the line passes the same road twice (an out-and-back, a loop crossing
    itself) that takes the passing the rider is on. (part, metres along) or None."""
    best = None
    for i in range(first, last + 1):
        d, along = _near(line, i, lat, lng)
        if d > ON_ROUTE_M:
            continue
        key = (along if expect is None else abs(along - expect), d)
        if best is None or key < best[0]:
            best = (key, i, along)
    return (best[1], best[2]) if best else None


def _follow(line, state, lat, lng):
    """The route state ({at, seg, miss}) after a reading at this position. Searched from BEHIND_M behind the last match to AHEAD_M ahead of
    it first, then the rest of the route ahead (rejoining it after a short cut), taking the place nearest the last match plus how far the
    rider has gone since; the first reading takes the first place along. Off the line, at and seg stay and miss counts."""
    n = len(line) - 1                        # parts of the line
    if n < 1:
        return state
    if state['at'] is None:
        got = _match(line, lat, lng, 0, n - 1)
    else:
        at, seg = state['at'], min(state['seg'] or 0, n - 1)
        was = _point_at(line, seg, at)
        expect = at + _metres(was[0], was[1], lat, lng)
        first = seg
        while first > 0 and line[first][2] > at - BEHIND_M:
            first -= 1
        last = seg
        while last < n - 1 and line[last + 1][2] < at + AHEAD_M:
            last += 1
        got = _match(line, lat, lng, first, last, expect)
        if got is None and last < n - 1:
            got = _match(line, lat, lng, last + 1, n - 1, expect)
    if got is None:
        return {**state, 'miss': state['miss'] + 1}
    return {'at': round(got[1], 1), 'seg': got[0], 'miss': 0}


def _clean_track(track):
    out = []
    for p in track if isinstance(track, list) else []:
        try:
            lat, lng, ts = float(p[0]), float(p[1]), float(p[2])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if -90 <= lat <= 90 and -180 <= lng <= 180 and lat == lat and lng == lng and ts == ts:
            out.append((lat, lng, ts))
    out.sort(key=lambda p: p[2])
    return out


def _add_point(db, share_id, lat, lng, ts):
    """Keep this point if the track has moved on enough since its last one. Also sets where the track began."""
    last = db.execute('SELECT lat, lng, ts FROM LivePoint WHERE shareId=? ORDER BY ts DESC LIMIT 1', [share_id]).fetchone()
    if last:
        if ts <= last['ts']:
            return False
        moved = _metres(last['lat'], last['lng'], lat, lng)
        if moved < MIN_MOVE_M or (moved < THIN_M and ts - last['ts'] < THIN_S):
            return False
        if db.execute('SELECT COUNT(*) FROM LivePoint WHERE shareId=?', [share_id]).fetchone()[0] >= MAX_POINTS:
            return False
    else:
        db.execute('UPDATE LiveShare SET startLat=?, startLng=? WHERE id=? AND startLat IS NULL', [lat, lng, share_id])
    db.execute('INSERT INTO LivePoint (shareId, ts, lat, lng) VALUES (?,?,?,?)', [share_id, ts, lat, lng])
    return True


def _take(db, share, c, ts):
    """One reading for a share: kept as its last, its position added to the track. An idle one ends the share."""
    if c.get('lat') is not None and c.get('lng') is not None:
        _add_point(db, share['id'], c['lat'], c['lng'], ts)
        if share['routeLine']:
            _save_route_state(db, share['id'], _follow(json.loads(share['routeLine']), _route_state(share), c['lat'], c['lng']))
    if c.get('state') == 'idle':
        db.execute('UPDATE LiveShare SET reading=?, readingAt=?, endedAt=?, expiresAt=? WHERE id=?',
                   [json.dumps(c), ts, ts, ts + AFTER_END_S, share['id']])
    else:
        db.execute('UPDATE LiveShare SET reading=?, readingAt=?, expiresAt=?, sport=COALESCE(?, sport) WHERE id=?',
                   [json.dumps(c), ts, max(share['expiresAt'], ts + SILENT_S), c.get('sport') or None, share['id']])


def record(db, rider_id, c, now=None):
    """A reading from the phone (services/live.update, already cleaned): given to the rider's running share of its recording, if there is
    one. Returns whether there was. Does not commit."""
    now = time.time() if now is None else now
    share = open_share(db, rider_id, c.get('recording'), now)
    if not share:
        return False
    _take(db, share, c, now)
    return True


def stop(db, rider_id, recording=None, share_id=None, now=None):
    """Stop sharing: the rider's running share of this recording (or the one with this id, if it is theirs), revoked so the link ends at once.
    Its points go now. Returns how many were stopped. Commits."""
    now = time.time() if now is None else now
    if share_id is not None:
        rows = db.execute('SELECT id FROM LiveShare WHERE id=? AND riderId=? AND revokedAt IS NULL', [share_id, rider_id]).fetchall()
    else:
        rows = db.execute(f'SELECT id FROM LiveShare WHERE riderId=? AND recording=? AND {_live_sql(now)}',
                          [rider_id, recording_id(recording)]).fetchall()
    for r in rows:
        db.execute('UPDATE LiveShare SET revokedAt=?, routeLine=NULL, routeHide=NULL WHERE id=?', [now, r['id']])
        db.execute('DELETE FROM LivePoint WHERE shareId=?', [r['id']])
    db.commit()
    return len(rows)


def lookup(db, token, now=None):
    """The share this token opens, while it works: None for an unknown, revoked or expired one alike."""
    now = time.time() if now is None else now
    if not token or not isinstance(token, str) or not token.startswith(PREFIX) or len(token) > 100:
        return None
    return db.execute(f'SELECT * FROM LiveShare WHERE tokenHash=? AND {_live_sql(now)}', [_hash(token)]).fetchone()


def sweep(db, now=None):
    """The points, last reading, route and sealed token of shares that have expired or been stopped: gone; and the shares themselves a day past
    their end, with the record of whom their link was emailed to. The worker runs this with live.go_idle. Returns how many points went. Commits when it changed anything."""
    now = time.time() if now is None else now
    ended = [r[0] for r in db.execute('SELECT id FROM LiveShare WHERE (revokedAt IS NOT NULL OR expiresAt <= ?) AND (reading IS NOT NULL OR '
                                      'sealedToken IS NOT NULL OR routeLine IS NOT NULL OR id IN (SELECT shareId FROM LivePoint))',
                                      [now]).fetchall()]
    old = [r[0] for r in db.execute('SELECT id FROM LiveShare WHERE COALESCE(revokedAt, expiresAt) <= ?', [now - 86400]).fetchall()]
    if not ended and not old:
        return 0                        # read only, so the worker takes no write lock every time it looks
    n = 0
    for sid in ended:
        n += db.execute('DELETE FROM LivePoint WHERE shareId=?', [sid]).rowcount
        db.execute('UPDATE LiveShare SET reading=NULL, sealedToken=NULL, startLat=NULL, startLng=NULL, routeLine=NULL, routeHide=NULL, '
                   'routeAt=NULL, routeSeg=NULL WHERE id=?', [sid])
    for sid in old:
        db.execute('DELETE FROM LivePoint WHERE shareId=?', [sid])
        db.execute('DELETE FROM LiveShare WHERE id=?', [sid])
    contacts.forget(db, [about(sid) for sid in old])        # who it was sent to goes with it
    db.commit()
    return n


# Sending the link to the rider's contacts

SEND_JOB = 'live_link_send'


def about(share_id):
    """The share, as the contacts' outbox names it (services/contacts.py)."""
    return f'live:{share_id}'


def send_to_contacts(db, share):
    """A share has just started: its link to each of the rider's contacts ticked for live links, by the worker. Returns how many are waiting
    to be sent. Commits."""
    waiting = contacts.queue(db, share['riderId'], about(share['id']), 'live')
    if waiting:
        jobs.enqueue(db, SEND_JOB, {'share': share['id']}, once=False)
    return waiting


def recipients(db, share_id):
    """Who the share's link was sent to and how it went, for the phone: [{name, state: sending|sent|failed, error}]."""
    return contacts.report(db, about(share_id))


def _with_article(words):
    return ('an ' if words[:1] in 'aeiou' else 'a ') + words


def link_message(db, share, url):
    """(subject, text, sender name) of the email that sends a contact the link: who it's from, what it shows, and when it ends."""
    from services import sports
    name = first_name(db, share['riderId']) or 'Someone'
    sport = share['sport'] or ''
    words = _LABELS.get(sport) or (sports.label(sport) if sport else 'activity')
    what = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', words).lower()       # a sport with no label of its own: 'TrailRun' -> 'trail run'
    rate = 'pace' if sports.rate_style(sport) in ('pace', 'swim') else 'speed'
    after = 'an hour' if AFTER_END_S == 3600 else f'{AFTER_END_S // 60} minutes'
    text = (f"{name} has started {_with_article(what)} and chose you to follow along. This link shows where {name} is now, the track so "
            f"far, and the distance, time and {rate}:\n\n{url}\n\n"
            f"It opens in any browser, with no account to make. It stops working {after} after the {what} ends.\n\n"
            f"{name} set this up in Headwind, which sent this email, so a reply to it may not reach {name}.\n")
    return f"Follow {name}'s {what} live", text, f'{name} via Headwind'


@jobs.handler(SEND_JOB, quick=True)
def _send_link(job):
    """Email the share's link to the contacts waiting for it. A share stopped (or ended) before this ran sends nothing: its link would
    already be dead."""
    from database import get_db
    db = get_db()
    sid = job['args']['share']
    share = db.execute('SELECT * FROM LiveShare WHERE id=?', [sid]).fetchone()
    token = token_of(share) if share and share['revokedAt'] is None and share['expiresAt'] > time.time() else None
    if not token:
        contacts.fail(db, about(sid), 'The link was stopped before it could be sent.')
        return
    base, why = link_base()
    if not base:                            # the outside address was changed since the share started
        contacts.fail(db, about(sid), why)
        return
    subject, text, sender = link_message(db, share, link(base, token))
    contacts.deliver(db, about(sid), subject, text, sender_name=sender)


def _hidden(share, lat, lng, zones=None):
    """Whether a position isn't shown: near where the share's track began, or inside one of the rider's privacy zones (a Hider)."""
    if share['startLat'] is not None and _metres(share['startLat'], share['startLng'], lat, lng) < HIDE_START_M:
        return True
    return bool(zones) and zones.inside(lat, lng)


_LABELS = {'OpenWaterSwim': 'Open water swim', 'VirtualRun': 'Treadmill run'}     # the phone's sports services/sports.LABELS doesn't name


def first_name(db, rider_id):
    r = db.execute('SELECT name FROM Rider WHERE id=?', [rider_id]).fetchone()
    name = ((r['name'] if r else '') or '').strip()
    return name.split()[0][:40] if name else ''


def _clock(secs):
    secs = int(max(0, secs or 0))
    return '%d:%02d:%02d' % (secs // 3600, (secs % 3600) // 60, secs % 60) if secs >= 3600 else '%d:%02d' % (secs // 60, secs % 60)


def view(db, share, since=None, now=None):
    """What the page shows for a share: only this share's figures, position and track, and the route it follows (_route_view). `since`: the
    time of the last point the page has (it asks for those after it; the route's line comes only with the first, which has none). Units are
    the rider's setting (services/units.py)."""
    from services import privacy_zones, sports, units
    now = time.time() if now is None else now
    zones = privacy_zones.hider(db, share['riderId'], also=json.loads(share['routeHide']) if share['routeHide'] else ())
    c = json.loads(share['reading']) if share['reading'] else {}
    sport = c.get('sport') or share['sport'] or ''
    style = sports.rate_style(sport)
    dist = c.get('distance_m')
    secs = c.get('elapsed_s')
    avg = dist / secs if dist and secs else None
    pos = None
    hidden = False
    if c.get('lat') is not None and c.get('lng') is not None:
        if _hidden(share, c['lat'], c['lng'], zones):
            hidden = True
        else:
            pos = [c['lat'], c['lng']]
    try:
        since = float(since) if since not in (None, '') else None
    except ValueError:
        since = None
    rows = db.execute('SELECT ts, lat, lng FROM LivePoint WHERE shareId=? AND ts > ? ORDER BY ts',
                      [share['id'], since if since is not None else -1.0]).fetchall()
    points = [[round(r['lat'], 6), round(r['lng'], 6)] for r in rows if not _hidden(share, r['lat'], r['lng'], zones)]
    if share['endedAt']:
        status = 'finished'
    elif not share['readingAt']:
        status = 'waiting'
    elif now - share['readingAt'] > NO_SIGNAL_S:
        status = 'nosignal'
    else:
        status = 'live'
    route = _route_view(db, share, c, zones, since is None, now, status)
    return {
        **route,
        'name': first_name(db, share['riderId']),
        'sport': _LABELS.get(sport) or (sports.label(sport) if sport else 'Activity'),
        'icon': sports.icon(sport) if sport else '',
        'status': status,
        'now': now,
        'updatedAt': share['readingAt'],
        'endedAt': share['endedAt'],
        'expiresAt': share['expiresAt'],
        'distance': units.fmt_dist(dist) if dist and sport not in sports.NO_DISTANCE else None,
        'time': _clock(secs) if secs is not None else None,
        'rateLabel': 'Pace' if style in ('pace', 'swim') else 'Speed',
        'rateNow': units.fmt_rate(c.get('speed_mps'), style) if status == 'live' and c.get('speed_mps') else None,
        'rateAvg': units.fmt_rate(avg, style) if avg else None,
        'battery': c.get('battery'),
        'position': pos,
        'hidden': hidden,
        'points': points,
        'last': rows[-1]['ts'] if rows else since,
    }


def _moving_speed(db, share, c, until):
    """Metres a second over the last RECENT_S of the share's track, counting only the stretches between points moving at MOVING_MPS or
    more, so a stop at a café doesn't slow the finish time. With under a minute of that, the reading's own average. None for neither."""
    rows = db.execute('SELECT ts, lat, lng FROM LivePoint WHERE shareId=? AND ts >= ? AND ts <= ? ORDER BY ts',
                      [share['id'], until - RECENT_S, until]).fetchall()
    dist = secs = 0.0
    for a, b in zip(rows, rows[1:]):
        dt = b['ts'] - a['ts']
        d = _metres(a['lat'], a['lng'], b['lat'], b['lng'])
        if dt > 0 and d / dt >= MOVING_MPS:
            dist += d
            secs += dt
    if secs >= 60:
        return dist / secs
    d, t = c.get('distance_m'), c.get('elapsed_s')
    return d / t if d and t and d / t >= MOVING_MPS else None


def _route_view(db, share, c, zones, with_line, now, status):
    """The route part of view(): hasRoute; routeShown; route, the line's pieces outside the hidden circles (its ends, the privacy zones),
    only when shown and with_line; route_done_m and route_left_m along it, with routeDone and routeLeft in the rider's units; offRoute; and
    eta, the epoch time it should end at the recent moving speed, while it's going. Distance and finish time show when the line doesn't."""
    from services import units
    if not share['routeLine']:
        return {'hasRoute': False}
    line = json.loads(share['routeLine'])
    total = line[-1][2]
    at = share['routeAt']
    out = {'hasRoute': True, 'routeShown': bool(share['showRoute']), 'route': None, 'offRoute': (share['routeMiss'] or 0) >= OFF_AFTER,
           'route_done_m': None, 'route_left_m': None, 'routeDone': None, 'routeLeft': units.fmt_dist(total), 'eta': None}
    if with_line and share['showRoute']:
        out['route'] = [[[round(p[0], 5), round(p[1], 5)] for p in piece] for piece in zones.pieces([[p[0], p[1]] for p in line])]
    if at is not None:
        left = max(0.0, total - at)
        out.update(route_done_m=round(at), route_left_m=round(left), routeDone=units.fmt_dist(at), routeLeft=units.fmt_dist(left))
        if status in ('live', 'nosignal') and left > 0:
            speed = _moving_speed(db, share, c, share['readingAt'] or now)
            if speed:
                out['eta'] = round((share['readingAt'] or now) + left / speed)
    return out


RECENT_LIST = 20            # the Phones page lists this many of the latest links


def _utc(epoch):
    """An epoch time as SQLite's datetime('now') writes one, for the fmt_when filter."""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y-%m-%d %H:%M:%S') if epoch else None


def listing(db, now=None):
    """The latest links, running first, for the Phones page: [{id, rider, sport, device, started, ended, state: running|finished|stopped|
    expired, working, url, route, sent}]. A link works (and can be stopped) until it's stopped or expires, an hour after a finished one;
    sweep deletes them a day after. url is None when the outside address has changed since, or the token can't be opened."""
    from services import sports
    now = time.time() if now is None else now
    base, _ = link_base()
    rows = db.execute(f'''SELECT s.*, d.name AS deviceName, r.name AS riderName, (s.revokedAt IS NULL AND s.expiresAt > {float(now)!r}) AS working
                          FROM LiveShare s
                          LEFT JOIN DeviceToken d ON d.id = s.deviceId LEFT JOIN Rider r ON r.id = s.riderId
                          ORDER BY working DESC, s.createdAt DESC LIMIT ?''', [RECENT_LIST]).fetchall()
    out = []
    for r in rows:
        if r['revokedAt']:
            state = 'stopped'
        elif not r['working']:
            state = 'expired'
        elif r['endedAt']:
            state = 'finished'
        else:
            state = 'running'
        token = token_of(r) if r['working'] else None
        sport = r['sport'] or ''
        out.append({'id': r['id'], 'rider': ((r['riderName'] or '').split() or [''])[0], 'device': r['deviceName'],
                    'sport': _LABELS.get(sport) or (sports.label(sport) if sport else 'Activity'), 'icon': sports.icon(sport) if sport else '',
                    'started': _utc(r['createdAt']), 'ended': _utc(r['revokedAt'] or r['endedAt']), 'until': _utc(r['expiresAt']),
                    'state': state, 'working': bool(r['working']), 'url': link(base, token) if base and token else None,
                    'route': bool(r['routeId']), 'sent': [c['name'] for c in recipients(db, r['id']) if c['state'] == 'sent']})
    return out
