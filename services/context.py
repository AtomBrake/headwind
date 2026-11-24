from database import query_db
from routes.riders import _compute_badges
from services import units

# ActivityMemory and the best-effort brackets are stored in miles / mph / feet (as are the similarity searches below). Everything the coach reads goes
# through these, so it gets the rider's own units and never has to convert.
def _mi(v):
    return units.fmt_dist(float(v or 0) * units.MI)


def _mph(v):
    return units.fmt_speed(float(v or 0) / units.MPH_PER_MPS)


def _ft(v):
    return units.fmt_elev(float(v or 0) / units.FT_PER_M)


def _rate(v_mph, style):
    """A speed stored in mph, read as this sport reads it: speed, pace, or pace per 100 m."""
    return units.fmt_rate(float(v_mph or 0) / units.MPH_PER_MPS, style)


def _mins(secs):
    return f'{int(secs or 0) // 60} min'


def _tags(dist_mi, elev_ft, avg_power, avg_hr, ride=True):
    tags = []
    if ride:                # the distance and climbing marks are a ride's: a 10-mile run is a long one
        if dist_mi >= 30:       tags.append('long_ride')
        elif dist_mi <= 10:     tags.append('short_ride')
        if elev_ft >= 3000:     tags.append('big_climb')
        elif elev_ft >= 1500:   tags.append('hilly')
        if avg_power and avg_power >= 210: tags.append('hard_power')
    if avg_hr and avg_hr >= 160:       tags.append('high_hr')
    return ','.join(tags)


def save_ride_memory(activity, ai_summary):
    """The activity's figures and its analysis in ActivityMemory, which later analyses read as history: any sport (its own is on Activity)."""
    from database import get_db
    from services.sports import is_ride

    dist_mi  = float(activity['distance'] or 0) / 1609.344
    elev_ft  = float(activity['totalElevationGain'] or 0) * 3.28084
    spd_mph  = float(activity['averageSpeed'] or 0) * 2.23694
    power    = float(activity['averageWatts'] or 0) or None
    norm_pw  = float(activity['weightedAvgWatts'] or 0) or None
    hr       = float(activity['averageHeartrate'] or 0) or None
    cals     = float(activity['calories'] or 0) or None

    tags = _tags(dist_mi, elev_ft, power, hr, ride=is_ride(activity['sportType']))

    db = get_db()
    db.execute('''
        INSERT INTO ActivityMemory
            (activityId, activityDate, activityName, distanceMi, movingTime, elevationFt,
             avgSpeedMph, avgPower, normPower, avgHR, calories, aiSummary, tags, updatedAt)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
        ON CONFLICT(activityId) DO UPDATE SET
            aiSummary=excluded.aiSummary,
            tags=excluded.tags,
            updatedAt=datetime('now')
    ''', [
        str(activity['id']),
        str(activity['startDateLocal'])[:10],
        activity['name'],
        round(dist_mi, 2),
        activity['movingTime'],
        round(elev_ft),
        round(spd_mph, 2),
        round(power) if power else None,
        round(norm_pw) if norm_pw else None,
        round(hr, 1) if hr else None,
        round(cals) if cals else None,
        ai_summary,
        tags,
    ])
    db.commit()


def _fmt_dur(secs):
    m, s = divmod(int(abs(secs)), 60)
    h, m = divmod(m, 60)
    if h:
        return f'{h}:{m:02d}:{s:02d}'
    return f'{m}:{s:02d}'


def _fmt_date(d):
    try:
        from datetime import datetime
        dt = datetime.strptime(str(d)[:10], '%Y-%m-%d')
        from services.dates import day_month_year
        return day_month_year(dt)
    except Exception:
        return str(d)[:10]


