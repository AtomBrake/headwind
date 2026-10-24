"""The AI coach's analysis of each new ride as it's imported, when Settings.aiAutoAnalyse is on (the AI page). services/ingest.after_ride_added
queues the ride from inside the import's transaction; one background thread waits until the import has committed it, then analyses it with the
saved coach personality (services/ai.analyse_ride), one ride at a time.

Only new rides: a Strava export or Garmin's first sync brings in years of them, each a paid API call, so a ride that started more than RECENT_DAYS
ago is left for the AI page's batch analysis. Failures (no key, rate limit, provider down) are logged and kept on the Tasks page, and never retried:
the ride keeps its Analyse button. Never raises into the import."""
import logging
import queue
import threading
import time

log = logging.getLogger(__name__)

RECENT_DAYS = 3             # a ride that started longer ago than this is history, not a new ride
WAIT_COMMIT = 15 * 60       # seconds to wait for the import to commit a queued ride; after that it was rolled back
_POLL = 2                   # seconds between looks while the import still holds a ride uncommitted

_queue = queue.Queue()      # (app, ride id, when queued)
_pending = set()            # ride ids queued or being analysed: the ride page shows "Analysing…"
_lock = threading.Lock()
_started = False


def is_pending(act_id):
    with _lock:
        return str(act_id) in _pending


def _wanted(db, act_id):
    s = db.execute('SELECT aiAutoAnalyse FROM Settings WHERE id=1').fetchone()
    if not s or not s[0]:
        return False
    a = db.execute(f"SELECT sportType, aiKudos FROM Activity WHERE id=? AND date(startDateLocal) >= date('now', 'localtime', '-{RECENT_DAYS} days')",
                   [act_id]).fetchone()
    from services.sports import is_ride
    return bool(a) and is_ride(a['sportType']) and not a['aiKudos']      # the kept copy of a duplicate may have been analysed already


def queue_ride(db, act_id):
    """From inside an import's transaction: analyse this ride once the import has committed it, if it should be. Never raises; does not commit."""
    try:
        if not _wanted(db, act_id):
            return
        from flask import current_app
        app = current_app._get_current_object()
        with _lock:
            if str(act_id) in _pending:
                return
            _pending.add(str(act_id))
        _queue.put((app, str(act_id), time.monotonic()))
        log.info('Ride %s queued for AI analysis', act_id)
        _start()
    except Exception:
        log.warning('Queueing a new ride for AI analysis failed', exc_info=True)


def _start():
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_worker, name='auto-analyse', daemon=True).start()


def _worker():
    while True:
        item = _queue.get()
        try:
            if not _handle(item):
                _queue.put(item)                    # not committed yet: back of the queue, look again shortly
                time.sleep(_POLL)
        except Exception:
            log.exception('AI analysis of a new ride failed')
            _done(item[1])


def run_queued():
    """Analyse everything queued now, in this thread (for tests, where no background thread runs). Rides not committed yet are dropped."""
    while True:
        try:
            item = _queue.get_nowait()
        except queue.Empty:
            return
        if not _handle(item, wait=False):
            _done(item[1])


def _done(act_id):
    with _lock:
        _pending.discard(str(act_id))


def _handle(item, wait=True):
    """Analyse one queued ride. False when the import hasn't committed it yet (and may still)."""
    app, act_id, queued_at = item
    with app.app_context():
        from database import get_db
        db = get_db()
        activity = db.execute('SELECT * FROM Activity WHERE id=?', [act_id]).fetchone()
        if activity is None:
            if wait and time.monotonic() - queued_at < WAIT_COMMIT:
                return False
            log.warning('Ride %s was queued for AI analysis but never saved', act_id)
            _done(act_id)
            return True
        try:
            if not activity['aiKudos']:                 # not analysed from the ride page meanwhile
                _analyse(db, activity)
        finally:
            _done(act_id)
    return True


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
        from flask import current_app
        from services.notify import send_notification
        app_url = (current_app.config.get('APP_URL') or '').rstrip('/')
        send_notification(f'Ride analysed: {name}', text.strip().split('\n\n')[0][:400], f"{app_url}/rides/{activity['id']}" if app_url else None)
    except Exception:
        log.warning('Notification of a ride analysis failed', exc_info=True)
