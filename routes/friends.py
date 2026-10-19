import json
import logging
import threading
import time
import urllib.parse
import urllib.request
import urllib.error

from flask import Blueprint, Response, abort, jsonify, redirect, render_template, request, stream_with_context, url_for

log = logging.getLogger(__name__)

from database import get_db, query_db
from services.segments import scan_activity_against_segments, scan_all_activities, _refresh_prs, seg_sport
from services.limits import bounded_lines
from services.peer_http import open_peer
from services import feed_tokens

bp = Blueprint('friends', __name__)

BATCH = 50
MAX_IDS = 100        # rides asked for by id in one request (?ids=): a short URL, and an interrupted request loses little

# Riders who live on this instance. A synced friend is stored as a Rider too, and their rides were shared with us, not with
# whoever holds our feed token, so the feed never offers them.
OWN_RIDERS_SQL = 'id NOT IN (SELECT riderId FROM Friend WHERE riderId IS NOT NULL)'


def _feed_token():
    """The friend's FeedToken row (what they may read), or 403. Header only: a token in the query string would end up in proxy
    access logs. Looked up by its hash, so there's no secret to compare in constant time."""
    row = feed_tokens.lookup(request.headers.get('X-Feed-Token', ''))
    if not row:
        abort(403)
    return row


@bp.route('/api/riders')
def riders_list():
    """Token-authenticated rider list — lets a friend's instance discover who's here."""
    if not _feed_token()['shareRides']:
        return jsonify([])
    riders = query_db(f'SELECT id, name, isDefault FROM Rider WHERE {OWN_RIDERS_SQL} ORDER BY isDefault DESC, name ASC')
    return jsonify([dict(r) for r in riders])


@bp.route('/api/foods-feed')
def foods_feed():
    """Token-authenticated NDJSON of this instance's own user-made foods (see services/shared_foods.py). A token that doesn't
    share foods gets a complete, empty feed, so the friend's copy of our foods is cleared on their next sync."""
    share = _feed_token()['shareFoods']
    from services import shared_foods

    def generate():
        owner = query_db('SELECT name FROM Rider WHERE isDefault=1 LIMIT 1', one=True)
        yield json.dumps({'type': 'meta', 'name': owner['name'] if owner else 'Unknown'}) + '\n'
        n = 0
        for rec in (shared_foods.feed_records() if share else ()):
            n += 1
            yield json.dumps(rec) + '\n'
        yield json.dumps({'type': 'end', 'count': n}) + '\n'      # lets the receiver know the feed arrived whole

    return Response(stream_with_context(generate()), mimetype='application/x-ndjson')


@bp.route('/api/food-image/<ref>')
def food_image(ref):
    """A photo referenced by /api/foods-feed ('<sha1>.<ext>')."""
    if not _feed_token()['shareFoods']:
        abort(403)
    from services import food_cache
    food_cache.init_path()
    hit = food_cache.local_image('local:' + ref)
    if not hit:
        abort(404)
    return Response(hit[0], mimetype=hit[1], headers={'Cache-Control': 'public, max-age=86400'})


