from calendar import month_name, monthrange
from datetime import date, datetime, timedelta, timezone

from urllib.parse import urlencode

from flask import Blueprint, redirect, render_template, request, session

from database import get_db, query_db
from services import sports
from services.dates import day_month
from services.sport_filter import SportFilter, chart_groups, speed_sql

bp = Blueprint('dashboard', __name__)


def _weekly_data(rider_id, sf=None):
    """The last 12 weeks of the sports the filter leaves in: totals, and the same per stat group ('by') for the stacked bars. Without a filter, rides
    only (the phone app's weekly bars). The week's own distance is None when the sports don't share one: a swim's doesn't add to a ride's."""
    today  = date.today()
    monday = today - timedelta(days=today.weekday())
    first  = monday - timedelta(weeks=11)
    clause, cparams = sf.sql() if sf else (sports.RIDE_SQL, [])
    rows = query_db(
        f"SELECT date(startDateLocal) AS d, sportType, distance, movingTime, {sports.climb_sql()} AS totalElevationGain, calories FROM Activity "
        f"WHERE riderId=? AND date(startDateLocal) >= ? AND date(startDateLocal) < ? AND {clause}",
        [rider_id, first.isoformat(), (monday + timedelta(days=7)).isoformat()] + cparams,
    )
    keys = ('dist_m', 'secs', 'elev_m', 'cals')
    weeks = []
    for i in range(11, -1, -1):
        ws = monday - timedelta(weeks=i)
        weeks.append({'label': day_month(ws), 'from': ws.isoformat(), 'to': (ws + timedelta(days=6)).isoformat(),   # metres: the page shows them in the rider's units
                      'current': i == 0, 'by': {}, **dict.fromkeys(keys, 0)})
    for r in rows:
        w = weeks[(date.fromisoformat(r['d']) - first).days // 7]
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
    """A walk or run without a name of its own gets "Morning walk", as on the Workouts page."""
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
    return [dict(v, group=k, label=sports.stat_label(k), icon=sports.STAT_ICONS.get(k, ''), href=link(sf.only(k)))
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
    and the Workouts page's (sport)."""
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


def _riders(args):
    """(every rider, the rider shown, their id): ?rider= or the owner."""
    all_riders = query_db('SELECT * FROM Rider ORDER BY isDefault DESC, name')
    owner      = next((r for r in all_riders if r['isDefault']), all_riders[0] if all_riders else None)
    try:
        rid = int(args.get('rider') or owner['id'])
    except (TypeError, ValueError):
        rid = owner['id'] if owner else None
    active_rider = query_db('SELECT * FROM Rider WHERE id=?', [rid], one=True) or owner
    return all_riders, active_rider, rid


def _rider_args(active_rider):
    return [] if not active_rider or active_rider['isDefault'] else [('rider', active_rider['id'])]


def _activities(where, params):
    """The history list's activities under these filters, newest first."""
    rows = query_db(f'''
        SELECT a.id, a.name, a.sportType, a.startDateLocal, a.distance, a.movingTime,
               a.totalElevationGain, {speed_sql('a.')} AS averageSpeed, a.averageWatts, a.averageHeartrate,
               a.city, a.country, a.aiKudos,
               r.name AS riderName, r.avatarPath AS riderAvatar, r.isDefault AS riderIsDefault,
               r.id AS riderId
        FROM Activity a
        LEFT JOIN Rider r ON r.id = a.riderId
        WHERE {' AND '.join(where)}
        ORDER BY a.startDateLocal DESC
    ''', params)
    return [dict(a, name=_name(a), isRide=sports.is_ride(a['sportType'])) for a in rows]


@bp.route('/dashboard/history')
def history():
    """The days of one stretch of the history tree (a month, from= to=), drawn when it is opened: the dashboard draws only the open month, so it
    doesn't carry every activity ever recorded. Same rider, sport and gear filter as the dashboard it came from."""
    _, active_rider, rid = _riders(request.args)
    sf = SportFilter(get_db(), rid, request.args)
    gf = _gear_filter(get_db(), rid, request.args.get('gear', '').strip())
    date_from, date_to = request.args.get('from', '').strip(), request.args.get('to', '').strip()
    clause, cparams = sf.sql('a.sportType')
    where, params = ['a.riderId=?', clause], [rid] + cparams
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
    """Open the newest year and month of a history tree that has nothing in the current one (a gear filter's list, say), so it starts on
    something; the other months are still fetched when they're opened."""
    if grouped and not any(y['is_current'] for y in grouped):
        grouped[0]['is_current'] = True
    for y in grouped:
        if y['is_current'] and y['months'] and not any(m['is_current'] for m in y['months']):
            y['months'][0]['is_current'] = True
    return grouped


def _gear_types(db, rid, value, sf, link):
    """For a "no gear" list: [(sport, n, link to that sport alone, active)] of the activities it has, the "All" link first (sport None)."""
    from services import gear
    counts = gear.no_gear_counts(db, rid, value)
    if not counts:
        return []
    names = [s for s, _ in sf.sports]
    only = sf.kept[0] if len(sf.kept) == 1 else None
    return [(None, sum(n for _, n in counts), link([]), not sf.skip)] + \
           [(s, n, link([x for x in names if x != s]), s == only) for s, n in counts]


def _activity_list(args, list_path):
    """The activity list's filters and rows, shared by the dashboard and the Activities page: (the template's values, where, params, the rider
    links' args). Name, dates, distance, gear and the sports left in (services/sport_filter) all come from the URL, so a filtered list can be
    linked."""
    all_riders, active_rider, rid = _riders(args)
    q         = args.get('q', '').strip()
    date_from = args.get('from', '').strip()
    date_to   = args.get('to', '').strip()
    min_dist, max_dist, min_m, max_m = dist_filters(args)
    sf        = SportFilter(get_db(), rid, args)     # the sports left in, for the totals, the chart and the list alike
    gf        = _gear_filter(get_db(), rid, args.get('gear', '').strip())    # kept in the history tree: a gear filter's list is paged by month
    is_filtered = any([q, date_from, date_to, min_dist, max_dist])

    where  = ['a.riderId=?']
    params = [rid]
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

    rider_args = _rider_args(active_rider)
    def link(skip):
        args_ = rider_args + sf.args(skip) + gf['args']
        return list_path + ('?' + urlencode(args_) if args_ else '')

    activities = _activities(where, params)
    ctx = dict(
        rid=rid,
        list_path=list_path,
        typed=args.get('typed', ''),
        back_url=list_path + '?' + urlencode([(k, v) for k, v in args.items(multi=True) if k != 'typed']),
        sport_choices=[('Ride', 'Ride'), ('MountainBikeRide', 'Mountain bike ride'), ('GravelRide', 'Gravel ride'), ('VirtualRide', 'Indoor ride'), ('Walk', 'Walk'), ('Run', 'Run'), ('VirtualRun', 'Indoor run'), ('Hike', 'Hike')],
        activities=activities,
        grouped=(_open_newest if gf['value'] else (lambda g: g))(_group_activities(activities)) if not is_filtered else [],
        search_results=activities if is_filtered else [],
        is_filtered=is_filtered,
        q=q, date_from=date_from, date_to=date_to,
        min_dist=min_dist, max_dist=max_dist,
        gear=gf['value'], gear_choices=gf['choices'], row_picker=gf['row_picker'], gear_pickers=gf['pickers'],
        gear_types=_gear_types(get_db(), rid, gf['value'], sf, link),
        sf=sf,
        sport_links=[(label, icon, link(skip), active) for label, icon, skip, active in sf.shortcuts()],
        all_riders=all_riders,
        active_rider=active_rider,
        rider_query=urlencode(rider_args + sf.args() + gf['args']),     # kept on every link the page makes: the rider, the sports left out, the gear
        clear_url=list_path + ('?' + urlencode(rider_args + sf.args()) if rider_args or sf.args() else ''),     # Clear drops the search and the gear
    )
    return ctx, where, params, link


def remember_list(label):
    """Note this list page and its filters as the way back from an activity (the crumb on templates/ride.html), so going back from an activity
    (after any Prev and Next) lands on the list as it was left. One-off notices (typed=, error=) aren't kept."""
    args = [(k, v) for k, v in request.args.items(multi=True) if k not in ('typed', 'error')]
    session['list_back'] = {'label': label, 'url': request.path + ('?' + urlencode(args) if args else '')}


@bp.route('/activities')
def activities_page():
    """Every activity, rides and the rest together, newest first: the dashboard's history and search on a page of their own."""
    ctx, where, params, _ = _activity_list(request.args, '/activities')
    remember_list('Activities')
    totals = query_db(f"SELECT COUNT(*) AS n, SUM(a.movingTime) AS secs FROM Activity a WHERE {' AND '.join(where)}", params, one=True)
    return render_template('activities.html', totals=totals, **ctx)


@bp.route('/dashboard')
def dashboard():
    athlete = query_db('SELECT * FROM Athlete LIMIT 1', one=True)

    ctx, where, params, link = _activity_list(request.args, '/dashboard')
    active_rider, sf, rid = ctx['active_rider'], ctx['sf'], ctx['rid']

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
        fclause, fparams = sf.sql()
        year_speed = [
            {'id': r['id'], 'd': r['d'], 'mps': float(r['mps']), 'name': _name(r)}
            for r in query_db(
                f"SELECT id, date(startDateLocal) as d, {speed_sql()} AS mps, name, sportType, startDateLocal FROM Activity "
                f"WHERE riderId=? AND strftime('%Y', startDateLocal) = strftime('%Y', 'now') AND {speed_sql()} > 0 AND {fclause} "
                f"ORDER BY startDateLocal",
                [rid] + fparams,
            )
        ]

    recovery = None
    if active_rider and active_rider['isDefault']:
        recovery = query_db(
            'SELECT date, restingHR, hrv, hrvBalanced, sleepHours, sleepScore, bodyBattery, steps, stressScore '
            'FROM GarminDaily ORDER BY date DESC LIMIT 1',
            one=True,
        )

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

    try:
        from services import gear
        from services import kit
        gear_due = (kit.due_items(get_db(), rid, include_soon=False) + gear.due_items(get_db(), rid, include_soon=False))[:4]   # shoes and the like, then bike parts
    except Exception:
        gear_due = []
    from services import merged_gear
    gear_merged = merged_gear.count(get_db(), rid)      # merged activities whose two recordings are on different gear

    try:
        from services import sanity
        flagged = sanity.flagged(get_db(), rid)
    except Exception:
        flagged = []

    from services import goals
    rider_goals = goals.goals(get_db(), rid)
    rider_challenges = goals.challenges(get_db(), rid)
    live_challenges = [c for c in rider_challenges if c['status'] == 'on' and c['joined']]
    invitations = sum(1 for c in rider_challenges if c['invitation'] and c['status'] != 'finished')

    return render_template(
        'dashboard.html',
        gear_due=gear_due,
        flagged=flagged,
        gear_merged=gear_merged,
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
