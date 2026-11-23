"""The AI coach's analysis of each new ride as it's imported, when Settings.aiAutoAnalyse is on (the AI page). services/ingest.after_ride_added
queues the ride as a job (services/jobs.py) from inside the import's transaction, so the job is there once the ride is, and never for a ride the
import rolled back. The worker analyses it with the saved coach personality (services/ai.analyse_ride), one ride at a time.

Only new rides: a Strava export or Garmin's first sync brings in years of them, each a paid API call, so a ride that started more than RECENT_DAYS
ago is left for the AI page's batch analysis. Failures (no key, rate limit, provider down) are logged and kept on the Tasks page, and never retried:
the ride keeps its Analyse button. Never raises into the import."""
import logging

from services import features, jobs
from services import streams as _streams

log = logging.getLogger(__name__)

RECENT_DAYS = 3             # a ride that started longer ago than this is history, not a new ride
KIND = 'ai_auto_analyse'


def is_pending(act_id, db=None):
    """Whether the ride is queued or being analysed: the ride page shows "Analysing…"."""
    if db is None:
        from database import get_db
        db = get_db()
    return db.execute(f"SELECT 1 FROM Job WHERE kind=? AND state IN ('queued', 'running') AND json_extract(args, '$.ride')=?",
                      [KIND, str(act_id)]).fetchone() is not None


def _wanted(db, act_id):
    s = db.execute('SELECT aiAutoAnalyse FROM Settings WHERE id=1').fetchone()
    if not s or not s[0]:
        return False
    a = db.execute(f"SELECT sportType, aiKudos, riderId FROM Activity WHERE id=? AND date(startDateLocal) >= date('now', 'localtime', '-{RECENT_DAYS} days')",
                   [act_id]).fetchone()
    from services.sports import is_ride
    if a and a['riderId'] is not None and not features.on('coach', a['riderId']):
        return False                                    # the AI coach turned off in Settings
    return bool(a) and is_ride(a['sportType']) and not a['aiKudos']      # the kept copy of a duplicate may have been analysed already


def queue_ride(db, act_id):
    """From inside an import's transaction: analyse this ride once the import has committed it, if it should be. Never raises; does not commit."""
    try:
        if not _wanted(db, act_id) or is_pending(act_id, db):
            return
        jobs.enqueue(db, KIND, {'ride': str(act_id)}, once=False)
        log.info('Ride %s queued for AI analysis', act_id)
    except Exception:
        log.warning('Queueing a new ride for AI analysis failed', exc_info=True)


@jobs.handler(KIND)
def _run(job):
    from database import get_db
    db = get_db()
    act_id = job['args']['ride']
    activity = db.execute(f'SELECT *, {_streams.sql()} FROM Activity WHERE id=?', [act_id]).fetchone()
    if activity is None:
        log.warning('Ride %s was queued for AI analysis but has gone since', act_id)
    elif activity['riderId'] is not None and not features.on('coach', activity['riderId']):
        log.info('Ride %s not analysed: the AI coach was turned off in Settings since it was queued', act_id)
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
        send_notification(f'Ride analysed: {name}', text.strip().split('\n\n')[0][:400], f"{app_url}/activities/{activity['id']}" if app_url else None)
    except Exception:
        log.warning('Notification of a ride analysis failed', exc_info=True)
