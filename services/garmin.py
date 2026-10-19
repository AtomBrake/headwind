import logging
import contextlib
import io
import json
import secrets
import threading
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

# Activity type keys that have meaningful GPS data worth importing
# Activity types with no GPS data that aren't worth importing
_SKIP_TYPES = {
    'strength_training', 'yoga', 'fitness_equipment', 'elliptical',
    'stair_climbing', 'indoor_rowing', 'pilates', 'barre', 'floor_climbing',
    'breathwork', 'meditation',
}


def garmin_sport(type_key):
    """Garmin's activity type (`typeKey`, e.g. 'mountain_biking', 'lap_swimming', 'treadmill_running') -> our sport. Rides are Ride / VirtualRide /
    EBikeRide (an e-bike ride races other e-bike rides for segment PRs: services/sports.segment_class);
    everything else is saved as a workout under its own sport. Anything not recognised is 'Other', never a ride: a ride that is really a
    swim breaks the ride totals and the sanity checks."""
    k = (type_key or '').lower()
    if 'motor' in k or 'snowmobil' in k:                      # motorcycling, motocross: 'cycl' but not a bike ride
        return 'Other'
    if k in ('indoor_cycling', 'virtual_ride') or ('virtual' in k and ('cycl' in k or 'bik' in k or 'ride' in k)):
        return 'VirtualRide'
    if k.startswith('e_') and ('bik' in k or 'mtb' in k):        # e_bike_fitness, e_bike_mountain, e_enduro_mtb
        return 'EBikeRide'
    if 'cycl' in k or 'bik' in k or k in ('ride', 'bmx'):
        return 'Ride'
    for needle, sport in (('run', 'Run'), ('walk', 'Walk'), ('hik', 'Hike'), ('mountaineer', 'Hike'), ('swim', 'Swim'), ('surf', 'Surf'),
                          ('paddl', 'Paddle'), ('kayak', 'Paddle'), ('canoe', 'Paddle'), ('raft', 'Paddle'), ('row', 'Row'),
                          ('ski', 'Ski'), ('snowboard', 'Ski'), ('skat', 'Skate'), ('golf', 'Golf'), ('climb', 'Climb')):
        if needle in k:
            return sport
    return 'Other'


import os as _os

log = logging.getLogger(__name__)

TOKEN_DIR = Path(_os.environ['HEADWIND_TOKEN_DIR']) if _os.environ.get('HEADWIND_TOKEN_DIR') else Path(__file__).parent.parent / '.garmin_tokens'

# In-memory holding pen for logins paused on an MFA challenge. Keyed by a random
# token handed to the browser (kept in the Flask session, not a cookie itself);
# the value is the *live* Garmin client object, because the installed
# garminconnect library stores MFA-pending state on the client instance itself
# (see resume_login below) rather than in anything serializable — there is no
# token we could stash in the DB and hand to a fresh client on the next request.
# Safe as a plain module dict because this app runs single-process
# (debug=True, use_reloader=False — see bike-flask/CLAUDE.md).
_PENDING_MFA = {}
_MFA_TTL_SECS = 300  # Garmin's own SMS/email codes expire on a similar timescale


def _prune_pending():
    now = time.time()
    for tok in [t for t, (_, exp) in _PENDING_MFA.items() if exp < now]:
        _PENDING_MFA.pop(tok, None)


def _client(email, password):
    from garminconnect import Garmin

    TOKEN_DIR.mkdir(exist_ok=True)
    # login() loads tokens from tokenstore if present; saves them after password login
    api = Garmin(email=email, password=password)
    api.login(tokenstore=str(TOKEN_DIR))
    return api


def start_login(email, password):
    """
    First step of interactive first-time Garmin auth (setup wizard / Settings).
    Returns {'ok': True} once tokens are cached and ready for _client() to use,
    or {'ok': False, 'needs_mfa': True, 'token': ...} when Garmin wants a code —
    pass that token + the code to complete_mfa() within 5 minutes.
    Raises garminconnect's GarminConnectAuthenticationError / …TooManyRequestsError
    / …ConnectionError on real failures — callers should catch and show str(e).
    """
    from garminconnect import Garmin

    TOKEN_DIR.mkdir(exist_ok=True)
    _prune_pending()

    # Deliberately no tokenstore= here: login()'s tokenstore path loads and trusts
    # whatever tokens already exist on disk, silently ignoring the password we were
    # just given (that's fine for the routine _client() background-sync path, but
    # this function's whole job is to actually check the credentials someone just
    # typed — otherwise a wrong password, or stale tokens from a previous account,
    # would come back as a false "connected").
    api = Garmin(email=email, password=password, return_on_mfa=True)
    status, _ = api.login()
    if status == 'needs_mfa':
        token = secrets.token_urlsafe(16)
        _PENDING_MFA[token] = (api, time.time() + _MFA_TTL_SECS)
        return {'ok': False, 'needs_mfa': True, 'token': token}

    # return_on_mfa=True makes the library skip its own post-login token dump
    # even on a clean, no-MFA success — do it ourselves so _client() finds it next time.
    with contextlib.suppress(Exception):
        api.client.dump(str(TOKEN_DIR))
    return {'ok': True}


