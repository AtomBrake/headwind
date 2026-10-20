"""The same ride recorded twice (e.g. phone app AND a Garmin head unit): find it, keep the better recording, park the other.

Parked rides are NOT deleted. They move to the ActivityDuplicate table (full row as JSON) and can be restored: swapped in as the main
ride, kept as a separate ride, or discarded for good. Keeping the parking lot outside Activity means every existing query (stats,
charts, badges, HA sensors, segments) keeps seeing exactly one ride, with no filtering to remember.

Matching is on the real instant (UTC), never on a local-time string: a phone GPX is UTC, Garmin gives local time, and comparing the raw
strings during British Summer Time is how a 1-hour gap hid the first duplicate ever seen here.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from services import tz

log = logging.getLogger(__name__)
UTC = timezone.utc

OVERLAP_MIN = 0.60          # the two recordings must overlap for at least this share of the shorter one
DIST_TOL = 0.15             # ...and agree on distance within 15% (different devices measure a ride a little differently)
SEARCH_DAYS = 1


def ensure_schema(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS ActivityDuplicate (
            id        TEXT PRIMARY KEY,                 -- the parked activity's own id
            primaryId TEXT NOT NULL,                    -- the ride kept in its place
            riderId   INTEGER,
            source    TEXT,                             -- 'Garmin' / 'Phone or file' (display only)
            reason    TEXT,                             -- why it lost, shown to the user
            status    TEXT NOT NULL DEFAULT 'parked',   -- parked | kept_both
            rowJson   TEXT NOT NULL,                    -- the full Activity row
            parkedAt  TEXT DEFAULT (datetime('now'))
        )''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_actdup_primary ON ActivityDuplicate(primaryId)')


# ---------- time + matching (pure) ----------
def instant(value):
    """A timezone-aware UTC datetime from an ISO string. Naive strings are the home timezone's local time (what Garmin gives us)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=tz.zone())).astimezone(UTC)


def start_instant(row):
    """The real start of an activity row/dict (UTC), or None. Every path that knows it stores the UTC instant in startDate and the local time in
    startDateLocal (Garmin's startTimeGMT, FIT and Strava export times, a GPX with a 'Z', the phone app, manual entries), so startDate is the one
    to trust: Garmin's local time is the clock where the ride happened, which on a trip abroad is not the home zone (a Vancouver walk read as
    London time is 8 hours out and never overlaps its Strava copy). When the two are the same string it is a naive time saved in both (a file
    with no zone): read that as home-zone local, which is also what a UTC time means whenever the home zone is on UTC. Except from Garmin:
    startTimeGMT is always UTC, and Garmin puts that same time in startTimeLocal too when it had no zone for the activity (old uploads, phone
    apps), so a Garmin row's two equal strings are UTC (read as UK time, a summer ride sat an hour before its Strava copy and both were kept)."""
    keys = row.keys()
    utc = row['startDate'] if 'startDate' in keys else None
    local = row['startDateLocal'] if 'startDateLocal' in keys else None
    if utc and (str(utc)[:19] != str(local or '')[:19] or str(row['id'] if 'id' in keys else '').startswith('garmin_')):
        try:
            dt = datetime.fromisoformat(str(utc).replace('Z', '+00:00'))
            return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC)
        except ValueError:
            pass
    return instant(local or utc)


def span(row):
    """(start, end) instants of an activity row/dict, or None if it has no usable start."""
    start = start_instant(row)
    if not start:
        return None
    secs = max(int(row['elapsedTime'] or 0), int(row['movingTime'] or 0))
    return start, start + timedelta(seconds=secs)


FRAGMENT_SLACK_S = 120     # a fragment starts no earlier than this before the whole ride (and no later than its end)
FRAGMENT_MAX = 0.5          # ...lasts at most this share of it, and has at least this share of itself inside it
TRACK_AGREE_M = 1000        # two GPS tracks of one ride are this close at the same moment
VIRTUAL_START_S = 600       # two virtual rides (a watch's "Indoor Cycling" and its Zwift copy) start this close...
VIRTUAL_LENGTH_TOL = 0.20   # ...and last this nearly as long, whatever distance each made up


def _get(row, key, default=None):
    return row[key] if key in row.keys() else default


def _virtual(row):
    return 'virtual' in str(_get(row, 'sportType') or '').lower()


def _secs(s):
    return (s[1] - s[0]).total_seconds()