@bp.route('/api/feed')
def feed():
    """Token-authenticated NDJSON stream — no session required.
    Each line is a JSON object with a 'type' field: meta | segment | ride | manifest | end ('end' only once everything was sent).
    A 'ride' is any of the rider's activities, of any sport (rides only before 0.7.6; the line keeps its name for older friends).
    shareRides on the token: share the activities.
    Accepts ?since=YYYY-MM-DD and ?rider=<name> to filter. The token decides whether segments and rides are sent at all, and
    its date window (inclusive) narrows the rides.
    Since 0.7.6 a friend asks ?manifest=1 instead: the segments and a manifest, [id, updatedAt] of every ride it may have, and no rides; then
    ?ids=<id>,<id>,... for just the rides it is missing or that changed here (no segments). A friend on an older version sends neither and gets
    the rides that started after `since`, as before.
    """
    scope = dict(_feed_token())

    since = request.args.get('since')
    rider_name = request.args.get('rider')
    manifest = request.args.get('manifest') == '1'
    ids = [i for i in (request.args.get('ids') or '').split(',') if i][:MAX_IDS] if 'ids' in request.args else None

    def generate():
        from database import get_db as _get_db
        db = _get_db()

        if rider_name:
            rider = db.execute(f'SELECT * FROM Rider WHERE name=? COLLATE NOCASE AND {OWN_RIDERS_SQL}', [rider_name]).fetchone()
        else:
            rider = db.execute('SELECT * FROM Rider WHERE isDefault=1').fetchone()
        yield json.dumps({'type': 'meta', 'name': rider['name'] if rider else 'Unknown'}) + '\n'

        if scope['shareSegments'] and ids is None:
            for s in db.execute('SELECT id, name, startLat, startLng, endLat, endLng, '
                                "distanceM, elevationGainM, polyline, COALESCE(sport, 'ride') AS family FROM Segment WHERE friendId IS NULL"):
                # `sport` is what a friend on a version before 0.7.3 reads: 'run' for anything on foot, else 'ride'. `family` is the whole answer.
                yield json.dumps({'type': 'segment', **dict(s), 'sport': 'run' if s['family'] == 'foot' else 'ride'}) + '\n'

        owner_id = rider['id'] if rider else None
        where, args = ['riderId=?'], [owner_id]
        if scope['sinceDate']:
            where.append('substr(startDateLocal, 1, 10) >= ?')
            args.append(scope['sinceDate'])
        if scope['untilDate']:
            where.append('substr(startDateLocal, 1, 10) <= ?')
            args.append(scope['untilDate'])

        if manifest:
            # No such rider (renamed?): no manifest, so the friend deletes nothing. Rides no longer shared: an empty one, so they go.
            if owner_id:
                rides = db.execute(f"SELECT id, COALESCE(updatedAt, createdAt, '') FROM Activity WHERE {' AND '.join(where)}", args).fetchall() \
                    if scope['shareRides'] else []
                yield json.dumps({'type': 'manifest', 'rides': [[r[0], r[1]] for r in rides]}) + '\n'
        elif owner_id and scope['shareRides']:
            if ids is not None:
                where.append('id IN ({})'.format(','.join('?' * len(ids)) or "''"))
                args.extend(ids)
            elif since:
                where.append('startDateLocal > ?')
                args.append(since)
            cur = db.execute(f'''
                SELECT id, name, type, sportType, startDate, startDateLocal, distance, movingTime,
                       elapsedTime, totalElevationGain, averageSpeed, maxSpeed,
                       averageHeartrate, maxHeartrate, averageWatts, weightedAvgWatts,
                       averageCadence, calories, startLat, startLng, streams,
                       weatherTempC, weatherWindKph, weatherGustKph, weatherWindDir,
                       weatherHumidity, weatherRainMm, weatherCode, weatherSummary, weatherWindRel, steps,
                       COALESCE(updatedAt, createdAt, '') AS updatedAt
                FROM Activity WHERE {' AND '.join(where)} ORDER BY startDateLocal DESC
            ''', args)
            for row in cur:
                d = dict(row)
                d.pop('type', None)  # avoid collision with the NDJSON routing key
                yield json.dumps({'type': 'ride', **d}) + '\n'
        yield json.dumps({'type': 'end'}) + '\n'

    return Response(stream_with_context(generate()), mimetype='application/x-ndjson')


@bp.route('/friends')
def index():
    settings = query_db('SELECT friendSyncInterval FROM Settings WHERE id=1', one=True)
    sync_interval = settings['friendSyncInterval'] if settings and settings['friendSyncInterval'] is not None else 15

    friends = query_db('''
        SELECT f.*, r.name AS rider_name, r.avatarPath AS rider_avatar
        FROM Friend f
        LEFT JOIN Rider r ON r.id = f.riderId
        ORDER BY f.name
    ''')

    return render_template('friends.html', friends=friends, feed_tokens=feed_tokens.tokens(),
                           sync_interval=sync_interval)


