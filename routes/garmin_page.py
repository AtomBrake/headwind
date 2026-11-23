import json

from flask import Blueprint, render_template, request
from database import query_db
from services import health, tz, whose

bp = Blueprint('garmin_page', __name__)


@bp.route('/recovery')
def index():
    days = int(request.args.get('days', 60))

    # Garmin's figure for a day where it has one, else what the rider's iPhone sent from Apple Health (services/health)
    rows = health.recovery_days(whose.rider_id(), tz.today().isoformat(), days - 1)[::-1]

    # Dates that have a ride (for chart markers)
    ride_dates = {
        r['d'] for r in query_db('''
            SELECT DISTINCT date(startDateLocal) as d FROM Ride
            WHERE date(startDateLocal) >= date('now', ? || ' days')
        ''', [f'-{days}'])
    }

    # Build day-by-day series covering the full range (gaps → null)
    from datetime import timedelta
    start = tz.today() - timedelta(days=days - 1)
    date_index = {r['date']: r for r in rows}

    labels, rhr, battery, sleep, steps, stress, has_ride = [], [], [], [], [], [], []
    stages = {'deep': [], 'rem': [], 'light': [], 'awake': []}     # a night without stages is drawn as one bar of its hours
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        r = date_index.get(d)
        labels.append(d)
        rhr.append(r['restingHR'] if r else None)
        battery.append(r['bodyBattery'] if r else None)
        sleep.append(r['sleepHours'] if r else None)
        staged = bool(r and r['sleepDeep'] is not None)
        for k, col in (('deep', 'sleepDeep'), ('rem', 'sleepRem'), ('light', 'sleepLight')):
            stages[k].append(r[col] if staged else None)
        stages['awake'].append(round(r['sleepAwakeMin'] / 60, 2) if staged and r['sleepAwakeMin'] else None)
        steps.append(r['steps'] if r else None)
        stress.append(r['stressScore'] if r else None)
        has_ride.append(1 if d in ride_dates else None)

    table_rows = [r for r in reversed(rows) if any([
        r['restingHR'], r['hrv'], r['bodyBattery'], r['sleepHours'], r['sleepScore'], r['steps'], r['stressScore']
    ])]

    # Most recent day with intraday streams for the "today" charts
    intraday = query_db(
        "SELECT date, hrStream, bodyBatteryStream FROM GarminDaily "
        "WHERE hrStream IS NOT NULL OR bodyBatteryStream IS NOT NULL "
        "ORDER BY date DESC LIMIT 1",
        one=True
    )
    today_hr_stream = json.loads(intraday['hrStream']) if intraday and intraday['hrStream'] else []
    today_bb_stream = json.loads(intraday['bodyBatteryStream']) if intraday and intraday['bodyBatteryStream'] else []
    today_intraday_date = intraday['date'] if intraday else None

    return render_template('garmin.html',
        labels=labels,
        rhr=rhr,
        battery=battery,
        sleep=sleep,
        stages=stages if any(v is not None for v in stages['deep']) else None,
        steps=steps,
        stress=stress,
        has_ride=has_ride,
        table_rows=table_rows,
        days=days,
        today_hr_stream=today_hr_stream,
        today_bb_stream=today_bb_stream,
        today_intraday_date=today_intraday_date,
        source_label=' and '.join(name for key, name in (('garmin', 'Garmin'), (health.SOURCE, 'Apple Health'))
                                  if any(key in (r['source'] or '') for r in rows)),
    )
