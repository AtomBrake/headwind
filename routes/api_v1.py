"""Endpoints for the phone app (Bearer device token, see services/device_auth.py).

  GET  /api/v1/ping        who this instance is (the app calls it right after pairing), the rider's bikes for the app's bike picker, and
                            server_url, the https outside address set in Settings (null when there's none), and favourite_sports: the
                            rider's favourites ({label, icon, group} or {label, icon, sport}, for GET /api/v1/activities' group= or sport=)
  GET  /api/v1/today       everything the app's home screen needs in ONE request (fast start)
  POST /api/v1/activities  every activity from the phone, the Watch or Apple Health, whatever its sport (services/uploads.py): multipart
                            with file=GPX for one with a track, JSON for a session with no track (strength, a pool swim, an indoor ride).
                            Idempotent per client_id. POST /api/v1/activities/known {client_ids} says which the server has.
  POST /api/v1/rides, POST /api/v1/workouts   the older upload paths for a ride or another sport with a track: the same, with the kind
                            decided and the reply the released apps read. Kept until they all send to /activities (ping's api 2 says it's there).
  GET  /api/v1/activities  every activity, newest first and paged; GET /api/v1/activities/<id> one, DELETE deletes it
  POST /api/v1/activities/<id>/bike   change a ride's bike (JSON {bike_id: id or null}); .../sport, .../commute, .../duplicate/<dup>/<action>
  POST /api/v1/activities/<id>/photos   add one photo (multipart: file); DELETE .../photos/<pid>; GET /api/v1/photos/<name> serves one;
                            POST .../photos/order puts them in order (JSON {ids}); PATCH .../photos/<pid> sets a caption (JSON {caption})
  GET  /api/v1/rides, /api/v1/rides/<kind>/<id>[/...]   the older paths for the same, with kind ('ride' or 'workout') in the path and the
                            answers, and ride_id in a duplicate's. Kept until the apps all use /activities (ping's api 3 says it's there).
  GET  /api/v1/workouts    recent workouts
  DELETE /api/v1/workouts/<id>
  GET  /api/v1/zwift/<slug>.png   a Zwift world's map, for a virtual ride's zwift_world in GET /api/v1/activities/<id>
  POST /api/v1/health/days  Apple Health's daily figures from the iPhone (JSON {days: [{date, metric, value}]}), GET /api/v1/health what's stored,
                            DELETE /api/v1/health forgets it all (services/health.py)
  POST /api/v1/devices/watch   a token of its own for the phone's Apple Watch (services/device_auth.create_child)
  POST /api/v1/friends/tokens  a feed token for a friend, with its share code (services/feed_tokens.py), for the app to show as a QR code;
                            POST /api/v1/friends/probe {code} who a friend's code connects to, POST /api/v1/friends {code, rider, name} adds them;
                            GET /api/v1/friends lists them, for GET /api/v1/activities?rider=<their rider id>|all (a friend's activities, read-only)
  POST /api/v1/live        the phone's live reading while it records (services/live.py), with `recording`, the recording's id;
                            POST /api/v1/live/share {recording, sport, track} starts a live tracking link for it (or gives the running one),
                            DELETE /api/v1/live/share {recording} stops it (services/live_share.py)
The nutrition endpoints the app also uses (/nutrition/api/log, /water, /search, /lookup/<barcode> ...) accept the same token.
"""
import logging
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request

from database import get_db, query_db
from services import external_url, friend_rides, tz
from services.sports import KIND_SQL, kind as sport_kind, kind_of
from services import streams as _streams

log = logging.getLogger(__name__)
bp = Blueprint('api_v1', __name__, url_prefix='/api/v1')
MAX_GPX = 25 * 1024 * 1024
MAX_PHOTOS = 60                    # per activity, from the app
OLD_KINDS = ('ride', 'workout')    # the kind in the older /rides/<kind>/<id> paths; the /activities/<id> ones have none (kind None)
# A whole request is at most limits.MAX_PHONE_REQUEST (the size hook in app.py)


def _rider():
    return query_db('SELECT id, name FROM Rider WHERE isDefault=1 LIMIT 1', one=True)


def _today():
    return tz.today().isoformat()


def _public(w):
    w = dict(w)
    w.pop('streams', None)
    return w


@bp.route('/ping')
def ping():
    r = _rider()
    from services import favourites
    s = query_db('SELECT units, calorieAdjustPct, favouriteSports FROM Settings WHERE id=1', one=True)
    # 2: POST /activities takes every upload, and /activities/known is there. 3: GET /activities and /activities/<id>[/...], with no kind
    return jsonify({'ok': True, 'api': 3,
                    'rider': r['name'] if r else None, 'units': (s['units'] if s else None) or 'imperial',
                    'calorie_adjust_pct': (s['calorieAdjustPct'] if s and s['calorieAdjustPct'] is not None else 0),
                    'favourite_sports': [{'label': d['label'], 'icon': d['icon'], ('group' if d['arg'][0] == 'group' else 'sport'): d['arg'][1]}
                                         for d in map(favourites.describe, favourites.parse(s['favouriteSports'] if s else None))],
                    'server_time': tz.now().isoformat(timespec='seconds'), 'bikes': _bikes(r['id']) if r else [],
                    'server_url': external_url.https() or None})        # the outside address: an app that paired on another can offer to move


def _bikes(rider_id):
    """The rider's bikes that aren't archived, for the app's bike picker: id, name, kind (services/gear.BIKE_KINDS), whether it is the default
    for every other ride, and default_for: the kinds of ride it is the default for (sport keys such as 'EBikeRide', 'MountainBikeRide', and
    'Commute'), so the picker can start on the bike the server would pick (services/gear.pick_bike)."""
    from services import gear
    db = get_db()
    d = db.execute('SELECT defaultBikeId FROM Rider WHERE id=?', [rider_id]).fetchone()
    return [{'id': b['id'], 'name': b['name'], 'kind': b['kind'], 'is_default': bool(d and b['id'] == d[0]),
             'default_for': [k for k in gear.bike_defaults_of(db, b['id']) if k != gear.ANY]}
            for b in gear.list_bikes(db, rider_id)]


def _own_bike(rider_id, bike_id):
    """bike_id as an int if it is one of the rider's bikes that isn't archived, else None."""
    from services import gear
    if isinstance(bike_id, bool):
        return None
    try:
        b = gear.get_bike(get_db(), int(bike_id))
    except (TypeError, ValueError):
        return None
    return b['id'] if b and b['riderId'] == rider_id and not b['archived'] else None


def _weight_kg(rider_id):
    # the phone's live calorie estimate needs kilos regardless of the display unit
    try:
        from services import goal_model
        w = goal_model.current_weight_kg(rider_id)
        return round(w, 1) if w else None
    except Exception:
        return None