def complete_mfa(token, code):
    """
    Second step: finishes a login start_login() paused on 'needs_mfa'.
    Returns {'ok': True} on success. Raises the same garminconnect exceptions
    as start_login() on a wrong/expired code (str(e) is safe to show the user) —
    a wrong code leaves the pending entry in place so the same live session can
    be retried with a corrected code, rather than forcing a whole new login attempt.
    """
    _prune_pending()
    entry = _PENDING_MFA.get(token)
    if not entry:
        from garminconnect import GarminConnectAuthenticationError
        raise GarminConnectAuthenticationError(
            'That code has expired — please reconnect Garmin and try again.'
        )
    api, _ = entry
    api.resume_login(None, code)  # raises on a wrong code; entry stays pending for a retry
    _PENDING_MFA.pop(token, None)
    with contextlib.suppress(Exception):
        api.client.dump(str(TOKEN_DIR))
    return {'ok': True}


def _parse_rhr(stats):
    try:
        return int(stats.get('restingHeartRate') or 0) or None
    except Exception:
        return None


def _parse_hrv(hrv_data):
    try:
        summary = hrv_data.get('hrvSummary') or {}
        last_night = summary.get('lastNight')
        status     = summary.get('status') or ''
        balanced   = 1 if 'BALANCED' in status.upper() else 0
        return (int(last_night) if last_night else None, balanced)
    except Exception:
        return (None, 0)


def _parse_sleep(sleep_data):
    try:
        dto   = sleep_data.get('dailySleepDTO') or {}
        secs  = dto.get('sleepTimeSeconds') or 0
        hours = round(secs / 3600, 1) if secs else None
        score_obj = (dto.get('sleepScores') or {}).get('overall') or {}
        score = score_obj.get('value')
        return (hours, int(score) if score is not None else None)
    except Exception:
        return (None, None)


def _parse_body_battery(bb_data):
    try:
        if not bb_data:
            return None
        charged = bb_data[-1].get('charged') if isinstance(bb_data, list) else None
        return int(charged) if charged is not None else None
    except Exception:
        return None


def _parse_steps(steps_data):
    try:
        if not steps_data:
            return None
        total = sum(x.get('steps', 0) or 0 for x in steps_data)
        return int(total) if total > 0 else None
    except Exception:
        return None


def _parse_stress(stress_data):
    try:
        val = (stress_data or {}).get('avgStressLevel')
        # Garmin returns -1 when there's no data
        if val is None or val < 0:
            return None
        return int(val)
    except Exception:
        return None


def _parse_calories(stats):
    try:
        total  = stats.get('totalKilocalories')
        active = stats.get('activeKilocalories')
        return (
            int(total)  if total  and total  > 0 else None,
            int(active) if active and active > 0 else None,
        )
    except Exception:
        return None, None


def _parse_weigh_ins(data):
    """{'YYYY-MM-DD': kg} from get_weigh_ins(): each day's last weigh-in (Garmin stores grams)."""
    from services.weight_trend import MIN_SANE_KG, MAX_SANE_KG
    days = {}
    for s in (data or {}).get('dailyWeightSummaries') or []:
        try:
            entries = [w for w in (s.get('allWeightMetrics') or []) if w.get('weight')]
            last = max(entries, key=lambda w: w.get('timestampGMT') or w.get('date') or 0) if entries else s.get('latestWeight')
            day = s.get('summaryDate') or (last or {}).get('calendarDate')
            if not last or not last.get('weight') or not day:
                continue
            kg = round(float(last['weight']) / 1000, 2)
            if MIN_SANE_KG <= kg <= MAX_SANE_KG:
                days[day[:10]] = kg
        except Exception:
            continue
    return days


def _sync_weigh_ins(api, db, rider_id, start, end):
    """Upsert Garmin weigh-ins into WeightLog. Only rows Garmin wrote are updated: a manual entry
    (or another scale's, e.g. Home Assistant) for the same day is left alone.
    Returns (days Garmin had a weigh-in, rows changed)."""
    found = _parse_weigh_ins(api.get_weigh_ins(start, end))
    changed = 0
    for day, kg in found.items():
        existing = db.execute('SELECT id, weightKg, source FROM WeightLog WHERE riderId=? AND logDate=?',
                              [rider_id, day]).fetchone()
        if not existing:
            db.execute("INSERT INTO WeightLog (riderId, logDate, weightKg, source) VALUES (?,?,?,'garmin')", [rider_id, day, kg])
            changed += 1
        elif existing['source'] == 'garmin' and abs(existing['weightKg'] - kg) > 0.001:
            db.execute('UPDATE WeightLog SET weightKg=? WHERE id=?', [kg, existing['id']])
            changed += 1
    return len(found), changed


