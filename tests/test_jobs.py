"""Background work queued in the database (services/jobs.py) and run by the worker (services/worker.py): a job runs once, even with two workers
taking from the queue; one queued inside a transaction that's rolled back never runs; a restart leaves a running job failed, never running for
ever; Wake carries a flag from one process to another."""
import threading
import time

import pytest
from flask import Flask

import database
from services import jobs, worker

ran = []


@jobs.handler('test_append')
def _append(job):
    time.sleep(job['args'].get('sleep', 0))
    ran.append(job['args']['n'])


@jobs.handler('test_fail')
def _fail(job):
    raise RuntimeError('it broke')


@jobs.handler('test_quick', quick=True)
def _quick(job):
    jobs.progress(database.get_db(), job['id'], result=job['args']['n'] * 2)


@pytest.fixture
def app(tmp_path):
    a = Flask(__name__)
    a.config['DATABASE'] = str(tmp_path / 't.db')
    a.teardown_appcontext(database.close_db)
    with a.app_context():
        database.migrate_db()
    jobs.bind(a)
    ran.clear()
    return a


def test_a_job_runs_once_and_says_how_it_ended(app):
    with app.app_context():
        db = database.get_db()
        first = jobs.enqueue(db, 'test_append', {'n': 1})
        assert jobs.enqueue(db, 'test_append', {'n': 2}) is None                  # one of a kind at a time
        assert jobs.enqueue(db, 'test_append', {'n': 3}, once=False)
        bad = jobs.enqueue(db, 'test_fail')
    assert jobs.run_queued(app) == 3 and ran == [1, 3]
    with app.app_context():
        db = database.get_db()
        assert jobs.get(db, first)['state'] == 'done'
        assert (jobs.get(db, bad)['state'], jobs.get(db, bad)['error']) == ('failed', 'it broke')
        with pytest.raises(ValueError):
            jobs.enqueue(db, 'no_such_kind')


def test_also_keeps_two_kinds_apart(app):
    with app.app_context():
        db = database.get_db()
        assert jobs.enqueue(db, 'test_append', {'n': 1})
        assert jobs.enqueue(db, 'test_fail', also=('test_append',)) is None


def test_one_queued_in_a_transaction_that_is_rolled_back_never_runs(app):
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT INTO Rider (name) VALUES ('x')")                       # an import's transaction
        jobs.enqueue(db, 'test_append', {'n': 1})
        db.rollback()
    assert jobs.run_queued(app) == 0


def test_a_busy_worker_still_runs_what_a_page_waits_for(app):
    """At MAX_AT_ONCE the worker claims only quick jobs (a Garmin sign-in), which a page waits for with wait()."""
    with app.app_context():
        db = database.get_db()
        jobs.enqueue(db, 'test_append', {'n': 1})
        quick = jobs.enqueue(db, 'test_quick', {'n': 21})
        assert jobs.claim(db, only=jobs.QUICK)['id'] == quick                       # the older, slow one waits
        assert jobs.claim(db, skip_kinds=['test_append'], only=jobs.QUICK) is None
        jobs.finish(db, quick)
        assert jobs.wait(db, quick, 1)['state'] == 'done'
        slow = db.execute("SELECT id FROM Job WHERE kind='test_append'").fetchone()[0]
        start = time.monotonic()
        assert jobs.wait(db, slow, 0.3, poll=0.05) is None and time.monotonic() - start >= 0.3


def test_wait_gives_the_job_once_the_worker_has_run_it(app):
    with app.app_context():
        jid = jobs.enqueue(database.get_db(), 'test_quick', {'n': 21})
    t = threading.Thread(target=lambda: (time.sleep(0.2), jobs.run_queued(app)))
    t.start()
    with app.app_context():
        job = jobs.wait(database.get_db(), jid, 5, poll=0.05)
    t.join()
    assert job['state'] == 'done' and job['progress'] == {'result': 42}


def test_progress_is_kept_for_the_page(app):
    with app.app_context():
        db = database.get_db()
        jid = jobs.enqueue(db, 'test_append', {'n': 1})
        jobs.progress(db, jid, done=3)
        jobs.progress(db, jid, total=10)
        assert jobs.get(db, jid)['progress'] == {'done': 3, 'total': 10}