@bp.route('/today')
def today():
    from routes import nutrition as nu
    from services import workouts
    from services.mqtt import _best_steps_for
    rider = _rider()
    if not rider:
        return jsonify({'error': 'no rider'}), 409
    d = _today()
    day = nu.day_log(d).get_json()
    recent = nu.recent_foods().get_json()
    favs = nu.list_favourites().get_json()
    g = query_db('SELECT steps FROM GarminDaily WHERE date=?', [d], one=True)
    goal = (query_db('SELECT stepGoal FROM Settings WHERE id=1', one=True) or {'stepGoal': None})['stepGoal'] or 8000
    eaten = {k: round(sum((e.get(k) or 0) for e in day.get('entries', [])), 1) for k in ('calories', 'protein', 'carbs', 'fat', 'fibre')}
    goals = day.get('goals') or {}
    return jsonify({
        'date': d, 'rider': rider['name'],
        'goals': goals,
        'eaten': eaten,
        'remaining': {'calories': round((goals.get('cal') or 0) - eaten['calories']) if goals.get('cal') else None,
                      'protein': round((goals.get('protein') or 0) - eaten['protein']) if goals.get('protein') else None},
        'water_ml': day.get('water_ml', 0), 'water_goal_ml': goals.get('water'),
        'burned': day.get('burned'), 'burn_source': day.get('burn_source'),
        'steps': {'today': _best_steps_for(rider['id'], d, g['steps'] if g else None), 'goal': goal},
        'weight': day.get('weight'),
        'weight_kg': _weight_kg(rider['id']),
        'calorie_adjust_pct': __import__('services.calorie_adjust', fromlist=['get_pct']).get_pct(),   # the phone applies the same % to its own live estimate
        'entries': day.get('entries', []),
        'recent': (recent.get('items') if isinstance(recent, dict) else recent) or [],
        'favourites': favs or [],
        'workouts': [_labelled(w) for w in workouts.recent(rider['id'], 0)],
    })


def _labelled(w):
    """A workout as /today and /sync send it, with what a person reads for its sport and its stat group, so the app needn't know every sport."""
    from services import sports as sp
    return {**w, 'label': sp.label(w.get('sport')), 'group': sp.stat_group(w.get('sport'))}


def _period_start(kind, today):
    if kind == 'week':
        return today - timedelta(days=today.weekday())
    if kind == 'month':
        return today.replace(day=1)
    return today.replace(month=1, day=1)


@bp.route('/overview')
def overview():
    """The web Dashboard's numbers, shaped for the phone: lifetime + week/month/year ride totals, 12-week chart, walks/runs, latest recovery."""
    from routes.dashboard import _weekly_data
    rider = _rider()
    if not rider:
        return jsonify({'error': 'no rider'}), 409
    rid = rider['id']
    today = tz.today()

    def sums(since=None):
        """{'ride': row, 'workout': row} over every activity since a date: one query, split by services/sports."""
        q = f'SELECT {KIND_SQL} kind, COUNT(*) n, SUM(distance) d, SUM(totalElevationGain) e, SUM(movingTime) t, SUM(calories) c FROM Activity WHERE riderId=?'
        a = [rid]
        if since:
            q += ' AND date(startDateLocal)>=?'; a.append(since.isoformat())
        got = {r['kind']: r for r in query_db(q + ' GROUP BY kind', a)}
        return {k: got.get(k) or {'n': 0, 'd': 0, 'e': 0, 't': 0, 'c': 0} for k in ('ride', 'workout')}

    def tot(r):
        return {'rides': r['n'] or 0, 'distance_m': round(r['d'] or 0), 'elev_m': round(r['e'] or 0), 'moving_s': int(r['t'] or 0), 'calories': round(r['c'] or 0)}

    def wk(r):
        return {'count': r['n'] or 0, 'distance_m': round(r['d'] or 0), 'calories': round(r['c'] or 0)}

    period = {k: sums(_period_start(k, today)) for k in ('week', 'month', 'year')}

    weekly = [{'label': w['label'], 'distance_m': w['dist_m'], 'elev_m': w['elev_m'], 'calories': w['cals'], 'current': w['current']} for w in _weekly_data(rid)]
    every = _weekly_data(rid, _EverySport())
    groups = _group_totals(rid, {k: _period_start(k, today) for k in ('week', 'month', 'year')})
    weekly_all = [{'label': w['label'], 'current': w['current'],
                   'by': {g: {'distance_m': v['dist_m'], 'moving_s': v['secs'], 'elev_m': v['elev_m'], 'calories': v['cals']} for g, v in w['by'].items()}}
                  for w in every]
    from services import health
    sports = [r['sportType'] for r in query_db('SELECT DISTINCT sportType FROM Ride WHERE riderId=? AND sportType IS NOT NULL ORDER BY sportType', [rid])]
    return jsonify({
        'rider': rider['name'], 'all': tot(sums()['ride']),
        'week': tot(period['week']['ride']), 'month': tot(period['month']['ride']), 'year': tot(period['year']['ride']),
        'workouts': {k: wk(period[k]['workout']) for k in ('week', 'month', 'year')},
        'weekly': weekly, 'sports': sports, 'recovery': health.latest_recovery(rid),
        'groups': groups, 'weekly_all': weekly_all,
    })


class _EverySport:
    """A sport filter that leaves every sport in, for _weekly_data's per-group bars."""
    group = None

    def sql(self, col='sportType'):
        return '1=1', []


def _group_totals(rid, starts):
    """Every stat group the rider has (services/sports.stat_group), with its totals for the week, month, year and all time: count, distance, time,
    climbing and calories, and how its speed reads ('speed', 'pace', 'swim', or 'time' for the sports with no distance). Rides first, then on foot,
    swims and the rest by name, as on the dashboard. A distance is only ever added up within one group."""
    from services import sports as sp
    out = {}
    for key, since in [('all', None)] + list(starts.items()):
        q = (f'SELECT sportType, COUNT(*) n, SUM(distance) d, SUM({sp.climb_sql()}) e, SUM(movingTime) t, SUM(calories) c '
             'FROM Activity WHERE riderId=?')
        a = [rid]
        if since:
            q += ' AND date(startDateLocal)>=?'; a.append(since.isoformat())
        for r in query_db(q + ' GROUP BY sportType', a):
            g = sp.stat_group(r['sportType'])
            if g not in out:
                if key != 'all':
                    continue                             # a group appears once it has anything at all, so 'all' sets the list
                timed = r['sportType'] in sp.NO_DISTANCE
                out[g] = {'key': g, 'label': sp.stat_label(g), 'icon': sp.STAT_ICONS.get(g) or sp.icon(r['sportType']),
                          'style': 'time' if timed else sp.rate_style(group=g), 'has_distance': not timed,
                          'totals': {k: {'count': 0, 'distance_m': 0, 'moving_s': 0, 'elev_m': 0, 'calories': 0} for k in ('week', 'month', 'year', 'all')}}
            t = out[g]['totals'][key]
            t['count'] += r['n'] or 0
            t['distance_m'] += r['d'] or 0
            t['moving_s'] += r['t'] or 0
            t['elev_m'] += r['e'] or 0
            t['calories'] += r['c'] or 0
    for g in out.values():
        for t in g['totals'].values():
            for k in ('distance_m', 'moving_s', 'elev_m', 'calories'):
                t[k] = round(t[k])
    return [out[g] for g in sorted(out, key=sp.stat_order)]


