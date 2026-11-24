import json
import logging
from datetime import datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from database import get_db, query_db
from services import jobs, logs
from services import streams as _streams
from services.friend_rides import FRIEND_RIDERS_SQL

bp = Blueprint('ai_page', __name__)
log = logging.getLogger(__name__)

# This instance's own activities, every sport: a friend's are coached on their instance (services/friend_rides)
OWN_SQL = f'(riderId IS NULL OR riderId NOT IN ({FRIEND_RIDERS_SQL}))'
# Something to coach: a distance or a moving time (an empty Apple Health workout has neither)
SOMETHING_SQL = '(COALESCE(distance, 0) > 0 OR COALESCE(movingTime, 0) > 0)'


def _memory_viz_data():
    """The Working Memory card: a dot for each analysed activity (size its moving time, colour its sport), each month's count, time and
    distance, the rides' average speed by month, and the latest few."""
    rows = query_db('''
        SELECT m.activityDate, m.activityName, m.distanceMi, m.avgSpeedMph, m.elevationFt, m.movingTime, m.aiSummary, a.sportType
        FROM ActivityMemory m LEFT JOIN Activity a ON a.id = m.activityId
        WHERE m.activityDate IS NOT NULL
        ORDER BY m.activityDate ASC
    ''')
    if not rows:
        return [], [], [], []

    from services import sports, units
    from services.sport_filter import GROUP_COLOURS, OTHER_COLOURS
    mi, mph = units.MI, units.MPH_PER_MPS                  # ActivityMemory is stored in miles and mph; shown in the rider's units

    # Date range for timeline positioning
    dates = [datetime.strptime(r['activityDate'], '%Y-%m-%d').date() for r in rows]
    min_d, max_d = dates[0], dates[-1]
    span = max((max_d - min_d).days, 1)
    max_time = max((r['movingTime'] or 0) for r in rows) or 1

    groups = sorted({sports.stat_group(r['sportType']) for r in rows}, key=sports.stat_order)
    others = iter(OTHER_COLOURS * 4)
    colours = {g: GROUP_COLOURS.get(g) or next(others, '--c-grey') for g in groups}
    legend = [{'label': sports.stat_label(g), 'icon': sports.STAT_ICONS.get(g) or sports.icon(g), 'color': colours[g]} for g in groups]

    dots = []
    for i, r in enumerate(rows):
        g = sports.stat_group(r['sportType'])
        style = sports.rate_style(group=g) if r['sportType'] not in sports.NO_DISTANCE else None
        dist = units.dist(float(r['distanceMi'] or 0) * mi)
        dots.append({
            'x': round(((dates[i] - min_d).days / span) * 100, 2),
            'size': round(3 + ((r['movingTime'] or 0) / max_time) * 7, 1),       # 3–10 px radius
            'color': colours[g],
            'name': r['activityName'] or '',
            'sport': sports.label(r['sportType']),
            'date': r['activityDate'],
            'figs': ' · '.join(x for x in (
                f'{dist:.1f} {units.spec()["dist"]}' if style and dist else None,
                units.fmt_rate(float(r['avgSpeedMph'] or 0) / mph, style) if style and r['avgSpeedMph'] else None,
                f"{int(r['movingTime'] or 0) // 60} min") if x),
        })

    # Monthly breakdown: every sport's count, time and distance; the average speed is the rides' only, as a run's or a swim's would skew it
    from services.sports import RIDE_SQL
    monthly_raw = query_db(f'''
        SELECT strftime('%Y-%m', m.activityDate) as mo,
               COUNT(*) as cnt,
               SUM(m.distanceMi) as total_dist,
               SUM(m.movingTime) as total_time,
               AVG(CASE WHEN {RIDE_SQL.replace('sportType', 'a.sportType')} AND m.avgSpeedMph > 0 THEN m.avgSpeedMph END) as avg_spd
        FROM ActivityMemory m LEFT JOIN Activity a ON a.id = m.activityId
        WHERE m.activityDate IS NOT NULL
        GROUP BY mo ORDER BY mo
    ''')
    max_time_mo = max((r['total_time'] or 0) for r in monthly_raw) or 1
    monthly = [{
        'label':      datetime.strptime(r['mo'], '%Y-%m').strftime('%b %Y'),
        'cnt':        r['cnt'],
        'total_dist': round(units.dist((r['total_dist'] or 0) * mi), 1),
        'hours':      round((r['total_time'] or 0) / 3600, 1),
        'avg_spd':    round(units.speed(r['avg_spd'] / mph), 1) if r['avg_spd'] else None,
        'bar_pct':    round(((r['total_time'] or 0) / max_time_mo) * 100),
    } for r in monthly_raw]

    # Ride speed sparkline: the months with rides in them
    spd = [m for m in monthly if m['avg_spd'] is not None]
    if len(spd) > 1:
        lo, hi = min(m['avg_spd'] for m in spd), max(m['avg_spd'] for m in spd)
        rng = max(hi - lo, 0.5)
        for i, m in enumerate(spd):
            m['spark_x'] = round(i / (len(spd) - 1) * 200, 1)
            m['spark_y'] = round((1 - (m['avg_spd'] - lo) / rng) * 40 + 5, 1)
    sparkline = spd if len(spd) > 1 else []

    # Recent memories
    recent = [dict(r, sport_icon=sports.icon(r['sportType']), has_distance=r['sportType'] not in sports.NO_DISTANCE and (r['distanceMi'] or 0) > 0)
              for r in query_db('''
        SELECT m.activityDate, m.activityName, m.distanceMi, m.movingTime, m.aiSummary, a.sportType
        FROM ActivityMemory m LEFT JOIN Activity a ON a.id = m.activityId
        WHERE m.activityDate IS NOT NULL
        ORDER BY m.activityDate DESC LIMIT 6
    ''')]

    return dots, monthly, recent, {'legend': legend, 'sparkline': sparkline}


