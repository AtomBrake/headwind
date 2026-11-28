import logging
import os
import threading
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse
from flask import Flask, jsonify, redirect, request, session, url_for, render_template
from config import Config
from database import close_db, get_db, migrate_db

from services import logs

logs.setup()                    # stderr only until create_app knows where the database (and so the log folder) is
log = logging.getLogger(__name__)

# Scripts only from this server's files: the libraries are in static/vendor (scripts/vendor.py) and the pages' own scripts in
# static/js. Nothing inline runs: a page passes its data in <script type="application/json"> or data- attributes, and its handlers
# are data-click= and the rest (static/js/actions.js), not onclick=.
SCRIPT_SOURCES = ("'self'",)
CSP = "frame-ancestors 'none'; base-uri 'self'; object-src 'none'; script-src " + ' '.join(SCRIPT_SOURCES)


def _friends_autosync(app):
    import logging
    log = logging.getLogger('friends.autosync')
    time.sleep(30)  # let the app finish starting up
    while True:
        try:
            with app.app_context():
                from database import query_db
                s = query_db('SELECT friendSyncInterval FROM Settings WHERE id=1', one=True)
                interval = int(s['friendSyncInterval']) if s and s['friendSyncInterval'] is not None else 15
            if interval <= 0:
                time.sleep(300)
                continue
            time.sleep(interval * 60)
            with app.app_context():
                from database import get_db
                from services import features, jobs
                from services.rider_mode import owner_rider_id
                owner = owner_rider_id()                         # friends are the instance's until each user has their own (release G)
                if owner is not None and not features.on('friends', owner):
                    continue                                     # Friends turned off in Settings: no sync until it's back on
                jobs.enqueue(get_db(), 'friends_autosync')      # routes/friends._autosync_job; not while the last is still going
        except Exception as e:
            log.warning('Friends autosync loop error: %s', e)
            time.sleep(60)


def _track_summaries(app):
    """Once after start-up: the track summaries (services/tracks.py) of activities that have none, so the heatmap and the first new segment don't
    wait for them. After an upgrade that is every activity, reading each one's streams once; after that, only what arrived without one. Then,
    in the same thread so they never write at once, the km best efforts rides saved before there were any lack (services/best_efforts.fill_km)."""
    time.sleep(20)                              # let the app finish starting up
    try:
        with app.app_context():
            from database import get_db
            from services import tasks, tracks
            db = get_db()
            missing = db.execute('SELECT COUNT(*) FROM Activity a LEFT JOIN ActivityTrack t ON t.activityId = a.id '
                                 'WHERE t.activityId IS NULL').fetchone()[0]
            if missing:
                task_id = tasks.start(db, 'track_summaries', 'Map summaries of activities')
                tasks.progress(db, task_id, 0, missing)
                db.commit()
                n = tracks.fill(db, on_batch=lambda done, total: tasks.progress(db, task_id, done, total))
                tasks.finish(db, task_id, f"{n:,} activit{'y' if n == 1 else 'ies'} summarised for the heatmap and new segments")
    except Exception as e:
        log.warning('Track summaries: %s', e)
    try:                                        # then, once after the update that brought them, every ride's best efforts in km
        with app.app_context():
            from database import get_db
            from services import best_efforts, tasks
            db = get_db()
            if not db.execute('SELECT bestEffortsKmDone FROM Settings WHERE id=1').fetchone()[0]:
                task_id = tasks.start(db, 'best_efforts_km', 'Best efforts in kilometres')
                n = best_efforts.fill_km(db, on_batch=lambda done, total: tasks.progress(db, task_id, done, total))
                tasks.finish(db, task_id, f"Worked out for {n:,} ride{'' if n == 1 else 's'}: 5 to 160 km, shown when the units are metric")
    except Exception as e:
        log.warning('Best efforts in km: %s', e)


def _ensure_default_avatar(app):
    """New riders get custard_cream.svg as their picture. It ships in static/img and is copied into the avatar folder, which in
    Docker is the /data volume (the image replaces static/avatars with a link to it) and with AVATAR_DIR is the user's data
    folder: both start empty, so the picture was a broken image there."""
    import shutil
    av_dir = os.environ.get('AVATAR_DIR') or os.path.join(app.root_path, 'static', 'avatars')
    dest = os.path.join(av_dir, 'custard_cream.svg')
    try:
        if not os.path.exists(dest):
            os.makedirs(av_dir, exist_ok=True)
            shutil.copyfile(os.path.join(app.root_path, 'static', 'img', 'custard_cream.svg'), dest)
    except OSError as e:
        log.warning('Could not put the default rider picture in %s: %s', av_dir, e)