def _build_segment_context(activity_id):
    efforts = query_db('''
        SELECT e.id, e.segmentId, e.activityId, e.startSecs, e.elapsedSecs, e.isPR, e.activityDate,
               s.id AS seg_id, s.name AS seg_name, s.distanceM
        FROM SegmentEffort e
        JOIN Segment s ON s.id = e.segmentId
        WHERE e.activityId = ?
        ORDER BY s.name, e.startSecs
    ''', [activity_id])

    if not efforts:
        return ''
    from services.segments import lap_numbers
    laps = lap_numbers(efforts)

    lines = ['Segments on this activity:']

    for eff in efforts:
        seg_id   = eff['seg_id']
        seg_name = eff['seg_name']
        this_secs = eff['elapsedSecs']
        dist_m   = eff['distanceM'] or 0

        # Full leaderboard for this segment
        board = query_db('''
            SELECT elapsedSecs, activityDate
            FROM SegmentEffort
            WHERE segmentId = ?
            ORDER BY elapsedSecs ASC
        ''', [seg_id])

        total     = len(board)
        rank      = next((i + 1 for i, r in enumerate(board) if r['elapsedSecs'] == this_secs), total)
        best_secs = board[0]['elapsedSecs'] if board else this_secs
        best_date = board[0]['activityDate'] if board else eff['activityDate']
        avg_secs  = sum(r['elapsedSecs'] for r in board) / total if total else this_secs

        gap_to_pr  = this_secs - best_secs  # 0 if this IS the PR
        is_pr      = gap_to_pr == 0

        # Last 5 efforts on this segment (chronological, excluding today)
        recent = query_db('''
            SELECT elapsedSecs, activityDate
            FROM SegmentEffort
            WHERE segmentId = ? AND activityId != ?
            ORDER BY activityDate DESC LIMIT 5
        ''', [seg_id, activity_id])

        if is_pr:
            status = f'PERSONAL BEST'
            if len(board) > 1:
                prev_best_secs = board[1]['elapsedSecs']
                status += (
                    f' (prev best: {_fmt_dur(prev_best_secs)} on {_fmt_date(board[1]["activityDate"])},'
                    f' improved by {_fmt_dur(prev_best_secs - this_secs)})'
                )
        else:
            status = f'#{rank} of {total} (gap to PR: {_fmt_dur(gap_to_pr)})'

        lap = f" (lap {laps[eff['id']]})" if eff['id'] in laps else ''
        line = f'- {seg_name}{lap}: {_fmt_dur(this_secs)} — {status}'
        line += f'\n  All-time: {total} efforts, avg {_fmt_dur(avg_secs)}, best {_fmt_dur(best_secs)} ({best_date})'

        if recent:
            recent_times = [_fmt_dur(r['elapsedSecs']) for r in recent]
            recent_secs  = [r['elapsedSecs'] for r in recent]
            if len(recent_secs) >= 3:
                first_half  = sum(recent_secs[len(recent_secs)//2:]) / max(1, len(recent_secs) - len(recent_secs)//2)
                second_half = sum(recent_secs[:len(recent_secs)//2]) / max(1, len(recent_secs)//2)
                diff = second_half - first_half
                if abs(diff) < 0.03 * first_half:
                    trend = 'stable'
                elif diff < 0:
                    trend = 'getting faster'
                else:
                    trend = 'getting slower'
            else:
                trend = 'insufficient history'
            line += f'\n  Last {len(recent)} efforts (newest first): {", ".join(recent_times)} — {trend}'

        lines.append(line)

    # Broader 6-month segment trends — all segments the rider uses regularly
    six_months_ago = query_db("SELECT date('now', '-180 days') as d", one=True)['d']
    regular_segs = query_db('''
        SELECT s.id, s.name, COUNT(*) as cnt
        FROM SegmentEffort e
        JOIN Segment s ON s.id = e.segmentId
        WHERE e.activityDate >= ?
        GROUP BY s.id
        HAVING cnt >= 3
        ORDER BY cnt DESC
    ''', [six_months_ago])

    if regular_segs:
        lines.append('')
        lines.append('Regular segment trends (last 6 months, segments with 3+ efforts):')
        for seg in regular_segs:
            monthly = query_db('''
                SELECT strftime('%Y-%m', activityDate) as ym, AVG(elapsedSecs) as avg_secs
                FROM SegmentEffort
                WHERE segmentId = ? AND activityDate >= ?
                GROUP BY ym ORDER BY ym
            ''', [seg['id'], six_months_ago])

            if len(monthly) >= 2:
                first_avg = monthly[0]['avg_secs']
                last_avg  = monthly[-1]['avg_secs']
                delta     = last_avg - first_avg
                if abs(delta) < 0.03 * first_avg:
                    trend_str = 'consistent'
                elif delta < 0:
                    trend_str = f'improving ({abs(delta):.0f}s faster avg vs 6 months ago)'
                else:
                    trend_str = f'slower ({delta:.0f}s avg vs 6 months ago)'
                lines.append(
                    f'- {seg["name"]}: {seg["cnt"]} efforts, '
                    f'recent avg {_fmt_dur(last_avg)} — {trend_str}'
                )

    return '\n'.join(lines)


def _build_achievement_context(activity_id, activity_date, sport=None):
    """Best times this activity set. A ride's are its BestEffort brackets; a run's or a swim's its SportEffort distances (services/sport_records).
    Each is held against the rider's own of the same kind, indoors against indoors."""
    from services.sports import is_ride
    if not is_ride(sport):
        return _build_sport_record_context(activity_id, sport)
    # The Ride view, and this rider's own: BestEffort has rows for anything with a track, and a walk is neither a ride's best 5 miles nor the
    # best another rider's ride has to beat. An indoor ride (Zwift, a turbo) is held against the indoor rides only, an outdoor one the outdoor ones.
    from services.best_efforts import effort_set
    from services.sports import indoor_sql, is_virtual
    es = effort_set(units.current())                    # in miles, or in km for a metric rider
    achievements = query_db(f'''
        SELECT e.{es.col} AS dist, e.elapsedSecs, e.avgSpeedMps, a.riderId, a.sportType
        FROM {es.table} e JOIN Ride a ON a.id = e.activityId
        WHERE e.activityId = ?
    ''', [activity_id])

    if not achievements:
        return ''

    lines = ['Achievements set on this ride:']

    for ach in achievements:
        d_mi   = units.fmt_dist(es.metres(float(ach['dist'])), places=0)
        secs   = ach['elapsedSecs']
        mph    = units.fmt_speed(ach['avgSpeedMps'])

        # What was the previous best for this distance bracket?
        prev = query_db(f'''
            SELECT e.elapsedSecs, e.activityDate
            FROM {es.table} e JOIN Ride a ON a.id = e.activityId
            WHERE e.{es.col} = ? AND e.activityId != ? AND a.riderId IS ? AND {indoor_sql(is_virtual(ach['sportType']))}
            ORDER BY e.elapsedSecs ASC LIMIT 1
        ''', [ach['dist'], activity_id, ach['riderId']], one=True)

        if prev:
            improvement = prev['elapsedSecs'] - secs
            lines.append(
                f'- Fastest {d_mi}: {_fmt_dur(secs)} at {mph} '
                f'(beat previous best of {_fmt_dur(prev["elapsedSecs"])} '
                f'from {_fmt_date(prev["activityDate"])} by {_fmt_dur(improvement)})'
            )
        else:
            lines.append(f'- Fastest {d_mi}: {_fmt_dur(secs)} at {mph} (first recorded effort at this distance)')

    return '\n'.join(lines)


def _build_sport_record_context(activity_id, sport):
    """A run's or a swim's best times over the standard distances (services/sport_records), each against the rider's best before it: a new best,
    or how far off it. Nothing for other sports, which have no best times."""
    from database import get_db
    from services import sport_records
    from services.sports import is_virtual
    k = sport_records.kind(sport)
    if not k:
        return ''
    db = get_db()
    act = db.execute(f'SELECT id, riderId, startDateLocal, {_streams_sql()} FROM Activity WHERE id=?', [activity_id]).fetchone()
    if not act:
        return ''
    if not db.execute('SELECT 1 FROM SportEffort WHERE activityId=? AND kind=?', [activity_id, k]).fetchone():
        sport_records.index(db, activity_id, act['startDateLocal'], sport, act['streams'])
        db.commit()
    mine = db.execute('SELECT distanceM, elapsedSecs FROM SportEffort WHERE activityId=? AND kind=? AND distanceM > 0 ORDER BY distanceM',
                      [activity_id, k]).fetchall()
    if not mine:
        return ''
    names = dict(sport_records.DISTANCES[k])
    before = sport_records.bests(db, act['riderId'], k, "e.activityId != ? AND e.activityDate <= ?",
                                 [activity_id, str(act['startDateLocal'])[:10]], indoor=is_virtual(sport))
    lines, close = [], []
    for row in mine:
        name, secs = names.get(row['distanceM'], f"{row['distanceM']:.0f} m"), row['elapsedSecs']
        prev = before.get(row['distanceM'])
        if prev is None:
            lines.append(f'- Best {name}: {_fmt_dur(secs)} (first recorded effort at this distance)')
        elif secs < prev['elapsedSecs']:
            lines.append(f"- Best {name}: {_fmt_dur(secs)} (beat previous best of {_fmt_dur(prev['elapsedSecs'])} from "
                         f"{_fmt_date(prev['activityDate'])} by {_fmt_dur(prev['elapsedSecs'] - secs)})")
        else:
            close.append(f"{name} {_fmt_dur(secs)} (best {_fmt_dur(prev['elapsedSecs'])}, {_fmt_date(prev['activityDate'])})")
    out = []
    if lines:
        out = [f'Best times set on this {"swim" if k == "swim" else "run"}:'] + lines
    if close:
        out.append(f'Quickest stretches against personal bests: {"; ".join(close)}')
    return '\n'.join(out)


def _streams_sql():
    from services import streams as _streams
    return _streams.sql()


def _build_weather_context(activity):
    """Return a single-line weather summary for the AI, or empty string."""
    summary = activity['weatherSummary'] if activity['weatherSummary'] else None
    if not summary:
        return ''

    parts = [summary]

    wind_kph = activity['weatherWindKph']
    gust_kph = activity['weatherGustKph']
    wind_rel = activity['weatherWindRel']
    rain_mm  = activity['weatherRainMm']
    temp_c   = activity['weatherTempC']

    # Flag notably strong wind
    if wind_kph and wind_kph >= 30:
        parts.append('strong wind conditions')
    elif wind_kph and wind_kph >= 20:
        parts.append('moderate wind')

    # Flag notable gust spike
    if gust_kph and wind_kph and gust_kph >= wind_kph * 1.5 and gust_kph >= 30:
        parts.append(f'gusty (up to {gust_kph:.0f}kph)')

    # Wind relative to route
    if wind_rel and wind_rel not in ('calm', None):
        if wind_kph and wind_kph >= 15:
            parts.append('wind direction varied round the loop' if wind_rel == 'mixed' else f'mostly {wind_rel}')

    # Rain
    if rain_mm and rain_mm >= 1.0:
        parts.append('wet conditions')

    # Temperature extremes
    if temp_c is not None:
        if temp_c <= 5:
            parts.append('cold')
        elif temp_c >= 28:
            parts.append('hot')

    # Deduplicate and return
    seen = set()
    unique = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return ', '.join(unique)


def _build_other_training_context(rider_id, exclude_id, day, p):
    """Everything else the rider did in the 30 days up to this activity's day, any other sport: the rest of the training load. A ride's notes see
    the runs and gym sessions around it, a run's the rides. Strength and yoga have no distance, so they show their time."""
    kind_sql, kind_params = p.history_sql()
    rows = query_db(f'''
        SELECT name, sportType, startDateLocal, distance, movingTime, totalElevationGain, averageHeartrate
        FROM Activity
        WHERE riderId IS ?
          AND id != ?
          AND date(startDateLocal) BETWEEN date(?, '-30 days') AND date(?)
          AND NOT ({kind_sql})
          AND (COALESCE(distance, 0) > 0 OR COALESCE(movingTime, 0) > 0)
        ORDER BY startDateLocal DESC
    ''', [rider_id, exclude_id, day, day, *kind_params])

    if not rows:
        return ''

    from services import sports
    lines = [f'Other training (30 days up to this {p.noun}):']
    for r in rows:
        elev_m  = float(r['totalElevationGain'] or 0)
        parts   = [units.fmt_dist(r['distance'])] if r['distance'] else []
        parts.append(_mins(r['movingTime']))
        if elev_m >= 15 and sports.has_climbing(r['sportType']):
            parts.append(f'{units.fmt_elev(elev_m)} gain')
        if r['averageHeartrate']:
            parts.append(f"avg HR {r['averageHeartrate']:.0f}")
        lines.append(f'  {_fmt_date(str(r["startDateLocal"])[:10])}: {sports.label(r["sportType"])} — {r["name"]} — {", ".join(parts)}')

    return '\n'.join(lines)


def _build_garmin_context(ride_date, rid, steps=True):
    """Return rider rid's recovery/readiness block for the 3 days up to and including ride_date: Garmin's, or Apple Health's for a day Garmin has
    nothing for (services/health). Apple's HRV is SDNN, not Garmin's overnight RMSSD, so it's named as such and has no balance. steps=False
    (Steps turned off) leaves the day's steps out."""
    from services import health
    rows = health.recovery_days(rid, ride_date, 3)

    if not rows:
        return ''

    sources = {s for r in rows for s in (r['source'] or '').split('+') if s}
    lines = [('Garmin' if sources == {'garmin'} else 'Apple Health' if sources == {health.SOURCE} else 'Garmin and Apple Health')
             + ' recovery data (up to ride day):']
    for r in rows:
        parts = []
        if r['restingHR']:
            parts.append(f'resting HR {r["restingHR"]}bpm')
        if r['hrv']:
            if r['hrv_kind'] == 'sdnn':
                parts.append(f'HRV {r["hrv"]}ms (Apple Watch SDNN, not comparable with overnight RMSSD)')
            else:
                status = 'balanced' if r['hrvBalanced'] else 'unbalanced'
                parts.append(f'HRV {r["hrv"]} ({status})')
        if r['sleepHours']:
            parts.append(f'sleep {r["sleepHours"]}h')
            if r['sleepDeep'] is not None:
                parts.append(f'deep {r["sleepDeep"]:.1f}h, REM {r["sleepRem"]:.1f}h, light {r["sleepLight"]:.1f}h')
            if r['sleepEfficiency']:
                parts.append(f'efficiency {r["sleepEfficiency"]}% ({r["sleepAwakeMin"] or 0} min awake)')
            if r['sleepScore']:
                parts.append(f'score {r["sleepScore"]}')
        if r['bodyBattery']:
            parts.append(f'body battery {r["bodyBattery"]}%')
        if r['steps'] and steps:
            parts.append(f'steps {r["steps"]:,}')
        if r['stressScore']:
            parts.append(f'stress {r["stressScore"]}')
        if parts:
            lines.append(f'  {_fmt_date(r["date"])}: {", ".join(parts)}')

    return '\n'.join(lines) if len(lines) > 1 else ''


def _build_badge_context(rid, ride_id):
    totals = query_db(
        'SELECT COUNT(*) as rides, SUM(distance) as dist, SUM(totalElevationGain) as elev '
        'FROM Ride WHERE riderId=?', [rid], one=True)
    if not totals:
        return ''
    categories = _compute_badges(rid, totals)
    total_earned = sum(1 for cat in categories for b in cat['badges'] if b['earned'])
    total_badges = sum(len(cat['badges']) for cat in categories)
    unlocked = [
        f'  - {b["icon"]} {b["name"]}: {b["desc"]}'
        for cat in categories for b in cat['badges']
        if b.get('ride_id') and str(b['ride_id']) == str(ride_id)
    ]
    lines = [f'Trophy case: {total_earned}/{total_badges} badges earned']
    if unlocked:
        lines.append('Milestones unlocked on this ride:')
        lines.extend(unlocked)
    return '\n'.join(lines)


def _memory_sql(p, rider_id, exclude_id, day):
    """The WHERE (and its params) for this activity's history in ActivityMemory: this rider's own activities of the same kind (Profile.history_sql),
    up to this one's day, so an older activity analysed today isn't compared with what came after it."""
    kind_sql, kind_params = p.history_sql()
    where = f'''activityId != ?
          AND activityDate <= ?
          AND activityId IN (SELECT id FROM Activity WHERE riderId IS ? AND {kind_sql})
          AND NOT (activityName = 'Ride Activity' AND avgPower IS NULL)'''
    if p.distance:
        where += '\n          AND distanceMi > 0'
    return where, [exclude_id, day, rider_id, *kind_params]


def _build_comeback_progress(p, where, params, cur_spd_mph=None, cur_pwr_w=None):
    """Monthly averages since comeback start, to surface gains clearly: speed (or pace) and power for a sport with a distance, time and heart
    rate for one without."""
    from datetime import datetime
    current_ym = datetime.now().strftime('%Y-%m')

    rows = query_db(f'''
        SELECT strftime('%Y-%m', activityDate) as ym,
               COUNT(*) as rides,
               AVG(distanceMi) as avg_dist,
               AVG(avgSpeedMph) as avg_spd,
               AVG(avgPower) as avg_pwr,
               MAX(avgSpeedMph) as best_spd,
               MAX(avgPower) as best_pwr,
               AVG(movingTime) as avg_time,
               AVG(avgHR) as avg_hr
        FROM ActivityMemory
        WHERE {where}
          AND activityDate >= '2026-01-01'
          {'AND distanceMi > 2' if p.family == 'ride' else ''}
        GROUP BY ym
        ORDER BY ym
    ''', params)

    if len(rows) < 2:
        return ''

    best = 'best' if p.rate == 'speed' else 'quickest'
    lines = [f'Comeback progress by month, {p.nouns} (Jan 2026 onwards — read the OVERALL arc, not month-to-month noise):']
    for r in rows:
        partial_note = ' ⚠️ partial month' if r['ym'] == current_ym else ''
        if p.distance:
            figs = f"avg {_rate(r['avg_spd'], p.rate)} ({best} {_rate(r['best_spd'], p.rate)})"
            if p.family == 'ride' or r['avg_pwr']:
                figs += ' | ' + (f"avg {r['avg_pwr']:.0f}W, best {r['best_pwr']:.0f}W" if r['avg_pwr'] else 'no power data')
        else:
            figs = f"avg {_mins(r['avg_time'])}" + (f", avg HR {r['avg_hr']:.0f}" if r['avg_hr'] else '')
        lines.append(f"  {r['ym']}{partial_note}: {p.count(r['rides'])} | {figs}")

    # Add today's activity vs current month avg for context
    cur_month_row = next((r for r in rows if r['ym'] == current_ym), None)
    if cur_month_row and p.distance and (cur_spd_mph or cur_pwr_w):
        parts = []
        if cur_spd_mph and cur_month_row['avg_spd']:
            direction = 'above' if cur_spd_mph > cur_month_row['avg_spd'] else 'below'
            if p.rate != 'speed':
                direction = 'quicker than' if direction == 'above' else 'slower than'
            parts.append(f'{_rate(cur_spd_mph, p.rate)} ({direction} {current_ym} avg of {_rate(cur_month_row["avg_spd"], p.rate)})')
        if cur_pwr_w and cur_month_row['avg_pwr']:
            direction = 'above' if cur_pwr_w > cur_month_row['avg_pwr'] else 'below'
            parts.append(f'{cur_pwr_w:.0f}W ({direction} {current_ym} avg of {cur_month_row["avg_pwr"]:.0f}W)')
        if parts:
            lines.append(f"  Today's {p.noun}: {', '.join(parts)}")

    # Overall delta: first month vs most recent COMPLETE month (not partial)
    complete_rows = [r for r in rows if r['ym'] != current_ym]
    if not complete_rows:
        complete_rows = rows
    first, last_complete = rows[0], complete_rows[-1]
    if p.distance:
        spd_gain = last_complete['avg_spd'] - first['avg_spd'] if first['avg_spd'] else 0
        if first['avg_spd'] and spd_gain / first['avg_spd'] > 0.01:
            pct = spd_gain / first['avg_spd'] * 100
            what = 'speed up' if p.rate == 'speed' else 'pace quicker by'
            lines.append(f'  → Overall {what} {pct:.0f}% from {first["ym"]} to {last_complete["ym"]} (ignore partial current month)')
        if first['avg_pwr'] and last_complete['avg_pwr']:
            pwr_gain = last_complete['avg_pwr'] - first['avg_pwr']
            if pwr_gain > 5:
                pct = pwr_gain / first['avg_pwr'] * 100
                lines.append(f'  → Overall power up {pct:.0f}% from {first["ym"]} to {last_complete["ym"]}')

    return '\n'.join(lines)


def _trend(vals):
    if len(vals) < 3: return 'insufficient data'
    first_half = sum(vals[:len(vals)//2]) / max(1, len(vals)//2)
    second_half = sum(vals[len(vals)//2:]) / max(1, len(vals) - len(vals)//2)
    diff = second_half - first_half
    if abs(diff) < 0.05 * first_half: return 'flat'
    return 'trending up' if diff > 0 else 'trending down'


def _history_row(r, p, power):
    """One line of the history table, in the columns _history_header gives."""
    hr = f"{r['avgHR']:.0f}" if r['avgHR'] else '—'
    if not p.distance:
        kcal = f"{r['calories']:.0f}" if r['calories'] else '—'
        return f"{r['activityDate']} | {_mins(r['movingTime']):>7} | {hr:>4} | {kcal:>5} | {r['activityName']}"
    cols = [r['activityDate'], f"{_mi(r['distanceMi']):>8}", f"{_rate(r['avgSpeedMph'], p.rate):>9}"]
    if p.climbing:
        cols.append(f"{_ft(r['elevationFt']):>7}")
    if power:
        cols.append(f"{(str(round(r['avgPower'])) + 'W') if r['avgPower'] else '—':>5}")
    cols += [f'{hr:>4}', r['activityName']]
    return ' | '.join(cols)


def _history_header(p, power):
    if not p.distance:
        return 'Date       | Time    | HR   | kcal  | Name'
    cols = ['Date      ', 'Dist    ', 'Speed    ' if p.rate == 'speed' else 'Pace     ']
    if p.climbing:
        cols.append('Elev   ')
    if power:
        cols.append('Power')
    return ' | '.join(cols + ['HR  ', 'Name'])


def build_context(activity):
    """What the coach knows besides the activity's own figures: its history (the same kind of activity only: services/coach_sports), the other
    training around it, recovery, segments, the same route, best times and badges."""
    from services.coach_sports import profile
    p = profile(activity['sportType'])
    ride_id  = str(activity['id'])
    day      = str(activity['startDateLocal'])[:10]
    dist_mi  = float(activity['distance'] or 0) / 1609.344
    elev_ft  = float(activity['totalElevationGain'] or 0) * 3.28084
    where, params = _memory_sql(p, activity['riderId'], ride_id, day)

    recent = query_db(f'SELECT * FROM ActivityMemory WHERE {where} ORDER BY activityDate DESC LIMIT 20', params)

    # Like for like: about the same distance (and climb, where climbing counts), or for a session with no distance about the same length
    if p.distance:
        similar = 'distanceMi BETWEEN ? AND ?' + (' AND elevationFt BETWEEN ? AND ?' if p.climbing else '')
        sim_params = [dist_mi * 0.7, dist_mi * 1.3] + ([max(0, elev_ft * 0.6), elev_ft * 1.4] if p.climbing else [])
    else:
        secs = float(activity['movingTime'] or 0)
        similar, sim_params = 'movingTime BETWEEN ? AND ?', [secs * 0.7, secs * 1.3]
    comparable = query_db(f'SELECT * FROM ActivityMemory WHERE {where} AND {similar} ORDER BY activityDate DESC LIMIT 5',
                          params + sim_params)

    month = query_db(f"SELECT * FROM ActivityMemory WHERE {where} AND activityDate >= date(?, '-30 days') ORDER BY activityDate DESC",
                     params + [day])

    lines = []

    # Comeback progress FIRST — most important signal for a returning athlete
    cur_spd = float(activity['averageSpeed'] or 0) * 2.23694 or None
    cur_pwr = float(activity['averageWatts'] or 0) or None
    comeback_ctx = _build_comeback_progress(p, where, params, round(cur_spd, 2) if cur_spd else None, round(cur_pwr) if cur_pwr else None)
    if comeback_ctx:
        lines.append(comeback_ctx)
        lines.append('')

    power = any(r['avgPower'] for r in recent)
    if recent:
        lines.append(f'{p.label} history (last {p.count(len(recent))}):')
        lines.append(_history_header(p, power))
        for r in recent:
            lines.append(_history_row(r, p, power))
        lines.append('')

    if comparable:
        lines.append(f'Comparable {p.nouns} ({"similar distance" + (" & elevation" if p.climbing else "") if p.distance else "similar length"}):')
        for r in comparable:
            if p.distance:
                figs = [_mi(r['distanceMi']), _rate(r['avgSpeedMph'], p.rate)]
                if p.climbing:
                    figs.append(f"{_ft(r['elevationFt'])} climb")
                if r['avgPower']:
                    figs.append(f"{r['avgPower']:.0f}W")
            else:
                figs = [_mins(r['movingTime'])]
            if r['avgHR']:
                figs.append(f"HR {r['avgHR']:.0f}")
            lines.append(f"  {r['activityDate']}: {', '.join(figs)}")
        lines.append('')

    if month:
        lines.append(f'30-day summary ({p.count(len(month))}):')
        if p.distance:
            dists  = [r['distanceMi']  for r in month]
            speeds = [r['avgSpeedMph'] for r in month]
            elevs  = [r['elevationFt'] or 0 for r in month]
            powers = [r['avgPower'] for r in month if r['avgPower']]
            lines.append(f'  Distance : avg {_mi(sum(dists)/len(dists))}, best {_mi(max(dists))}, {_trend(dists)}')
            if p.climbing:
                lines.append(f'  Elevation: avg {_ft(sum(elevs)/len(elevs))}, best {_ft(max(elevs))}')
            best = 'best' if p.rate == 'speed' else 'quickest'
            trend = _trend(speeds) if p.rate == 'speed' else _trend(speeds).replace('up', 'quicker').replace('down', 'slower')
            lines.append(f'  {"Speed" if p.rate == "speed" else "Pace "}    : avg {_rate(sum(speeds)/len(speeds), p.rate)}, '
                         f'{best} {_rate(max(speeds), p.rate)}, {trend}')
            if powers:
                lines.append(f'  Power    : avg {sum(powers)/len(powers):.0f}W, best {max(powers):.0f}W, {_trend(powers)}')
            lines.append(f'  Last 3 {p.nouns}: {", ".join(_mi(r["distanceMi"]) for r in month[:3])}')
        else:
            times = [float(r['movingTime'] or 0) for r in month]
            lines.append(f'  Time     : avg {_mins(sum(times)/len(times))}, longest {_mins(max(times))}, {_trend(times)}')
            hrs = [r['avgHR'] for r in month if r['avgHR']]
            if hrs:
                lines.append(f'  Avg HR   : {sum(hrs)/len(hrs):.0f}, {_trend(hrs)}')
        lines.append('')

    if not recent and not month:
        lines.append(f'No previous {p.nouns} in memory yet — this may be one of the first analysed.')

    # What the rider has switched off stays out (services/features.py): no recovery with Recovery off, no steps with Steps off, no segments with
    # Segments off. Nothing here reads the food diary; anything that adds it checks 'nutrition' the same way. The rider is the activity's, as
    # this also runs in the background (services/auto_analyse.py).
    from services import features
    rid = activity['riderId']
    def wanted(name):
        return rid is None or features.on(name, rid)

    garmin_ctx = _build_garmin_context(day, rid, steps=wanted('steps')) if wanted('recovery') else ''
    if garmin_ctx:
        lines.append('')
        lines.append(garmin_ctx)

    other_ctx = _build_other_training_context(activity['riderId'], ride_id, day, p)
    if other_ctx:
        lines.append('')
        lines.append(other_ctx)

    seg_ctx = _build_segment_context(ride_id) if wanted('segments') else ''
    if seg_ctx:
        lines.append('')
        lines.append(seg_ctx)

    route_ctx = _build_route_context(ride_id)
    if route_ctx:
        lines.append('')
        lines.append(route_ctx)

    ach_ctx = _build_achievement_context(ride_id, day, activity['sportType'])
    if ach_ctx:
        lines.append('')
        lines.append(ach_ctx)

    if activity['riderId']:
        badge_ctx = _build_badge_context(activity['riderId'], ride_id)
        if badge_ctx:
            lines.append('')
            lines.append(badge_ctx)

    return '\n'.join(lines)


def _build_route_context(ride_id):
    """The same route ridden before (services/matched): where this one ranks, and how it compares with the last few, with their wind. The
    "comparable rides" above only match distance and climb; these followed the same roads, so their times compare directly."""
    from database import get_db
    from services import matched
    try:
        m = matched.compare(get_db(), ride_id)
    except Exception:
        return ''
    if not m:
        return ''
    t = m['this']
    lines = [f"Same route (same start, finish and roads; {m['total']} times since {_fmt_date(str(m['first']))}): this one is "
             f"{_fmt_dur(t['movingTime'])} moving, the {m['rank']}{'th' if 10 <= m['rank'] % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(m['rank'] % 10, 'th')} "
             f"quickest of {m['total']}; best {_fmt_dur(m['best']['movingTime'])} on {_fmt_date(str(m['best']['startDateLocal']))}."]
    if m['median'] is not None:
        lines.append(f"  vs the last {len(m['recent'])} here: median {_fmt_dur(m['median'])}, this one {_fmt_dur(abs(m['delta']))} "
                     f"{'quicker' if m['delta'] < 0 else 'slower'}, beating {m['wins']} of them")
        for r in m['recent'][:5]:
            wind = f", {r['weatherWindRel']}" if r.get('weatherWindRel') else ''
            lines.append(f"  {str(r['startDateLocal'])[:10]}: {_fmt_dur(r['movingTime'])}{wind}")
    return '\n'.join(lines)


def get_weather_line(activity):
    """Return a concise weather line for embedding in the AI prompt, or None."""
    return _build_weather_context(activity) or None


def build_comparison_receipts(activity):
    """Return specific before/after comparison receipts for AI coaching."""
    ride_id   = str(activity['id'])
    ride_date = str(activity['startDateLocal'])[:10]
    dist_mi   = float(activity['distance'] or 0) / 1609.344
    elev_ft   = float(activity['totalElevationGain'] or 0) * 3.28084
    spd_mph   = float(activity['averageSpeed'] or 0) * 2.23694

    receipts = []

    current_efforts = query_db('''
        SELECT e.elapsedSecs, s.id AS seg_id, s.name AS seg_name
        FROM SegmentEffort e
        JOIN Segment s ON s.id = e.segmentId
        WHERE e.activityId = ?
        ORDER BY s.name
    ''', [ride_id])

    for eff in current_efforts:
        seg_id   = eff['seg_id']
        seg_name = eff['seg_name']
        cur_secs = eff['elapsedSecs']

        prev_best  = query_db('''
            SELECT elapsedSecs, activityDate FROM SegmentEffort
            WHERE segmentId = ? AND activityId != ?
            ORDER BY elapsedSecs ASC LIMIT 1
        ''', [seg_id, ride_id], one=True)

        first_eff = query_db('''
            SELECT elapsedSecs, activityDate FROM SegmentEffort
            WHERE segmentId = ? AND activityId != ?
            ORDER BY activityDate ASC LIMIT 1
        ''', [seg_id, ride_id], one=True)

        recent_eff = query_db('''
            SELECT elapsedSecs, activityDate FROM SegmentEffort
            WHERE segmentId = ? AND activityId != ?
              AND activityDate BETWEEN date(?, '-56 days') AND date(?, '-14 days')
            ORDER BY activityDate DESC LIMIT 1
        ''', [seg_id, ride_id, ride_date, ride_date], one=True)

        def _pr_age_years(date_str):
            try:
                from datetime import datetime
                d = datetime.strptime(str(date_str)[:10], '%Y-%m-%d')
                return (datetime.now() - d).days // 365
            except Exception:
                return 0

        def _make(comp_type, row):
            if not row:
                return None
            prev_secs = row['elapsedSecs']
            delta_s   = prev_secs - cur_secs  # positive = today is faster
            delta_pct = abs(delta_s) / prev_secs * 100 if prev_secs else 0
            if delta_s > 0:
                delta_str = f'{_fmt_dur(delta_s)} faster'
            elif delta_s < 0:
                delta_str = f'{_fmt_dur(abs(delta_s))} slower'
            else:
                delta_str = 'identical time'
            age_yrs = _pr_age_years(row['activityDate'])
            historical = age_yrs >= 2
            if comp_type == 'previous_best':
                if historical:
                    hint = f'historical best from {str(row["activityDate"])[:4]} — aspirational target, not a current-form benchmark'
                else:
                    hint = 'new personal best' if delta_s > 0 else 'just off the PR'
            elif comp_type == 'first_effort':
                hint = 'progression since first attempt'
            else:
                hint = 'recent form improving' if delta_s > 0 else 'slightly off recent pace'
            return {
                'type': 'segment',
                'comparison_type': comp_type,
                'segment': seg_name,
                'current': _fmt_dur(cur_secs),
                'previous': _fmt_dur(prev_secs),
                'previous_date': _fmt_date(row['activityDate']),
                'delta': delta_str,
                'delta_percent': f'{delta_pct:.1f}%',
                'delta_seconds': delta_s,
                'hint': hint,
                'historical': historical,
            }

        r_recent = _make('recent_effort', recent_eff)
        r_best   = _make('previous_best', prev_best)
        r_first  = _make('first_effort',  first_eff)

        if r_recent:
            receipts.append(r_recent)

        if r_best:
            # Skip if same row as recent effort
            if not recent_eff or prev_best['activityDate'] != recent_eff['activityDate']:
                receipts.append(r_best)

        if r_first and r_best:
            # Only add if first effort is genuinely different from the all-time best row
            if (first_eff['activityDate'] != prev_best['activityDate'] or
                    first_eff['elapsedSecs'] != prev_best['elapsedSecs']):
                receipts.append(r_first)
        elif r_first and not r_best:
            receipts.append(r_first)

    # --- Similar activities' speed (or pace) comparisons: the same kind of activity only (services/coach_sports), and none without a distance ---
    from services.coach_sports import profile
    p = profile(activity['sportType'])
    similar = []
    if p.distance and spd_mph:
        where, params = _memory_sql(p, activity['riderId'], ride_id, ride_date)
        climb = ' AND elevationFt BETWEEN ? AND ?' if p.climbing else ''
        similar = query_db(f'''
            SELECT activityId, activityDate, activityName, distanceMi, avgSpeedMph, elevationFt, avgPower
            FROM ActivityMemory
            WHERE {where}
              AND distanceMi BETWEEN ? AND ?{climb}
            ORDER BY activityDate DESC LIMIT 3
        ''', params + [dist_mi * 0.8, dist_mi * 1.2] + ([max(0, elev_ft * 0.7), elev_ft * 1.4] if p.climbing else []))

    for sim in similar:
        sim_spd = float(sim['avgSpeedMph'] or 0)
        if sim_spd == 0:
            continue
        spd_delta = spd_mph - sim_spd
        if abs(spd_delta) < 0.015 * sim_spd:            # about 0.2 mph on a 14 mph ride: noise
            continue

        quicker = spd_delta > 0
        if p.rate == 'speed':
            direction = 'faster' if quicker else 'slower'
            delta = f'{_mph(abs(spd_delta))} {direction}'
            hint = f'speed {"up" if quicker else "down"} on comparable {"terrain" if p.climbing else "distance"}'
        else:
            direction = 'quicker' if quicker else 'slower'
            per = 100 if p.rate == 'swim' else units.spec()['distM']           # pace per 100 m, per mile or per km
            secs = abs(per / (sim_spd / units.MPH_PER_MPS) - per / (spd_mph / units.MPH_PER_MPS))
            delta = f'{_fmt_dur(secs)} {"/100 m" if p.rate == "swim" else units.spec()["pace"]} {direction}'
            hint = f'pace {direction} on comparable {"terrain" if p.climbing else "distance"}'

        pwr_note = ''
        if activity['averageWatts'] and sim['avgPower']:
            pwr_d = float(activity['averageWatts']) - float(sim['avgPower'])
            if abs(pwr_d) < 5:
                pwr_note = ', same power output'
                if quicker:
                    hint = 'quicker for the same power — efficiency gain'
            elif pwr_d < 0 and quicker:
                pwr_note = f', {abs(pwr_d):.0f}W less power'
                hint = 'quicker with less power — significant efficiency gain'
            elif pwr_d > 0 and quicker:
                pwr_note = f', {abs(pwr_d):.0f}W more power'

        receipts.append({
            'type': 'similar_ride',
            'comparison_type': 'similar_ride',
            'noun': p.noun,
            'previous_name': sim['activityName'],
            'previous_date': _fmt_date(str(sim['activityDate'])),
            'current_speed': _rate(spd_mph, p.rate),
            'previous_speed': _rate(sim_spd, p.rate),
            'current_elev': _ft(elev_ft) if p.climbing else None,
            'previous_elev': _ft(sim['elevationFt']) if p.climbing else None,
            'delta': f'{delta}{pwr_note}',
            'hint': hint,
        })

    # Sort: recent improvements first, non-historical PRs next, historical last
    # Within each tier, bigger delta first
    def _seg_key(r):
        if r.get('historical'):
            return (2, -abs(r['delta_seconds']))
        if r['comparison_type'] == 'recent_effort':
            return (0, -abs(r['delta_seconds']))
        return (1, -abs(r['delta_seconds']))

    seg_r  = sorted([r for r in receipts if r['type'] == 'segment'], key=_seg_key)
    ride_r = [r for r in receipts if r['type'] == 'similar_ride']
    return (seg_r + ride_r)[:10]