@bp.route('/perform')
def perform():
    """PRs for the Perform tab: all-time fastest at each distance bracket, biggest climbs, and segment PRs.
    Deliberately all-time-only (not the web /data page's year/month grid, which doesn't suit a phone screen) —
    reuses the same BestEffort/Segment/SegmentEffort tables the web page reads, no separate computation."""
    from services.best_efforts import BRACKETS_MI
    from services.sports import indoor_sql
    rider = _rider()
    if not rider:
        return jsonify({'error': 'no rider'}), 409
    rid = rider['id']

    best_efforts = []
    for dist_mi in BRACKETS_MI:
        e = query_db('''
            SELECT e.elapsedSecs, e.avgSpeedMps, e.activityId, e.activityDate, a.name as rideName
            FROM BestEffort e JOIN Ride a ON a.id = e.activityId
            WHERE a.riderId=? AND e.distanceMi=? AND {outdoor}
            ORDER BY e.elapsedSecs ASC LIMIT 1
        '''.format(outdoor=indoor_sql(False)), [rid, dist_mi], one=True)
        # the Ride view: BestEffort has rows for anything with a track, and a walk is not a ride's best 5 miles; nor is a Zwift ride
        if e:
            best_efforts.append({
                'distanceMi': dist_mi, 'secs': e['elapsedSecs'], 'avgSpeedMps': e['avgSpeedMps'] or 0,
                'activityId': e['activityId'], 'activityName': e['rideName'], 'date': e['activityDate'],
                'rideId': e['activityId'], 'rideName': e['rideName'],       # the older keys, until the Android app reads the new
            })

    climbs = query_db('''
        SELECT id, name, totalElevationGain, date(startDateLocal) as d
        FROM Ride WHERE riderId=? AND totalElevationGain > 0
        ORDER BY totalElevationGain DESC LIMIT 5
    ''', [rid])
    biggest_climbs = [{'activityId': c['id'], 'activityName': c['name'], 'elevM': round(c['totalElevationGain']), 'date': c['d'],
                       'rideId': c['id'], 'rideName': c['name']} for c in climbs]

    segs = query_db('''
        SELECT s.id, s.name, s.distanceM, s.elevationGainM,
               COUNT(e.id) AS effort_count, MIN(e.elapsedSecs) AS best_secs,
               MAX(CASE WHEN e.isPR=1 THEN e.activityDate END) AS pr_date
        FROM Segment s
        JOIN SegmentEffort e ON e.segmentId = s.id
        JOIN Ride a ON a.id = e.activityId AND a.riderId=?
        GROUP BY s.id
        HAVING best_secs IS NOT NULL
        ORDER BY pr_date DESC
    ''', [rid])
    segment_list = []
    # Every rider's fastest effort per segment, in one query rather than one per segment
    ids = [s['id'] for s in segs]
    fastest = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        fastest.update({r['segmentId']: r['t'] for r in query_db(
            f"SELECT segmentId, MIN(elapsedSecs) t FROM SegmentEffort WHERE segmentId IN ({','.join('?' * len(chunk))}) GROUP BY segmentId", chunk)})
    for s in segs:
        kom = {'t': fastest.get(s['id'])}
        segment_list.append({
            'id': s['id'], 'name': s['name'], 'distanceM': s['distanceM'], 'elevationGainM': s['elevationGainM'],
            'effortCount': s['effort_count'], 'bestSecs': s['best_secs'], 'prDate': s['pr_date'],
            # global MIN(elapsedSecs) across every rider is always <= the owner's own MIN (their efforts are a subset)
            # — equality means the owner is fastest (or tied), i.e. holds the KOM.
            'isKom': bool(kom and kom['t'] is not None and s['best_secs'] is not None and kom['t'] == s['best_secs']),
        })

    return jsonify({'best_efforts': best_efforts, 'biggest_climbs': biggest_climbs, 'segments': segment_list})


@bp.route('/rides', methods=['POST'])
def upload_ride():
    """The older path for a phone-recorded ride with a track (multipart: file=GPX, optional bike_id, client_id, source): POST /activities with
    the kind decided, and the reply the released apps read. Kept until they all send to /activities."""
    rider = _rider()
    if not rider:
        return jsonify({'error': 'no rider'}), 409
    res, err = _upload(rider, kind='ride')
    if err:
        return err
    imported = int(res['created'])
    # imported=0/skipped=1 means it was already uploaded (retry after a dropped connection) — not an error,
    # ride still identifies which one so the app can show "Uploaded X mi" either way.
    return jsonify({'status': 'duplicate' if res['duplicate'] else ('imported' if imported else 'skipped'), 'imported': imported,
                    'skipped': int(not imported and not res['duplicate']), 'errors': 0, 'ride': res.get('activity') or _summary(res['id']),
                    'duplicate': res['duplicate']})


def _summary(act_id):
    row = query_db('SELECT id, name, distance FROM Activity WHERE id=?', [act_id], one=True)
    return dict(row) if row else {'id': act_id}


def _upload(rider, kind=None):
    """One upload from the phone through services/uploads.receive, whatever its sport: multipart with file=GPX (and sport, name, client_id,
    source, bike_id, calories, steps), or JSON for a session with no track. Returns (result, None) or (None, an error reply)."""
    from services import uploads
    f = request.files.get('file')
    if f is not None:
        if not f.filename:
            return None, (jsonify({'error': 'file (GPX) is required'}), 400)
        data = f.read(MAX_GPX + 1)
        if len(data) > MAX_GPX:
            return None, (jsonify({'error': 'file too large'}), 413)
        form = request.form
        try:
            kcal = float(form['calories']) if form.get('calories') else None
        except ValueError:
            kcal = None
        steps = form.get('steps')
        args = dict(gpx=data, filename=f.filename, sport=form.get('sport'), name=form.get('name'), client_id=form.get('client_id'),
                    source=form.get('source'), calories=kcal, steps=int(steps) if steps and steps.isdigit() else None,
                    bike_id=_own_bike(rider['id'], form.get('bike_id')) if form.get('bike_id') else None)
    elif kind:
        return None, (jsonify({'error': 'file (GPX) is required'}), 400)
    else:
        b = request.get_json(silent=True) or {}
        start = str(b['start']) if b.get('start') else f"{b.get('date')}T{str(b.get('time') or '12:00')[:5]}:00"
        args = dict(sport=b.get('sport'), name=b.get('name'), client_id=b.get('client_id'), source=b.get('source'),
                    bike_id=_own_bike(rider['id'], b.get('bike_id')) if b.get('bike_id') is not None else None,
                    session={'start': start, **{k: b.get(k) for k in ('duration_s', 'distance_m', 'elev_m', 'calories', 'avg_hr', 'notes')}})
    try:
        res = uploads.receive(get_db(), rider['id'], kind=kind, **args)
    except uploads.Refused as e:
        return None, (jsonify({'error': str(e)}), e.status)
    if res['created']:
        _after_upload(res, rider)
    return res, None


def _after_upload(res, rider):
    """Home Assistant and the push notification for a new activity (never fatal). A ride's import has already updated Home Assistant."""
    try:
        if res['via'] == 'track':
            from services.mqtt import push_workout, push_update_nutrition
            push_workout(res['workout'], rider['name'], f"{external_url.get()}/activities/{res['id']}")
            push_update_nutrition()                      # the day's burn changed
        elif res['via'] == 'session':
            _refresh_after_change(res['kind'])
    except Exception as e:
        log.warning('upload side effects failed (non-fatal): %s', e)


def _listed_riders(rider, which):
    """{riderId: name} for GET /api/v1/activities?rider=: empty for the phone's own rider, a friend's rider id, or 'all' for both. None for anything
    else, another local rider's included: the app only ever sees its own and its friends'."""
    friends = friend_rides.friend_riders(get_db())
    if not which:
        return {rider['id']: rider['name']}
    if which == 'all':
        return {rider['id']: rider['name'], **friends}
    try:
        fid = int(which)
    except ValueError:
        return None
    return {fid: friends[fid]} if fid in friends else None


