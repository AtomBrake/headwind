"""What Headwind does in the background, for the Tasks page (routes/tasks.py). Jobs record their runs in TaskLog: the start-up repairs (one row each
time one changes something), the Garmin sync and friend sync (a row per run, 'running' until it finishes). The page combines that with the state
the jobs already keep in Settings (Garmin history and weigh-ins, the Garmin sync's last error) and in memory (an import, the MQTT link).

Each run is also written to the log, and its lines carry the run's log id (services/logs.py): the request's when a page started it, else t<row id>,
kept in TaskLog.logId so the Tasks page can point at them.

Never raises into the job it describes: a logging problem must not stop a sync."""
import logging
from contextlib import contextmanager
from datetime import datetime, timezone

from services import logs

log = logging.getLogger(__name__)
KEEP = 300          # rows kept; older ones are pruned


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS TaskLog (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        task       TEXT NOT NULL,               -- e.g. startup:utc_starts, garmin_sync, friend_sync
        label      TEXT NOT NULL,               -- what a person reads: "Start times of imported rides"
        startedAt  TEXT NOT NULL,
        finishedAt TEXT,
        status     TEXT NOT NULL,               -- running | done | failed
        result     TEXT,                        -- one line: what it did
        error      TEXT,
        seen       INTEGER DEFAULT 0            -- start-up repairs: shown in a notice until the Tasks page has been opened
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_tasklog_task ON TaskLog(task, id)')
    if 'logId' not in {r[1] for r in db.execute('PRAGMA table_info(TaskLog)')}:
        db.execute('ALTER TABLE TaskLog ADD COLUMN logId TEXT')      # the log id its lines carry


def _prune(db):
    db.execute('DELETE FROM TaskLog WHERE id <= (SELECT MAX(id) FROM TaskLog) - ?', [KEEP])


def record(db, task, label, result, status='done', error=None):
    """A finished job in one row (the start-up repairs, which run before anyone can look). Does not commit."""
    try:
        t = now()
        db.execute('INSERT INTO TaskLog (task, label, startedAt, finishedAt, status, result, error, logId) VALUES (?,?,?,?,?,?,?,?)',
                   [task, label, t, t, status, result, error, logs.current_id()])
        _prune(db)
        log.log(logging.WARNING if error else logging.INFO, '%s: %s', label, error or result)
    except Exception as e:
        log.warning('Task log write failed: %s', e)


class _Run:
    def __init__(self, db, row_id):
        self.db, self.id, self.result = db, row_id, None


@contextmanager
def run(db, task, label):
    """with tasks.run(db, 'garmin_sync', 'Garmin sync') as t: ...; t.result = 'what happened'. Shows as running while inside, then done, or failed with
    the exception's text (which is re-raised). Commits its own rows."""
    row_id = start(db, task, label)
    r = _Run(db, row_id)
    try:
        yield r
    except Exception as e:
        _finish(db, row_id, 'failed', r.result, str(e)[:300], exc_info=True)
        raise
    _finish(db, row_id, 'done', r.result, None)


def _finish(db, row_id, status, result, error, exc_info=False):
    if row_id is None:
        return
    try:
        db.execute('UPDATE TaskLog SET finishedAt=?, status=?, result=?, error=? WHERE id=?', [now(), status, result, error, row_id])
        db.commit()
        label = (db.execute('SELECT label FROM TaskLog WHERE id=?', [row_id]).fetchone() or ['Task'])[0]
        if error:
            log.warning('%s failed: %s', label, error, exc_info=exc_info)
        else:
            log.info('%s finished: %s', label, result or 'done')
    except Exception as e:
        log.warning('Task log write failed: %s', e)
    if logs.current_id() == f't{row_id}':      # the background thread's lines stop carrying this run's id
        logs.bind(None)


def start(db, task, label):
    """For a job that handles its own errors: a 'running' row now, finish() it later. Returns the row id (None if logging failed). Commits."""
    try:
        row_id = db.execute("INSERT INTO TaskLog (task, label, startedAt, status) VALUES (?,?,?,'running')", [task, label, now()]).lastrowid
        if not logs.current_id():               # a background thread: its lines carry t<row id> until finish()
            logs.bind(f't{row_id}')
        db.execute('UPDATE TaskLog SET logId=? WHERE id=?', [logs.current_id(), row_id])
        _prune(db)
        db.commit()
        log.info('%s started', label)
        return row_id
    except Exception as e:
        log.warning('Task log write failed: %s', e)
        return None


def finish(db, row_id, result=None, error=None):
    """Done, or failed when there is an error. Commits."""
    _finish(db, row_id, 'failed' if error else 'done', result, error)


def close_orphans(db):
    """At start-up: a row still 'running' belongs to a run the last shutdown cut short. Does not commit."""
    db.execute("UPDATE TaskLog SET status='failed', finishedAt=?, error='stopped when Headwind restarted' WHERE status='running'", [now()])


def last(db, task):
    r = db.execute('SELECT * FROM TaskLog WHERE task=? ORDER BY id DESC LIMIT 1', [task]).fetchone()
    return dict(r) if r else None


def unseen_startup(db):
    return db.execute("SELECT COUNT(*) FROM TaskLog WHERE task LIKE 'startup:%' AND seen=0").fetchone()[0]


def overview(db):
    """Everything the Tasks page shows: {'jobs': [card dicts], 'startup': [rows], 'history': [rows]}. A card: name, state (running | waiting | done |
    failed | off | idle), detail line, when, and the action it offers (None, or {'url', 'label'})."""
    s = db.execute('SELECT * FROM Settings WHERE id=1').fetchone()
    s = dict(s) if s else {}
    from services import garmin
    garmin_on = garmin.connected(s)
    jobs = []

    # Garmin sync (health data every interval; rides too in 'full' mode)
    g = last(db, 'garmin_sync')
    if not garmin_on:
        jobs.append(_card('Garmin sync', 'off', 'Garmin is not connected (Settings → Garmin Connect).'))
    elif s.get('garminSignInNeeded'):
        jobs.append(_card('Garmin sync', 'failed', garmin.SIGN_IN_AGAIN + ' Syncs carry on once you have.', s['garminSignInNeeded'],
                          {'url': '/settings#garmin', 'label': 'Sign in again'}))
    else:
        state = 'running' if g and g['status'] == 'running' else ('failed' if s.get('garminLastError') else ('done' if s.get('garminLastOk') else 'idle'))
        detail = (f"Failing ({s.get('garminFailCount') or 1} in a row): {s['garminLastError']}. Retrying within half an hour." if state == 'failed'
                  else (g or {}).get('result') or 'Health data' + (' and rides' if s.get('garminSyncMode') == 'full' else '') + f", every {_hours(s.get('garminSyncHours'))}.")
        jobs.append(_card('Garmin sync', state, detail, (g or {}).get('finishedAt') or s.get('garminLastOk'),
                          {'url': '/tasks/run/garmin', 'label': 'Sync now'} if state != 'running' else None))

        # Activities the Garmin sync gave up on (services/garmin_failures): skipped until an update or Try again
        from services import garmin_failures
        gone = garmin_failures.given_up(db)
        if gone:
            why = {'download': "wouldn't download", 'parse': "its file couldn't be read", 'insert': "couldn't be saved"}
            listed = '; '.join(f"{r['name'] or 'activity ' + r['activityId']} ({r['startDate'] or 'no date'}): {why.get(r['kind'], r['kind'])}"
                               for r in gone[:5])
            more = f' and {len(gone) - 5} more' if len(gone) > 5 else ''
            jobs.append(_card('Garmin activities not imported', 'failed',
                              f"{len(gone)} activit{'y' if len(gone) == 1 else 'ies'} the sync gave up on: {listed}{more}. "
                              'Each is tried once more after Headwind is updated.',
                              gone[0]['lastAt'], {'url': '/tasks/run/garmin-retry', 'label': 'Try again'}))

    # Garmin health history and weigh-ins (Settings columns kept by services/garmin.backfill_history / backfill_weigh_ins)
    for name, done, status, retry, key in (('Garmin health history', 'garminHistoryDone', 'garminHistoryStatus', 'garminHistoryRetryAt', 'history'),
                                           ('Garmin weight history', 'garminWeightsDone', 'garminWeightsStatus', 'garminWeightsRetryAt', 'weights')):
        if not garmin_on:
            continue
        if not s.get('garminHistoryFrom'):
            jobs.append(_card(name, 'idle', 'Waiting for you to choose how much history to fetch (Settings → Garmin Connect).'))
        elif s.get(done):
            jobs.append(_card(name, 'done', s.get(status) or 'Complete.'))
        elif s.get(retry) and s[retry] > now():
            jobs.append(_card(name, 'waiting', s.get(status) or 'Waiting to try again.', None, {'url': f'/tasks/run/{key}', 'label': 'Try now'}))
        else:
            jobs.append(_card(name, 'running', s.get(status) or 'Starting…'))

    # Friend sync
    friends = db.execute('SELECT name, lastSynced FROM Friend ORDER BY name').fetchall()
    if friends:
        f = last(db, 'friend_sync')
        every = s.get('friendSyncInterval') if s.get('friendSyncInterval') is not None else 15
        state = 'off' if every is not None and int(every) <= 0 else ((f or {}).get('status') or 'idle')
        detail = (f or {}).get('error') or (f or {}).get('result') or ', '.join(f"{r['name']}: {_ago(r['lastSynced'])}" for r in friends)
        jobs.append(_card('Friend sync', 'off' if state == 'off' else state, 'Automatic sync is off.' if state == 'off' else detail,
                          (f or {}).get('finishedAt'), {'url': '/friends', 'label': 'Friends'}))

    # Home Assistant / MQTT (state kept in memory by services/mqtt.py)
    if s.get('mqttHost'):
        try:
            from services import mqtt
            import time
            fails, retry_at = mqtt._fail_count, mqtt._next_retry
            if fails:
                wait = max(0, int(retry_at - time.time()))
                jobs.append(_card('Home Assistant (MQTT)', 'waiting' if wait else 'failed',
                                  f"Can't reach the MQTT broker ({fails} attempt{'s' if fails != 1 else ''})" + (f'; next try in {wait // 60 + 1} min.' if wait else '.')))
            else:
                jobs.append(_card('Home Assistant (MQTT)', 'done', 'Connected: sensors are published when anything changes, and every 5 minutes.'))
        except Exception:
            log.debug('MQTT card on the Tasks page failed', exc_info=True)

    # The activity type check started on the Activity types page (routes/garmin.py)
    c = last(db, 'sport_check')
    if c:
        jobs.append(_card('Activity type check', c['status'], c['error'] or c['result'] or 'Asking Garmin for the type of each Garmin ride…',
                          c['finishedAt'], {'url': '/garmin/sports', 'label': 'Open'}))

    # New rides analysed by the AI coach as they're imported (services/auto_analyse.py), when that's on
    if s.get('aiAutoAnalyse'):
        a = last(db, 'ai_analysis')
        jobs.append(_card('AI analysis of new rides', a['status'] if a else 'idle',
                          f"{a['label']}: {a['error'] or a['result'] or 'in progress…'}" if a else 'Waiting for a new ride.',
                          (a or {}).get('finishedAt'), {'url': '/ai', 'label': 'AI Coach'}))

    # An import started on the Import page
    try:
        from routes import import_rides
        job = import_rides._current_job
        if job is not None:
            st = dict(job.state)
            if not job.done:
                jobs.append(_card('Import', 'running', f"{st.get('done', 0)} / {st.get('total', '?')} files", None, {'url': '/import', 'label': 'Open'}))
            elif st.get('error'):
                jobs.append(_card('Import', 'failed', st['error'], None, {'url': '/import', 'label': 'Open'}))
            else:
                jobs.append(_card('Import', 'done', f"{st.get('imported', 0)} imported, {st.get('skipped', 0)} skipped, {st.get('errors', 0)} errors.", None,
                                  {'url': '/import', 'label': 'Open'}))
    except Exception:
        log.debug('Import card on the Tasks page failed', exc_info=True)

    startup = [dict(r) for r in db.execute("SELECT * FROM TaskLog WHERE task LIKE 'startup:%' ORDER BY id DESC LIMIT 30")]
    history = [dict(r) for r in db.execute("SELECT * FROM TaskLog WHERE task NOT LIKE 'startup:%' ORDER BY id DESC LIMIT 40")]
    return {'jobs': jobs, 'startup': startup, 'history': history}


def _card(name, state, detail, when=None, action=None):
    return {'name': name, 'state': state, 'detail': detail, 'when': when, 'action': action}


def _hours(h):
    h = float(h or 0.5)
    return f'{round(h * 60)} minutes' if h < 1 else f"{h:g} hour{'s' if h != 1 else ''}"


def _ago(iso):
    if not iso:
        return 'never'
    try:
        dt = datetime.fromisoformat(str(iso).replace('Z', '+00:00'))
        dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        mins = int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
    except ValueError:
        return str(iso)
    return 'just now' if mins < 1 else f'{mins} min ago' if mins < 60 else f'{mins // 60} h ago' if mins < 1440 else f'{mins // 1440} days ago'