@bp.route('/friends/sync-interval', methods=['POST'])
def set_sync_interval():
    try:
        interval = int(request.form.get('interval', 15))
    except ValueError:
        interval = 15
    db = get_db()
    db.execute('UPDATE Settings SET friendSyncInterval=? WHERE id=1', [interval])
    db.commit()
    return redirect(url_for('friends.index'))


@bp.route('/friends/tokens', methods=['POST'])
def create_token():
    """Returns the new token once, as JSON (only its hash is kept)."""
    token, tid = feed_tokens.create(request.form.get('name'), request.form)
    return jsonify({'id': tid, 'token': token})


@bp.route('/friends/tokens/<int:tid>', methods=['POST'])
def update_token(tid):
    feed_tokens.update(tid, request.form)
    return redirect(url_for('friends.index') + '#feed-tokens')


@bp.route('/friends/tokens/<int:tid>/revoke', methods=['POST'])
def revoke_token(tid):
    feed_tokens.revoke(tid)
    return redirect(url_for('friends.index') + '#feed-tokens')


@bp.route('/friends/probe', methods=['POST'])
def probe():
    """Fetch the rider list from a remote instance to populate the Add Friend dropdown."""
    data  = request.get_json(silent=True) or {}
    url   = (data.get('url')   or '').strip().rstrip('/')
    token = (data.get('token') or '').strip()
    if not url:
        return jsonify({'error': 'URL required'}), 400

    probe_url = url + '/api/riders'
    headers   = {'User-Agent': 'Headwind/1.0'}
    if token:
        headers['X-Feed-Token'] = token

    try:
        resp = open_peer(probe_url, headers, timeout=10)
        riders = json.loads(resp.read())
        return jsonify({'riders': riders})
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return jsonify({'error': 'Invalid token — check the feed token and try again'})
        if e.code == 404:
            # Older instance without /api/riders — return a synthetic default entry
            return jsonify({'riders': [{'id': None, 'name': 'Default rider', 'isDefault': 1}]})
        return jsonify({'error': f'HTTP {e.code} from remote instance'})
    except Exception as e:
        log.warning('Fetching riders from a friend failed', exc_info=True)
        return jsonify({'error': f'Could not connect: {e}'})


@bp.route('/friends/add', methods=['POST'])
def add():
    name       = (request.form.get('name')       or '').strip()
    url        = (request.form.get('url')        or '').strip().rstrip('/')
    token      = (request.form.get('token')      or '').strip()
    rider_name = (request.form.get('riderName')  or '').strip() or None

    if not name or not url:
        return redirect(url_for('friends.index'))

    db = get_db()
    db.execute('INSERT INTO Friend (name, url, token, riderName) VALUES (?,?,?,?)',
               [name, url, token, rider_name])
    db.commit()
    fid = db.execute('SELECT last_insert_rowid()').fetchone()[0]

    # Large initial syncs can take minutes — run in background so the browser doesn't hang
    from flask import current_app
    app = current_app._get_current_object()
    threading.Thread(target=_bg_sync, args=(app, fid), daemon=True).start()
    return redirect(url_for('friends.index'))


def _bg_sync(app, friend_id):
    with app.app_context():
        _do_sync(friend_id)


@bp.route('/friends/<int:fid>/sync', methods=['POST'])
def sync(fid):
    count, err = _do_sync(fid)
    return jsonify({'ok': err is None, 'synced': count, 'error': err})


@bp.route('/friends/<int:fid>/token', methods=['POST'])
def set_friend_token(fid):
    """Swap in a new token a friend gave us (e.g. their own per-friend token in place of the old shared one), keeping their rides."""
    token = (request.form.get('token') or '').strip()
    if token:
        db = get_db()
        db.execute('UPDATE Friend SET token=? WHERE id=?', [token, fid])
        db.commit()
    return redirect(url_for('friends.index'))