@bp.route('/activities', methods=['GET'])
@bp.route('/rides', defaults={'old': True})
def activity_list(old=False):
    """Every activity, rides and the rest, as one newest-first list, paged: ?offset=0&limit=30&sport=Ride&group=foot&q=text&rider=. group is a stat group
    (services/sports.stat_group: ride, foot, swim, or the sport itself); rider is a friend's rider id (GET /api/v1/friends) or 'all' for yours and
    every friend's, and each item says whose it is (rider, own). The older /rides gives each its kind as well."""
    rider = _rider()
    if not rider:
        return jsonify({'error': 'no rider'}), 409
    riders = _listed_riders(rider, (request.args.get('rider') or '').strip())
    if riders is None:
        return jsonify({'error': 'not found'}), 404
    try:
        offset = max(0, int(request.args.get('offset', 0))); limit = min(100, max(1, int(request.args.get('limit', 30))))
    except ValueError:
        return jsonify({'error': 'bad paging'}), 400
    sport = (request.args.get('sport') or '').strip().lower()
    group = (request.args.get('group') or '').strip()
    q = (request.args.get('q') or '').strip()[:100]
    who = ','.join('?' * len(riders))
    src = (
        f"SELECT {KIND_SQL} kind, CAST(id AS TEXT) id, riderId, name, sportType sport, startDateLocal, distance, movingTime, totalElevationGain elev, averageSpeed spd, "
        f"averageHeartrate hr, calories, city, summaryPolyline FROM Activity WHERE riderId IN ({who})")
    where, args = [], list(riders)
    theirs = [i for i in riders if i != rider['id']]
    if theirs:
        # A friend's that starts more than a day ahead (sanity.future_start, from a friend on a version that still sends them) would top the
        # list until then: left out. It still opens on its own. The phone's own stay, flagged for the rider to fix.
        from services import sanity
        held, held_args = sanity.not_future_sql(get_db(), f"riderId IN ({','.join('?' * len(theirs))})", theirs)
        where.append(held); args += held_args
    if sport:
        where.append('lower(sport)=?'); args.append(sport)
    if group:
        from services import sports as sp
        names = [r[0] for r in query_db(f'SELECT DISTINCT sportType FROM Activity WHERE riderId IN ({who})', list(riders)) if sp.stat_group(r[0]) == group]
        if not names:
            return jsonify({'total': 0, 'offset': offset, 'items': []})
        where.append(f"COALESCE(sport, '') IN ({','.join('?' * len(names))})"); args += [n or '' for n in names]
    if q:
        where.append('(name LIKE ? OR city LIKE ?)'); args += [f'%{q}%', f'%{q}%']
    w = (' WHERE ' + ' AND '.join(where)) if where else ''
    total = query_db(f'SELECT COUNT(*) n FROM ({src}){w}', args, one=True)['n']
    rows = query_db(f'SELECT * FROM ({src}){w} ORDER BY startDateLocal DESC LIMIT ? OFFSET ?', args + [limit, offset])
    def preview(r):
        # ~28-point route outline for the list thumbnail: the summary polyline when there is one (small, and already in the page's query), else
        # the stream (a whole ride's JSON, so only read when it has to be)
        import json as _json
        rid_ = r['id']
        try:
            pts = []
            if r['summaryPolyline']:
                import polyline as pl
                pts = pl.decode(r['summaryPolyline'])
            if not pts:
                row = query_db(f'SELECT {_streams.sql()} FROM Activity WHERE id=?', [rid_], one=True)
                pts = ((_json.loads(row['streams']) if row and row['streams'] else {}).get('latlng') or {}).get('data') or []
            return [[round(p[0], 5), round(p[1], 5)] for p in _downsample(pts, 28)]
        except Exception:
            return []

    from services import sports as sp
    items = [{**({'kind': r['kind']} if old else {}), 'id': r['id'], 'preview': preview(r), 'name': r['name'], 'sport': r['sport'],
              'label': sp.label(r['sport']), 'group': sp.stat_group(r['sport']), 'date': str(r['startDateLocal'])[:19],
              'distance_m': round(r['distance'] or 0), 'moving_s': int(r['movingTime'] or 0), 'elev_m': round(r['elev'] or 0),
              'avg_speed_mps': round(r['spd'] or 0, 2), 'avg_hr': round(r['hr']) if r['hr'] else None,
              'calories': round(r['calories']) if r['calories'] else None, 'city': r['city'],
              'rider': riders.get(r['riderId']), 'own': r['riderId'] == rider['id']} for r in rows]
    return jsonify({'total': total, 'offset': offset, 'items': items})


