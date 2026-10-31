"""A web import keeps going when the browser leaves the page, and the page can re-attach to it. No DB, the processing is faked."""
import io
import time
import zipfile

from flask import Flask

from routes import import_rides


def _app(monkeypatch, n, tmp_path):
    def fake(zf, names, rider_id=None):
        yield import_rides._event({'total': n, 'source': 'files'})
        for i in range(n):
            yield import_rides._progress(i + 1, n, i + 1, 0, 0)
        yield import_rides._event({'complete': True, 'imported': n, 'skipped': 0, 'errors': 0})
    monkeypatch.setattr(import_rides, '_process_generic_zip', fake)
    monkeypatch.setattr(import_rides, '_current_job', None)
    app = Flask('t')
    app.config['DATABASE'] = str(tmp_path / 't.db')         # a zip is saved beside it while it's imported (services/strava_export)
    app.register_blueprint(import_rides.bp)
    return app


def _zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('a.gpx', '<gpx/>')
    buf.seek(0)
    return buf


def test_import_finishes_after_the_browser_disconnects_and_can_be_reattached(monkeypatch, tmp_path):
    app = _app(monkeypatch, 300, tmp_path)             # well past the 200 events that used to fill the queue and stall the worker
    client = app.test_client()
    resp = client.post('/import/upload', data={'riderId': '1', 'zipfile': (_zip(), 'rides.zip')}, buffered=False)
    assert '"total": 300' in next(resp.response).decode()
    resp.close()                                       # the user browses away

    job = import_rides._current_job
    deadline = time.time() + 5
    while not job.done and time.time() < deadline:
        time.sleep(0.01)
    assert job.done

    body = client.get('/import/status').get_data(as_text=True)
    events = [e for e in body.split('\n\n') if e.startswith('data:')]
    assert '"total": 300' in events[0] and '"done": 300' in events[1] and '"complete": true' in events[2]
    assert len(events) == 3                            # caught up with only the latest progress

    assert client.get('/import/status').get_data(as_text=True) == ''   # the result is shown once


def test_status_is_empty_when_nothing_was_imported(monkeypatch, tmp_path):
    assert _app(monkeypatch, 1, tmp_path).test_client().get('/import/status').get_data(as_text=True) == ''


def test_progress_snapshot_for_the_indicator_until_dismissed(monkeypatch, tmp_path):
    app = _app(monkeypatch, 5, tmp_path)
    client = app.test_client()
    client.post('/import/upload', data={'riderId': '1', 'zipfile': (_zip(), 'rides.zip')}, buffered=False).close()
    job = import_rides._current_job
    deadline = time.time() + 5
    while not job.done and time.time() < deadline:
        time.sleep(0.01)

    d = client.get('/import/progress').get_json()
    assert d['running'] is False and d['complete'] is True and d['done'] == 5 and d['total'] == 5 and d['imported'] == 5
    assert client.get('/import/progress').get_json() == d           # stays until someone acknowledges it
    client.post('/import/progress/dismiss')
    assert client.get('/import/progress').get_json() == {}
    assert client.get('/import/status').get_data(as_text=True) == ''  # the import page won't show it again either


def test_progress_is_empty_when_nothing_was_imported(monkeypatch, tmp_path):
    assert _app(monkeypatch, 1, tmp_path).test_client().get('/import/progress').get_json() == {}