def _live_idle(app):
    """A live ride whose phone has gone quiet is marked idle in Home Assistant (services/live.go_idle), and the track of a live tracking link
    that has ended is deleted (services/live_share.sweep). Here, not in the process that took the phone's last reading, which may be any of the
    web processes."""
    from services import live, live_share
    while True:
        time.sleep(live.IDLE_CHECK_S)
        try:
            with app.app_context():
                from database import get_db
                live.go_idle(get_db())
                live_share.sweep(get_db())
        except Exception:
            log.warning('Checking for a live ride gone quiet failed', exc_info=True)


def _mqtt_heartbeat(app):
    time.sleep(10)  # let the app finish starting up
    tick = 0
    while True:
        tick += 1
        try:
            if tick % 12 == 1:                      # about hourly (and once at start-up): time-based parts (sealant, bar tape) can become due with no new ride
                with app.app_context():
                    from database import get_db
                    from services import gear
                    gear.evaluate_alerts(get_db())
                    get_db().commit()
        except Exception as e:
            log.warning('Gear alert sweep failed: %s', e)
        try:
            if tick % 12 == 1:                      # hourly too: what was deleted more than 30 days ago leaves Recently deleted, photo files and all
                with app.app_context():
                    from database import get_db
                    from services import recently_deleted, tasks
                    n = recently_deleted.purge(get_db(), app.config['DATABASE'])
                    if n:
                        tasks.record(get_db(), 'bin_purge', 'Recently deleted',
                                     f"{n} activit{'y' if n == 1 else 'ies'} deleted more than {recently_deleted.DAYS} days ago deleted for good")
                        get_db().commit()
        except Exception as e:
            log.warning('Emptying Recently deleted failed: %s', e)
        try:
            with app.app_context():
                from services.mqtt import push_update
                push_update(background=True)
                from services import live
                live.announce()                               # the live-ride entities exist from the start (idle), so the Live card can be shown before a first ride
                from services.homeassistant import import_rider, sync_if_due, sync_weather_if_due
                sync_if_due(import_rider())
                sync_weather_if_due()
                from services.goal_model import auto_update
                from services.rider_mode import owner_rider_id
                auto_update(owner_rider_id())                 # the nutrition goals are the owner's until each rider has their own (release A4)
        except Exception:
            log.warning('Home Assistant / goal sweep in the heartbeat failed', exc_info=True)
        time.sleep(300)  # MQTT safety net + Home Assistant import poll (HA honours its own interval)