def _haversine_m(p, q):
    from math import asin, cos, radians, sin, sqrt
    dlat, dlng = radians(q[0] - p[0]), radians(q[1] - p[1])
    h = sin(dlat / 2) ** 2 + cos(radians(p[0])) * cos(radians(q[0])) * sin(dlng / 2) ** 2
    return 2 * 6371000 * asin(min(1.0, sqrt(h)))


def _timed_track(row):
    """([seconds from the start], [[lat, lng]]) for the points with a position, or None when the row has no timed GPS track."""
    try:
        st = json.loads(row['streams']) if _get(row, 'streams') else {}
        t, ll = (st.get('time') or {}).get('data') or [], (st.get('latlng') or {}).get('data') or []
    except (ValueError, TypeError, AttributeError):
        return None
    if not t or len(t) != len(ll):
        return None
    pts = [(x, p) for x, p in zip(t, ll) if x is not None and p and p[0] is not None and p[1] is not None]
    return ([x for x, _ in pts], [p for _, p in pts]) if len(pts) > 1 else None


def _tracks_agree(part, whole, sp, sw):
    """For a fragment with a GPS track inside a ride with one: True when, sampled at the same moments, the two are mostly in the same place. Two
    tracks of one ride are; a ride that only seems to contain another (a device left recording, paused, until the next day's ride) is not.
    True when either has no track to compare (a phone's speed-sensor recording, an indoor ride)."""
    from bisect import bisect_left
    a, b = _timed_track(part), _timed_track(whole)
    if not a or not b:
        return True
    off = (sp[0] - sw[0]).total_seconds()                # the fragment's second 0 is the whole ride's second `off`
    n = len(a[0])
    checked = agree = 0
    for i in sorted({round(k * (n - 1) / 8) for k in range(9)}):
        when = a[0][i] + off
        j = bisect_left(b[0], when)
        j = min((k for k in (j - 1, j) if 0 <= k < len(b[0])), key=lambda k: abs(b[0][k] - when))
        if abs(b[0][j] - when) > FRAGMENT_SLACK_S:
            continue                                     # the whole ride was paused then
        checked += 1
        agree += _haversine_m(a[1][i], b[1][j]) <= TRACK_AGREE_M
    return checked > 0 and agree * 2 >= checked


def fragment_of(part, whole):
    """True if `part` is a piece of the ride `whole`: both rides, `part` starts during it (FRAGMENT_SLACK_S early at most), at least half of it
    lies inside it, it lasts at most half as long, and where both have a GPS track they were in the same place. A phone app with a Garmin speed
    sensor recorded bits of rides like this (0 m or only the wheel's distance, no GPS), often running on for a few minutes after the ride's
    own device was stopped; a Zwift session inside the watch's "Indoor Cycling" is one too."""
    from services.sports import is_ride
    if not (is_ride(_get(part, 'sportType')) and is_ride(_get(whole, 'sportType'))):
        return False
    sp, sw = span(part), span(whole)
    if not sp or not sw or _secs(sw) <= 0:
        return False
    slack = timedelta(seconds=FRAGMENT_SLACK_S)
    if sp[0] < sw[0] - slack or sp[0] > sw[1] or _secs(sp) > FRAGMENT_MAX * _secs(sw):
        return False
    if (min(sp[1], sw[1]) - max(sp[0], sw[0])).total_seconds() < FRAGMENT_MAX * _secs(sp):
        return False                                     # mostly before or after it (a short ride just after another): not a piece of it
    return _tracks_agree(part, whole, sp, sw)