@bp.route('/friends/<int:fid>/delete', methods=['POST'])
def delete(fid):
    db = get_db()
    friend = query_db('SELECT riderId FROM Friend WHERE id=?', [fid], one=True)
    if friend and friend['riderId']:
        db.execute('DELETE FROM SegmentEffort WHERE activityId IN '
                   '(SELECT id FROM Activity WHERE riderId=?)', [friend['riderId']])
        db.execute('DELETE FROM BestEffort WHERE activityId IN (SELECT id FROM Activity WHERE riderId=?)', [friend['riderId']])
        db.execute('DELETE FROM RideMemory WHERE rideId IN (SELECT id FROM Activity WHERE riderId=?)', [friend['riderId']])
        db.execute('DELETE FROM Activity WHERE riderId=?', [friend['riderId']])
        db.execute('DELETE FROM Rider WHERE id=?', [friend['riderId']])
    # Segments imported from this friend cascade-delete their efforts via ON DELETE CASCADE
    db.execute('DELETE FROM Segment WHERE friendId=?', [fid])
    db.execute('DELETE FROM Friend WHERE id=?', [fid])
    db.commit()

    # Refresh PRs for remaining segments
    for seg in query_db('SELECT id FROM Segment'):
        _refresh_prs(db, seg['id'])
    db.commit()

    return redirect(url_for('friends.index'))


_syncing = set()                 # friend ids with a sync running: a second one would only fight the first for the write lock
_syncing_lock = threading.Lock()


def _do_sync(friend_id):
    """Rides + segments, then the friend's shared foods. A foods problem never fails the ride sync."""
    with _syncing_lock:
        if friend_id in _syncing:
            return 0, 'Already syncing'
        _syncing.add(friend_id)
    try:
        return _do_sync_once(friend_id)
    finally:
        with _syncing_lock:
            _syncing.discard(friend_id)


def _do_sync_once(friend_id):
    result = _do_ride_sync(friend_id)
    try:
        from services import shared_foods
        friend = query_db('SELECT * FROM Friend WHERE id=?', [friend_id], one=True)
        if friend:
            n, err = shared_foods.sync_friend(friend)
            if err:
                log.info('Shared foods sync for "%s": %s', friend['name'], err)
    except Exception as e:
        log.warning('Shared foods sync failed for friend %s: %s', friend_id, e)
    return result


_SHARED_COLS = ['name', 'type', 'sportType', 'startDate', 'startDateLocal', 'distance', 'movingTime', 'elapsedTime', 'totalElevationGain',
              'averageSpeed', 'maxSpeed', 'averageHeartrate', 'maxHeartrate', 'averageWatts', 'weightedAvgWatts', 'averageCadence', 'calories',
              'startLat', 'startLng', 'streams', 'weatherTempC', 'weatherWindKph', 'weatherGustKph', 'weatherWindDir', 'weatherHumidity',
              'weatherRainMm', 'weatherCode', 'weatherSummary', 'weatherWindRel', 'steps']
_ZERO_IF_MISSING = {'distance', 'movingTime', 'elapsedTime', 'totalElevationGain', 'averageSpeed', 'maxSpeed'}


class _Pull:
    """What one friend sync has received so far."""
    def __init__(self, friend):
        self.friend = friend
        self.name = friend['name']
        self.rider_id = friend['riderId']
        self.rides = {}          # local id -> the friend's updatedAt for it (None from a version before 0.7.6): stored, not matched yet
        self.segments = 0
        self.manifest = None     # remote id -> updatedAt, every ride the friend shares (0.7.6 on)
        self.complete = False    # the feed said 'end'


def _open_feed(friend, params):
    url = friend['url'].rstrip('/') + '/api/feed' + ('?' + '&'.join(params) if params else '')
    headers = {'User-Agent': 'Headwind/1.0'}
    if friend['token']:
        headers['X-Feed-Token'] = friend['token']
    log.info('Friends sync: streaming feed for "%s" from %s', friend['name'], url)
    try:
        return open_peer(url, headers, timeout=60), None
    except urllib.error.HTTPError as e:
        log.warning('Friends sync: HTTP %s from %s', e.code, url)
        return None, f'HTTP {e.code} from {url}'
    except Exception as e:
        log.warning('Friends sync: connect failed for "%s": %s', friend['name'], e)
        return None, str(e)