def _garmin_heartbeat(app):
    """Pull Garmin health data (steps, sleep, HR…) on a fixed interval. A failure is logged, recorded (so Home
    Assistant can show 'Garmin sync failing') and retried within minutes rather than waiting a whole interval."""
    import logging
    time.sleep(60)  # let the app finish starting up
    while True:
        interval_hours = 0.5  # default 30 minutes
        ok, err = None, None
        try:
            with app.app_context():
                import json
                import logging
                from database import query_db, get_db
                log = logging.getLogger(__name__)
                from services.garmin import connected
                s = query_db('SELECT garminEmail, garminPassword, garminSyncHours, garminSyncMode, garminDeviceSync, garminSweepAt FROM Settings WHERE id=1', one=True)
                if connected(s):
                    interval_hours = s['garminSyncHours'] or 0.5
                    from services import tasks
                    from services.garmin import sync_garmin, sync_garmin_activities, fetch_ride_hr, _client, health_days, device_upload
                    from services.rider_mode import owner_rider_id
                    rider_id = owner_rider_id()     # the one Garmin account is the owner's until each user connects their own (release A7)
                    task_id = tasks.start(get_db(), 'garmin_sync', 'Garmin sync')
                    result = []
                    api, dev_sync, days, sweep = None, None, 0, False
                    try:
                        api = _client()      # one login for the whole run: each loads the profile and settings
                        # When did the watch itself last reach Garmin's cloud? (Headwind can only see what has been uploaded.) It decides how
                        # many days to read: none when nothing was uploaded since the last sync, all HISTORY_RECENT once a day.
                        dev_sync = device_upload(api)
                        days, sweep = health_days(s['garminDeviceSync'], dev_sync, s['garminSweepAt'])
                        read = sync_garmin(rider_id, days=days, api=api, strict=True)   # an outage must not count as read
                        if days and not read:                # Recovery, Steps and Nutrition all off (services/garmin.health_reads)
                            result.append('Health data not read: turned off in Settings')
                            dev_sync = None                  # not read, so not marked as read: switched on again, it's read then
                        else:
                            result.append(f"Health data synced ({days} day{'s' if days != 1 else ''})" if days else 'No new watch upload')
                        ok = True
                    except Exception as e:
                        ok, err = False, str(e)[:200]
                        log.warning('Garmin sync failed (will retry soon): %s', e)

                    if ok and s['garminSyncMode'] == 'full':
                        if rider_id is not None:
                            try:
                                final = {}
                                for final in sync_garmin_activities(rider_id, api=api):
                                    pass
                                if final.get('error'):
                                    result.append(f"activities failed: {final['error']}")
                                else:
                                    n = final.get('imported', 0)
                                    result.append(f"{n} new activit{'y' if n == 1 else 'ies'}" if n else 'no new activities')
                            except Exception as e:
                                log.warning('Garmin activity sync failed: %s', e)
                                result.append(f'activities failed: {str(e)[:120]}')
                            if sweep:                       # once a day: anything deleted or changed in Garmin since it was imported
                                from services import garmin_changes
                                try:
                                    with tasks.run(get_db(), garmin_changes.TASK, 'Garmin changes check') as t:
                                        t.result = garmin_changes.describe(garmin_changes.run(get_db(), api, rider_id))
                                except Exception:
                                    pass                    # logged as failed by tasks.run; tomorrow's sweep tries again
                    tasks.finish(get_db(), task_id, '; '.join(result) + '.' if ok else None, None if ok else err)

                    # Backfill HR for the rider's recent rides that landed without it (a plain GPX import has none). Only after a new upload
                    # (or in the daily sweep): with nothing uploaded, Garmin has no more heart rate than last time.
                    from services import streams as _streams
                    missing = query_db(f'''
                        SELECT a.id, a.startDate, a.elapsedTime, {_streams.sql('a')}
                        FROM Ride a
                        WHERE a.riderId = ?
                          AND a.averageHeartrate IS NULL
                          AND a.startDate IS NOT NULL
                          AND a.elapsedTime IS NOT NULL
                          AND a.startDate >= datetime('now', '-7 days')
                    ''', [rider_id]) if ok and days else []
                    if missing:
                        try:
                            garmin_api = api
                            db = get_db()
                            for act in missing:
                                try:
                                    streams = json.loads(act['streams']) if act['streams'] else {}
                                    time_stream = (streams.get('time') or {}).get('data')
                                    hr = fetch_ride_hr(garmin_api, act['startDate'], act['elapsedTime'], time_stream)
                                    if hr:
                                        streams['heartrate'] = {
                                            'type': 'heartrate',
                                            'data': hr['stream_data'],
                                            'series_type': 'time',
                                            'original_size': len(hr['stream_data']),
                                            'resolution': 'medium' if time_stream else 'low',
                                        }
                                        db.execute('UPDATE Activity SET averageHeartrate=?, maxHeartrate=? WHERE id=?',
                                                   [hr['avg'], hr['max'], act['id']])
                                        _streams.save(db, act['id'], streams)
                                        db.commit()
                                        log.info('Garmin HR backfill: enriched %s — avg=%s max=%s', act['id'], hr['avg'], hr['max'])
                                except Exception as hre:
                                    log.warning('Garmin HR backfill failed for %s: %s', act['id'], hre)
                        except Exception:
                            log.warning('Garmin HR backfill failed', exc_info=True)

                    # Record the outcome and tell HA straight away (last-sync time, fresh steps). The upload time only once a sync has read
                    # what came with it, so a failed one is read again next time.
                    db = get_db()
                    if ok:
                        from datetime import datetime, timezone
                        now = datetime.now(timezone.utc).isoformat(timespec='seconds')
                        if dev_sync:
                            db.execute('UPDATE Settings SET garminDeviceSync=? WHERE id=1', [dev_sync])
                        if sweep:
                            db.execute('UPDATE Settings SET garminSweepAt=? WHERE id=1', [now])
                        db.execute("UPDATE Settings SET garminLastOk=?, garminLastError=NULL, garminFailCount=0 WHERE id=1", [now])
                    else:
                        db.execute("UPDATE Settings SET garminLastError=?, garminFailCount=COALESCE(garminFailCount,0)+1 WHERE id=1", [err])
                    db.commit()
                    try:
                        from services.mqtt import push_update
                        push_update()
                    except Exception:
                        log.warning('Home Assistant update after the Garmin sync failed', exc_info=True)
                    if not ok:
                        fails = (query_db('SELECT garminFailCount c FROM Settings WHERE id=1', one=True) or {'c': 1})['c'] or 1
                        interval_hours = min(interval_hours, 0.17 * min(fails, 3))   # retry after 10, 20, then 30 minutes
        except Exception as e:
            logging.getLogger(__name__).warning('Garmin heartbeat error: %s', e)
        from services.garmin import SYNC_WAKE
        SYNC_WAKE.wait(interval_hours * 3600)       # or straight away when the Tasks page asks
        SYNC_WAKE.clear()