def fetch_ride_hr(api, start_utc_iso, elapsed_secs, time_stream=None):
    """
    Pull minute-by-minute HR from Garmin for the ride's time window.
    Checks GarminDaily.hrStream first (already synced locally), falls back to live API.
    If time_stream (list of elapsed seconds from Strava) is provided, interpolates
    HR values onto it so the chart aligns with distance/speed.
    Returns {'avg': int, 'max': int, 'stream_data': [bpm, ...]} or None.
    """
    import bisect
    from datetime import datetime, timezone

    start_dt = datetime.fromisoformat(start_utc_iso.replace('Z', '+00:00'))
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms   = start_ms + int(elapsed_secs) * 1000
    date_str = start_dt.strftime('%Y-%m-%d')

    # Prefer locally-stored hrStream from GarminDaily (already synced, no extra API call)
    raw = []
    try:
        from database import query_db
        row = query_db('SELECT hrStream FROM GarminDaily WHERE date=?', [date_str], one=True)
        if row and row['hrStream']:
            raw = json.loads(row['hrStream'])
    except Exception:
        log.debug('Reading the stored Garmin HR day failed', exc_info=True)

    # Fall back to live API if local data is absent
    if not raw:
        hr_data = api.get_heart_rates(date_str)
        raw     = hr_data.get('heartRateValues') or []

    # Ride-only pairs for avg/max
    ride_pairs = [(ts, bpm) for ts, bpm in raw if bpm is not None and start_ms <= ts <= end_ms]
    if not ride_pairs:
        return None

    bpms = [bpm for _, bpm in ride_pairs]
    avg  = round(sum(bpms) / len(bpms))
    peak = max(bpms)

    if time_stream:
        # Include up to 5 min before start so interpolation has a proper anchor
        # at elapsed=0 rather than snapping to the first in-window Garmin point.
        buffer_ms = 5 * 60 * 1000
        interp_pairs = [(ts, bpm) for ts, bpm in raw
                        if bpm is not None and (start_ms - buffer_ms) <= ts <= end_ms]
        timestamps = [ts for ts, _ in interp_pairs]
        hr_vals    = [bpm for _, bpm in interp_pairs]
        stream_data = []
        for elapsed in time_stream:
            t   = start_ms + elapsed * 1000
            idx = bisect.bisect_left(timestamps, t)
            if idx == 0:
                stream_data.append(hr_vals[0])
            elif idx >= len(timestamps):
                stream_data.append(hr_vals[-1])
            else:
                t0, t1 = timestamps[idx - 1], timestamps[idx]
                v0, v1 = hr_vals[idx - 1], hr_vals[idx]
                frac = (t - t0) / (t1 - t0) if t1 > t0 else 0
                stream_data.append(round(v0 + frac * (v1 - v0)))
    else:
        stream_data = bpms

    return {'avg': avg, 'max': peak, 'stream_data': stream_data}


def _is_rate_limit(e):
    return type(e).__name__ == 'GarminConnectTooManyRequestsError' or '429' in str(e)


class _Calls:
    """Makes Garmin calls for a run of days. An ordinary failure comes back as None, so one missing metric doesn't lose
    the rest of the day. With raise_rate_limit a rate limit is raised instead, so the history backfill can stop and resume
    later. `ok` counts the calls that answered, so a total outage isn't mistaken for days with no data."""

    def __init__(self, raise_rate_limit=False):
        self.raise_rate_limit, self.ok = raise_rate_limit, 0

    def __call__(self, fn, *args):
        try:
            r = fn(*args)
        except Exception as e:
            if self.raise_rate_limit and _is_rate_limit(e):
                raise
            return None
        self.ok += 1
        return r


def _fetch_day(call, api, d):
    """One day's Garmin daily metrics as a dict (any value may be None)."""
    stats = call(api.get_stats, d)
    total_cal, active_cal = _parse_calories(stats)
    hrv, balanced = _parse_hrv(call(api.get_hrv_data, d))
    sleep_hrs, sleep_score = _parse_sleep(call(api.get_sleep_data, d))

    bb_data = call(api.get_body_battery, d, d)
    bb_stream = []
    try:
        if isinstance(bb_data, list):
            for item in bb_data:
                for pair in (item.get('bodyBatteryValuesArray') or []):
                    if isinstance(pair, (list, tuple)) and len(pair) >= 2 and pair[1] is not None:
                        bb_stream.append([int(pair[0]), int(pair[1])])
    except Exception:
        bb_stream = []

    hr_raw = call(api.get_heart_rates, d)
    try:
        hr_stream = [[int(ts), int(bpm)] for ts, bpm in ((hr_raw or {}).get('heartRateValues') or []) if bpm is not None]
    except Exception:
        hr_stream = []

    return {
        'restingHR': _parse_rhr(stats), 'hrv': hrv, 'hrvBalanced': balanced,
        'sleepHours': sleep_hrs, 'sleepScore': sleep_score,
        'bodyBattery': _parse_body_battery(bb_data),
        'steps': _parse_steps(call(api.get_steps_data, d)),
        'stressScore': _parse_stress(call(api.get_stress_data, d)),
        'hrStream': json.dumps(hr_stream) if hr_stream else None,
        'bodyBatteryStream': json.dumps(bb_stream) if bb_stream else None,
        'totalCalories': total_cal, 'activeCalories': active_cal,
    }


def _day_has_data(m):
    return any(v is not None for k, v in m.items() if k != 'hrvBalanced')


