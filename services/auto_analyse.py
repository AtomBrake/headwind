"""The AI coach's analysis of each new activity as it's imported, when Settings.aiAutoAnalyse is on (the AI page). services/ingest.after_ride_added
queues the activity as a job (services/jobs.py) from inside the import's transaction, so the job is there once the activity is, and never for one
the import rolled back. The worker analyses it with the saved coach personality (services/ai.analyse_ride), one at a time.

Only the sports picked on the AI page (Settings.aiAutoSports): a JSON list of keys as favourites have them, a group ('group:ride': every kind of
ride, one first recorded tomorrow too) or one sport ('sport:Run'). NULL is every sport. An install from before the choice keeps rides only
(database._step_14). An activity with neither a distance nor a moving time (an empty Apple Health workout) has nothing to coach.

Only new activities: a Strava export or Garmin's first sync brings in years of them, each a paid API call, so one that started more than
RECENT_DAYS ago is left for the AI page's batch analysis. Failures (no key, rate limit, provider down) are logged and kept on the Tasks page, and
never retried: the activity keeps its Analyse button. Never raises into the import."""
import json
import logging

from services import features, jobs, sports
from services import streams as _streams

log = logging.getLogger(__name__)

RECENT_DAYS = 3             # an activity that started longer ago than this is history, not a new one
KIND = 'ai_auto_analyse'


def chosen(raw):
    """Settings.aiAutoSports read: None for every sport, else the list of keys ('group:ride', 'sport:Run'), anything unreadable dropped."""
    from services.favourites import _split
    if raw is None or raw == '':
        return None
    try:
        keys = json.loads(raw)
    except ValueError:
        return None
    return [k for k in keys if isinstance(k, str) and _split(k)] if isinstance(keys, list) else None


def covers(keys, sport):
    """Whether keys (chosen) take in this sport. A group is a stat group (services/sports.stat_group); a sport is matched by its canonical name,
    a row with no sport as a ride."""
    if keys is None:
        return True
    sport = sports.canonical(sport or 'Ride')
    return f'group:{sports.stat_group(sport)}' in keys or f'sport:{sport}' in keys


def save_choice(db, every, keys):
    """Store the sports picked on the AI page: every=True for every sport (NULL), else the keys (anything that isn't one dropped). Does not commit."""
    from services.favourites import _split
    keys = [k for k in dict.fromkeys(keys or []) if _split(k)]
    db.execute('UPDATE Settings SET aiAutoSports=? WHERE id=1', [None if every else json.dumps(keys)])
    return None if every else keys


def is_pending(act_id, db=None):
    """Whether the activity is queued or being analysed: its page shows "Analysing…"."""
    if db is None:
        from database import get_db
        db = get_db()
    return db.execute(f"SELECT 1 FROM Job WHERE kind=? AND state IN ('queued', 'running') AND json_extract(args, '$.ride')=?",
                      [KIND, str(act_id)]).fetchone() is not None


def _wanted(db, act_id):
    s = db.execute('SELECT aiAutoAnalyse, aiAutoSports FROM Settings WHERE id=1').fetchone()
    if not s or not s[0]:
        return False
    a = db.execute(f"SELECT sportType, aiKudos, riderId, distance, movingTime FROM Activity WHERE id=? "
                   f"AND date(startDateLocal) >= date('now', 'localtime', '-{RECENT_DAYS} days')", [act_id]).fetchone()
    if not a or a['aiKudos']:                           # the kept copy of a duplicate may have been analysed already
        return False
    if a['riderId'] is not None and not features.on('coach', a['riderId']):
        return False                                    # the AI coach turned off in Settings
    if not (a['distance'] or 0) and not (a['movingTime'] or 0):
        return False                                    # nothing recorded to coach
    return covers(chosen(s[1]), a['sportType'])


def queue_ride(db, act_id):
    """From inside an import's transaction: analyse this activity once the import has committed it, if it should be. Never raises; does not commit."""
    try:
        if not _wanted(db, act_id) or is_pending(act_id, db):
            return
        jobs.enqueue(db, KIND, {'ride': str(act_id)}, once=False)
        log.info('Activity %s queued for AI analysis', act_id)
    except Exception:
        log.warning('Queueing a new activity for AI analysis failed', exc_info=True)


@jobs.handler(KIND)
def _run(job):
    from database import get_db
    db = get_db()
    act_id = job['args']['ride']
    activity = db.execute(f'SELECT *, {_streams.sql()} FROM Activity WHERE id=?', [act_id]).fetchone()
    if activity is None:
        log.warning('Activity %s was queued for AI analysis but has gone since', act_id)
    elif activity['riderId'] is not None and not features.on('coach', activity['riderId']):
        log.info('Activity %s not analysed: the AI coach was turned off in Settings since it was queued', act_id)
    elif not activity['aiKudos']:                       # not analysed from the ride page meanwhile
        _analyse(db, activity)


def _analyse(db, activity):
    from services import tasks
    from services.ai import analyse_ride
    name = activity['name'] or activity['id']
    try:
        with tasks.run(db, 'ai_analysis', f'AI analysis of "{name}"') as t:
            text = analyse_ride(db, activity)
            t.result = 'Analysed as it was imported.'
    except Exception:
        return                                          # logged and kept on the Tasks page by tasks.run
    try:
        from services import external_url
        from services.notify import send_notification
        app_url = external_url.get()
        send_notification(f'{sports.label(activity["sportType"])} analysed: {name}', text.strip().split('\n\n')[0][:400], f"{app_url}/activities/{activity['id']}" if app_url else None)
    except Exception:
        log.warning('Notification of a ride analysis failed', exc_info=True)