def _garmin_history(app):
    """The first-run Garmin health-history backfill. Picks up where it left off after a restart, a rate limit or an
    outage; answering the first-run question wakes it straight away (services.garmin.HISTORY_WAKE)."""
    from datetime import datetime, timezone
    from services import garmin
    garmin.HISTORY_WAKE.wait(90)  # let the app and the first regular sync start
    while True:
        garmin.HISTORY_WAKE.clear()
        try:
            with app.app_context():
                from database import query_db
                from services.rider_mode import owner_rider_id       # the Garmin account's rider: the owner's until release A7
                s = query_db('SELECT garminEmail, garminPassword, garminHistoryFrom, garminHistoryDone, garminHistoryRetryAt, '
                             'garminWeightsDone, garminWeightsRetryAt FROM Settings WHERE id=1', one=True)
                now = datetime.now(timezone.utc).isoformat(timespec='seconds')
                on = garmin.connected(s)
                daily, weigh_ins = garmin.health_reads(owner_rider_id())     # switched off: waits, and carries on once it's on again
                if (on and weigh_ins and s['garminHistoryFrom'] and not s['garminWeightsDone']
                        and (not s['garminWeightsRetryAt'] or s['garminWeightsRetryAt'] <= now)):
                    garmin.backfill_weigh_ins(owner_rider_id())      # quick (a year per call), so before the long day-by-day pass
                if (on and daily and s['garminHistoryFrom'] and not s['garminHistoryDone']
                        and (not s['garminHistoryRetryAt'] or s['garminHistoryRetryAt'] <= now)):
                    garmin.backfill_history(owner_rider_id())
        except Exception as e:
            log.warning('Garmin history backfill error: %s', e)
        garmin.HISTORY_WAKE.wait(600)