@bp.route('/ai')
def index():
    settings = query_db('SELECT * FROM Settings WHERE id=1', one=True)
    total    = query_db(f'SELECT COUNT(*) FROM Activity WHERE {OWN_SQL} AND {SOMETHING_SQL}', one=True)[0]
    analysed = query_db(f"SELECT COUNT(*) FROM Activity WHERE {OWN_SQL} AND {SOMETHING_SQL} AND aiKudos IS NOT NULL AND aiKudos != ''", one=True)[0]
    memories = query_db('SELECT COUNT(*) FROM ActivityMemory', one=True)[0]
    dots, monthly, recent, viz = _memory_viz_data()
    from services import ai, auto_analyse, favourites, whose
    rid = whose.rider_id()
    auto_sports = auto_analyse.chosen(settings['aiAutoSports'] if settings and 'aiAutoSports' in settings.keys() else None)
    sport_choices = favourites.choices(get_db(), rid) if rid else []
    for key in auto_sports or []:                      # a sport picked once, of which nothing is left, still shows ticked
        if key not in {c['key'] for c in sport_choices} and favourites.describe(key):
            sport_choices.append(favourites.describe(key))
    ai_ready = ai.get_chat() is not None
    return render_template('ai.html', settings=settings,
                           total=total, analysed=analysed, memories=memories,
                           dots=dots, monthly=monthly, recent=recent, viz=viz,
                           sport_choices=sport_choices, auto_sports=auto_sports,
                           ai_ready=ai_ready, missing_key=None if ai_ready else ai.missing_key_message('to analyse new activities automatically'),
                           recent_days=auto_analyse.RECENT_DAYS)


@bp.route('/ai/goals', methods=['POST'])
def save_goals():
    goals = request.form.get('goals', '').strip()
    db = get_db()
    db.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
    db.execute('UPDATE Settings SET coachingGoals=? WHERE id=1', [goals])
    db.commit()
    flash('Goals saved.', 'success')
    return redirect(url_for('ai_page.index'))


@bp.route('/ai/auto-analyse', methods=['POST'])
def save_auto_analyse():
    """Analyse each new activity of the sports picked as it's imported (services/auto_analyse.py). Only turns on once an AI provider is set up,
    and with at least one sport picked."""
    from services import auto_analyse
    on = request.form.get('auto') == '1'
    every = request.form.get('every') == '1'
    keys = request.form.getlist('sport')
    if on:
        from services import ai
        if ai.get_chat() is None:
            flash(ai.missing_key_message('to analyse new activities automatically'), 'error')
            return redirect(url_for('ai_page.index'))
        if not every and not keys:
            flash('Pick at least one sport to analyse, or Every sport.', 'error')
            return redirect(url_for('ai_page.index'))
    db = get_db()
    db.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
    db.execute('UPDATE Settings SET aiAutoAnalyse=? WHERE id=1', [1 if on else 0])
    if every or keys:                                  # turning it off with nothing ticked keeps the sports picked before
        auto_analyse.save_choice(db, every, keys)
    db.commit()
    flash('New activities will be analysed as they arrive.' if on else 'New activities will no longer be analysed automatically.', 'success')
    return redirect(url_for('ai_page.index'))