def test_a_restart_leaves_a_running_job_failed(app):
    with app.app_context():
        db = database.get_db()
        jid = jobs.enqueue(db, 'test_append', {'n': 1})
        jobs.claim(db)
        assert jobs.fail_orphans(db) == 1
        assert (jobs.get(db, jid)['state'], jobs.get(db, jid)['error']) == ('failed', 'stopped when Headwind restarted')


def test_wake_crosses_connections(app):
    w = jobs.Wake('test')
    w.clear()
    assert not w.wait(0.1)
    threading.Timer(0.2, w.set).start()
    t = time.monotonic()
    assert w.wait(10) and time.monotonic() - t < 5
    w.clear()
    assert not w.is_set()


def test_two_workers_run_each_job_once(app, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, 'start_loops', lambda a: None)
    monkeypatch.setattr(worker, '_IDLE', 0.05)
    with app.app_context():
        db = database.get_db()
        for n in range(20):
            jobs.enqueue(db, 'test_append', {'n': n, 'sleep': 0.01}, once=False)
    stop = threading.Event()
    workers = [threading.Thread(target=worker.serve, args=(app, stop), daemon=True) for _ in range(2)]
    for w in workers:
        w.start()
    # Wait for the jobs to be marked done, not for ran: a job's thread appends to ran and then records it done (jobs.finish), and serve
    # doesn't wait for its job threads when stopped, so a slow runner could still be writing the last one when the count is read.
    deadline = time.monotonic() + 30
    with app.app_context():
        db = database.get_db()
        while time.monotonic() < deadline:
            if db.execute("SELECT COUNT(*) FROM Job WHERE state='done'").fetchone()[0] == 20:
                break
            time.sleep(0.05)
    stop.set()
    for w in workers:
        w.join(5)
    assert sorted(ran) == list(range(20))
    with app.app_context():
        db = database.get_db()
        assert db.execute("SELECT COUNT(*) FROM Job WHERE state='done'").fetchone()[0] == 20
        assert jobs.worker_alive(db)


@jobs.handler('test_events_while_writing')
def _events_while_writing(job):
    db = database.get_db()
    with jobs.Events(job) as ev:
        db.execute("INSERT INTO Rider (name) VALUES ('mid-write')")       # the job holds the database...
        ev.emit({'n': 1})                                                  # ...so this waits in memory, rather than block or commit
        assert db.in_transaction
        ev.emit({'n': 2})


def test_events_wait_while_the_job_holds_the_database(app):
    with app.app_context():
        jid = jobs.enqueue(database.get_db(), 'test_events_while_writing')
    jobs.run_queued(app)
    with app.app_context():
        db = database.get_db()
        assert jobs.get(db, jid)['state'] == 'done'
        assert jobs.events(db, jid) == [{'n': 1}, {'n': 2}] and jobs.events(db, jid, 1) == [{'n': 2}]
        assert db.execute("SELECT 1 FROM Rider WHERE name='mid-write'").fetchone()        # the job's own write was kept


def test_the_garmin_activity_sync_runs_as_a_job(tmp_path, monkeypatch):
    import app as app_module
    import config
    from services import credentials, garmin
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'g.db'))
    monkeypatch.setattr(garmin, 'signed_in', lambda: True)
    app = app_module.create_app()
    with app.app_context():
        d = database.get_db()
        d.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        d.execute("UPDATE Settings SET garminSyncMode='full', garminEmail='a@b.c' WHERE id=1")
        d.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        d.commit()
        av = credentials.auth_version()

    def sync(rider_id, api=None):
        yield {'msg': 'Fetching the list'}
        yield {'imported': 1, 'skipped': 0}
        yield {'done': True, 'imported': 1, 'skipped': 0}
    monkeypatch.setattr(garmin, 'sync_garmin_activities', sync)
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'], s['av'] = True, av
    job = c.post('/garmin/sync-activities').get_json()['job']
    assert c.get('/garmin/sync-activities').status_code == 405                    # no GET starts work
    assert c.get(f'/tasks/job/{job}').get_json()['state'] == 'queued'
    jobs.run_queued(app)
    d = c.get(f'/tasks/job/{job}').get_json()
    assert d['state'] == 'done' and d['events'] == [{'msg': 'Fetching the list'}, {'imported': 1, 'skipped': 0},
                                                    {'done': True, 'imported': 1, 'skipped': 0}]
    assert c.get('/tasks/job/999').status_code == 404