def _save_day(db, d, m):
    """Upsert one day into GarminDaily; a value Garmin didn't return never blanks one already stored."""
    from services.calorie_adjust import apply as _kcal_apply
    total_cal, active_cal = m['totalCalories'], m['activeCalories']
    total_adj = int(round(_kcal_apply(total_cal))) if total_cal is not None else None     # global burn adjustment (raw kept alongside)
    active_adj = int(round(_kcal_apply(active_cal))) if active_cal is not None else None
    db.execute('''
        INSERT INTO GarminDaily (date, restingHR, hrv, hrvBalanced, sleepHours, sleepScore, bodyBattery, steps, stressScore, hrStream, bodyBatteryStream, totalCalories, activeCalories, totalCaloriesRaw, activeCaloriesRaw)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(date) DO UPDATE SET
            restingHR           = COALESCE(excluded.restingHR,          restingHR),
            hrv                 = COALESCE(excluded.hrv,                hrv),
            hrvBalanced         = excluded.hrvBalanced,
            sleepHours          = COALESCE(excluded.sleepHours,         sleepHours),
            sleepScore          = COALESCE(excluded.sleepScore,         sleepScore),
            bodyBattery         = COALESCE(excluded.bodyBattery,        bodyBattery),
            steps               = COALESCE(excluded.steps,              steps),
            stressScore         = COALESCE(excluded.stressScore,        stressScore),
            hrStream            = COALESCE(excluded.hrStream,           hrStream),
            bodyBatteryStream   = COALESCE(excluded.bodyBatteryStream,  bodyBatteryStream),
            totalCalories       = COALESCE(excluded.totalCalories,      totalCalories),
            activeCalories      = COALESCE(excluded.activeCalories,     activeCalories),
            totalCaloriesRaw    = COALESCE(excluded.totalCaloriesRaw,   totalCaloriesRaw),
            activeCaloriesRaw   = COALESCE(excluded.activeCaloriesRaw,  activeCaloriesRaw)
    ''', [d, m['restingHR'], m['hrv'], m['hrvBalanced'], m['sleepHours'], m['sleepScore'], m['bodyBattery'], m['steps'], m['stressScore'],
          m['hrStream'], m['bodyBatteryStream'], total_adj, active_adj, total_cal, active_cal])


def _push_weights():
    try:
        from services.mqtt import push_update_nutrition
        push_update_nutrition()   # the weight-trend sensors changed
    except Exception:
        log.warning('Home Assistant nutrition update after Garmin weigh-ins failed', exc_info=True)


def health_days(prev_upload, new_upload, last_sweep, now=None):
    """How many days (today back) the regular sync reads Garmin's daily metrics for: seven calls a day. The watch's data only reaches Garmin
    when it uploads (Settings.garminDeviceSync, the last upload a sync was done for), so with no upload since there is nothing new, and after one,
    the days since the one before. Once a day all HISTORY_RECENT, which also catches what that misses (a second device, Garmin's own late
    recalculation). Returns (days, is the daily sweep)."""
    from datetime import datetime, timezone
    now = now or datetime.now(timezone.utc)
    def when(v):
        try:
            t = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
            return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None
    sweep = when(last_sweep)
    if sweep is None or (now - sweep).total_seconds() >= 23.5 * 3600:      # a little under a day, so a 30 minute interval doesn't drift past it
        return HISTORY_RECENT, True
    new, prev = when(new_upload), when(prev_upload)
    if new is None:
        return 2, False                                  # couldn't tell: today and yesterday
    if prev is not None and new <= prev:
        return 0, False                                  # nothing uploaded since the last sync
    if prev is None:
        return HISTORY_RECENT, False
    return max(2, min(HISTORY_RECENT, (now.date() - prev.date()).days + 2)), False


def device_upload(api):
    """When the watch last uploaded to Garmin's cloud (ISO, UTC), or None."""
    from datetime import datetime, timezone
    try:
        up = api.get_device_last_used().get('lastUsedDeviceUploadTime')
        return datetime.fromtimestamp(up / 1000, tz=timezone.utc).isoformat(timespec='seconds') if up else None
    except Exception:
        return None


def sync_garmin(email, password, days=7, api=None, strict=False):
    """Fetch the last `days` days of Garmin daily metrics and upsert into GarminDaily. Weigh-ins (a scale uploads by itself, not through the
    watch) are read for at least the last two days. `api`: a client already logged in. `strict`: raise when Garmin answered none of the
    daily-metric calls (an outage), instead of passing it off as days with no data."""
    from database import get_db

    api = api or _client(email, password)
    db  = get_db()
    call = _Calls()

    today = date.today()
    for i in range(days):
        d = (today - timedelta(days=i)).isoformat()
        _save_day(db, d, _fetch_day(call, api, d))
    if strict and days and not call.ok:
        raise RuntimeError('Garmin answered none of the daily-metric calls')

    # Weigh-ins (Index scale or typed into Garmin Connect) feed the Nutrition weight trend
    weights = 0
    rider = db.execute('SELECT id FROM Rider WHERE isDefault=1 LIMIT 1').fetchone()
    if rider:
        try:
            _, weights = _sync_weigh_ins(api, db, rider['id'], (today - timedelta(days=max(days, 2) - 1)).isoformat(), today.isoformat())
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning('Garmin weigh-in sync failed: %s', e)

    db.commit()
    if weights:
        _push_weights()
    return days


# ── First-run health history ─────────────────────────────────────────────
# When Garmin is first connected the rider is asked how far back to pull health history (default: all of it).
# The regular sync covers the last HISTORY_RECENT days; backfill_history() walks back from there in windows of
# HISTORY_WINDOW days, saving its place after each one so a restart, a rate limit or an outage just resumes.

HISTORY_RECENT = 14
HISTORY_WINDOW = 28            # get_daily_steps answers up to 28 days in one request
HISTORY_FLOOR = date(2005, 1, 1)
HISTORY_EMPTY_STOP = 13        # 'all' stops after ~a year of windows with no steps and no weigh-ins
HISTORY_RETRY_MINS = 60        # wait after a rate limit or outage
HISTORY_WAKE = threading.Event()   # set to start the backfill thread now instead of at its next check
SYNC_WAKE = threading.Event()      # set to run the regular Garmin sync now instead of after its interval (the Tasks page's "Sync now")