def _read_feed(db, pull, resp):
    """Store everything in one feed response as it lands. Returns an error text, or None."""
    friend_id = pull.friend['id']
    try:
        for raw_line in bounded_lines(resp, 500 * 1024 ** 2, 2_000_000, 900):
            line = raw_line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line.decode())
            except Exception:
                continue

            t = obj.get('type')

            if t == 'meta':
                pull.name = obj.get('name') or pull.friend['name']
                if not pull.rider_id:
                    db.execute('INSERT INTO Rider (name, isDefault) VALUES (?, 0)', [pull.name])
                    pull.rider_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
                    db.execute('UPDATE Friend SET riderId=? WHERE id=?', [pull.rider_id, friend_id])
                    log.info('Friends sync: created rider "%s" (id=%s)', pull.name, pull.rider_id)
                else:
                    db.execute('UPDATE Rider SET name=? WHERE id=?', [pull.name, pull.rider_id])

            elif t == 'segment':
                if _store_segment(db, friend_id, obj):
                    pull.segments += 1

            elif t == 'ride' and pull.rider_id:
                pull.rides[_store_ride(db, friend_id, pull.rider_id, obj)] = obj.get('updatedAt')
                if len(pull.rides) % BATCH == 0:
                    log.info('Friends sync: streamed %d rides for "%s"…', len(pull.rides), pull.name)

            elif t == 'manifest':
                pull.manifest = {str(r[0]): r[1] or '' for r in obj.get('rides') or [] if isinstance(r, list) and len(r) == 2}

            elif t == 'end':
                pull.complete = True

            db.commit()   # each item as it lands: never hold the write lock while waiting on the network for the next
        return None
    except Exception as e:
        log.warning('Friends sync: stream error for "%s": %s', pull.name, e)
        db.commit()  # save whatever we got
        return str(e)
    finally:
        resp.close()


def _store_segment(db, friend_id, obj):
    """One of the friend's segments. Marked matchPending when it is new or where it is, its length or its family changed: every sync sends
    every segment, and only those are matched again. Returns False for one that is ignored."""
    from services.segments import clean_polyline, valid_coord
    _sc = valid_coord(obj.get('startLat'), obj.get('startLng'))
    _ec = valid_coord(obj.get('endLat'), obj.get('endLng'))
    if not _sc or not _ec:
        return False                       # a friend's segment with impossible coordinates is ignored
    _fam = seg_sport({'sport': obj.get('family') or obj.get('sport')})     # 0.7.3 sent 'eride' for e-bike segments, older versions 'run' for foot
    _shape = clean_polyline(obj.get('polyline'))
    _poly = json.dumps(_shape) if _shape else None
    existing = db.execute(
        "SELECT id, startLat, startLng, endLat, endLng, distanceM, polyline, COALESCE(sport, 'ride') "
        'FROM Segment WHERE friendId=? AND sourceSegId=?',
        [friend_id, obj['id']]
    ).fetchone()
    if existing:
        changed = tuple(existing[1:]) != (_sc[0], _sc[1], _ec[0], _ec[1], obj.get('distanceM'), _poly, _fam)
        db.execute('''UPDATE Segment SET name=?, startLat=?, startLng=?, endLat=?, endLng=?,
                          distanceM=?, elevationGainM=?, polyline=?, sport=?, matchPending=MAX(COALESCE(matchPending, 0), ?) WHERE id=?''', [
            obj.get('name'), _sc[0], _sc[1], _ec[0], _ec[1],
            obj.get('distanceM'), obj.get('elevationGainM'), _poly, _fam, int(changed),
            existing[0],
        ])
    else:
        db.execute('''INSERT INTO Segment (name, startLat, startLng, endLat, endLng,
                          distanceM, elevationGainM, polyline, friendId, sourceSegId, sport, matchPending)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,1)''', [
            obj.get('name'), _sc[0], _sc[1], _ec[0], _ec[1],
            obj.get('distanceM'), obj.get('elevationGainM'), _poly,
            friend_id, obj['id'], _fam,
        ])
    return True