def same_ride(a, b, fragments=True):
    """True if two activity rows are probably one ride captured by two devices. fragments=False leaves out fragment_of."""
    sa, sb = span(a), span(b)
    if not sa or not sb:
        return False
    if fragments and (fragment_of(a, b) or fragment_of(b, a)):          # a piece of the other: distance and start can't agree, and needn't
        return True
    if _virtual(a) and _virtual(b):                     # a watch's indoor ride and Zwift's: each makes up its own distance, so only time counts
        la, lb = _secs(sa), _secs(sb)
        return (abs((sa[0] - sb[0]).total_seconds()) <= VIRTUAL_START_S and la > 0 and lb > 0
                and abs(la - lb) <= VIRTUAL_LENGTH_TOL * max(la, lb))
    overlap = (min(sa[1], sb[1]) - max(sa[0], sb[0])).total_seconds()
    shorter = min((sa[1] - sa[0]).total_seconds(), (sb[1] - sb[0]).total_seconds())
    da, db_ = float(a['distance'] or 0), float(b['distance'] or 0)
    if da > 0 and db_ > 0 and abs(da - db_) > DIST_TOL * max(da, db_):
        return False
    if da <= 0 or db_ <= 0:                             # no distance to compare (indoor / no GPS): demand an almost identical start and length
        la, lb = (sa[1] - sa[0]).total_seconds(), (sb[1] - sb[0]).total_seconds()
        return abs((sa[0] - sb[0]).total_seconds()) <= 120 and la > 0 and lb > 0 and abs(la - lb) <= 0.2 * max(la, lb)
    if shorter <= 0:                                    # no durations at all: fall back to "started within a minute"
        return abs((sa[0] - sb[0]).total_seconds()) <= 60 and da > 0 and db_ > 0
    return overlap >= OVERLAP_MIN * shorter


# Names nobody chose: what Strava ("Morning Ride", "Lunch Weight Training"), Garmin ("London Cycling", "Indoor Rowing") and the importers
# ("Imported Ride", "Ride Activity", "Garmin Activity") give an activity on their own, and Headwind's own "Morning walk" label.
_PARTS_OF_DAY = {'morning', 'lunch', 'afternoon', 'evening', 'night'}
_STRAVA_SPORTS = {'ride', 'run', 'walk', 'hike', 'swim', 'workout', 'training', 'yoga', 'pilates', 'row', 'ski', 'skate', 'paddling', 'climbing',
                  'stepper', 'stair-stepper', 'elliptical', 'kayaking', 'canoeing', 'surfing', 'golf', 'crossfit', 'activity'}
_GARMIN_SPORTS = {'cycling', 'biking', 'e-bike', 'running', 'walking', 'hiking', 'swimming', 'strength', 'cardio', 'yoga', 'pilates', 'rowing',
                  'elliptical', 'stepper', 'hiit', 'breathwork', 'multisport', 'kayaking', 'paddling', 'climbing', 'skiing', 'snowboarding', 'training',
                  'activity'}
_BARE_SPORTS = {'ride', 'run', 'walk', 'hike', 'swim', 'workout', 'virtualride', 'new ride', 'imported ride'}


def default_name(name):
    """True if an activity's name is one a device, a service or an importer made up, not one the user chose."""
    n = ' '.join(str(name or '').lower().split())
    if not n or n in _BARE_SPORTS:
        return True
    words = n.split(' ')
    if words[0] in _PARTS_OF_DAY and 2 <= len(words) <= 5 and words[-1] in _STRAVA_SPORTS:
        return True
    return len(words) <= 5 and words[-1] in _GARMIN_SPORTS          # "<where> <sport>", or the sport alone


def _name_rank(name):
    """2 = a name someone chose, 1 = a made-up one, 0 = none at all."""
    return 0 if not str(name or '').strip() else (1 if default_name(name) else 2)


def _take_better_name(db, primary_id, kept_name, other_name):
    """Give the kept activity the other copy's name if that one ranks higher ("Box Hill loop" on the phone copy beats Garmin's "London Cycling").
    True if it changed. Does not commit."""
    if _name_rank(other_name) <= _name_rank(kept_name):
        return False
    db.execute('UPDATE Activity SET name=? WHERE id=?', [other_name, primary_id])
    return True


def source_label(row):
    return 'Garmin' if str(row['id']).startswith('garmin_') else ('Manual entry' if str(row['id']).startswith('man_') else 'Phone or file')