def _downsample(seq, n):
    if not seq:
        return []
    step = max(1, -(-len(seq) // n))
    out = seq[::step]
    if seq[-1] is not out[-1]:
        out.append(seq[-1])
    return out


@bp.route('/sensors', methods=['POST'])
def post_sensors():
    """A phone's motion-sensor recording (JSON: client_id, fields, rows, mount, device, sensors_only): kept as a sidecar and attached to the ride that overlaps it in time.
    Idempotent per client_id. See services/sensors.py."""
    from services import sensors
    rider = _rider()
    if not rider:
        return jsonify({'error': 'no rider'}), 409
    payload = request.get_json(silent=True)
    db = get_db()
    res, err = sensors.store(db, rider['id'], payload)
    if err:
        return jsonify({'error': err}), 400
    db.commit()
    return jsonify(res)


@bp.route('/live', methods=['POST', 'GET'])
def live():
    """POST: the phone's live position/speed/sensors while it records ({state: riding|idle, recording, lat, lng, speed_mps, distance_m, elapsed_s,
    alt_m, accuracy_m, sport, battery_pct, sensors: {rough, tilt, press}}). Published to Home Assistant by services/live.py, and kept for the
    recording's live tracking link if it has one. GET: the last reading (for debugging)."""
    from services import live as live_svc
    if request.method == 'GET':
        return jsonify(live_svc.snapshot() or {})
    c = live_svc.update(request.get_json(silent=True))
    return jsonify({'ok': True, 'state': c['state']})


def _share_json(row, url):
    return {'id': row['id'], 'url': url, 'recording': row['recording'], 'expires_at': row['expiresAt'], 'ended': bool(row['endedAt']),
            'send_every_s': 5}


@bp.route('/live/share', methods=['POST', 'DELETE'])
def live_share():
    """POST {recording, sport, track: [[lat, lng, epoch s], ...]}: a live tracking link for the recording in progress, or the one it already
    has: {id, url, expires_at, created}. `track` is what was recorded before sharing began, so the page has the track so far. 409 with
    {error, settings_url} when there's no outside address anyone could open it on. DELETE {recording} (or ?recording=): stop sharing it, the
    link ending at once. The rider is the default rider, as for the rest of /api/v1."""
    from flask import g
    from services import live_share as share_svc
    rider = _rider()
    if not rider:
        return jsonify({'error': 'no rider'}), 409
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    recording = body.get('recording', request.args.get('recording'))
    db = get_db()
    if request.method == 'DELETE':
        return jsonify({'stopped': share_svc.stop(db, rider['id'], recording)})
    base, why = share_svc.link_base()
    if not base:
        return jsonify({'error': why, 'settings_url': share_svc.SETTINGS_PATH}), 409
    row, token, created = share_svc.start(db, rider['id'], recording, sport=body.get('sport'), device_id=getattr(g, 'device_id', None),
                                          track=body.get('track'))
    if token is None:               # one already running whose token this server can't open: end it and start again
        share_svc.stop(db, rider['id'], share_id=row['id'])
        row, token, created = share_svc.start(db, rider['id'], recording, sport=body.get('sport'), device_id=getattr(g, 'device_id', None),
                                              track=body.get('track'))
    return jsonify(dict(_share_json(row, share_svc.link(base, token)), created=created)), 201 if created else 200


@bp.route('/activities/<rid>')
@bp.route('/rides/<kind>/<rid>')
def activity_detail(rid, kind=None):
    """One activity of any sport: all the stats, a route for the map and small elevation/speed/heart-rate series. A friend's opens too, with own
    false, their name and when it was synced (services/friend_rides), for the app to show and leave unchanged. On the older path the kind in the
    URL is what the app had in hand, and the answer carries the activity's own kind (services/sports), so a stale one still finds it."""
    import json as _json
    from services.friend_rides import FRIEND_RIDERS_SQL, friend_of
    rider = _rider()
    if not rider:
        return jsonify({'error': 'no rider'}), 409
    if kind is not None and kind not in OLD_KINDS:
        return jsonify({'error': 'bad kind'}), 400
    row = query_db(f'SELECT *, {_streams.sql()} FROM Activity WHERE id=? AND (riderId=? OR riderId IN ({FRIEND_RIDERS_SQL}))', [rid, rider['id']], one=True)
    if not row:
        return jsonify({'error': 'not found'}), 404
    r = dict(row)
    own_kind = sport_kind(r['sportType'])
    friend = friend_of(get_db(), r['id']) if r['riderId'] != rider['id'] else None
    try:
        streams = _json.loads(r.get('streams') or '{}')
    except Exception:
        streams = {}
    coords = (streams.get('latlng') or {}).get('data') or []
    if not coords and r.get('summaryPolyline'):
        try:
            import polyline as pl
            coords = pl.decode(r['summaryPolyline'])
        except Exception:
            coords = []
    dist = (streams.get('distance') or {}).get('data') or []

    def series(key):
        vals = (streams.get(key) or {}).get('data') or []
        if len(vals) < 5:
            return None
        idx = list(range(len(vals)))
        keep = _downsample(idx, 150)
        return [{'d': round(dist[i]) if i < len(dist) else i, 'v': round(vals[i], 2)} for i in keep]

    def num(k, nd=None):
        v = r.get(k)
        return None if v is None else (round(v, nd) if nd is not None else v)

    dups = []
    if own_kind == 'ride' and not friend:
        from services import duplicates
        for d in duplicates.parked_for(get_db(), str(r['id'])):
            try:
                o = _json.loads(d['rowJson'])
            except ValueError:
                continue
            dups.append({'id': d['id'], 'source': d['source'], 'reason': d['reason'], 'date': str(o.get('startDateLocal'))[:19], 'distance_m': round(o.get('distance') or 0),
                         'moving_s': o.get('movingTime'), 'avg_hr': o.get('averageHeartrate'), 'avg_watts': o.get('averageWatts')})

    return jsonify({
        'duplicates': dups,
        'own': not friend, 'rider': friend['name'] if friend else rider['name'],
        'synced': str(r.get('updatedAt') or r.get('createdAt'))[:19] if friend else None,
        **({'kind': own_kind} if kind else {}), 'id': str(r['id']), 'name': r.get('name'), 'sport': r.get('sportType'),
        'date': str(r.get('startDateLocal'))[:19], 'city': r.get('city'), 'source': r.get('source'), 'commute': r.get('commute') == 1,
        'distance_m': num('distance', 0), 'moving_s': r.get('movingTime'), 'elapsed_s': r.get('elapsedTime'), 'elev_m': num('totalElevationGain', 0),
        'avg_speed_mps': num('averageSpeed', 2), 'max_speed_mps': num('maxSpeed', 2),
        'avg_hr': num('averageHeartrate', 0), 'max_hr': num('maxHeartrate', 0),
        'avg_watts': num('averageWatts', 0), 'max_watts': num('maxWatts', 0), 'kj': num('kilojoules', 0), 'cadence': num('averageCadence', 0),
        'calories': num('calories', 0), 'steps': r.get('steps'), 'suffer': num('sufferScore', 0),
        'weather': {'summary': r.get('weatherSummary'), 'temp_c': num('weatherTempC', 1), 'wind_kph': num('weatherWindKph', 0), 'rain_mm': num('weatherRainMm', 1)},
        'description': r.get('description'), 'notes': r.get('notes'), 'kudos': r.get('aiKudos'),
        'track': [[round(c[0], 6), round(c[1], 6)] for c in _downsample(coords, 700)],
        'zwift_world': _zwift_world(r.get('sportType'), coords),
        'series': {'elevation': series('altitude'), 'speed': series('velocity_smooth'), 'heartrate': series('heartrate'), 'watts': series('watts')},
        'sensors': __import__('services.sensors', fromlist=['for_ride']).for_ride(get_db(), str(r['id'])),
        'label': __import__('services.sports', fromlist=['label']).label(r.get('sportType')),
        'photos': _photo_list(r['id']),
    })


def _zwift_world(sport, coords):
    """The Zwift world a virtual ride's track is in, as the ride page draws it (routes/activities._zwift_world) but with its map at /api/v1/zwift,
    which takes the device token; None for a real ride."""
    from routes.activities import _zwift_world as world
    w = world(sport, coords)
    return w and dict(w, url=f"/api/v1/zwift/{w['slug']}.png")


@bp.route('/zwift/<slug>.png')
def zwift_map(slug):
    """A Zwift world's map for the app, as the web's /heatmap/zwift/<slug>.png serves it (which wants a login, not a token)."""
    from flask import Response
    from services import zwift
    png = zwift.map_image(slug)
    if png is None:
        known = slug in zwift.BY_SLUG
        return jsonify({'error': 'Zwift map unavailable' if known else 'not found'}), 502 if known else 404
    return Response(png, mimetype='image/png', headers={'Cache-Control': 'public, max-age=604800'})


def _photo_list(activity_id):
    """An activity's photos for the app: id, caption and where to fetch each (GET /api/v1/photos/<name>, with the device token)."""
    from services import photos
    return [{'id': p['id'], 'caption': p['caption'], 'url': f"/api/v1/photos/{p['filename']}", 'thumb_url': f"/api/v1/photos/{photos.thumb_name(p['filename'])}"}
            for p in photos.for_activity(get_db(), activity_id)]


def _own_activity(rid):
    """The rider's activity row (id, sportType), or None: another rider's, or a friend's synced one, isn't the phone's to change."""
    rider = _rider()
    if not rider:
        return None
    return get_db().execute('SELECT id, sportType FROM Activity WHERE id=? AND riderId=?', [rid, rider['id']]).fetchone()


@bp.route('/activities/<rid>/photos', methods=['POST'])
@bp.route('/rides/<kind>/<rid>/photos', methods=['POST'])
def add_photo(rid, kind=None):
    """One photo for an activity (multipart: file, optional caption). The app sends a JPEG it has already shrunk; photos.save makes the full-size and
    thumbnail copies and drops the EXIF (location and all). Returns the activity's photos."""
    from services import photos
    if kind not in (None, *OLD_KINDS) or not _own_activity(rid):
        return jsonify({'error': 'not found'}), 404
    f = request.files.get('file')
    if not f:
        return jsonify({'error': 'file (a picture) is required'}), 400
    data = f.read(photos.MAX_BYTES + 1)
    db = get_db()
    if db.execute('SELECT COUNT(*) FROM ActivityPhoto WHERE activityId=?', [str(rid)]).fetchone()[0] >= MAX_PHOTOS:
        return jsonify({'error': f'an activity can have at most {MAX_PHOTOS} photos'}), 413
    try:
        photos.save(db, rid, data, current_app.config['DATABASE'], caption=(request.form.get('caption') or '')[:photos.MAX_CAPTION] or None,
                    source_key=_photo_key(rid, request.form.get('client_id')), position=photos.next_position(db, rid))
    except ValueError as e:
        return jsonify({'error': str(e)}), 413 if len(data) > photos.MAX_BYTES else 422
    db.commit()
    return jsonify({'photos': _photo_list(rid)}), 201


def _photo_key(rid, client_id):
    """photos.save's sourceKey for a photo the app sends with its own id, so a retried upload isn't added twice."""
    c = (client_id or '').strip()
    return f'app:{rid}:{c[:64]}' if c else None


@bp.route('/activities/<rid>/photos/<int:pid>', methods=['DELETE'])
@bp.route('/rides/<kind>/<rid>/photos/<int:pid>', methods=['DELETE'])
def remove_photo(rid, pid, kind=None):
    from services import photos
    if kind not in (None, *OLD_KINDS) or not _own_activity(rid):
        return jsonify({'error': 'not found'}), 404
    db = get_db()
    gone = photos.delete(db, pid, rid, current_app.config['DATABASE'])
    db.commit()
    return jsonify({'deleted': gone, 'photos': _photo_list(rid)}), (200 if gone else 404)


@bp.route('/activities/<rid>/photos/order', methods=['POST'])
@bp.route('/rides/<kind>/<rid>/photos/order', methods=['POST'])
def order_photos(rid, kind=None):
    """The activity's photos in a new order: JSON {ids: [...]}, every photo exactly once, or 400. The first is the cover."""
    from services import photos
    if kind not in (None, *OLD_KINDS) or not _own_activity(rid):
        return jsonify({'error': 'not found'}), 404
    db = get_db()
    try:
        photos.reorder(db, rid, (request.get_json(silent=True) or {}).get('ids'))
    except ValueError as e:
        return jsonify({'error': str(e), 'photos': _photo_list(rid)}), 400
    db.commit()
    return jsonify({'photos': _photo_list(rid)})


@bp.route('/activities/<rid>/photos/<int:pid>', methods=['PATCH'])
@bp.route('/rides/<kind>/<rid>/photos/<int:pid>', methods=['PATCH'])
def caption_photo(rid, pid, kind=None):
    """A photo's caption: JSON {caption}, an empty one clears it."""
    from services import photos
    if kind not in (None, *OLD_KINDS) or not _own_activity(rid):
        return jsonify({'error': 'not found'}), 404
    body = request.get_json(silent=True) or {}
    if 'caption' not in body or not isinstance(body['caption'], (str, type(None))):
        return jsonify({'error': 'caption (text, or empty to clear it) is required'}), 400
    db = get_db()
    if not photos.set_caption(db, pid, rid, body['caption']):
        return jsonify({'error': 'not found'}), 404
    db.commit()
    return jsonify({'photos': _photo_list(rid)})


@bp.route('/photos/<name>')
def photo_file(name):
    """A photo or its thumbnail, as the web's /activities/photo/<name> serves it, for the app (which has a token, not a login)."""
    from flask import send_from_directory
    from services import photos
    if not photos.valid_name(name):
        return jsonify({'error': 'not found'}), 404
    return send_from_directory(photos.photo_dir(current_app.config['DATABASE']), name, max_age=86400)


@bp.route('/sync/nutrition')
def sync_nutrition():
    """Everything the phone's local database needs to mirror this rider's nutrition: food + water logs for the last ?days=120,
    per-day burn for the last fortnight, goals, today's steps and weight. The phone merges it (its own unsent edits win)."""
    from routes import nutrition as nu
    from services import goal_model, workouts
    from services.mqtt import _best_steps_for
    rider = _rider()
    if not rider:
        return jsonify({'error': 'no rider'}), 409
    rid = rider['id']
    try:
        days = min(730, max(1, int(request.args.get('days', 120))))
    except ValueError:
        return jsonify({'error': 'bad days'}), 400
    today = tz.today()
    since = (today - timedelta(days=days)).isoformat()
    rows = [dict(r) for r in query_db(
        'SELECT id, logDate, foodName, calories, protein, carbs, fat, fibre, sugar, alcoholUnits, servingG, quantity, barcode, mealType, source, brand, imageUrl, '
        'nutriScoreGrade, createdAt FROM FoodLog WHERE riderId=? AND logDate>=? ORDER BY createdAt ASC, id ASC', [rid, since])]
    created = {r['id']: r['createdAt'] for r in rows}
    entries = nu._annotate_food_rows([dict(r) for r in rows])
    for e in entries:
        e['createdAt'] = created.get(e['id'])
    water = [dict(r) for r in query_db('SELECT id, logDate, ml FROM HydrationLog WHERE riderId=? AND logDate>=? ORDER BY id', [rid, since])]
    meta = {}
    for i in range(0, 15):
        d = (today - timedelta(days=i)).isoformat()
        est = goal_model.day_burn(rid, d)
        if est:
            meta[d] = {'burned': est[0], 'burn_source': est[1]}
    g = query_db('SELECT steps FROM GarminDaily WHERE date=?', [today.isoformat()], one=True)
    goal = (query_db('SELECT stepGoal FROM Settings WHERE id=1', one=True) or {'stepGoal': None})['stepGoal'] or 8000
    return jsonify({
        'server_time': tz.now().isoformat(timespec='seconds'), 'since': since, 'today': today.isoformat(),
        'entries': entries, 'water': water, 'days': meta, 'goals': nu._get_goals(),
        'steps': {'today': _best_steps_for(rid, today.isoformat(), g['steps'] if g else None), 'goal': goal},
        'weight_kg': _weight_kg(rid), 'workouts': workouts.recent(rid, 30),
        'weights': [{'id': r['id'], 'date': r['logDate'], 'kg': r['weightKg'], 'source': r['source']}
                    for r in query_db('SELECT id, logDate, weightKg, source FROM WeightLog WHERE riderId=? ORDER BY logDate', [rid])],
        'weight_settings': nu._weight_settings(),
        'profile': dict(query_db('SELECT sex, birthYear, birthDate, heightCm, lossLbPerWeek, stepGoal, goalAuto, rideKcalWeek, rideGoalWeek FROM Settings WHERE id=1', one=True) or {}),
        'steps_days': [{'date': d['date'], 'best': d['best'], 'manual': d['manual']} for d in nu.steps_list().get_json()['days']],
        'saved_meals': nu.list_saved_meals().get_json(),
    })


@bp.route('/workouts', methods=['POST'])
def post_workout():
    """The older path for a sport other than a ride with a track (multipart: file=GPX, sport, name, client_id, steps, calories, source):
    POST /activities with the kind decided, and the reply the released apps read. Kept until they all send to /activities."""
    rider = _rider()
    if not rider:
        return jsonify({'error': 'no rider'}), 409
    if request.files.get('file') is None:
        return jsonify({'error': 'file (GPX) is required'}), 400
    res, err = _upload(rider, kind='workout')
    if err:
        return err
    from services import workouts
    w = res.get('workout') or workouts._get(res['id'])
    return jsonify({'status': res['status'], 'workout': _public(w)}), (201 if res['created'] else 200)


@bp.route('/workouts', methods=['GET'])
def list_workouts():
    rider = _rider()
    from services import workouts
    try:
        days = max(0, min(int(request.args.get('days', 30)), 400))
    except ValueError:
        return jsonify({'error': 'bad days'}), 400
    return jsonify({'workouts': [_labelled(w) for w in workouts.recent(rider['id'], days)] if rider else []})


@bp.route('/workouts/<wid>', methods=['DELETE'])
def delete_workout(wid):
    rider = _rider()
    db = get_db()
    from services import workouts as _wk
    n = _wk.delete(db, wid, rider['id'] if rider else -1)
    db.commit()
    if n:
        try:
            from services.mqtt import push_update_nutrition
            push_update_nutrition()
        except Exception:
            log.warning('Home Assistant nutrition update after a phone upload failed', exc_info=True)
    return jsonify({'deleted': bool(n)}), (200 if n else 404)


@bp.route('/activities', methods=['POST'])
def post_activity():
    """Every activity from the phone, the Watch or Apple Health (services/uploads.py), idempotent per client_id. With a track, multipart:
    file=GPX, sport (the file's own when none), name?, client_id, source (ios or android), bike_id? (a ride's), calories?, steps?. With none,
    JSON: {sport, date 'YYYY-MM-DD', time 'HH:MM' (the server's local time) or start (ISO 8601 with its offset, as the iPhone sends it),
    duration_s, distance_m (not for Strength, HIIT or Yoga), elev_m?, calories?, avg_hr?, name?, notes?, client_id?, source? (manual, ios or
    android), bike_id?}; its sports are services/manual_activity.SPORTS. A bike_id that isn't one of the rider's gets the default bike.
    Replies {status 'created'|'exists', kind, id, duplicate}."""
    rider = _rider()
    if not rider:
        return jsonify({'error': 'no rider'}), 409
    res, err = _upload(rider)
    if err:
        return err
    out = {k: res[k] for k in ('status', 'created', 'kind', 'id', 'duplicate')}
    if res.get('sport_guess'):
        out['sport_guess'] = res['sport_guess']
    return jsonify(out), (201 if res['created'] else 200)


@bp.route('/activities/known', methods=['POST'])
def known_activities():
    """Which of the phone's client ids the server has (JSON {client_ids: [...]}, at most services/uploads.MAX_KNOWN): live, set aside behind
    another recording, or deleted. Apple Health's sync asks before reading a workout's route, and leaves those out. Replies {known: [...]}."""
    from services import uploads
    rider = _rider()
    if not rider:
        return jsonify({'error': 'no rider'}), 409
    ids = (request.get_json(silent=True) or {}).get('client_ids')
    if not isinstance(ids, list):
        return jsonify({'error': 'client_ids must be a list'}), 400
    if len(ids) > uploads.MAX_KNOWN:
        return jsonify({'error': f'at most {uploads.MAX_KNOWN} client_ids at once'}), 400
    return jsonify({'known': uploads.known(get_db(), rider['id'], ids)})


def _refresh_after_change(kind):
    """Re-publish the Home Assistant sensors after an activity was added or removed (never fatal)."""
    try:
        if kind == 'workout':
            from services.mqtt import push_update_nutrition
            push_update_nutrition()
        else:
            from services.mqtt import push_update
            push_update()
    except Exception as e:
        log.warning('sensor refresh failed (non-fatal): %s', e)


@bp.route('/health/days', methods=['POST'])
def health_days():
    """Apple Health's daily figures from the iPhone: JSON {days: [{date: 'YYYY-MM-DD', metric, value}]}, up to health.MAX_ITEMS at once. The metrics
    are health.METRICS plus weight_kg. Sending a day again replaces it. Returns {saved, skipped, errors}."""
    from services import health
    rider = _rider()
    if not rider:
        return jsonify({'error': 'no rider'}), 409
    db = get_db()
    try:
        res = health.save_days(db, rider['id'], (request.get_json(silent=True) or {}).get('days'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    db.commit()
    if res['saved']:
        _refresh_after_change('workout')                 # steps, weight and the day's burn are on the nutrition sensors
    return jsonify(res)


@bp.route('/health', methods=['GET', 'DELETE'])
def health_summary():
    """GET: for each Apple Health metric, the last day stored and how many days there are. DELETE: forget all of it."""
    from services import health
    rider = _rider()
    if not rider:
        return jsonify({'error': 'no rider'}), 409
    if request.method == 'DELETE':
        db = get_db()
        n = health.delete_all(db, rider['id'])
        db.commit()
        _refresh_after_change('workout')
        return jsonify({'deleted': n})
    return jsonify({'metrics': health.summary(rider['id'])})


@bp.route('/devices/watch', methods=['POST'])
def watch_token():
    """A token for this phone's Apple Watch, so it can upload a ride when the phone isn't with it. Only a phone's own token can ask (not a Watch's,
    and not a web login); an earlier Watch token of this phone's stops working. Returns {token, name}, shown to nobody: the phone passes it on."""
    from flask import g
    from services import device_auth
    parent = getattr(g, 'device_id', None)
    if parent is None:
        return jsonify({'error': 'only a paired phone can do this'}), 403
    name = f"{(getattr(g, 'device_name', None) or 'Phone')[:44]} · Apple Watch"
    made = device_auth.create_child(parent, name)
    if not made:
        return jsonify({'error': 'only a paired phone can do this'}), 403
    return jsonify({'token': made[0], 'name': name}), 201


@bp.route('/friends/tokens', methods=['POST'])
def friend_token():
    """A feed token for one friend, as on the Friends page: JSON {name, rides, segments, foods (true when left out), since, until
    ('YYYY-MM-DD' or empty), riders (the ids of the riders here it shares; just the default rider when left out), server_url (the
    address the phone paired with, which a friend can reach)}. Returns the token once, with its share code and the headwind://friend
    link for the app to show as a QR code."""
    from routes.friends import new_token, share_url
    d = request.get_json(silent=True) or {}
    name = (d.get('name') or '').strip()
    if not name:
        return jsonify({'error': "Enter your friend's name"}), 400
    url = (d.get('server_url') or '').strip().rstrip('/')
    if not url.startswith(('https://', 'http://')):
        url = share_url()
    scope = {'shareActivities': d.get('rides', True), 'shareSegments': d.get('segments', True), 'shareFoods': d.get('foods', True),
             'sinceDate': d.get('since'), 'untilDate': d.get('until'), 'riders': d.get('riders')}
    return jsonify(new_token(name, scope, url)), 201


@bp.route('/friends/probe', methods=['POST'])
def friend_probe():
    """What a friend's share code (or its headwind://friend link) connects to: JSON {code} -> {url, riders: [{name, isDefault}]}."""
    from routes.friends import probe_riders
    from services import feed_tokens
    shared = feed_tokens.parse_share_code((request.get_json(silent=True) or {}).get('code'))
    if not shared:
        return jsonify({'error': "That isn't a friend code from Headwind."}), 400
    riders, error = probe_riders(*shared)
    if error:
        return jsonify({'error': error}), 502
    return jsonify({'url': shared[0], 'riders': [{'name': r.get('name'), 'isDefault': bool(r.get('isDefault'))} for r in riders]})


@bp.route('/friends', methods=['POST'])
def friend_add():
    """Add a friend from their share code, as Add & Sync on the Friends page: JSON {code, rider (the name picked from probe, empty for
    their default), name (how they're shown here)}. The first sync runs in the background."""
    from routes.friends import add_friend
    from services import feed_tokens
    d = request.get_json(silent=True) or {}
    shared = feed_tokens.parse_share_code(d.get('code'))
    if not shared:
        return jsonify({'error': "That isn't a friend code from Headwind."}), 400
    rider = (d.get('rider') or '').strip()
    name = (d.get('name') or '').strip()[:60] or rider
    if not name:
        return jsonify({'error': 'Enter a name to show them as'}), 400
    rider = None if rider in ('', 'Default rider') else rider
    return jsonify({'id': add_friend(name, shared[0], shared[1], rider), 'name': name}), 201


@bp.route('/friends')
def friend_list():
    """The friends synced to here, for the Activities list's Whose picker: [{rider_id (for GET /api/v1/activities?rider=), name, last_synced}].
    A friend added but not synced yet has no rider, so isn't listed."""
    rows = query_db('SELECT riderId, name, lastSynced FROM Friend WHERE riderId IS NOT NULL ORDER BY name COLLATE NOCASE')
    return jsonify({'friends': [{'rider_id': r['riderId'], 'name': r['name'], 'last_synced': r['lastSynced']} for r in rows]})


@bp.route('/activities/<rid>/sport', methods=['POST'])
@bp.route('/rides/<kind>/<rid>/sport', methods=['POST'])
def change_sport(rid, kind=None):
    """Change what an activity is, e.g. a walk that was recorded as a ride: JSON {sport: Ride|VirtualRide|Walk|Run|Hike}. The response carries the
    new kind (and the id, which no longer changes; older apps read it from here)."""
    from services import convert
    rider = _rider()
    db = get_db()
    row = db.execute('SELECT riderId FROM Activity WHERE id=?', [rid]).fetchone() if kind in (None, *OLD_KINDS) else None
    if not rider or not row or row['riderId'] != rider['id']:
        return jsonify({'error': 'not found'}), 404
    try:
        res = convert.change_sport(db, None, rid, (request.get_json(silent=True) or {}).get('sport'))
        db.commit()
    except ValueError as e:
        db.rollback()
        return jsonify({'error': str(e)}), 400
    if res['changed']:
        _refresh_after_change('ride'); _refresh_after_change('workout')
    return jsonify(res)


@bp.route('/activities/<rid>/bike', methods=['POST'])
@bp.route('/rides/<kind>/<rid>/bike', methods=['POST'])
def set_bike(rid, kind=None):
    """Put a ride on another bike, or on none: JSON {bike_id: id or null}. Moving between a pedal bike and an e-bike picks its PRs again
    (services/gear.set_ride_bike)."""
    from services import gear
    from services.sports import is_ride
    rider = _rider()
    db = get_db()
    row = db.execute('SELECT riderId, sportType FROM Activity WHERE id=?', [rid]).fetchone() if kind in (None, *OLD_KINDS) else None
    if not rider or not row or row['riderId'] != rider['id']:
        return jsonify({'error': 'not found'}), 404
    if not is_ride(row['sportType']):
        return jsonify({'error': 'only rides have a bike'}), 400
    raw = (request.get_json(silent=True) or {}).get('bike_id')
    bike_id = None if raw is None else _own_bike(rider['id'], raw)
    if raw is not None and bike_id is None:
        return jsonify({'error': 'that bike is not available'}), 400
    gear.set_ride_bike(db, rid, bike_id)
    if bike_id:
        gear.evaluate_alerts(db, rider_id=rider['id'])     # as the web's routes/gear.ride_bike: the new bike's parts may now be due
    db.commit()
    _refresh_after_change('ride')
    return jsonify({'id': rid, 'bike_id': bike_id})


@bp.route('/activities/<rid>/commute', methods=['POST'])
@bp.route('/rides/<kind>/<rid>/commute', methods=['POST'])
def set_commute(rid, kind=None):
    """Tick or untick 'Commute' on a ride or a workout: JSON {commute: true|false}. Unticked is stored as 0, as on the web (routes/activities.set_commute)."""
    rider = _rider()
    db = get_db()
    row = db.execute('SELECT riderId FROM Activity WHERE id=?', [rid]).fetchone() if kind in (None, *OLD_KINDS) else None
    if not rider or not row or row['riderId'] != rider['id']:
        return jsonify({'error': 'not found'}), 404
    commute = (request.get_json(silent=True) or {}).get('commute')
    if not isinstance(commute, bool):
        return jsonify({'error': 'commute must be true or false'}), 400
    db.execute('UPDATE Activity SET commute=? WHERE id=?', [int(commute), rid])
    from services import gear
    gear.regear(db, rid)                    # as on the web: gear given automatically follows the tick
    db.commit()
    return jsonify({'id': str(rid), 'commute': commute})


@bp.route('/activities/<rid>/duplicate/<dup_id>/<action>', methods=['POST'])
@bp.route('/rides/ride/<rid>/duplicate/<dup_id>/<action>', methods=['POST'], defaults={'old': True})
def resolve_duplicate(rid, dup_id, action, old=False):
    """The same ride recorded twice: action = swap (use the other recording) | keep (both are real rides) | discard (delete the other one).
    Replies with the id of the one kept; the older path calls it ride_id."""
    from services import duplicates
    rider = _rider()
    db = get_db()
    d = db.execute("SELECT primaryId, riderId FROM ActivityDuplicate WHERE id=? AND status='parked'", [dup_id]).fetchone()
    if not rider or not d or str(d['primaryId']) != str(rid) or d['riderId'] != rider['id']:
        return jsonify({'error': 'not found'}), 404
    new_main = rid
    if action == 'swap':
        new_main = duplicates.swap(db, dup_id) or rid
    elif action == 'keep':
        duplicates.keep_both(db, dup_id)
    elif action == 'discard':
        duplicates.discard(db, dup_id)
    else:
        return jsonify({'error': 'action must be swap, keep or discard'}), 400
    db.commit()
    _refresh_after_change('ride')
    return jsonify({'ok': True, ('ride_id' if old else 'id'): new_main})


@bp.route('/activities/<rid>', methods=['DELETE'])
@bp.route('/rides/<kind>/<rid>', methods=['DELETE'])
def delete_activity(rid, kind=None):
    """Delete an activity from the phone. A deleted ride is remembered so a Garmin re-sync does not bring it back."""
    from services import duplicates
    rider = _rider()
    db = get_db()
    if kind is not None and kind not in OLD_KINDS:
        return jsonify({'error': 'kind must be ride or workout'}), 400
    kind = kind_of(db, rid) or kind or 'ride'            # the activity's own kind, not the one the app had in hand
    if kind == 'workout':
        from services import workouts as _wk
        n = _wk.delete(db, rid, rider['id'] if rider else -1)
    else:
        row = db.execute('SELECT riderId FROM Activity WHERE id=?', [rid]).fetchone()
        n = 1 if (row and rider and row['riderId'] == rider['id'] and duplicates.delete_activity(db, rid)) else 0
        if n:
            db.execute('DELETE FROM ActivityMemory WHERE activityId=?', [rid])
    db.commit()
    if n:
        _refresh_after_change(kind)
    return jsonify({'deleted': bool(n)}), (200 if n else 404)