def _activity_where(date_from, date_to, force):
    """The activities the batch analyses: this instance's own, with something recorded (the sport is _of_sport's)."""
    where, params = [OWN_SQL, SOMETHING_SQL], []
    if not force:
        where.append("(aiKudos IS NULL OR aiKudos = '')")
    if date_from:
        where.append('date(startDateLocal) >= ?')
        params.append(date_from)
    if date_to:
        where.append('date(startDateLocal) <= ?')
        params.append(date_to)
    return 'WHERE ' + ' AND '.join(where), params


def _of_sport(rows, key):
    """The rows (with sportType) of the sport picked for the batch: a favourites key ('group:ride', 'sport:Run'), or '' for every sport. Matched
    as the analysis of new activities matches its sports (services/auto_analyse.covers)."""
    from services import auto_analyse
    if not key:
        return list(rows)
    keys = auto_analyse.chosen(json.dumps([key])) or ['none']          # a key that isn't one matches nothing, not everything
    return [r for r in rows if auto_analyse.covers(keys, r['sportType'])]


def _bulk_args(src):
    return {'from': src.get('from', ''), 'to': src.get('to', ''), 'force': src.get('force', '') == '1', 'sport': src.get('sport', '')}


@bp.route('/ai/bulk-analyse', methods=['POST'])
def bulk_analyse():
    """Queue the batch for the worker and return {job}: the page follows it (static/js/app.js followJob) rather than holding one of the
    server's threads for as long as the AI takes over hundreds of activities. One already queued or running is the one returned."""
    db = get_db()
    job = jobs.enqueue(db, 'ai_bulk_analyse', _bulk_args(request.form)) or jobs.active(db, 'ai_bulk_analyse')['id']
    return jsonify({'job': job})


@jobs.handler('ai_bulk_analyse')
def _bulk_analyse_job(job):
    """The page's events, as the stream used to send them: start {total}, progress {i, total, name, date}, error {name, detail}, then done
    {analysed, skipped}."""
    from services.ai import AIDeclined, AIUnavailable, analyse_ride
    db = get_db()
    a = job['args']
    with jobs.Events(job) as ev:
        clause, params = _activity_where(a.get('from', ''), a.get('to', ''), a.get('force'))
        # Only the ids up front: each activity is read whole when its turn comes, not all of them (streams and all) before the first
        rides = _of_sport(query_db(f'SELECT id, name, startDateLocal, sportType FROM Activity {clause} ORDER BY startDateLocal ASC', params),
                          a.get('sport', ''))
        total = len(rides)
        ev.emit({'type': 'start', 'total': total})
        analysed = skipped = 0
        for i, listed in enumerate(rides):
            name = listed['name'] or listed['id']
            date = str(listed['startDateLocal'] or '')[:10]
            ev.emit({'type': 'progress', 'i': i + 1, 'total': total, 'name': name, 'date': date})
            activity = db.execute(f'SELECT *, {_streams.sql()} FROM Activity WHERE id=?', [listed['id']]).fetchone()
            if not activity:                           # deleted while the others were analysed
                skipped += 1
                continue
            try:
                analyse_ride(db, activity)
                analysed += 1
            except (AIUnavailable, AIDeclined) as e:   # our own words: no key set, or the model said no
                skipped += 1
                ev.emit({'type': 'error', 'name': name, 'detail': str(e)})
            except Exception:
                log.exception('Bulk analysis of activity %s failed', activity['id'])
                skipped += 1
                ev.emit({'type': 'error', 'name': name, 'detail': logs.failed('Analysis failed')})
        ev.emit({'type': 'done', 'analysed': analysed, 'skipped': skipped})


@bp.route('/ai/count')
def count():
    a = _bulk_args(request.args)
    clause, params = _activity_where(a['from'], a['to'], a['force'])
    return jsonify({'count': len(_of_sport(query_db(f'SELECT sportType FROM Activity {clause}', params), a['sport']))})