def quality(row):
    """(score, reasons) for how much a recording is worth keeping. Higher wins; a tie keeps the one already stored."""
    s, why = 0, []
    rid = str(row['id'])
    if rid.startswith('garmin_'):
        s += 40; why.append('recorded on a Garmin device')
    if rid.startswith('man_'):
        s -= 50; why.append('typed in by hand')
    if row['averageHeartrate']:
        s += 20; why.append('has heart rate')
    if row['averageWatts']:
        s += 10; why.append('has power')
    if row['averageCadence']:
        s += 5; why.append('has cadence')
    pts, alt = 0, False
    try:
        st = json.loads(row['streams']) if row['streams'] else {}
        pts = len((st.get('latlng') or {}).get('data') or [])
        alt = any(a is not None for a in (st.get('altitude') or {}).get('data') or [])
    except (ValueError, TypeError, AttributeError):
        pass
    s += min(10, pts // 500)
    if pts == 0 and not rid.startswith('man_'):
        s -= 5; why.append('no GPS track')
    if alt:                                             # an old Garmin copy of a run kept no elevation; the file re-uploaded later did
        s += 3; why.append('has elevation')
    return s, why


def _gps_points(row):
    try:
        return len(((json.loads(row['streams']) if row['streams'] else {}).get('latlng') or {}).get('data') or [])
    except (ValueError, TypeError, AttributeError):
        return 0


def _whole_beats_fragment(existing, new):
    """(whole, fragment, reason) when one is a fragment of the other (fragment_of) with no GPS track, or well short of its distance (more than
    DIST_TOL): the whole ride is kept whatever recorded the piece, or the totals would lose the rest of the ride. None otherwise: two recordings
    of the same distance (a ride inside one whose stops ran its time on) and the better recording wins as usual. (Zwift inside a watch's
    indoor ride is settled before this, by _app_beats_watch.)"""
    for part, whole in ((new, existing), (existing, new)):
        if not fragment_of(part, whole):
            continue
        dp, dw = float(part['distance'] or 0), float(whole['distance'] or 0)
        no_gps, short = _gps_points(part) == 0, dw > 0 and dp < (1 - DIST_TOL) * dw
        if no_gps or short:
            mins = max(1, round(_secs(span(part)) / 60))
            what = 'with no GPS track' if no_gps else f'with {round(100 * dp / dw)}% of its distance'
            return whole, part, (f'Kept the whole ride: the other recording is only a {mins}-minute piece of it, {what} '
                                 '(a phone app or sensor that recorded part of the ride, or a device that stopped early).')
    return None


def _app_beats_watch(existing, new):
    """(app copy, watch copy, reason) for two virtual rides where one has the app's route (Zwift's track) and the other has none (a watch's
    "Indoor Cycling"): the app's recording is kept, whatever the watch scores, unless it has no distance or no length. A Zwift ride inside a
    longer watch session (a warm-up, then a race) is kept too; the watch session goes. None for any other pair."""
    for app, watch in ((new, existing), (existing, new)):
        s = span(app)
        if (_virtual(app) and _virtual(watch) and _gps_points(app) > 0 and _gps_points(watch) == 0
                and float(app['distance'] or 0) > 0 and s and _secs(s) > 0):
            return app, watch, ('Kept the Zwift (or other app) recording: it has the route, and the distance the app rode; a watch counts an '
                                'indoor ride\'s distance its own way.')
    return None


def pick_winner(existing, new):
    """Returns (winner, loser, reason_text). `existing` wins ties."""
    piece = _app_beats_watch(existing, new) or _whole_beats_fragment(existing, new)
    if piece:
        return piece
    se, we = quality(existing)
    sn, wn = quality(new)
    if sn > se:
        winner, loser, why = new, existing, wn
    else:
        winner, loser, why = existing, new, we
    reason = ('Kept the ' + source_label(winner) + ' recording (' + ', '.join(why) + ').') if why else ('Kept the ' + source_label(winner) + ' recording (the one already saved).')
    return winner, loser, reason


# ---------- database ----------
def _kept_both_partners(db, act_id):
    rows = db.execute("SELECT id, primaryId FROM ActivityDuplicate WHERE status='kept_both' AND (id=? OR primaryId=?)", [act_id, act_id]).fetchall()
    return {r['id'] for r in rows} | {r['primaryId'] for r in rows}


def find_duplicates(db, row, exclude_ids=(), fragments=True):
    """Other activities by the same rider that look like the same ride (fragments: see same_ride)."""
    s = span(row)
    if not s:
        return []
    day = s[0].astimezone(tz.zone()).date()
    lo, hi = (day - timedelta(days=SEARCH_DAYS)).isoformat(), (day + timedelta(days=SEARCH_DAYS + 1)).isoformat()
    cands = db.execute("SELECT * FROM Activity WHERE riderId=? AND id<>? AND substr(startDateLocal,1,10) BETWEEN ? AND ?", [row['riderId'], row['id'], lo, hi]).fetchall()
    skip = set(exclude_ids) | _kept_both_partners(db, row['id'])
    return [c for c in cands if c['id'] not in skip and same_ride(row, c, fragments)]


def _drop_derived(db, act_id):
    from services.segments import _refresh_prs
    seg_ids = [r[0] for r in db.execute('SELECT DISTINCT segmentId FROM SegmentEffort WHERE activityId=?', [act_id])]
    db.execute('DELETE FROM SegmentEffort WHERE activityId=?', [act_id])
    db.execute('DELETE FROM BestEffort WHERE activityId=?', [act_id])
    db.execute('DELETE FROM RideMemory WHERE rideId=?', [act_id])
    db.execute('DELETE FROM SportEffort WHERE activityId=?', [act_id])
    return seg_ids


def rebuild_derived(db, act_id):
    """Best efforts + segment efforts + PRs for one activity (after it has been restored as the main recording). A run, walk, ... gets its own
    (run best times, run segments) instead."""
    from services.best_efforts import save_best_efforts
    from services.segments import scan_activity_against_segments, _refresh_prs
    from services.sports import is_ride
    row = db.execute('SELECT * FROM Activity WHERE id=?', [act_id]).fetchone()
    if not row:
        return
    if not is_ride(row['sportType']):
        from services import workouts
        workouts.refresh_derived(db, act_id)
        return
    seg_ids = _drop_derived(db, act_id)
    save_best_efforts(db, row['id'], row['startDateLocal'], row['streams'])
    segments = db.execute('SELECT * FROM Segment').fetchall()
    if segments:
        scan_activity_against_segments(db, row, segments)
        seg_ids = list({*seg_ids, *[s['id'] for s in segments]})
    for sid in seg_ids:
        _refresh_prs(db, sid)


def park(db, loser_id, primary_id, reason):
    """Move an activity out of Activity into ActivityDuplicate. Does not commit."""
    from services.segments import _refresh_prs
    row = db.execute('SELECT * FROM Activity WHERE id=?', [loser_id]).fetchone()
    if not row:
        return False
    ensure_schema(db)
    winner = db.execute('SELECT * FROM Activity WHERE id=?', [primary_id]).fetchone()
    if winner:                                          # never lose something the user typed / chose on the ride that is being parked
        from services.sports import is_ride
        for col in ('notes', 'description') + (('bikeId',) if is_ride(winner['sportType']) else ('kitId',)):      # a ride has a bike, the rest kit
            if col in row.keys() and col in winner.keys() and row[col] and not winner[col]:
                db.execute(f'UPDATE Activity SET {col}=? WHERE id=?', [row[col], primary_id])
        if 'commute' in row.keys() and row['commute'] is not None and winner['commute'] is None:
            db.execute('UPDATE Activity SET commute=? WHERE id=?', [row['commute'], primary_id])
        _take_better_name(db, primary_id, winner['name'], row['name'])
        from services import photos
        photos.move(db, loser_id, primary_id)
    db.execute('INSERT OR REPLACE INTO ActivityDuplicate (id, primaryId, riderId, source, reason, status, rowJson) VALUES (?,?,?,?,?,?,?)',
               [loser_id, primary_id, row['riderId'], source_label(row), reason, 'parked', json.dumps(dict(row))])
    # Copies set aside under this one now hang off the one kept: a copy set aside under a copy that is itself set aside was lost to everything
    # that follows primaryId to a live activity (the Strava bike or shoes of the copy, services/strava_gear._rides)
    db.execute("UPDATE ActivityDuplicate SET primaryId=? WHERE primaryId=? AND status='parked' AND id<>?", [primary_id, loser_id, primary_id])
    seg_ids = _drop_derived(db, loser_id)
    db.execute('DELETE FROM Activity WHERE id=?', [loser_id])
    for sid in seg_ids:
        _refresh_prs(db, sid)
    log.warning('Duplicate ride: parked %s, kept %s (%s)', loser_id, primary_id, reason)
    return True


def resolve(db, new_id):
    """Call after a ride (and its best efforts / segments) has been stored. If it duplicates an existing ride, keeps the better recording
    and parks the other. Returns {'kept': id, 'parked': id, 'reason': text} or None. Does not commit."""
    ensure_schema(db)
    db.execute("DELETE FROM ActivityDuplicate WHERE id=? AND status='deleted'", [new_id])     # brought back on purpose
    new = db.execute('SELECT * FROM Activity WHERE id=?', [new_id]).fetchone()
    if not new:
        return None
    dups = find_duplicates(db, new)
    if not dups:
        return None
    current = new
    result = None
    for other in dups:                                  # normally exactly one
        winner, loser, reason = pick_winner(other, current)
        if not park(db, loser['id'], winner['id'], reason):
            continue
        result = {'kept': winner['id'], 'parked': loser['id'], 'reason': reason}
        if loser['id'] == current['id']:
            break                                       # the new ride lost; nothing more to compare
        current = db.execute('SELECT * FROM Activity WHERE id=?', [winner['id']]).fetchone() or current
    if result and result['kept'] == new_id:
        rebuild_derived(db, new_id)                     # it displaced an older row that had its own derived data
    return result


def exists_anywhere(db, act_id):
    """True if the id is a live activity OR one parked as a duplicate, so a re-sync never re-adds a ride the user already resolved.
    (Deleted rides are tombstones, see is_deleted: a file you upload yourself may bring a deleted ride back, an automatic sync may not.)"""
    ensure_schema(db)
    return bool(db.execute("SELECT 1 FROM Activity WHERE id=? UNION SELECT 1 FROM ActivityDuplicate WHERE id=? AND status<>'deleted'", [act_id, act_id]).fetchone())


def is_deleted(db, act_id):
    ensure_schema(db)
    return bool(db.execute("SELECT 1 FROM ActivityDuplicate WHERE id=? AND status='deleted'", [act_id]).fetchone())


def tombstone(db, act_id, rider_id):
    """Remember that the user deleted this ride (only the id, none of its data). Does not commit."""
    ensure_schema(db)
    db.execute("INSERT OR REPLACE INTO ActivityDuplicate (id, primaryId, riderId, source, reason, status, rowJson) VALUES (?,?,?,?,?,?,?)",
               [act_id, '', rider_id, 'deleted', 'deleted by you', 'deleted', '{}'])


def _drop_photos(db, act_ids):
    from flask import current_app
    from services import photos
    photos.delete_for(db, act_ids, current_app.config['DATABASE'])


def delete_activity(db, act_id):
    """The one place a ride is deleted (web button, phone app): derived data, parked duplicates of it, then a tombstone. Does not commit."""
    from services.segments import _refresh_prs
    row = db.execute('SELECT id, riderId FROM Activity WHERE id=?', [act_id]).fetchone()
    if not row:
        return False
    seg_ids = _drop_derived(db, act_id)
    db.execute('DELETE FROM Activity WHERE id=?', [act_id])
    _drop_photos(db, [act_id])
    db.execute('UPDATE RideSensor SET rideKind=NULL, rideId=NULL WHERE rideId=?', [act_id])      # the phone's sensor recording stays, waiting for another ride
    db.execute("UPDATE ActivityDuplicate SET primaryId='' WHERE primaryId=? AND status='kept_both'", [act_id])
    for sid in seg_ids:
        _refresh_prs(db, sid)
    tombstone(db, act_id, row['riderId'])
    return True


def parked_for(db, primary_id):
    ensure_schema(db)
    return db.execute("SELECT id, source, reason, status, parkedAt, rowJson FROM ActivityDuplicate WHERE primaryId=? AND status='parked' ORDER BY parkedAt", [primary_id]).fetchall()


def _insert_row(db, row):
    cols = list(row.keys())
    db.execute(f"INSERT OR REPLACE INTO Activity ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [row[c] for c in cols])


def _restore(db, dup_id):
    d = db.execute('SELECT * FROM ActivityDuplicate WHERE id=?', [dup_id]).fetchone()
    if not d:
        return None, None
    row = json.loads(d['rowJson'])
    if not row:                                         # discarded: the data is gone
        return None, None
    _insert_row(db, row)
    return d, row


def swap(db, dup_id):
    """Make the parked recording the main one; the current main one is parked in its place. Returns the new main id (or None)."""
    d = db.execute('SELECT * FROM ActivityDuplicate WHERE id=?', [dup_id]).fetchone()
    if not d or d['status'] != 'parked':
        return None
    old_primary = d['primaryId']
    row = json.loads(d['rowJson'])
    if not row:
        return None
    db.execute('DELETE FROM ActivityDuplicate WHERE id=?', [dup_id])
    if db.execute('SELECT 1 FROM Activity WHERE id=?', [old_primary]).fetchone():
        park(db, old_primary, dup_id, 'You chose to use the other recording.')
    _insert_row(db, row)
    others = db.execute("SELECT id FROM ActivityDuplicate WHERE primaryId=? AND id<>?", [old_primary, old_primary]).fetchall()
    for o in others:                                    # anything else parked under the old main now hangs off the new one
        db.execute('UPDATE ActivityDuplicate SET primaryId=? WHERE id=?', [dup_id, o['id']])
    rebuild_derived(db, dup_id)
    return dup_id


def keep_both(db, dup_id):
    """Restore the parked ride as its own ride and remember never to merge this pair again."""
    d, _ = _restore(db, dup_id)
    if not d:
        return None
    db.execute("UPDATE ActivityDuplicate SET status='kept_both' WHERE id=?", [dup_id])
    rebuild_derived(db, dup_id)
    return dup_id


def discard(db, dup_id):
    """Delete a parked recording for good. Its id stays remembered (so a Garmin re-sync does not bring it back)."""
    n = db.execute("UPDATE ActivityDuplicate SET rowJson='{}', status='discarded' WHERE id=? AND status='parked'", [dup_id]).rowcount
    return bool(n)


def recover_names(db):
    """Run once (Settings.dupNameFixDone): before park() looked at names, a merge kept the kept recording's own name even when it was made up
    (Garmin's "London Cycling") and the copy set aside had one the user chose. That copy is still whole in rowJson, so its name is taken back by
    the same rule. Discarded copies have no data left; friends' activities are left alone. Commits. Returns {'checked', 'renamed', 'ran'}."""
    ensure_schema(db)
    s = db.execute('SELECT dupNameFixDone FROM Settings WHERE id=1').fetchone()
    if not s or s['dupNameFixDone']:
        return {'checked': 0, 'renamed': 0, 'ran': False}
    # Only the ids go through the sort: rowJson is a whole activity with its streams, and sorting every parked copy at once filled the disk
    # (SQLite's temporary sort) on a large install. Each copy is read on its own below.
    rows = db.execute("""SELECT d.id, d.primaryId FROM ActivityDuplicate d JOIN Activity a ON a.id=d.primaryId
                          WHERE d.status='parked' AND a.riderId NOT IN (SELECT riderId FROM Friend WHERE riderId IS NOT NULL)
                          ORDER BY d.parkedAt""").fetchall()
    renamed = set()
    for r in rows:
        row_json = db.execute('SELECT rowJson FROM ActivityDuplicate WHERE id=?', [r['id']]).fetchone()
        try:
            other = json.loads(row_json['rowJson']).get('name')
        except (ValueError, TypeError, AttributeError):
            continue
        kept = db.execute('SELECT name FROM Activity WHERE id=?', [r['primaryId']]).fetchone()
        if _take_better_name(db, r['primaryId'], kept['name'], other):
            renamed.add(r['primaryId'])
    db.execute('UPDATE Settings SET dupNameFixDone=1 WHERE id=1')
    db.commit()
    if renamed:
        log.warning('Duplicates: %d merged activit%s took back the name chosen on the copy set aside', len(renamed), 'y' if len(renamed) == 1 else 'ies')
    return {'checked': len(rows), 'renamed': len(renamed), 'ran': True}


def recheck_workouts(db):
    """Run once (Settings.workoutDupCheckDone), after walks, runs, ... moved in with the rides: the duplicate check never compared a workout with
    anything, so a Garmin run and its Strava copy were both kept. Checks every non-ride activity once; the weaker copy is set aside (not deleted).
    Friends' activities are left alone. Commits. Returns {'checked', 'duplicates', 'ran'}."""
    from services.sports import RIDE_SQL
    s = db.execute('SELECT workoutDupCheckDone FROM Settings WHERE id=1').fetchone()
    if not s or s['workoutDupCheckDone']:
        return {'checked': 0, 'duplicates': 0, 'ran': False}
    ids = [r[0] for r in db.execute(f"""SELECT id FROM Activity WHERE NOT {RIDE_SQL}
                                         AND riderId NOT IN (SELECT riderId FROM Friend WHERE riderId IS NOT NULL) ORDER BY startDateLocal""").fetchall()]
    found = 0
    for act_id in ids:
        if db.execute('SELECT 1 FROM Activity WHERE id=?', [act_id]).fetchone():      # may have been set aside already as another's twin
            if resolve(db, act_id):
                found += 1
    db.execute('UPDATE Settings SET workoutDupCheckDone=1 WHERE id=1')
    db.commit()
    if found:
        log.warning('Duplicates: %d walk(s), run(s), ... turned out to be an activity already here', found)
    return {'checked': len(ids), 'duplicates': found, 'ran': True}
