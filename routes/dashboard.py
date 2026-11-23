from calendar import month_name, monthrange
from datetime import date, datetime, timezone

from urllib.parse import urlencode

from flask import Blueprint, redirect, render_template, request, session

from database import get_db, query_db
from services import features, friend_rides, periods, sports, tz, whose
from services.dates import day_month
from services.sport_filter import SportFilter, chart_groups, speed_sql

bp = Blueprint('dashboard', __name__)


def _weekly_data(rider_id, sf=None, p=None):
    """The last 12 weeks of the sports the filter leaves in: totals, and the same per stat group ('by') for the stacked bars. Without a filter, rides
    only (the phone app's weekly bars). The week's own distance is None when the sports don't share one: a swim's doesn't add to a ride's.
    rider_id is one rider's id or a list of them (the Friends list). A week is the viewer's (services/periods, p: their Prefs): 7 days back to
    back ending today, so the last bar is the past 7 days, or calendar weeks from their chosen day."""
    ids = rider_id if isinstance(rider_id, (list, tuple)) else [rider_id]
    blocks = periods.blocks('week', 12, p or periods.resolve(ids[0]), tz.today())
    first, last = blocks[0].first, blocks[-1].last
    clause, cparams = sf.sql() if sf else (sports.RIDE_SQL, [])
    rows = query_db(
        f"SELECT date(startDateLocal) AS d, sportType, distance, movingTime, {sports.climb_sql()} AS totalElevationGain, calories FROM Activity "
        f"WHERE riderId IN ({','.join('?' * len(ids))}) AND date(startDateLocal) BETWEEN ? AND ? AND {clause}",
        ids + [first.isoformat(), last.isoformat()] + cparams,
    )
    keys = ('dist_m', 'secs', 'elev_m', 'cals')
    weeks = [{'label': b.dates, 'from': b.first.isoformat(), 'to': b.last.isoformat(),   # metres: the page shows them in the rider's units
              'current': i == len(blocks) - 1, 'by': {}, **dict.fromkeys(keys, 0)} for i, b in enumerate(blocks)]
    for r in rows:
        w = weeks[(date.fromisoformat(r['d']) - first).days // 7]           # every block is 7 days, back to back
        g = w['by'].setdefault(sports.stat_group(r['sportType']), dict.fromkeys(keys, 0))
        for k, v in zip(keys, (r['distance'], r['movingTime'], r['totalElevationGain'], r['calories'])):
            g[k] += v or 0
            w[k] += v or 0
    for w in weeks:
        for t in [w] + list(w['by'].values()):
            for k in keys:
                t[k] = round(t[k])
        if sf and not sf.group:
            w['dist_m'] = None
    return weeks


def _name(a):
    """A walk or run without a name of its own gets "Morning walk"."""
    if (a['name'] or '').strip() or sports.is_ride(a['sportType']):
        return a['name']
    from services.workouts import label
    return label({'name': None, 'sport': a['sportType'], 'startDateLocal': a['startDateLocal']})


def _group_totals(where, params, sf, link):
    """Each stat group's activities, distance and time under the same filters, for the "every sport" headline (no one mixed distance)."""
    out = {}
    for r in query_db(f"SELECT a.sportType, COUNT(*) AS n, SUM(a.distance) AS dist, SUM(a.movingTime) AS secs FROM Activity a "
                      f"WHERE {' AND '.join(where)} GROUP BY a.sportType", params):
        g = out.setdefault(sports.stat_group(r['sportType']), {'n': 0, 'dist': 0, 'secs': 0})
        g['n'] += r['n']; g['dist'] += r['dist'] or 0; g['secs'] += r['secs'] or 0
    return [dict(v, group=k, label=sports.stat_label(k), icon=sports.STAT_ICONS.get(k, ''), href=link(group=k))
            for k, v in sorted(out.items(), key=lambda kv: -kv[1]['secs'])]


def dist_filters(args):
    """The search form's distance range, typed in the rider's unit: (min text, max text, min metres or None, max metres or None). Old links that
    still say min_mi / max_mi are read as miles."""
    from services import units
    out = []
    for new, old in (('min_dist', 'min_mi'), ('max_dist', 'max_mi')):
        text, system = (args.get(new) or '').strip(), None
        if not text and (args.get(old) or '').strip():
            text, system = args.get(old).strip(), 'imperial'
        try:
            metres = units.to_metres(text, system) if text else None
        except ValueError:
            metres = None
        out.append((text, metres))
    return out[0][0], out[1][0], out[0][1], out[1][1]


def climb(a):
    """An activity row's climb as it adds to a total: none on the water (services/sports.has_climbing). Takes the dashboard's rows (sportType)
    and rows that carry the sport as `sport`."""
    keys = a.keys()
    sport = a['sportType'] if 'sportType' in keys else (a['sport'] if 'sport' in keys else None)
    return (a['totalElevationGain'] or 0) if sports.has_climbing(sport) else 0


def _group_activities(activities):
    today = date.today()
    tree = {}

    for a in activities:
        raw = str(a['startDateLocal'])[:19]
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            continue
        y, m, d = dt.year, dt.month, dt.day
        tree.setdefault(y, {}).setdefault(m, {}).setdefault(d, []).append(a)

    result = []
    for year in sorted(tree, reverse=True):
        yr_rides = yr_dist = yr_elev = 0
        months = []
        for mo in sorted(tree[year], reverse=True):
            mo_rides = mo_dist = mo_elev = 0
            days = []
            mo_secs = 0
            for dy in sorted(tree[year][mo], reverse=True):
                acts = tree[year][mo][dy]
                d_dist = sum(a['distance'] or 0 for a in acts)
                d_elev = sum(climb(a) for a in acts)
                d_secs = sum(a['movingTime'] or 0 for a in acts)
                dt_day = datetime(year, mo, dy)
                days.append({
                    'label':      day_month(dt_day),
                    'from':       dt_day.date().isoformat(),
                    'activities': acts,
                    'count':      len(acts),
                    'dist':       d_dist,
                    'elev':       d_elev,
                    'secs':       d_secs,
                })
                mo_rides += len(acts)
                mo_dist  += d_dist
                mo_elev  += d_elev
                mo_secs  += d_secs
            months.append({
                'name':       month_name[mo],
                'from':       date(year, mo, 1).isoformat(),
                'to':         date(year, mo, monthrange(year, mo)[1]).isoformat(),
                'num':        mo,
                'days':       days,
                'count':      mo_rides,
                'dist':       mo_dist,
                'elev':       mo_elev,
                'secs':       mo_secs,
                'is_current': year == today.year and mo == today.month,
            })
            yr_rides += mo_rides
            yr_dist  += mo_dist
            yr_elev  += mo_elev
        result.append({
            'year':       year,
            'months':     months,
            'count':      yr_rides,
            'dist':       yr_dist,
            'elev':       yr_elev,
            'secs':       sum(m['secs'] for m in months),
            'is_current': year == today.year,
        })
    return result


@bp.route('/')
def index():
    return redirect('/dashboard')


FRIENDS = whose.FRIENDS     # ?rider=friends on the dashboard and Activities: every friend's activities together, newest first, read-only


def _riders(args, friends=False):
    """(every rider, the rider shown, their id): ?rider= as whose.viewable allows it, or the request's own rider. With friends (the activity
    list's pages), ?rider=friends gives a stand-in for every friend synced here together, {'id': 'friends', 'name': 'Friends', 'isDefault': 0,
    'avatarPath': None, 'ids': [their rider ids]}, and no id: see _ids. Another rider who lives here is never one of them
    (services/friend_rides.friend_riders). With no friend synced it's the request's own rider, as for any rider that isn't there."""
    all_riders = query_db('SELECT * FROM Rider ORDER BY isDefault DESC, name')
    view = whose.viewable(args.get('rider'), friends=friends) or whose.viewable(None)
    if not features.on('friends'):                     # Friends off: no friend's riders to pick, and ?rider= one of them is your own list
        mine = set(friend_rides.friend_riders(get_db()))
        all_riders = [r for r in all_riders if r['id'] not in mine]
        if view.how in (whose.FRIEND, whose.FRIENDS):
            view = whose.viewable(None)
    if view.how == whose.FRIENDS:
        return all_riders, {'id': FRIENDS, 'name': 'Friends', 'isDefault': 0, 'avatarPath': None, 'ids': list(view.ids)}, None
    active_rider = query_db('SELECT * FROM Rider WHERE id=?', [view.id], one=True) if view.id is not None else None
    return all_riders, active_rider, view.id


def _rider_args(active_rider):
    return [] if not active_rider or active_rider['isDefault'] else [('rider', active_rider['id'])]


def _is_friends(active_rider):
    return bool(active_rider) and active_rider['id'] == FRIENDS


def _ids(active_rider, rid):
    """The rider ids whose activities the list shows: the one rider's, or every friend's for the Friends list."""
    return list(active_rider['ids']) if _is_friends(active_rider) else [rid]


def _whose_sql(ids):
    """(condition on a.riderId, params) for these riders. A friend's activity that starts more than a day ahead (sanity.future_start: a clock that
    was wrong, sent by a friend on a version that still shares them) is left out, as it would top the list until then; it keeps its own page.
    Your own stays, flagged for you to fix."""
    from services import sanity
    whose, params = f"a.riderId IN ({','.join('?' * len(ids))})", list(ids)
    friends = friend_rides.friend_riders(get_db())
    theirs = [i for i in ids if i in friends]
    if theirs:
        held, held_args = sanity.not_future_sql(get_db(), f"riderId IN ({','.join('?' * len(theirs))})", theirs, col='a.id')
        whose, params = f'{whose} AND {held}', params + held_args
    return whose, params


def _activities(where, params, order='a.startDateLocal DESC', limit=None, offset=0):
    """The history list's activities under these filters, newest first or in `order`, all of them or a page."""
    page = f' LIMIT {int(limit)} OFFSET {int(offset)}' if limit else ''
    rows = query_db(f'''
        SELECT a.id, a.name, a.sportType, a.startDateLocal, a.distance, a.movingTime,
               a.totalElevationGain, {speed_sql('a.')} AS averageSpeed, a.averageWatts, a.averageHeartrate,
               a.city, a.country, a.aiKudos,
               r.name AS riderName, r.avatarPath AS riderAvatar, r.isDefault AS riderIsDefault,
               r.id AS riderId
        FROM Activity a
        LEFT JOIN Rider r ON r.id = a.riderId
        WHERE {' AND '.join(where)}
        ORDER BY {order}{page}
    ''', params)
    return [dict(a, name=_name(a), isRide=sports.is_ride(a['sportType'])) for a in rows]


@bp.route('/dashboard/history')
def history():
    """The days of one stretch of the history tree (a month, from= to=), drawn when it is opened: the dashboard draws only the open month, so it
    doesn't carry every activity ever recorded. Same rider, sport and gear filter as the dashboard it came from."""
    _, active_rider, rid = _riders(request.args, friends=True)
    ids = _ids(active_rider, rid)
    sf = SportFilter(get_db(), ids, request.args)
    gf = _gear_filter(get_db(), rid, request.args.get('gear', '').strip())
    date_from, date_to = request.args.get('from', '').strip(), request.args.get('to', '').strip()
    clause, cparams = sf.sql('a.sportType')
    whose, wparams = _whose_sql(ids)
    where, params = [whose, clause], wparams + cparams
    if gf['sql']:
        where.append(gf['sql']); params += gf['params']
    if date_from:
        where.append('date(a.startDateLocal) >= ?'); params.append(date_from)
    if date_to:
        where.append('date(a.startDateLocal) <= ?'); params.append(date_to)
    days = [d for yr in _group_activities(_activities(where, params)) for mo in yr['months'] for d in mo['days']]
    list_path = request.args.get('list') if request.args.get('list') in LIST_PATHS else '/dashboard'
    rider_query = urlencode(_rider_args(active_rider) + sf.args() + gf['args'])
    return render_template('_history_days.html', days=days, sf=sf, rider_query=rider_query, list_path=list_path, row_picker=gf['row_picker'],
                           gear_pickers=gf['pickers'], back_url=list_path + ('?' + rider_query if rider_query else ''))


LIST_PATHS = ('/dashboard', '/activities')     # the pages that show the activity list (templates/_activity_list.html)


def _gear_filter(db, rid, value):
    """The list's gear filter, from ?gear=: none (no gear: a ride with no bike, or anything else with no shoes or other kit in a sport that has
    some), bike-none, kit-none (services/gear.no_gear_sql), bike-<id> or kit-<id>. Returns {value, sql (None for no filter), params, args (to keep it on links), choices
    for the form as [(group, [(value, label)])], row_picker (a bike or kit picker on each row, to deal with them one by one), pickers (the
    rider's bikes and kit for it, the retired ones last: an old activity may have been on one)}."""
    from services import gear, kit
    if rid is None:                                     # the Friends list: gear is one rider's own
        return dict(value='', sql=None, params=[], args=[], choices=[], row_picker=False, pickers={'bike': [], 'kit': []})
    bikes = gear.list_bikes(db, rid, include_archived=True)
    items = kit.list_kit(db, rid, include_retired=True)
    choices = [('', [('none', 'No gear (every sport)')])] if bikes or items else []
    if bikes:
        choices.append(('Bikes', [('bike-none', 'Rides with no bike')] + [(f"bike-{b['id']}", b['name'] + (' (retired)' if b['archived'] else '')) for b in bikes]))
    if items:
        choices.append(('Shoes and other gear', [('kit-none', 'Other sports with no gear')] + [(f"kit-{k['id']}", k['name'] + (' (retired)' if k['retiredOn'] else '')) for k in items]))
    out = dict(value='', sql=None, params=[], args=[], choices=choices, row_picker=False,
               pickers={'bike': bikes, 'kit': items})
    kind, _, which = (value or '').partition('-')
    if value in gear.NO_GEAR:
        sql, params = gear.no_gear_sql(db, rid, value)
        out.update(value=value, sql=sql, params=params, row_picker=True)
    elif kind in ('bike', 'kit') and which.isdigit():
        out.update(value=value, sql=f'a.{kind}Id = ?', params=[int(which)])
    if out['value']:
        out['args'] = [('gear', out['value'])]
    return out


def _open_newest(grouped):
    """Open the newest year and month of a history tree that has nothing in the current one (on the 1st, before anything's recorded, or a
    gear filter's list), so it starts on something; the other months are still fetched when they're opened."""
    if grouped and not any(y['is_current'] for y in grouped):
        grouped[0]['is_current'] = True
    for y in grouped:
        if y['is_current'] and y['months'] and not any(m['is_current'] for m in y['months']):
            y['months'][0]['is_current'] = True
    return grouped


def _gear_types(db, rid, value, sf, link):
    """For a "no gear" list: [(sport, n, link to that sport alone, active)] of the activities it has, the "All" link first (sport None)."""
    from services import gear
    if not value:
        return []
    counts = gear.no_gear_counts(db, rid, value)
    if not counts:
        return []
    names = [s for s, _ in sf.sports]
    only = sf.kept[0] if len(sf.kept) == 1 else None
    return [(None, sum(n for _, n in counts), link([]), not sf.skip)] + \
           [(s, n, link([x for x in names if x != s]), s == only) for s, n in counts]


def _activity_list(args, list_path):
    """The activity list's filters and rows, shared by the dashboard and the Activities page: (the template's values, where, params, the rider
    links' args). Name, dates, distance, gear, the sports left in (services/sport_filter), what each has, where it came from and the order
    (services/activity_filters) all come from the URL, so a filtered list can be linked. A search or one of the more filters gives one flat list,
    a page at a time; otherwise it's the history tree. ?rider=friends lists every friend's activities together, each row with its rider's
    avatar: nothing on it can be changed here, so it has no Select bar, gear filter or "change the type of all results"."""
    from services.activity_filters import PAGE, ActivityFilters
    all_riders, active_rider, rid = _riders(args, friends=True)
    ids       = _ids(active_rider, rid)
    q         = args.get('q', '').strip()
    date_from = args.get('from', '').strip()
    date_to   = args.get('to', '').strip()
    min_dist, max_dist, min_m, max_m = dist_filters(args)
    sf        = SportFilter(get_db(), ids, args)     # the sports left in, for the totals, the chart and the list alike
    gf        = _gear_filter(get_db(), rid, args.get('gear', '').strip())    # kept in the history tree: a gear filter's list is paged by month
    af        = ActivityFilters(args)
    is_filtered = any([q, date_from, date_to, min_dist, max_dist]) or af.flat

    whose, params = _whose_sql(ids)
    where  = [whose]
    if q:
        where.append('a.name LIKE ?');  params.append(f'%{q}%')
    if date_from:
        where.append('date(a.startDateLocal) >= ?'); params.append(date_from)
    if date_to:
        where.append('date(a.startDateLocal) <= ?'); params.append(date_to)
    if min_m is not None:
        where.append('a.distance >= ?'); params.append(min_m)
    if max_m is not None:
        where.append('a.distance <= ?'); params.append(max_m)
    if gf['sql']:
        where.append(gf['sql']); params += gf['params']
    clause, cparams = sf.sql('a.sportType')
    where.append(clause); params += cparams
    where += af.sql()

    rider_args = _rider_args(active_rider)
    def link(skip=None, group=None):
        args_ = rider_args + sf.args(skip, group) + gf['args'] + af.args()
        return list_path + ('?' + urlencode(args_) if args_ else '')

    total, ids = None, []
    if is_filtered:                                     # one flat list, a page at a time
        ids = [r[0] for r in query_db(f"SELECT a.id FROM Activity a WHERE {' AND '.join(where)}", params)]
        total = len(ids)
        activities = _activities(where, params, af.order, PAGE, (af.page - 1) * PAGE)
    else:
        activities = _activities(where, params)
    pages = -(-(total or 0) // PAGE)
    keep = rider_args + sf.args() + gf['args'] + af.args() + [(k, v) for k in ('q', 'from', 'to', 'min_dist', 'max_dist') for v in [args.get(k, '').strip()] if v]
    page_url = lambda n: list_path + '?' + urlencode(keep + ([('page', n)] if n > 1 else [])) + '#ride-history'
    ctx = dict(
        rid=rid,
        list_path=list_path,
        typed=args.get('typed', ''),
        back_url=list_path + '?' + urlencode([(k, v) for k, v in args.items(multi=True) if k != 'typed']),
        sport_choices=[('Ride', 'Ride'), ('MountainBikeRide', 'Mountain bike ride'), ('GravelRide', 'Gravel ride'), ('VirtualRide', 'Indoor ride'), ('Walk', 'Walk'), ('Run', 'Run'), ('VirtualRun', 'Indoor run'), ('Hike', 'Hike')],
        activities=activities,
        grouped=_open_newest(_group_activities(activities)) if not is_filtered else [],
        search_results=activities if is_filtered else [],
        result_ids=ids, result_total=total, af=af,
        narrowed=any([q, date_from, date_to, min_dist, max_dist]) or bool(af.on),     # not merely in another order: "change the type of all results" is offered
        page=af.page, pages=pages, prev_url=page_url(af.page - 1) if af.page > 1 else None, next_url=page_url(af.page + 1) if af.page < pages else None,
        is_filtered=is_filtered,
        q=q, date_from=date_from, date_to=date_to,
        min_dist=min_dist, max_dist=max_dist,
        gear=gf['value'], gear_choices=gf['choices'], row_picker=gf['row_picker'], gear_pickers=gf['pickers'],
        gear_types=_gear_types(get_db(), rid, gf['value'], sf, link),
        sf=sf,
        sport_links=[(label, icon, link(group=g), active) for label, icon, g, active in sf.shortcuts()],
        all_riders=all_riders,
        active_rider=active_rider,
        friends_list=_is_friends(active_rider),
        friend_riders=len(friend_rides.friend_riders(get_db())) if features.on('friends') else 0,     # the Friends button is offered once two have synced
        rider_query=urlencode(rider_args + sf.args() + gf['args'] + af.args()),     # kept on every link the page makes: the rider, the sports left out, the gear, the more filters
        clear_url=list_path + ('?' + urlencode(rider_args + sf.args()) if rider_args or sf.args() else ''),     # Clear drops the search and the gear
    )
    return ctx, where, params, link


def remember_list(label):
    """Note this list page and its filters as the way back from an activity (the crumb on templates/activity.html), so going back from an activity
    (after any Prev and Next) lands on the list as it was left. One-off notices (typed=, error=) aren't kept."""
    args = [(k, v) for k, v in request.args.items(multi=True) if k not in ('typed', 'error')]
    session['list_back'] = {'label': label, 'url': request.path + ('?' + urlencode(args) if args else '')}


@bp.route('/activities')
def activities_page():
    """Every activity, rides and the rest together, newest first: the dashboard's history and search on a page of their own."""
    ctx, where, params, _ = _activity_list(request.args, '/activities')
    remember_list('Activities')
    totals = query_db(f"SELECT COUNT(*) AS n, SUM(a.movingTime) AS secs, SUM(a.calories) AS kcal FROM Activity a WHERE {' AND '.join(where)}",
                      params, one=True)
    st = query_db('SELECT units FROM Settings WHERE id=1', one=True)
    return render_template('activities.html', totals=totals, today=tz.today().isoformat(), now=tz.now().strftime('%H:%M'),
                           units=(st['units'] if st and st['units'] else 'imperial'), error=request.args.get('error'),
                           can_add=bool(ctx['rid']) and not friend_rides.is_friend_rider(get_db(), ctx['rid']),
                           **ctx)


@bp.route('/activities/new', methods=['POST'])
def activities_new():
    """An activity typed in by hand (services/manual_activity.py), for the rider whose list it was added from."""
    from services import manual_activity
    f = request.form
    _, rider, rid = _riders(f)
    back = '/activities' + ('?' + urlencode(_rider_args(rider)) if _rider_args(rider) else '')
    km = f.get('unit') == 'km'
    try:
        if not rider or friend_rides.is_friend_rider(get_db(), rider['id']):
            raise ValueError("that rider's activities come from their own Headwind")
        dur = (float(f.get('hours') or 0) * 3600) + (float(f.get('minutes') or 0) * 60)
        dist = float(f.get('distance') or 0) * (1000 if km else 1609.344)
        elev = float(f['elevation']) * (1 if km else 0.3048) if f.get('elevation') else None
        manual_activity.create(get_db(), rider['id'], f.get('sport'), f"{f.get('date')}T{(f.get('time') or '12:00')[:5]}:00", dur, dist, elev,
                               f.get('calories') or None, f.get('name'), f.get('notes'))
    except (ValueError, TypeError) as e:
        return redirect(back + ('&' if '?' in back else '?') + urlencode({'error': str(e)}))
    from routes.api_v1 import _refresh_after_change
    _refresh_after_change(sports.kind(f.get('sport')))
    return redirect(back)


@bp.route('/workouts')
def workouts_page():
    """The Workouts page went into Activities: an old link or bookmark lands on the Activities list with the rides left out, keeping its filters."""
    _, rider, rid = _riders(request.args)
    sf = SportFilter(get_db(), rid, request.args)
    args = [(k, v) for k in ('q', 'from', 'to', 'min_dist', 'max_dist') for v in request.args.getlist(k) if v]
    if request.args.get('sport'):
        args.append(('sport', request.args['sport']))           # one sport, matched on part of its name (services/sport_filter)
    else:
        args += sf.args([s for s, _ in sf.sports if sports.stat_group(s) == 'ride'])
    args = _rider_args(rider) + args
    return redirect('/activities' + ('?' + urlencode(args) if args else ''))


@bp.route('/dashboard')
def dashboard():
    athlete = query_db('SELECT * FROM Athlete LIMIT 1', one=True)

    ctx, where, params, link = _activity_list(request.args, '/dashboard')
    active_rider, sf, rid = ctx['active_rider'], ctx['sf'], ctx['rid']
    ids = _ids(active_rider, rid)
    whose, wparams = _whose_sql(ids)

    # The headline numbers are for the sports left in. A distance only when they all share one (sf.group): a swim's doesn't add to a ride's.
    totals = query_db(f'''
        SELECT COUNT(*) as rides, SUM(a.distance) as dist,
               SUM({sports.climb_sql('a.totalElevationGain', 'a.sportType')}) as elev, SUM(a.movingTime) as secs,
               SUM(a.calories) as cals
        FROM Activity a
        WHERE {' AND '.join(where)}
    ''', params, one=True)
    group_totals = [] if sf.group else _group_totals(where, params, sf, link)

    # Speed (or pace) per activity this year: only when the sports left in share one, so a walk's pace never sits on a line of ride speeds.
    year_speed = []
    if sf.group:
        fclause, fparams = sf.sql('a.sportType')
        year_speed = [
            {'id': r['id'], 'd': r['d'], 'mps': float(r['mps']), 'name': _name(r)}
            for r in query_db(
                f"SELECT a.id, date(a.startDateLocal) as d, {speed_sql('a.')} AS mps, a.name, a.sportType, a.startDateLocal FROM Activity a "
                f"WHERE {whose} AND strftime('%Y', a.startDateLocal) = strftime('%Y', 'now') AND {speed_sql('a.')} > 0 AND {fclause} "
                f"ORDER BY a.startDateLocal",
                wparams + fparams,
            )
        ]

    recovery = None
    if active_rider and active_rider['isDefault'] and features.on('recovery'):
        from services import health
        recovery = health.latest_recovery(active_rider['id'])      # Garmin's, or Apple Health's for a rider without one

    # Live-ish current conditions from Home Assistant (services/homeassistant.sync_weather, refreshed
    # every ~5 min by the background heartbeat) — stale beyond a few hours means HA/the entity is
    # probably unreachable, so hide it rather than show a misleading old reading.
    weather = None
    ha_row = query_db(
        'SELECT haWeatherCondition, haWeatherTempC, haWeatherUpdatedAt FROM Settings WHERE id=1', one=True
    )
    if ha_row and ha_row['haWeatherCondition'] and ha_row['haWeatherUpdatedAt']:
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(ha_row['haWeatherUpdatedAt'])
            if age.total_seconds() < 3 * 3600:
                weather = {'condition': ha_row['haWeatherCondition'], 'temp_c': ha_row['haWeatherTempC']}
        except ValueError:
            pass

    if _is_friends(active_rider):                       # the Friends list: what follows is one rider's own, and none of it is changed here
        return render_template('dashboard.html', athlete=athlete, totals=totals, group_totals=group_totals, weekly=_weekly_data(ids, sf),
                               year_speed=year_speed, chart_groups=chart_groups(sf.groups), now=date.today(), weather=weather, **ctx)

    # One friend's own list: their activities are changed on their Headwind, not here, so none of the things to fix below is offered.
    gear_due, gear_merged, sport_merged, sport_fixes, sport_guesses, flagged, flag_groups = [], 0, 0, 0, 0, [], []
    if not friend_rides.is_friend_rider(get_db(), rid):
        if features.on('maintenance'):                 # the due list is maintenance's; the merged-gear prompt is Gear's
            try:
                from services import gear
                from services import kit
                gear_due = (kit.due_items(get_db(), rid, include_soon=False) + gear.due_items(get_db(), rid, include_soon=False))[:4]   # shoes and the like, then bike parts
            except Exception:
                gear_due = []
        if features.on('gear'):
            from services import merged_gear
            gear_merged = merged_gear.count(get_db(), rid)  # merged activities whose two recordings are on different gear
        from services import merged_sport, sport_fix, sport_guess
        sport_merged = merged_sport.count(get_db(), rid)    # ... or say different sports
        sport_fixes = sport_fix.count(get_db(), rid)        # Garmin activities saved with another sport than Garmin's type
        sport_guesses = len(sport_guess.pending(get_db(), rid))     # uploads saved as rides that moved like runs

        try:
            from services import sanity
            flagged = sanity.flagged(get_db(), rid)
            flag_groups = sanity.group_counts(flagged)     # to pick every one with the same reason
        except Exception:
            flagged, flag_groups = [], []

    from services import goals
    rider_goals = goals.goals(get_db(), rid) if features.on('goals') else []
    rider_challenges = goals.challenges(get_db(), rid) if features.on('goals') else []
    live_challenges = [c for c in rider_challenges if c['status'] == 'on' and c['joined']]
    invitations = sum(1 for c in rider_challenges if c['invitation'] and c['status'] != 'finished')

    return render_template(
        'dashboard.html',
        gear_due=gear_due,
        flagged=flagged, flag_groups=flag_groups,
        gear_merged=gear_merged, sport_merged=sport_merged, sport_fixes=sport_fixes, sport_guesses=sport_guesses,
        rider_goals=rider_goals,
        live_challenges=live_challenges,
        invitations=invitations,
        garmin_full=bool(query_db("SELECT 1 FROM Settings WHERE id=1 AND garminSyncMode='full'", one=True)),
        athlete=athlete,
        totals=totals,
        group_totals=group_totals,
        weekly=_weekly_data(rid, sf),
        year_speed=year_speed,
        chart_groups=chart_groups(sf.groups),
        now=date.today(),
        recovery=recovery,
        weather=weather,
        **ctx,
    )