def history_from(choice, today=None):
    """The first-run answer ('all', 'none' or a number of days back) as Settings.garminHistoryFrom."""
    if choice in ('all', 'none'):
        return choice
    days = int(choice)
    if days <= HISTORY_RECENT:
        return 'none'
    return ((today or date.today()) - timedelta(days=days)).isoformat()


def _days_with_steps(steps):
    """Dates get_daily_steps() shows any steps on, or None when the answer can't be read (then every day is fetched)."""
    if not isinstance(steps, list) or any(not isinstance(x, dict) or 'calendarDate' not in x for x in steps):
        return None
    return {x['calendarDate'][:10] for x in steps if (x.get('totalSteps') or 0) > 0}


def _history_status(db, **cols):
    sets = ', '.join(f'{k}=?' for k in cols)
    db.execute(f'UPDATE Settings SET {sets} WHERE id=1', list(cols.values()))
    db.commit()


def backfill_history(email, password, today=None, pause=0.5):
    """Pull older Garmin health history (daily metrics and weigh-ins) back to Settings.garminHistoryFrom, newest first.
    Days already stored are skipped, and only days get_daily_steps() shows activity on get the full set of calls.
    Returns the status line it saved, or None when there was nothing to do."""
    import logging
    from datetime import datetime, timezone
    from database import get_db

    log = logging.getLogger(__name__)
    db = get_db()
    s = db.execute('SELECT garminHistoryFrom, garminHistoryCursor, garminHistoryDone FROM Settings WHERE id=1').fetchone()
    if not s or not s['garminHistoryFrom'] or s['garminHistoryDone']:
        return None
    target = s['garminHistoryFrom']
    if target == 'none':
        msg = 'Only recent days are synced (no older history asked for).'
        _history_status(db, garminHistoryDone=1, garminHistoryStatus=msg)
        return msg

    today = today or date.today()
    floor = HISTORY_FLOOR if target == 'all' else max(date.fromisoformat(target), HISTORY_FLOOR)
    cursor = date.fromisoformat(s['garminHistoryCursor']) if s['garminHistoryCursor'] else today - timedelta(days=HISTORY_RECENT - 1)
    rider = db.execute('SELECT id FROM Rider WHERE isDefault=1 LIMIT 1').fetchone()
    call = _Calls(raise_rate_limit=True)
    empty_run, weights = 0, 0

    def retry_later(why):
        at = datetime.now(timezone.utc) + timedelta(minutes=HISTORY_RETRY_MINS)
        msg = f'{why} Carrying on from {cursor:%d %b %Y} at {at.astimezone():%H:%M}.'
        _history_status(db, garminHistoryRetryAt=at.isoformat(timespec='seconds'), garminHistoryStatus=msg)
        return msg

    try:
        api = _client(email, password)
        while cursor > floor:
            end = cursor - timedelta(days=1)
            start = max(end - timedelta(days=HISTORY_WINDOW - 1), floor)
            call.ok = 0
            found = 0
            active = _days_with_steps(call(api.get_daily_steps, start.isoformat(), end.isoformat()))
            if rider:
                w = call(_sync_weigh_ins, api, db, rider['id'], start.isoformat(), end.isoformat())
                if w is None and call.ok:           # Garmin answered, but not with the weigh-ins: don't move past this stretch, they'd never be asked for again
                    db.rollback()
                    return retry_later('Garmin did not send the weigh-ins.')
                if w:
                    found += w[0]
                    weights += w[1]
            have = {r[0] for r in db.execute('SELECT date FROM GarminDaily WHERE date BETWEEN ? AND ? AND (steps IS NOT NULL OR restingHR IS NOT NULL)',
                                             [start.isoformat(), end.isoformat()])}
            found += len(have)
            d = end
            while d >= start:
                ds = d.isoformat()
                if ds not in have and (active is None or ds in active):
                    m = _fetch_day(call, api, ds)
                    if _day_has_data(m):
                        _save_day(db, ds, m)
                        found += 1
                    if pause:
                        time.sleep(pause)
                d -= timedelta(days=1)
            if not call.ok:
                db.rollback()
                return retry_later('Garmin did not answer.')
            cursor = start
            empty_run = 0 if found else empty_run + 1
            _history_status(db, garminHistoryCursor=cursor.isoformat(), garminHistoryRetryAt=None,
                            garminHistoryStatus=f'Fetching health history — back to {cursor:%d %b %Y} so far.')
            if target == 'all' and empty_run >= HISTORY_EMPTY_STOP:
                break
    except Exception as e:
        db.rollback()
        if _is_rate_limit(e):
            return retry_later('Garmin asked Headwind to slow down.')
        log.warning('Garmin history backfill failed: %s', e)
        return retry_later('Could not reach Garmin.')
    finally:
        if weights:
            _push_weights()

    oldest = db.execute('SELECT MIN(date) FROM GarminDaily WHERE steps IS NOT NULL OR restingHR IS NOT NULL').fetchone()[0]
    msg = f'Health history complete — back to {date.fromisoformat(oldest):%d %b %Y}.' if oldest else 'Health history complete — Garmin had nothing older.'
    _history_status(db, garminHistoryDone=1, garminHistoryRetryAt=None, garminHistoryStatus=msg)
    return msg


WEIGHT_WINDOW = 365            # days of weigh-ins asked for in one request
WEIGHT_EMPTY_STOP = 3          # 'all': stop after this many years in a row with no weigh-ins