def create_app():
    app = Flask(__name__)
    from services import trusted_proxy
    app.wsgi_app = trusted_proxy.wrap(app.wsgi_app)   # X-Forwarded-* only from a trusted proxy
    app.config.from_object(Config)
    app.teardown_appcontext(close_db)
    logs.setup(app.config['DATABASE'])                # adds the log file beside the database
    logs.init_app(app)                                # request ids before any other before_request hook
    from version import __version__
    log.info('Headwind %s starting: log level %s, log file %s', __version__, logging.getLevelName(logs.level()),
             logs.file_path() or 'none')

    # Moves a plain saved password to its hash, and generates + logs the first-login password now (not lazily at first
    # sign-in) when none is configured
    from services import credentials
    credentials.admin_login()
    from services import limits
    limits.limit_images()                             # no uploaded picture over 50 megapixels is decoded

    with app.app_context():
        migrate_db()
        from services import vault
        vault.seal_plain(get_db())                    # keys and passwords saved before they were encrypted
        vault.seal_copies()                           # and in the copies of the database kept beside it (.pre-0.7.0, .pre-restore)
    _ensure_default_avatar(app)

    # ── Template filters ─────────────────────────────────────────
    from services import units as _units

    def _get_units():
        return _units.current()

    # Distances, climbs, speeds and paces in the rider's units (services/units.py). The *_val filters give the bare number, for charts and inputs.
    app.template_filter('fmt_dist')(lambda m, places=1: _units.fmt_dist(m, places=places))
    app.template_filter('fmt_elev')(lambda m: _units.fmt_elev(m))
    app.template_filter('fmt_speed')(lambda mps, places=1: _units.fmt_speed(mps, places=places))
    app.template_filter('fmt_pace')(lambda mps: _units.fmt_pace(mps))
    app.template_filter('fmt_swim_pace')(lambda mps: _units.fmt_swim_pace(mps))
    app.template_filter('pace_mi')(lambda mps: _units.fmt_pace(mps))       # old name, still used by a few templates
    from services import sports as _sports
    app.template_filter('has_climbing')(lambda sport: _sports.has_climbing(sport))       # no climb on the water: it's GPS noise
    app.template_filter('has_distance')(lambda sport: sport not in _sports.NO_DISTANCE)  # yoga, strength, HIIT: timed only
    app.template_filter('fmt_rate')(lambda mps, sport: _units.fmt_rate(mps, _sports.rate_style(sport)))   # speed, pace or per 100 m, by sport
    app.template_filter('fmt_temp')(lambda c: _units.fmt_temp(c))                   # weather: °C or °F (Settings.tempUnit)
    app.template_filter('fmt_wind')(lambda kph: _units.fmt_wind(kph))                # and the wind in mph or km/h, as the speeds are
    app.template_filter('wind_val')(lambda kph: round(_units.wind(kph)))
    app.template_filter('weather_text')(lambda text: _units.weather_text(text))
    app.template_filter('dist_val')(lambda m: _units.dist(m))
    app.template_filter('elev_val')(lambda m: _units.elev(m))
    app.template_filter('speed_val')(lambda mps: _units.speed(mps))

    @app.template_filter('fmt_duration')
    def fmt_duration(secs):
        secs = int(secs or 0)
        days, rem = divmod(secs, 86400)
        h, rem    = divmod(rem, 3600)
        m, s      = divmod(rem, 60)
        if days:
            return f'{days}d {h:02d}h {m:02d}m {s:02d}s'
        return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'

    @app.template_filter('fmt_hours')
    def fmt_hours(secs):
        """A long total: '312h 05m', or '45m' under an hour."""
        h, m = divmod(int(secs or 0) // 60, 60)
        return f'{h:,}h {m:02d}m' if h else f'{m}m'

    @app.template_filter('fmt_date')
    def fmt_date(val):
        try:
            from services.dates import day_month_year
            return day_month_year(datetime.fromisoformat(str(val)[:19]))
        except Exception:
            return str(val or '')

    @app.template_filter('fmt_when')
    def fmt_when(val):
        """A moment Headwind recorded itself (SQLite datetime('now'), UTC) at home time: '24 Oct 2026, 14:05'."""
        try:
            from datetime import timezone
            from services import tz
            from services.dates import day_month_year
            local = datetime.fromisoformat(str(val)[:19]).replace(tzinfo=timezone.utc).astimezone(tz.zone())
            return f'{day_month_year(local)}, {local:%H:%M}'
        except Exception:
            return str(val or '')

    @app.template_filter('weather_icon')
    def weather_icon(condition):
        from services.homeassistant import weather_icon as _wi
        return _wi(condition)

    @app.template_filter('sport_label')
    def sport_label(t):
        from services.sports import label
        return label(t)

    @app.template_filter('sport_icon')
    def sport_icon(t):
        return _sports.icon(t)

    @app.template_filter('wmo_label')
    def wmo_label(code):
        _labels = {
            0:'Clear sky', 1:'Mainly clear', 2:'Partly cloudy', 3:'Overcast',
            45:'Fog', 48:'Icy fog',
            51:'Light drizzle', 53:'Drizzle', 55:'Heavy drizzle',
            61:'Light rain', 63:'Rain', 65:'Heavy rain',
            71:'Light snow', 73:'Snow', 75:'Heavy snow', 77:'Snow grains',
            80:'Rain showers', 81:'Rain showers', 82:'Heavy showers',
            85:'Snow showers', 86:'Heavy snow showers',
            95:'Thunderstorm', 96:'Thunderstorm + hail', 99:'Thunderstorm',
        }
        try:
            return _labels.get(int(code), '')
        except (TypeError, ValueError):
            return ''

    # ── Blueprints ───────────────────────────────────────────────
    from routes.dashboard    import bp as dashboard_bp
    from routes.activities   import bp as activities_bp, old_rides as old_rides_bp
    from routes.settings     import bp as settings_bp
    from routes.sync         import bp as sync_bp
    from routes.kudos        import bp as kudos_bp
    from routes.import_rides import bp as import_bp
    from routes.data          import bp as data_bp
    from routes.mqtt_publish  import bp as mqtt_bp
    from routes.homeassistant import bp as homeassistant_bp
    from routes.login         import bp as login_bp
    from routes.segments      import bp as segments_bp
    from routes.riders        import bp as riders_bp
    from routes.heatmap       import bp as heatmap_bp
    from routes.ai_page       import bp as ai_bp
    from routes.garmin        import bp as garmin_bp
    from routes.garmin_page   import bp as garmin_page_bp
    from routes.about         import bp as about_bp
    from routes.setup         import bp as setup_bp
    from routes.friends       import bp as friends_bp
    from routes.nutrition      import bp as nutrition_bp
    from routes.route_builder  import bp as route_builder_bp
    from routes.saved_routes   import bp as saved_routes_bp

    # ── Auth guard ───────────────────────────────────────────────
    _PUBLIC = {'login.login_page', 'login.logout', 'static', 'demo.counter', 'demo.health',
               'friends.feed', 'friends.riders_list', 'import_rides.api_upload_ride',
               'friends.foods_feed', 'friends.food_image', 'avatar_files',
               'live_share.page', 'live_share.data'}       # a live tracking link, for whoever the rider sent it to

    # The phone app authenticates with a per-device Bearer token (services/device_auth.py) instead of a login session — accepted
    # only on the app's own API paths, never on the web pages.

    _BEARER_PATHS = ('/api/v1/', '/nutrition/api/')

    _WHOLE_UPLOADS = {'import_rides.upload', 'saved_routes.import_strava', 'settings.backup_import', 'setup.restore'}   # Strava export zips and backups: the app-wide 2 GB

    @app.before_request
    def limit_body():
        """Before the login check, so a request nobody signed in for can't be 2 GB: one too big for its endpoint is refused by its
        Content-Length, and one sent chunked (no Content-Length) stops at the limit as Werkzeug reads it (request.max_content_length)."""
        from services import limits
        ep = request.endpoint
        if ep in _WHOLE_UPLOADS:
            return None
        if request.path.startswith('/api/v1/') or ep == 'import_rides.api_upload_ride':
            limit = limits.MAX_PHONE_REQUEST
        elif ep in _PUBLIC or ep is None:
            limit = limits.MAX_PUBLIC_REQUEST
        else:
            limit = limits.MAX_PAGE_REQUEST
        request.max_content_length = limit
        if (request.content_length or 0) > limit:
            return jsonify(error='request too large'), 413
        return None

    from services import demo as _demo
    DEMO = _demo.enabled()
    if DEMO:
        _demo.block_private_networks()             # the web processes and the worker (it builds its app here too) reach nothing on the network around them
        _limiter = _demo.RateLimiter(limit=int(os.environ.get('DEMO_RATE_PER_MIN', '300')), window=60)

        @app.before_request
        def demo_guard():
            """Public demo: rate limit per client, refuse anything outside the allow-list (see services/demo.py)."""
            ep = request.endpoint
            if ep in ('static', 'avatar_files'):
                return None
            wait = _limiter.check(_demo.client_ip(request), cost=(4 if request.method in _demo.WRITE_METHODS else 1))
            if wait:
                resp = jsonify(error='Too many requests: slow down a little.')
                resp.status_code = 429
                resp.headers['Retry-After'] = str(wait)
                return resp
            why = _demo.decide(request.method, ep)
            if why:
                if request.path.startswith(('/api/', '/nutrition/api/', '/gear/api/')) or 'application/json' in (request.headers.get('Accept') or '') or request.is_json:
                    return jsonify(error=why, demo=True), 403
                return render_template('demo_blocked.html', why=why), 403
            return None

    @app.after_request
    def security_headers(resp):
        """On every response, not just the demo: no framing by other sites (clickjacking), no MIME sniffing, no full URLs
        leaking to other sites. The CSP (CSP above) runs only the scripts in this server's own files. HSTS only
        over HTTPS (directly or via a trusted proxy's X-Forwarded-Proto), so a plain-HTTP LAN install isn't locked out."""
        h = resp.headers
        h.setdefault('X-Frame-Options', 'DENY')
        h.setdefault('X-Content-Type-Options', 'nosniff')
        h.setdefault('Referrer-Policy', 'same-origin')
        h.setdefault('Content-Security-Policy', CSP)
        if request.is_secure:
            h.setdefault('Strict-Transport-Security', 'max-age=31536000')
        return resp

    from services import web_assets

    @app.url_defaults
    def static_version(endpoint, values):
        """?v=<hash> on every url_for('static', ...), so the file can be cached for a year (services/web_assets.py)."""
        if endpoint == 'static' and 'v' not in values and values.get('filename'):
            v = web_assets.static_version(app.static_folder, values['filename'])
            if v:
                values['v'] = v

    @app.after_request
    def cache_and_compress(resp):
        return web_assets.compress(web_assets.cache_static(resp), app.static_folder)

    riders_found = []      # once a rider exists there always is one (the owner can't be deleted): check_login stops asking

    @app.before_request
    def check_login():
        if request.endpoint in _PUBLIC or request.endpoint is None:
            return
        auth = request.headers.get('Authorization', '')
        if auth.startswith('Bearer ') and request.path.startswith(_BEARER_PATHS):
            from services import device_auth
            if device_auth.verify(auth[7:].strip()):
                return
            return jsonify(error='invalid or revoked token'), 401
        from services import credentials
        if session.get('logged_in') and session.get('av') != credentials.auth_version():
            if credentials.signed_in_before_hashing(session.get('av')):
                session['av'] = credentials.auth_version()   # same login, signed in before passwords were hashed
            else:
                session.clear()   # password/username changed since this session was issued
        if not session.get('logged_in'):
            if request.path.startswith('/api/v1/'):
                return jsonify(error='unauthorised'), 401
            return redirect(url_for('login.login_page'))
        # CSRF: a logged-in session must not be driven by another site. Browsers send Sec-Fetch-Site / Origin;
        # non-browser clients (curl, phone app with Bearer) send neither and are unaffected.
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if request.headers.get('Sec-Fetch-Site') == 'cross-site':
                return jsonify(error='cross-site request blocked'), 403
            origin = request.headers.get('Origin')
            if origin and origin != 'null' and urlparse(origin).netloc != request.host:
                return jsonify(error='cross-origin request blocked'), 403
        if not riders_found and request.endpoint not in ('setup.wizard', 'setup.restore', 'garmin.connect', 'garmin.connect_mfa',
                                                         'garmin.history', 'garmin.history_status'):
            from database import query_db
            if query_db('SELECT COUNT(*) FROM Rider', one=True)[0] == 0:
                return redirect('/setup')
            riders_found.append(True)

    @app.before_request
    def feature_gate():
        """After the login check: a feature switched off in Settings answers with its note or a JSON error (services/features.py)."""
        from services import features      # runs only once check_login has let the request through
        return features.gate()

    app.permanent_session_lifetime = timedelta(days=30)

    @app.context_processor
    def inject_units():
        return {'units': _get_units(), 'U': _units.spec(), 'TEMP': '°' + _units.temp_unit()}

    @app.context_processor
    def inject_appearance():
        from routes.settings import appearance
        return {'appearance': appearance()}

    @app.context_processor
    def inject_favourites():
        """The favourite sports' sidebar items (services/favourites.py)."""
        if not session.get('logged_in'):
            return {'favourite_sports': []}
        from services import favourites, page_facts
        try:
            row = page_facts.get() or get_db().execute('SELECT favouriteSports FROM Settings WHERE id=1').fetchone()
            return {'favourite_sports': favourites.sidebar(row['favouriteSports'] if row else None, request.endpoint, request.args)}
        except Exception:                                   # a database from before the column: nothing to show
            return {'favourite_sports': []}

    @app.context_processor
    def inject_task_notice():
        """How many start-up repairs ran that nobody has looked at yet (a notice on every page until the Tasks page is opened)."""
        if not session.get('logged_in') or request.endpoint == 'tasks.index':
            return {'startup_unseen': 0}
        try:
            from services import page_facts, tasks
            facts = page_facts.get()
            return {'startup_unseen': facts['startupUnseen'] if facts else tasks.unseen_startup(get_db())}
        except Exception:
            return {'startup_unseen': 0}

    @app.context_processor
    def inject_reimport_notice():
        """How many riders a release advises to import their Strava export again (services/strava_export.advice): a badge on Import."""
        if not session.get('logged_in'):
            return {'reimport_advised': 0}
        try:
            from services import page_facts, strava_export
            facts = page_facts.get()
            return {'reimport_advised': facts['reimportAdvised'] if facts else len(strava_export.advice(get_db(), app.config['DATABASE']))}
        except Exception:
            return {'reimport_advised': 0}

    @app.template_global()
    def map_keys():
        """The optional map keys for static/js/maps.js (templates/_maps.html), only on pages with a map."""
        from services import map_tiles
        return map_tiles.keys(get_db())

    @app.context_processor
    def inject_demo():
        return {'demo_mode': DEMO}

    @app.context_processor
    def inject_features():
        """feature('nutrition'): whether a switch in Settings → Features is on for the request's rider (services/features.py)."""
        from services import features
        return {'feature': features.Checker()}

    @app.context_processor
    def inject_rider_mode():
        from services.rider_mode import multi_rider, owner_rider_id
        return {'multi_rider': multi_rider(), 'owner_rider_id': owner_rider_id()}

    # Packaged/desktop installs keep photos in the user's data folder instead of the app folder (AVATAR_DIR); serve them at
    # the same /static/avatars/ URLs the templates already use.
    if os.environ.get('AVATAR_DIR'):
        from flask import send_from_directory

        @app.route('/static/avatars/<path:filename>')
        def avatar_files(filename):
            return send_from_directory(os.environ['AVATAR_DIR'], filename)

    from routes.gear import bp as gear_bp
    app.register_blueprint(gear_bp, url_prefix='/gear')
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(activities_bp, url_prefix='/activities')
    app.register_blueprint(old_rides_bp)
    app.register_blueprint(settings_bp, url_prefix='/settings')
    app.register_blueprint(sync_bp)
    app.register_blueprint(kudos_bp)
    app.register_blueprint(import_bp)
    app.register_blueprint(data_bp)
    app.register_blueprint(mqtt_bp)
    app.register_blueprint(homeassistant_bp)
    app.register_blueprint(login_bp)
    app.register_blueprint(segments_bp)
    app.register_blueprint(riders_bp)
    app.register_blueprint(heatmap_bp)
    from routes.roughness import bp as roughness_bp
    app.register_blueprint(roughness_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(garmin_bp)
    app.register_blueprint(garmin_page_bp)
    app.register_blueprint(about_bp)
    app.register_blueprint(setup_bp)
    app.register_blueprint(friends_bp)
    app.register_blueprint(nutrition_bp)
    app.register_blueprint(route_builder_bp)
    app.register_blueprint(saved_routes_bp)
    from routes.api_v1 import bp as api_v1_bp
    from routes.phones import bp as phones_bp
    app.register_blueprint(api_v1_bp)
    app.register_blueprint(phones_bp)
    from routes.tasks import bp as tasks_bp
    app.register_blueprint(tasks_bp)
    from routes.goals import bp as goals_bp
    app.register_blueprint(goals_bp)
    from routes.challenges import bp as challenges_bp
    app.register_blueprint(challenges_bp)
    from routes.matched import bp as matched_bp
    app.register_blueprint(matched_bp)
    from routes.live_share import bp as live_share_bp
    app.register_blueprint(live_share_bp)

    if DEMO:
        from routes.demo import bp as demo_bp
        app.register_blueprint(demo_bp)
    from services import jobs
    jobs.bind(app)                             # a page wakes the worker's loops through the database (jobs.Wake)
    from services import auto_analyse, backup, troubleshooting_copy  # noqa: F401  (services with job handlers, beside the routes': the worker runs what they queue)

    return app


def start_loops(app):
    """The timed background work, each in a thread: the track summaries once, then the Garmin and Home Assistant heartbeats, a live ride's
    idle check, the Garmin history, MQTT commands and the friends' automatic sync; in demo mode only its nightly reset. The worker starts them
    (services/worker.py), never the web server, so each runs once however many processes serve pages."""
    from services import demo as _demo
    threading.Thread(target=_track_summaries, args=(app,), daemon=True).start()
    if _demo.enabled():                        # no background threads that talk to the network; just the nightly reset
        threading.Thread(target=_demo.reset_loop, args=(app,), daemon=True).start()
        return
    threading.Thread(target=_mqtt_heartbeat,   args=(app,), daemon=True).start()
    threading.Thread(target=_live_idle,        args=(app,), daemon=True).start()
    threading.Thread(target=_garmin_heartbeat, args=(app,), daemon=True).start()
    threading.Thread(target=_garmin_history,   args=(app,), daemon=True).start()
    threading.Thread(target=__import__('services.mqtt_commands', fromlist=['run']).run, args=(app,), daemon=True).start()
    threading.Thread(target=_friends_autosync, args=(app,), daemon=True).start()


if __name__ == '__main__':
    # use_reloader=False → single process, no duplicate background threads
    debug = os.environ.get('HEADWIND_DEBUG') == '1'
    app = create_app()
    from services import worker
    worker.start_in_process(app)               # one process here: the background work runs in a thread of it
    if debug:   # the Werkzeug debugger runs code for anyone who reaches it, so it only listens on this machine
        log.warning('HEADWIND_DEBUG=1: debugger on, listening on 127.0.0.1 only. Never turn this on for a server others can reach.')
    app.run(debug=debug, use_reloader=False, load_dotenv=False,  # config.py loads the right env file; Flask would also pull in ./.env, leaking one instance's settings into another
            host='127.0.0.1' if debug else '0.0.0.0', port=int(os.environ.get('PORT', 5001)))
