import json
import traceback
from datetime import datetime

from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, stream_with_context, url_for
from database import get_db, query_db

bp = Blueprint('ai_page', __name__)


def _memory_viz_data():
    rows = query_db('''
        SELECT rideDate, rideName, distanceMi, avgSpeedMph, elevationFt, aiSummary
        FROM RideMemory WHERE rideDate IS NOT NULL
        ORDER BY rideDate ASC
    ''')
    if not rows:
        return [], [], []

    # Date range for timeline positioning
    dates = [datetime.strptime(r['rideDate'], '%Y-%m-%d').date() for r in rows]
    min_d, max_d = dates[0], dates[-1]
    span = max((max_d - min_d).days, 1)

    from services import units
    mi, mph = units.MI, units.MPH_PER_MPS                  # RideMemory is stored in miles and mph; shown in the rider's units
    speeds = [units.speed(float(r['avgSpeedMph'] or 0) / mph) for r in rows]
    dists  = [units.dist(float(r['distanceMi'] or 0) * mi) for r in rows]
    min_spd, max_spd = min(speeds), max(speeds)
    spd_range = max(max_spd - min_spd, 0.1)
    max_dist = max(dists) if dists else 1

    dots = []
    for i, r in enumerate(rows):
        x_pct   = ((dates[i] - min_d).days / span) * 100
        spd_pct = ((speeds[i] - min_spd) / spd_range) * 100
        size    = 3 + (dists[i] / max_dist) * 7       # 3–10 px radius
        dots.append({
            'x': round(x_pct, 2),
            'size': round(size, 1),
            'spd_pct': round(spd_pct),
            'name': r['rideName'] or '',
            'date': r['rideDate'],
            'dist': round(dists[i], 1),
            'speed': round(speeds[i], 1),
        })

    # Monthly breakdown
    monthly_raw = query_db('''
        SELECT strftime('%Y-%m', rideDate) as mo,
               COUNT(*) as cnt,
               SUM(distanceMi) as total_dist,
               AVG(avgSpeedMph) as avg_spd,
               AVG(elevationFt) as avg_elev
        FROM RideMemory WHERE rideDate IS NOT NULL
        GROUP BY mo ORDER BY mo
    ''')
    max_dist_mo = max((r['total_dist'] or 0) for r in monthly_raw) if monthly_raw else 1
    monthly = [{
        'label':      datetime.strptime(r['mo'], '%Y-%m').strftime('%b %Y'),
        'cnt':        r['cnt'],
        'total_dist': round(units.dist((r['total_dist'] or 0) * mi), 1),
        'avg_spd':    round(units.speed((r['avg_spd'] or 0) / mph), 1),
        'avg_elev':   round(r['avg_elev'] or 0),
        'bar_pct':    round(((r['total_dist'] or 0) / max_dist_mo) * 100),
    } for r in monthly_raw]

    # Speed sparkline — embed x,y coords directly into monthly dicts
    spd_vals = [m['avg_spd'] for m in monthly]
    if len(spd_vals) > 1:
        lo, hi = min(spd_vals), max(spd_vals)
        rng = max(hi - lo, 0.5)
        n = len(spd_vals)
        for i, m in enumerate(monthly):
            m['spark_x'] = round(i / (n - 1) * 200, 1)
            m['spark_y'] = round((1 - (m['avg_spd'] - lo) / rng) * 40 + 5, 1)
        sparkline = True
    else:
        sparkline = False
        for m in monthly:
            m['spark_x'] = 0
            m['spark_y'] = 25

    # Recent memories
    recent = query_db('''
        SELECT rideDate, rideName, distanceMi, avgSpeedMph, elevationFt, aiSummary
        FROM RideMemory WHERE rideDate IS NOT NULL
        ORDER BY rideDate DESC LIMIT 6
    ''')

    return dots, monthly, recent


@bp.route('/ai')
def index():
    settings = query_db('SELECT * FROM Settings WHERE id=1', one=True)
    total    = query_db('SELECT COUNT(*) FROM Ride', one=True)[0]
    analysed = query_db("SELECT COUNT(*) FROM Ride WHERE aiKudos IS NOT NULL AND aiKudos != ''", one=True)[0]
    memories = query_db('SELECT COUNT(*) FROM RideMemory', one=True)[0]
    dots, monthly, recent = _memory_viz_data()
    from services import ai, auto_analyse
    ai_ready = ai.get_chat() is not None
    return render_template('ai.html', settings=settings,
                           total=total, analysed=analysed, memories=memories,
                           dots=dots, monthly=monthly, recent=recent,
                           ai_ready=ai_ready, missing_key=None if ai_ready else ai.missing_key_message('to analyse new rides automatically'),
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
    """Analyse each new ride as it's imported (services/auto_analyse.py). Only turns on once an AI provider is set up."""
    on = request.form.get('auto') == '1'
    if on:
        from services import ai
        if ai.get_chat() is None:
            flash(ai.missing_key_message('to analyse new rides automatically'), 'error')
            return redirect(url_for('ai_page.index'))
    db = get_db()
    db.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
    db.execute('UPDATE Settings SET aiAutoAnalyse=? WHERE id=1', [1 if on else 0])
    db.commit()
    flash('New rides will be analysed as they arrive.' if on else 'New rides will no longer be analysed automatically.', 'success')
    return redirect(url_for('ai_page.index'))


def _activity_where(date_from, date_to, force):
    where, params = [], []
    if not force:
        where.append("(aiKudos IS NULL OR aiKudos = '')")
    if date_from:
        where.append('date(startDateLocal) >= ?')
        params.append(date_from)
    if date_to:
        where.append('date(startDateLocal) <= ?')
        params.append(date_to)
    clause = ('WHERE ' + ' AND '.join(where)) if where else ''
    return clause, params


@bp.route('/ai/bulk-analyse')
def bulk_analyse():
    date_from = request.args.get('from', '')
    date_to   = request.args.get('to', '')
    force     = request.args.get('force', '') == '1'

    def generate():
        db = get_db()
        clause, params = _activity_where(date_from, date_to, force)
        rides = query_db(
            f'SELECT * FROM Ride {clause} ORDER BY startDateLocal ASC',
            params
        )

        total = len(rides)
        yield f'data: {json.dumps({"type":"start","total":total})}\n\n'

        if total == 0:
            yield f'data: {json.dumps({"type":"done","analysed":0,"skipped":0})}\n\n'
            return

        analysed = 0
        skipped  = 0

        for i, activity in enumerate(rides):
            name = activity['name'] or activity['id']
            date = str(activity['startDateLocal'] or '')[:10]
            yield f'data: {json.dumps({"type":"progress","i":i+1,"total":total,"name":name,"date":date})}\n\n'
            try:
                from services.ai import analyse_ride
                analyse_ride(db, activity)
                analysed += 1
            except Exception:
                skipped += 1
                yield f'data: {json.dumps({"type":"error","name":name,"detail":traceback.format_exc(limit=1)})}\n\n'

        yield f'data: {json.dumps({"type":"done","analysed":analysed,"skipped":skipped})}\n\n'

    return Response(stream_with_context(generate()), mimetype='text/event-stream',
                    headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-cache'})


@bp.route('/ai/count')
def count():
    date_from = request.args.get('from', '')
    date_to   = request.args.get('to', '')
    force     = request.args.get('force', '') == '1'
    clause, params = _activity_where(date_from, date_to, force)
    row = query_db(f'SELECT COUNT(*) FROM Ride {clause}', params, one=True)
    return jsonify({'count': row[0]})