def backfill_weigh_ins(email, password, today=None):
    """Weigh-ins on their own, a year per request, back as far as the health-history choice (Settings.garminHistoryFrom) allows. The day-by-day history
    backfill also asks for them, but it used to move on past a stretch whose weigh-in request failed, so this pass (run once on every install,
    Settings.garminWeightsDone) fills in anything missed. Never overwrites a weight typed in Headwind or from Home Assistant. Stops and retries later
    on any failure. Returns the status line it saved, or None when there was nothing to do."""
    import logging
    from datetime import datetime, timezone
    from database import get_db
    db = get_db()
    s = db.execute('SELECT garminHistoryFrom, garminWeightsDone FROM Settings WHERE id=1').fetchone()
    rider = db.execute('SELECT id FROM Rider WHERE isDefault=1 LIMIT 1').fetchone()
    if not s or not s['garminHistoryFrom'] or s['garminWeightsDone'] or not rider:
        return None
    today = today or date.today()
    target = s['garminHistoryFrom']
    floor = (today - timedelta(days=HISTORY_RECENT - 1) if target == 'none'
             else HISTORY_FLOOR if target == 'all' else max(date.fromisoformat(target), HISTORY_FLOOR))
    end, empty, days, added = today, 0, 0, 0
    try:
        api = _client(email, password)
        while end >= floor and not (target == 'all' and empty >= WEIGHT_EMPTY_STOP):
            start = max(end - timedelta(days=WEIGHT_WINDOW - 1), floor)
            n, changed = _sync_weigh_ins(api, db, rider['id'], start.isoformat(), end.isoformat())
            db.commit()
            days, added = days + n, added + changed
            empty = 0 if n else empty + 1
            end = start - timedelta(days=1)
    except Exception as e:
        db.rollback()
        at = datetime.now(timezone.utc) + timedelta(minutes=HISTORY_RETRY_MINS)
        logging.getLogger(__name__).warning('Garmin weigh-in history failed: %s', e)
        msg = f'Weight history: {"Garmin asked Headwind to slow down" if _is_rate_limit(e) else "could not reach Garmin"}; trying again at {at.astimezone():%H:%M}.'
        _history_status(db, garminWeightsRetryAt=at.isoformat(timespec='seconds'), garminWeightsStatus=msg)
        return msg
    finally:
        if added:
            _push_weights()
    msg = (f'Weight history: {days} days with a weigh-in on Garmin, {added} added or updated here.' if days
           else 'Weight history: Garmin has no weigh-ins in that range.')
    _history_status(db, garminWeightsDone=1, garminWeightsRetryAt=None, garminWeightsStatus=msg)
    return msg


def save_laps(db, act_id, laps):
    """The file's laps and pool lengths (services/parser.fit_laps) on an activity that has none yet. Does not commit."""
    if laps:
        db.execute('UPDATE Activity SET laps=? WHERE id=? AND laps IS NULL', [laps, act_id])


def _save_workout(db, wid, rider_id, sport, name, start_utc, start_local, parsed, max_speed):
    """Store a Garmin activity that is not a ride (a workout), keeping the watch's calories (the walking/running estimate would be wrong for a swim).
    Does not commit."""
    from services.calorie_adjust import pair as _kcal_pair
    from services import workouts
    cal_raw, cal_adj = _kcal_pair(parsed.get('calories'))
    db.execute('''INSERT OR IGNORE INTO Activity (id, riderId, type, sportType, name, startDate, startDateLocal, distance, movingTime, elapsedTime, totalElevationGain,
                  averageSpeed, maxSpeed, averageHeartrate, calories, startLat, startLng, streams, source, caloriesRaw, rawData)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'{}')''',
               [wid, rider_id, sport, sport, (name or '').strip() or None, start_utc, start_local, parsed.get('distance') or 0, parsed.get('movingTime') or 0,
                parsed.get('elapsedTime') or 0, parsed.get('totalElevationGain') or 0, parsed.get('averageSpeed') or 0, max_speed,
                parsed.get('averageHeartrate'), cal_adj, parsed.get('startLat'), parsed.get('startLng'), parsed.get('streams'), 'garmin', cal_raw])
    save_laps(db, wid, parsed.get('laps'))
    workouts.refresh_derived(db, wid)                     # a run gets its best times and run-segment efforts
    from services import duplicates, gear
    dup = duplicates.resolve(db, wid)                     # the same session from Strava, a file or the phone: keep the better recording
    if dup:
        import logging
        logging.getLogger(__name__).warning('Garmin activity %s matched an existing recording; kept the better one', wid)
    gear.on_ride_added(db, (dup or {}).get('kept', wid))  # the rider's default shoes (or other kit) for the sport


def _from_summary(a):
    """An activity from what Garmin's activity list says about it, in parse_fit's shape: one typed into Garmin Connect has no file. No track."""
    dur = a.get('duration') or 0
    return {
        'distance': a.get('distance') or 0, 'movingTime': int(a.get('movingDuration') or dur), 'elapsedTime': int(a.get('elapsedDuration') or dur),
        'totalElevationGain': a.get('elevationGain') or 0, 'averageSpeed': a.get('averageSpeed') or 0, 'maxSpeed': a.get('maxSpeed') or 0,
        'averageHeartrate': a.get('averageHR'), 'averageWatts': a.get('avgPower'), 'averageCadence': None, 'calories': a.get('calories'),
        'startLat': a.get('startLatitude'), 'startLng': a.get('startLongitude'), 'streams': None, 'name': a.get('activityName'),
    }


