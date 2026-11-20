"""Background work, queued in the database for the worker (services/worker.py) to run, so it runs once, outside the web server's process, and its
state is in a table every process reads rather than in one process's memory.

A page queues a job (enqueue) and returns; the worker claims it, runs its handler (registered with @handler) and records how it ended. A job
reports how far it has got with progress(), which the page polls. What a person reads about a run (the Tasks page) is still TaskLog
(services/tasks.py), which the handlers write as before.

Wake is a threading.Event-like flag kept in the database, so a page in one process can wake a loop in another: the Tasks page's "Sync now"
wakes the Garmin sync (services/garmin.SYNC_WAKE).

Tests and anything else without a worker run what's queued with run_queued()."""
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone

log = logging.getLogger(__name__)

HANDLERS = {}           # kind -> fn(job): runs inside an app context; job is the Job row as a dict, args parsed
QUICK = set()           # kinds a page waits for (wait): the worker runs them even when it already has MAX_AT_ONCE going
_database = None        # the database's path, for Wake outside an app context (bind)


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def ensure_schema(db):
    """Does not commit."""
    db.execute('''CREATE TABLE IF NOT EXISTS Job (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        kind       TEXT NOT NULL,               -- a key of HANDLERS
        args       TEXT NOT NULL DEFAULT '{}',  -- JSON
        state      TEXT NOT NULL,               -- queued | running | done | failed
        progress   TEXT,                        -- JSON the page polls, as the handler reports it
        error      TEXT,
        logId      TEXT,                        -- the log id of the request that queued it: the job's lines carry it too
        createdAt  TEXT NOT NULL,
        startedAt  TEXT,
        finishedAt TEXT
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_job_state ON Job(state, id)')
    # What a job says as it goes, in order, for a page following it (Events, routes/tasks.job_events): one row each, so a long run's thousandth
    # line doesn't rewrite the other 999
    db.execute('CREATE TABLE IF NOT EXISTS JobEvent (jobId INTEGER NOT NULL, n INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY (jobId, n))')
    db.execute('CREATE TABLE IF NOT EXISTS Wake (name TEXT PRIMARY KEY, at TEXT NOT NULL)')


def handler(kind, quick=False):
    """@jobs.handler('garmin_sports_check') def fn(job): ... — what the worker runs for a job of this kind. quick: a few seconds' work that a
    page waits for (wait), run however busy the worker is."""
    def register(fn):
        HANDLERS[kind] = fn
        if quick:
            QUICK.add(kind)
        return fn
    return register


def bind(app):
    """Remember the database for Wake, which loops use outside an app context."""
    global _database
    _database = app.config['DATABASE']


def active(db, kinds):
    """The queued or running job of any of these kinds, as a dict, or None."""
    kinds = [kinds] if isinstance(kinds, str) else list(kinds)
    r = db.execute(f"SELECT * FROM Job WHERE kind IN ({','.join('?' * len(kinds))}) AND state IN ('queued', 'running') ORDER BY id LIMIT 1",
                   kinds).fetchone()
    return _row(r)


def enqueue(db, kind, args=None, once=True, also=()):
    """Queue a job and return its id. once: not while a job of this kind, or of the kinds in also, is queued or running; then nothing is queued
    and None is returned (the page shows that one). Commits, unless called inside a transaction the caller commits, as an import does, so the
    job goes or stays with what it was queued for."""
    from services import logs
    if kind not in HANDLERS:
        raise ValueError(f'no handler for {kind}')
    if once and active(db, [kind, *also]):
        return None
    in_txn = db.in_transaction
    jid = db.execute("INSERT INTO Job (kind, args, state, logId, createdAt) VALUES (?, ?, 'queued', ?, ?)",
                     [kind, json.dumps(args or {}), logs.current_id(), now()]).lastrowid
    if not in_txn:
        db.commit()
    log.info('Queued %s (job %d)', kind, jid)
    return jid


def get(db, job_id):
    return _row(db.execute('SELECT * FROM Job WHERE id=?', [job_id]).fetchone())


def last(db, kind):
    return _row(db.execute('SELECT * FROM Job WHERE kind=? ORDER BY id DESC LIMIT 1', [kind]).fetchone())


def _row(r):
    if r is None:
        return None
    d = dict(r)
    d['args'] = json.loads(d['args'] or '{}')
    d['progress'] = json.loads(d['progress']) if d.get('progress') else None
    return d


def progress(db, job_id, **fields):
    """Merge fields into the job's progress, for the page that polls it. Commits."""
    cur = get(db, job_id)
    if cur is None:
        return
    db.execute('UPDATE Job SET progress=? WHERE id=?', [json.dumps({**(cur['progress'] or {}), **fields}), job_id])
    db.commit()


def claim(db, skip_kinds=(), only=None):
    """The oldest queued job not of these kinds (and of the kinds in only, when given), now running, as a dict; None when there is none.
    Commits."""
    skip = list(skip_kinds)
    where = f" AND kind NOT IN ({','.join('?' * len(skip))})" if skip else ''
    if only is not None:
        only = list(only)
        where += f" AND kind IN ({','.join('?' * len(only))})"
    db.commit()
    db.execute('BEGIN IMMEDIATE')
    r = db.execute(f"SELECT id FROM Job WHERE state='queued'{where} ORDER BY id LIMIT 1", skip + (only or [])).fetchone()
    if r:
        db.execute("UPDATE Job SET state='running', startedAt=? WHERE id=?", [now(), r[0]])
    db.commit()
    return get(db, r[0]) if r else None


def finish(db, job_id, error=None):
    db.execute('UPDATE Job SET state=?, error=?, finishedAt=? WHERE id=?', ['failed' if error else 'done', error, now(), job_id])
    db.commit()


def fail_orphans(db):
    """At the worker's start: a job still 'running' was cut short when the last one stopped. Failed, not run again: a half-done import or
    sync is put right by running it again from its page, as after any failure. Commits."""
    n = db.execute("UPDATE Job SET state='failed', error='stopped when Headwind restarted', finishedAt=? WHERE state='running'", [now()]).rowcount
    old = "SELECT id FROM Job WHERE finishedAt < strftime('%Y-%m-%dT%H:%M:%S', 'now', '-30 days')"
    db.execute(f'DELETE FROM JobEvent WHERE jobId IN ({old})')
    db.execute(f'DELETE FROM Job WHERE id IN ({old})')
    db.commit()
    return n


class Events:
    """What a job says as it goes (any JSON-able dicts), for the page following it (events()). Written through a connection of its own, so
    they never commit the job's own work halfway: while the job's own connection is in a transaction (it holds the write lock, so no other
    can write), or another holds the database, they wait in memory and go with the next, or at the end. with jobs.Events(job) as ev: ev.emit({...}).
    state=True: every event's fields merged into the job's progress as well, for a glance at how it's going without reading them all."""

    def __init__(self, job, state=False):
        self.job_id, self.n, self._waiting = job['id'], 0, []
        self.state = {} if state else None

    def emit(self, event):
        self._waiting.append(event)
        if self.state is not None:
            self.state.update(event)
        self._flush(0.2)

    def _flush(self, timeout):
        if not self._waiting or not _database:
            return
        from flask import g, has_app_context
        own = g.get('db') if has_app_context() else None
        if own is not None and own.in_transaction and timeout < 1:
            return
        try:
            conn = sqlite3.connect(_database, timeout=timeout)
            try:
                conn.executemany('INSERT INTO JobEvent (jobId, n, data) VALUES (?, ?, ?)',
                                 [(self.job_id, self.n + i, json.dumps(e)) for i, e in enumerate(self._waiting)])
                if self.state is not None:
                    conn.execute('UPDATE Job SET progress=? WHERE id=?', [json.dumps(self.state), self.job_id])
                conn.commit()
            finally:
                conn.close()
        except sqlite3.OperationalError:            # locked: they go with the next
            return
        self.n += len(self._waiting)
        self._waiting = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *exc):
        from flask import g
        db = g.get('db')
        if db is not None and db.in_transaction:   # the job's own work is over: settle it, so the last events aren't kept waiting behind it
            db.rollback() if exc_type else db.commit()
        self._flush(30)


def events(db, job_id, since=0):
    """The job's events from number `since` on, in order."""
    return [json.loads(r[0]) for r in db.execute('SELECT data FROM JobEvent WHERE jobId=? AND n>=? ORDER BY n', [job_id, since])]


def run(app, job):
    """Run one claimed job in this thread, with the log id of the request that queued it (else the TaskLog row's its handler starts), and record
    how it ended."""
    from database import get_db
    from services import logs
    token = logs.bind(job.get('logId'))
    try:
        with app.app_context():
            error = None
            try:
                HANDLERS[job['kind']](job)
            except Exception as e:
                log.exception('Job %s (%d) failed', job['kind'], job['id'])
                error = str(e)[:300] or e.__class__.__name__
            finish(get_db(), job['id'], error)
    finally:
        logs.reset(token)


def wait(db, job_id, timeout, poll=0.25):
    """For a page that needs a job's answer before it can reply: the job as a dict once it has ended, or None after timeout seconds. Its
    kind should be quick (handler), so a busy worker doesn't leave it queued."""
    end = time.monotonic() + timeout
    while True:
        job = get(db, job_id)
        if job and job['state'] in ('done', 'failed'):
            return job
        if time.monotonic() >= end:
            return None
        time.sleep(poll)


def run_queued(app):
    """Run every queued job now, in order, in this thread (tests; anything without a worker). Returns how many ran."""
    from database import get_db
    n = 0
    while True:
        with app.app_context():
            job = claim(get_db())
        if not job:
            return n
        run(app, job)
        n += 1


def beat(db):
    """The worker is alive (services/worker.py, every BEAT seconds). Commits."""
    db.execute("INSERT OR REPLACE INTO Wake (name, at) VALUES ('worker:alive', ?)", [now()])
    db.commit()


def worker_alive(db, within=120):
    """Whether the worker has said it's alive in the last `within` seconds."""
    r = db.execute("SELECT at FROM Wake WHERE name='worker:alive'").fetchone()
    if not r:
        return False
    return (datetime.now(timezone.utc) - datetime.fromisoformat(r[0])).total_seconds() < within


class Wake:
    """A flag in the database, set in one process and waited on in another, as threading.Event is within one."""

    POLL = 2            # seconds between looks while waiting

    def __init__(self, name):
        self.name = name

    def _conn(self):
        if not _database:
            return None
        conn = sqlite3.connect(_database, timeout=30)
        conn.execute('CREATE TABLE IF NOT EXISTS Wake (name TEXT PRIMARY KEY, at TEXT NOT NULL)')
        return conn

    def set(self):
        conn = self._conn()
        if conn is None:
            return
        try:
            conn.execute('INSERT OR REPLACE INTO Wake (name, at) VALUES (?, ?)', [self.name, now()])
            conn.commit()
        finally:
            conn.close()

    def is_set(self):
        conn = self._conn()
        if conn is None:
            return False
        try:
            return conn.execute('SELECT 1 FROM Wake WHERE name=?', [self.name]).fetchone() is not None
        finally:
            conn.close()

    def clear(self):
        """Never raises: the loops call it outside their own try, and one left set only wakes them once more."""
        try:
            conn = self._conn()
            if conn is None:
                return
            try:
                conn.execute('DELETE FROM Wake WHERE name=?', [self.name])
                conn.commit()
            finally:
                conn.close()
        except sqlite3.Error:
            log.warning('Wake %s: could not clear it (database busy); it wakes its loop once more', self.name, exc_info=True)

    def wait(self, timeout):
        """True as soon as it's set, False after timeout seconds."""
        end = time.monotonic() + timeout
        while True:
            try:
                if self.is_set():
                    return True
            except sqlite3.Error:
                log.debug('Wake %s: database busy', self.name, exc_info=True)
            left = end - time.monotonic()
            if left <= 0:
                return False
            time.sleep(min(self.POLL, left))