def _store_ride(db, friend_id, rider_id, obj):
    """One of the friend's activities (any sport), new or changed: every field is taken again. srcUpdatedAt '' until it has been matched against the segments,
    so one stored by a sync that never got that far is asked for again. Returns its local id."""
    remote_id = f"f{friend_id}_{obj['id']}"
    vals = [obj.get(c) or 0 if c in _ZERO_IF_MISSING else obj.get(c) for c in _SHARED_COLS]
    vals[_SHARED_COLS.index('type')] = obj.get('sportType')       # the NDJSON routing key took 'type'
    db.execute(f'''
        INSERT INTO Activity (id, {', '.join(_SHARED_COLS)}, rawData, riderId, srcUpdatedAt, createdAt, updatedAt)
        VALUES (?, {', '.join('?' * len(_SHARED_COLS))}, '{{}}', ?, '', datetime('now'), datetime('now'))
        ON CONFLICT(id) DO UPDATE SET {', '.join(f'{c}=excluded.{c}' for c in _SHARED_COLS)},
            riderId=excluded.riderId, srcUpdatedAt='', updatedAt=datetime('now')
    ''', [remote_id, *vals, rider_id])
    return remote_id


def _forget_ride(db, act_id):
    """A ride the friend no longer shares (deleted, or out of the token's dates). Returns the segments it was on. Does not commit."""
    from services.duplicates import _drop_derived
    seg_ids = _drop_derived(db, act_id)
    db.execute('DELETE FROM Activity WHERE id=?', [act_id])
    return seg_ids


