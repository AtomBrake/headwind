"""A Strava export is kept after it's imported (services/strava_export.py), so it can be imported again without uploading it. Full app, throwaway
DB; the import's background thread runs straight through."""
import io
import os
import threading
import zipfile

import pytest

import app as app_module
import config
import database
from services import credentials, strava_export

GPX = ('<?xml version="1.0"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>Tour</name><trkseg>'
       + ''.join(f'<trkpt lat="{50.4 + i * 0.0001:.5f}" lon="-4.7"><ele>50</ele><time>2026-07-04T09:{i // 60:02d}:{i % 60:02d}Z</time></trkpt>'
                 for i in range(0, 600, 10))
       + '</trkseg></trk></gpx>')
CSV_HEAD = 'Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Moving Time,Elapsed Time,Distance,Filename\n'
ROW = '101,"Jul 4, 2026, 9:00:00 AM",Tour,Ride,600,0.66,590,600,660,activities/101.gpx\n'
MANUAL = '102,"Jul 5, 2026, 9:00:00 AM",Typed in,Ride,3600,20.0,3600,3600,20000,\n'


class _Thread:
    """The import's worker runs on start(), before the response streams; the app's own background threads don't run at all."""
    def __init__(self, *a, target=None, **kw):
        self.target = target
    def start(self):
        if self.target and self.target.__qualname__.startswith('_start.'):
            self.target()


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(threading, 'Thread', _Thread)
    a = app_module.create_app()
    with a.app_context():
        db = database.get_db()
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (2, 'Sam', 0)")
        db.commit()
    return a


@pytest.fixture
def client(app):
    c = app.test_client()
    with app.app_context(), c.session_transaction() as sess:
        sess['logged_in'], sess['av'] = True, credentials.auth_version()
    return c


def _export(*rows, extra=b''):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('activities.csv', CSV_HEAD + ''.join(rows or [ROW]))
        z.writestr('activities/101.gpx', GPX)
        if extra:
            z.writestr('padding.bin', extra)
    return buf.getvalue()


def _files_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('ride.gpx', GPX)
    return buf.getvalue()


def _post(client, url, data):
    body = client.post(url, data=data).get_data(as_text=True)
    return [e for e in body.split('\n\n') if e.startswith('data:')][-1]


def _upload(client, data, name='export.zip', **form):
    return _post(client, '/import/upload', {'riderId': '1', 'zipfile': (io.BytesIO(data), name), **form})


def _dir(app):
    return os.path.join(os.path.dirname(app.config['DATABASE']), 'strava_exports')


def _row(app, rider_id=1):
    with app.app_context():
        r = database.get_db().execute('SELECT * FROM StravaExport WHERE riderId=?', [rider_id]).fetchone()
        return dict(r) if r else None


def test_an_export_is_kept_and_recorded(app, client):
    data = _export(ROW, MANUAL)
    done = _upload(client, data)
    assert '"complete": true' in done and '"kept": true' in done
    assert os.listdir(_dir(app)) == ['1.zip']                                   # named for the rider, and no upload left behind
    assert open(os.path.join(_dir(app), '1.zip'), 'rb').read() == data
    r = _row(app)
    assert r['sizeBytes'] == len(data) and r['activities'] == 2 and r['photos'] == 1 and r['segments'] == 0
    page = client.get('/import').get_data(as_text=True)
    assert 'Strava export kept' in page and 'Import again' in page and 'reads exports differently' not in page


def test_import_again_reads_the_kept_file_and_leaves_it(app, client):
    _upload(client, _export())
    with app.app_context():
        db = database.get_db()
        db.execute("UPDATE StravaExport SET readAt='2020-01-01 00:00:00', readerVersion='older'")
        db.commit()
    assert 'reads exports differently' in client.get('/import').get_data(as_text=True)    # a release that reads exports differently says so
    done = _post(client, '/import/strava-export/1/again', {'importPhotos': '1', 'importSegments': '1'})
    assert '"complete": true' in done and '"unchanged": 1' in done
    assert os.path.isfile(os.path.join(_dir(app), '1.zip'))
    r = _row(app)
    assert r['readAt'] > '2020' and r['readerVersion'] != 'older' and r['segments'] == 1
    assert 'reads exports differently' not in client.get('/import').get_data(as_text=True)


def test_a_second_export_replaces_the_first(app, client):
    _upload(client, _export())
    bigger = _export(ROW, MANUAL, extra=b'x' * 5000)
    _upload(client, bigger)
    assert os.listdir(_dir(app)) == ['1.zip'] and os.path.getsize(os.path.join(_dir(app), '1.zip')) == len(bigger)
    assert _row(app)['activities'] == 2


def test_not_kept_when_unticked_and_other_uploads_are_never_kept(app, client):
    assert '"kept"' not in _upload(client, _export(), keepExport='0')
    assert '"complete": true' in _upload(client, _files_zip(), name='rides.zip')
    assert '"complete": true' in _upload(client, GPX.encode(), name='ride.gpx')
    assert 'Not a valid zip file' in _upload(client, b'not a zip', name='broken.zip')
    assert os.listdir(_dir(app)) == [] and _row(app) is None


def test_deleting_the_export_or_its_rider_deletes_the_file(app, client):
    _upload(client, _export())
    _upload(client, _export(), riderId='2')
    assert sorted(os.listdir(_dir(app))) == ['1.zip', '2.zip']
    client.post('/import/strava-export/1/delete')
    assert os.listdir(_dir(app)) == ['2.zip'] and _row(app) is None
    client.post('/riders/2/delete')
    assert os.listdir(_dir(app)) == [] and _row(app, 2) is None
    assert 'Strava export kept' not in client.get('/import').get_data(as_text=True)


def test_a_record_without_its_file_is_dropped(app, client):
    """A restored backup brings StravaExport rows but not the files (they're left out of the backup)."""
    _upload(client, _export())
    os.unlink(os.path.join(_dir(app), '1.zip'))
    assert 'Strava export kept' not in client.get('/import').get_data(as_text=True)
    assert _row(app) is None
    assert 'no longer kept' in _post(client, '/import/strava-export/1/again', {})


def test_an_upload_left_behind_is_cleared(app, client):
    left = os.path.join(strava_export.export_dir(app.config['DATABASE']), strava_export.UPLOAD_PREFIX + 'crashed.zip')
    open(left, 'wb').write(b'x')
    os.utime(left, (0, 0))
    _upload(client, _export())
    assert os.listdir(_dir(app)) == ['1.zip']