def sync_garmin_activities(email, password, rider_id, api=None):
    """
    Generator: pull activities from Garmin Connect, download FIT files, parse and insert.
    Yields dicts: {'msg': str} | {'imported': int, 'skipped': int} | {'done': True, ...}
    Incremental — stores garminActivitySyncDate in Settings so repeated calls only fetch new rides.
    The whole first page (the newest `limit`, one call either way) is looked at whatever the cursor says, so an activity that reached Garmin
    late, after a newer one from another device moved the cursor on, still comes in; one already here is skipped without a download.
    Only imports rides that don't already exist (deduplicates by timestamp & distance). `api`: a client already logged in.
    """
    import logging
    from database import get_db
    from services.parser import parse_fit, parse_activity_file, _map_sport
    from services.weather import fetch_weather, save_weather

    log = logging.getLogger(__name__)

    api = api or _client(email, password)
    db  = get_db()

    s = db.execute('SELECT garminActivitySyncDate FROM Settings WHERE id=1').fetchone()
    since = s['garminActivitySyncDate'] if s and s['garminActivitySyncDate'] else None
    from services import garmin_failures
    since = garmin_failures.rewind(db, since)        # back to an activity given up on that a newer Headwind may read

    yield {'msg': 'Connected to Garmin Connect' + (f' — fetching rides since {since}' if since else ' — full history sync')}

    imported = 0
    skipped  = 0
    newest   = since  # newest date fully handled — the next incremental sync cursor
    first_failed = None  # earliest date with a download/parse/insert failure still being retried; cursor must not pass it

    def failed(activity_id, kind, error, start_date, name):
        """Remember the failure (services/garmin_failures); one still being retried holds the cursor back, one given up on counts as handled."""
        nonlocal first_failed, skipped, newest
        skipped += 1
        log.warning('Garmin activity %s %s failed: %s', activity_id, kind, error)
        if garmin_failures.record(db, activity_id, kind, error, start_date, name):
            if start_date and (newest is None or start_date > newest):
                newest = start_date
        elif start_date and (first_failed is None or start_date < first_failed):
            first_failed = start_date

    offset = 0
    limit  = 100
    done   = False

    while not done:
        older_page = False      # this page reached past the cursor: no need for the next
        try:
            activities = api.get_activities(start=offset, limit=limit)
        except Exception as e:
            yield {'error': f'Garmin API error: {e}'}
            return

        if not activities:
            break

        for a in activities:
            activity_id  = str(a.get('activityId', ''))
            type_key     = ((a.get('activityType') or {}).get('typeKey') or '').lower()
            start_local  = (a.get('startTimeLocal') or '')[:19].replace(' ', 'T')
            start_date   = start_local[:10]

            # A watch with an unset clock stamps rides with bogus dates (one landed in 1999) — never import those
            if start_date and start_date < '2005-01-01':
                skipped += 1
                continue

            # Stop once we're strictly older than the cursor (activities are newest-first), after the first page. The cursor day itself
            # is re-scanned so later same-day rides aren't missed; the activity-ID check below prevents re-imports.
            if since and start_date < since:
                if offset:
                    done = True
                    break
                older_page = True

            # Skip activities with no GPS (gym, yoga, strength, etc.)
            if type_key in _SKIP_TYPES:
                skipped += 1
                continue

            db_id = f'garmin_{activity_id}'
            # Check if Garmin ID already exists
            from services import duplicates
            if duplicates.exists_anywhere(db, db_id) or duplicates.is_deleted(db, db_id):      # live (any sport), parked, discarded or deleted by the user: never bring it back
                skipped += 1
                if start_date and (newest is None or start_date > newest):
                    newest = start_date
                continue

            # Same ride already here from another source? A phone/file copy is fine: we still fetch the Garmin one (it has the sensors) and
            # resolve() keeps the better recording afterwards. Only skip when Garmin itself already gave us this ride under another id.
            garmin_distance = a.get('distance') or 0
            probe = {'id': db_id, 'startDateLocal': start_local, 'startDate': (a.get('startTimeGMT') or start_local or '').replace(' ', 'T'),     # the real instant: start_local is wherever the ride was
                     'riderId': rider_id, 'distance': garmin_distance,
                     'elapsedTime': int(a.get('elapsedDuration') or a.get('duration') or 0), 'movingTime': int(a.get('movingDuration') or a.get('duration') or 0)}
            if any(str(t['id']).startswith('garmin_') for t in duplicates.find_duplicates(db, probe)):
                skipped += 1
                if start_date and (newest is None or start_date > newest):
                    newest = start_date
                continue

            # One that failed before: not until its next try (services/garmin_failures), and never again once given up on
            fail = garmin_failures.get(db, activity_id)
            if fail and not garmin_failures.due(fail):
                skipped += 1
                if fail['gaveUp']:
                    if start_date and (newest is None or start_date > newest):
                        newest = start_date
                elif start_date and (first_failed is None or start_date < first_failed):
                    first_failed = start_date
                continue
            label = a.get('activityName')

            if a.get('manualActivity'):
                # Typed into Garmin Connect: there is no file to download, only what the list says
                parsed = _from_summary(a)
            else:
                # Download the original upload (a zip: <id>_ACTIVITY.fit from a device, or the .gpx / .tcx someone uploaded)
                try:
                    zip_bytes = api.download_activity(activity_id, dl_fmt=api.ActivityDownloadFormat.ORIGINAL)
                    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                        names = zf.namelist()
                        file_name = next((n for n in names if n.lower().endswith('.fit')), None) \
                            or next((n for n in names if n.lower().rsplit('.', 1)[-1] in ('gpx', 'tcx')), None)
                        file_bytes = zf.read(file_name) if file_name else None
                except Exception as e:
                    failed(activity_id, 'download', e, start_date, label)
                    continue

                if file_name:
                    try:
                        parsed = parse_fit(file_bytes) if file_name.lower().endswith('.fit') else parse_activity_file(file_name, file_bytes)
                        err = None if parsed else 'no data in the file'
                    except Exception as e:
                        parsed, err = None, e
                    if not parsed:
                        failed(activity_id, 'parse', f'{file_name}: {err}', start_date, label)
                        continue
                else:
                    parsed = _from_summary(a)               # nothing in the zip to read: what the list says is all there is

            # Prefer API summary for name and sport; FIT has accurate streams
            sport_type  = garmin_sport(type_key) if type_key else _map_sport(parsed.get('sportType') or 'Ride')
            name        = a.get('activityName') or parsed.get('name') or 'Garmin Activity'
            start_utc   = (a.get('startTimeGMT') or start_local or '').replace(' ', 'T')

            # Sanity check: Garmin FIT files from very old devices may give distance in mm
            dist = parsed.get('distance') or 0
            if dist > 800_000:  # >800 km → probably mm
                dist /= 1000
                parsed['distance'] = dist

            # The parser's max ignores impossible spikes (a raw max of the speed stream let one GPS jump make a 137 mph mountain-bike ride)
            max_speed = parsed.get('maxSpeed') or 0.0

            from services.sports import is_ride
            if not is_ride(sport_type):                             # a run, walk, swim, ...: a workout, not a ride
                try:
                    _save_workout(db, db_id, rider_id, sport_type, a.get('activityName') or parsed.get('name'), start_utc, start_local, parsed, max_speed)
                except Exception as e:
                    failed(activity_id, 'insert', f'{sport_type}: {e}', start_date, label)
                    continue
                garmin_failures.clear(db, activity_id)
                imported += 1
                if start_date and (newest is None or start_date > newest):
                    newest = start_date
                continue

            try:
                from services.calorie_adjust import pair as _kcal_pair
                cal_raw, cal_adj = _kcal_pair(parsed.get('calories'))     # global burn adjustment, applied as the figure is pulled in
                db.execute('''
                    INSERT INTO Activity (
                        id, name, type, sportType,
                        startDate, startDateLocal,
                        distance, movingTime, elapsedTime, totalElevationGain,
                        averageSpeed, maxSpeed, averageHeartrate, averageWatts,
                        averageCadence, calories,
                        startLat, startLng, streams, rawData, riderId, caloriesRaw,
                        createdAt, updatedAt
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))
                    ON CONFLICT(id) DO NOTHING
                ''', [
                    db_id, name, sport_type, sport_type,
                    start_utc, start_local,
                    parsed.get('distance') or 0,
                    parsed.get('movingTime') or 0,
                    parsed.get('elapsedTime') or 0,
                    parsed.get('totalElevationGain') or 0,
                    parsed.get('averageSpeed') or 0,
                    max_speed,
                    parsed.get('averageHeartrate'),
                    parsed.get('averageWatts'),
                    parsed.get('averageCadence'),
                    cal_adj,
                    parsed.get('startLat'),
                    parsed.get('startLng'),
                    parsed.get('streams'),
                    '{}',
                    rider_id,
                    cal_raw,
                ])
            except Exception as e:
                failed(activity_id, 'insert', e, start_date, label)
                continue
            save_laps(db, db_id, parsed.get('laps'))
            garmin_failures.clear(db, activity_id)

            if parsed.get('startLat') and parsed.get('startLng') and start_local:
                try:
                    w = fetch_weather(parsed['startLat'], parsed['startLng'], start_local, parsed.get('streams'))
                    if w:
                        save_weather(db, db_id, w)
                except Exception:
                    log.warning('Weather for a Garmin activity failed', exc_info=True)

            try:
                dup = duplicates.resolve(db, db_id)
                if dup:
                    log.warning('Garmin activity %s matched an existing recording; kept the better one', activity_id)
                from services import gear
                gear.on_ride_added(db, (dup or {}).get('kept', db_id))
                from services.ingest import after_ride_added
                after_ride_added(db, (dup or {}).get('kept', db_id))
            except Exception as e:
                log.error('Duplicate resolution failed for %s: %s', db_id, e)
            imported += 1
            if start_date and (newest is None or start_date > newest):
                newest = start_date
            if imported % 20 == 0:
                db.commit()
                yield {'imported': imported, 'skipped': skipped}

        if not done and (len(activities) < limit or older_page):
            break
        offset += limit

    db.commit()

    # Never advance the cursor past a failed ride: step back a day from the earliest failure so it's retried
    if first_failed:
        from datetime import date, timedelta
        retry_from = (date.fromisoformat(first_failed) - timedelta(days=1)).isoformat()
        if newest is None or retry_from < newest:
            newest = retry_from if (since is None or retry_from > since) else since
        yield {'msg': f'Some rides failed to download — they will be retried on the next sync'}

    # Save newest date as next incremental cursor
    if newest:
        db.execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
        db.execute('UPDATE Settings SET garminActivitySyncDate=? WHERE id=1', [newest])
        db.commit()

    yield {'done': True, 'imported': imported, 'skipped': skipped}
