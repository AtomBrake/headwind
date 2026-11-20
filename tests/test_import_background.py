"""A web import is a job the background worker runs (routes/import_rides: services/jobs.py), so it keeps going when the browser leaves the page,
and the page, or any other, can follow it again. Throwaway database, the processing is faked; the tests run the queue as the worker would."""
import io
import time
import zipfile

from flask import Flask

import database
from routes import import_rides, tasks
from services import jobs


def _app(monkeypatch, n, tmp_path):
    def fake(zf, names, rider_id=None):
        yield import_rides._event({'total': n, 'source': 'files'})
        for i in range(n):
            yield import_rides._progress(i + 1, n, i + 1, 0, 0)
        yield import_rides._event({'complete': True, 'imported': n, 'skipped': 0, 'errors': 0})
    monkeypatch.setattr(import_rides, '_process_generic_zip', fake)
    app = Flask('t')
    app.config['DATABASE'] = str(tmp_path / 't.db')         # the upload is saved beside it for the worker (services/strava_export)
    app.teardown_appcontext(database.close_db)
    app.register_blueprint(import_rides.bp)
    app.register_blueprint(tasks.bp)                     # the pill's /tasks/background and the job's events
    with app.app_context():
        database.migrate_db()
    jobs.bind(app)
    return app


def _zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('a.gpx', '<gpx/>')
    buf.seek(0)
    return buf


def _upload(client):
    return client.post('/import/upload', data={'riderId': '1', 'zipfile': (_zip(), 'rides.zip')}).get_json()


def test_an_upload_is_queued_and_the_page_can_follow_it_again(monkeypatch, tmp_path):
    app = _app(monkeypatch, 300, tmp_path)
    client = app.test_client()
    job = _upload(client)['job']                       # the request only saves the file and queues it
    assert client.get('/import/status').get_json() == {'job': job}
    assert client.get('/import/progress').get_json() == {'running': True}
    assert jobs.run_queued(app) == 1                   # the worker's part

    assert client.get('/import/status').get_json() == {'job': job}           # finished while nobody watched: shown when the page is opened
    events = client.get(f'/tasks/job/{job}').get_json()['events']
    assert events[0] == {'total': 300, 'source': 'files'} and events[-1]['complete'] is True
    assert events[-2]['done'] == 300                   # the last count is always said
    assert len(events) < 10                            # but not each of the 300: at most one a second
    client.post('/import/progress/dismiss')            # the page that showed it says so
    assert client.get('/import/status').get_json() == {}


def test_status_is_empty_when_nothing_was_imported(monkeypatch, tmp_path):
    assert _app(monkeypatch, 1, tmp_path).test_client().get('/import/status').get_json() == {}


def test_progress_snapshot_for_the_indicator_until_dismissed(monkeypatch, tmp_path):
    app = _app(monkeypatch, 5, tmp_path)
    client = app.test_client()
    _upload(client)
    jobs.run_queued(app)

    d = client.get('/import/progress').get_json()
    assert d['running'] is False and d['complete'] is True and d['done'] == 5 and d['total'] == 5 and d['imported'] == 5
    assert client.get('/import/progress').get_json() == d           # stays until someone acknowledges it
    pill = client.get('/tasks/background').get_json()['items']      # the pill at the top of every page
    assert pill == [{'id': 'import', 'state': 'done', 'url': '/import', 'text': '✓ Import done · 5 imported', 'pct': None}]
    client.post('/tasks/background/dismiss', data={'id': 'import'})
    assert client.get('/import/progress').get_json() == {}
    assert client.get('/tasks/background').get_json()['items'] == []
    assert client.get('/import/status').get_json() == {}             # the import page won't show it again either


def test_progress_is_empty_when_nothing_was_imported(monkeypatch, tmp_path):
    assert _app(monkeypatch, 1, tmp_path).test_client().get('/import/progress').get_json() == {}


def test_one_import_at_a_time(monkeypatch, tmp_path):
    app = _app(monkeypatch, 1, tmp_path)
    client = app.test_client()
    _upload(client)
    assert _upload(client) == {'error': 'An import is already running'}
    assert len([n for n in __import__('os').listdir(tmp_path / 'strava_exports')]) == 1       # the second upload isn't left waiting
    jobs.run_queued(app)
    assert 'job' in _upload(client)


def test_an_import_cut_short_by_a_restart_says_so(monkeypatch, tmp_path):
    app = _app(monkeypatch, 1, tmp_path)
    client = app.test_client()
    _upload(client)
    with app.app_context():
        db = database.get_db()
        jobs.claim(db)                                 # the worker had started it
        jobs.fail_orphans(db)                          # and the next one, starting, finds it still running
    assert client.get('/import/progress').get_json() == {'error': 'stopped when Headwind restarted', 'running': False}
    [pill] = client.get('/tasks/background').get_json()['items']
    assert pill['state'] == 'failed' and 'restarted' in pill['text']
    assert 'job' in _upload(client)                    # and another can start


def test_events_wait_for_the_jobs_own_transaction_rather_than_for_a_lock(monkeypatch, tmp_path):
    """An import writes before it says how far it's got, and commits later: its events can't be written meanwhile (it holds the lock), so they
    wait in memory instead of each trying for 0.2 s."""
    app = _app(monkeypatch, 1, tmp_path)
    with app.app_context():
        db = database.get_db()
        job = jobs.get(db, jobs.enqueue(db, 'import', {}))
        with jobs.Events(job) as ev:
            db.execute("INSERT INTO Rider (id, name) VALUES (5, 'A')")       # the job's own write, not committed yet
            started = time.monotonic()
            for i in range(20):
                ev.emit({'done': i})
            assert time.monotonic() - started < 0.5
            assert jobs.events(database.get_db(), job['id']) == []           # not yet: they'd commit the import halfway
        assert [e['done'] for e in jobs.events(db, job['id'])] == list(range(20))
        assert db.execute('SELECT name FROM Rider WHERE id=5').fetchone()[0] == 'A'       # the job's work was committed first


def test_the_worker_starting_clears_uploads_a_restart_cut_short(monkeypatch, tmp_path):
    """A Strava export is gigabytes: not left a day beside the database once nothing will read it."""
    import os
    app = _app(monkeypatch, 1, tmp_path)
    client = app.test_client()
    _upload(client)
    with app.app_context():
        db = database.get_db()
        jobs.claim(db)
        jobs.fail_orphans(db)                          # cut short by a restart
    _upload(client)                                    # queued behind it, not read yet
    folder = tmp_path / 'strava_exports'
    for name in os.listdir(folder):
        os.utime(folder / name, (0, 0))                # both long since written
    arriving = folder / '.upload-arriving.zip'         # a browser still sending one
    arriving.write_bytes(b'PK')
    with app.app_context():
        import_rides.clear_uploads(database.get_db())
        waiting = database.get_db().execute("SELECT args FROM Job WHERE state='queued'").fetchone()[0]
    assert sorted(os.listdir(folder)) == sorted(['.upload-arriving.zip', os.path.basename(__import__('json').loads(waiting)['upload'])])