def _chunks(items, n):
    items = list(items)
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _do_ride_sync(friend_id):
    """Segments and rides from one friend. From a friend on 0.7.6 or later: the segments and a manifest of every ride they share, then just the
    rides missing here or changed there, MAX_IDS at a time; a ride they no longer share goes. A friend on an older version gets the old request
    and sends the rides that started since the day of the last sync. The sync only counts as done (lastSynced) when everything arrived."""
    friend = query_db('SELECT * FROM Friend WHERE id=?', [friend_id], one=True)
    if not friend:
        return 0, 'Friend not found'

    rider = ['rider=' + urllib.parse.quote(friend['riderName'])] if friend['riderName'] else []
    # What a friend before 0.7.6 reads (it ignores manifest=1): trimmed to the date so we don't miss rides added on the same day as last sync
    since = ['since=' + friend['lastSynced'][:10]] if friend['lastSynced'] else []
    resp, err = _open_feed(friend, rider + since + ['manifest=1'])
    if err:
        return 0, err

    db = get_db()
    pull = _Pull(friend)
    err = _read_feed(db, pull, resp)
    gone_segs = set()

    if pull.manifest is not None and pull.complete and pull.rider_id:
        prefix = f'f{friend_id}_'
        remote = {prefix + k: u for k, u in pull.manifest.items()}
        local = {r[0]: r[1] for r in db.execute('SELECT id, srcUpdatedAt FROM Activity WHERE riderId=?', [pull.rider_id])}
        gone = [aid for aid in local if aid not in remote]
        if gone:
            log.info('Friends sync: %d rides no longer shared by "%s"', len(gone), pull.name)
            for aid in gone:
                gone_segs.update(_forget_ride(db, aid))
            db.commit()
        # A ride from before 0.7.6 has no srcUpdatedAt: it is current unless it changed there after the last sync
        before = (friend['lastSynced'] or '').replace('T', ' ')
        want, settle = [], []
        for aid, u in remote.items():
            if aid not in local:
                want.append(aid[len(prefix):])
            elif local[aid] is None:
                if u > before:
                    want.append(aid[len(prefix):])
                else:
                    settle.append((u, aid))
            elif local[aid] == '' or local[aid] < u:          # '': stored by a sync that stopped before matching it
                want.append(aid[len(prefix):])
        db.executemany('UPDATE Activity SET srcUpdatedAt=? WHERE id=?', settle)
        db.commit()
        if want:
            log.info('Friends sync: fetching %d new or changed rides from "%s"', len(want), pull.name)
        for ids in _chunks(want, MAX_IDS):
            resp, err = _open_feed(friend, rider + ['ids='+ ','.join(urllib.parse.quote(i, safe='') for i in ids)])
            if not err:
                pull.complete = False
                err = _read_feed(db, pull, resp)
                if not err and not pull.complete:
                    err = 'feed ended early'
            if err:
                break

    log.info('Friends sync: received %d rides, %d segments from "%s"', len(pull.rides), pull.segments, pull.name)

    # ── New and changed segments: matched from scratch against every activity near them ──
    # matchPending survives a sync that stopped before this, so the next one still matches them
    pending = [r[0] for r in db.execute('SELECT id FROM Segment WHERE friendId=? AND matchPending=1', [friend_id])]
    if pending:
        log.info('Friends sync: matching %d new or changed segments…', len(pending))
        scan_all_activities(db, segment_ids=pending)   # clears their old efforts, reads only the activities that go near them, picks PRs
        db.execute('UPDATE Segment SET matchPending=0 WHERE friendId=? AND matchPending=1', [friend_id])
        db.commit()

    # ── The received rides against the other segments (the pending ones have just seen them) ──
    affected = set(gone_segs)
    others = db.execute(f"SELECT * FROM Segment WHERE id NOT IN ({','.join('?' * len(pending))})", pending).fetchall()
    if pull.rides:
        log.info('Friends sync: scanning %d rides against %d segments…', len(pull.rides), len(others))
        done = 0
        for ids in _chunks(pull.rides, 500):
            marks = ','.join('?' * len(ids))
            # a changed ride is matched from scratch: its sport or its track may be different now
            affected.update(r[0] for r in db.execute(f'SELECT DISTINCT segmentId FROM SegmentEffort WHERE activityId IN ({marks})', ids))
            db.execute(f'DELETE FROM SegmentEffort WHERE activityId IN ({marks}) AND segmentId NOT IN ({",".join("?" * len(pending))})',
                       [*ids, *pending])
            acts = db.execute(f"SELECT id, startDateLocal, streams, sportType FROM Activity WHERE id IN ({marks}) "
                              "AND streams IS NOT NULL AND streams NOT IN ('null', '{}')", ids).fetchall() if others else []
            for act in acts:
                scan_activity_against_segments(db, act, others)
                db.commit()   # one ride at a time, so other writes (a token, a Garmin sync) wait milliseconds, not a minute
                done += 1
                if done % BATCH == 0:
                    log.info('Friends sync: segment scan %d / %d…', done, len(pull.rides))
                    time.sleep(0.5)
            affected.update(r[0] for r in db.execute(f'SELECT DISTINCT segmentId FROM SegmentEffort WHERE activityId IN ({marks})', ids))
            db.executemany('UPDATE Activity SET srcUpdatedAt=? WHERE id=?', [(pull.rides[i], i) for i in ids])
            db.commit()

    # Only the segments the received (or removed) rides were or are on can have a new PR
    affected -= set(pending)
    log.info('Friends sync: refreshing PRs on %d segments…', len(affected))
    for sid in affected:
        _refresh_prs(db, sid)
        db.commit()

    old_friend = pull.manifest is None and not pull.complete      # a version before 0.7.6 sends no 'end': all it can tell us is no error
    if not err and (pull.complete or old_friend):
        db.execute("UPDATE Friend SET lastSynced=datetime('now'), name=? WHERE id=?", [pull.name, friend_id])
    else:
        db.execute('UPDATE Friend SET name=? WHERE id=?', [pull.name, friend_id])
    db.commit()
    log.info('Friends sync: %s — %d rides, %d segments for "%s"', 'done' if not err else 'stopped early', len(pull.rides), pull.segments, pull.name)
    return len(pull.rides), err
