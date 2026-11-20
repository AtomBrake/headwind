"""Static files get versioned URLs and a year's caching; pages, JSON and static text go gzipped to a browser that accepts it."""
import gzip
import pathlib
import re

import pytest

import app as app_module
import config


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.delenv('HEADWIND_DEMO', raising=False)
    return app_module.create_app()


GZ = {'Accept-Encoding': 'gzip, deflate, br'}
CHART = 'vendor/chart.js-4.4.0/chart.umd.js'


def test_static_urls_carry_a_version(app):
    with app.test_request_context():
        url = app_module.url_for('static', filename=CHART)
        assert re.search(r'\?v=[0-9a-f]{10}$', url)
        assert app_module.url_for('static', filename='no/such.js').endswith('/static/no/such.js')   # nothing to hash: no ?v=


def test_versioned_static_is_cached_for_a_year(app):
    c = app.test_client()
    with app.test_request_context():
        url = app_module.url_for('static', filename=CHART)
    assert 'immutable' in c.get(url).headers['Cache-Control']
    assert 'immutable' not in (c.get('/static/' + CHART).headers.get('Cache-Control') or '')


def test_static_text_is_gzipped_and_unchanged(app):
    c = app.test_client()
    resp = c.get('/static/' + CHART, headers=GZ)
    assert resp.headers['Content-Encoding'] == 'gzip'
    assert 'Accept-Encoding' in resp.headers['Vary']
    on_disk = (pathlib.Path(app.static_folder) / CHART).read_bytes()
    assert gzip.decompress(resp.data) == on_disk
    assert int(resp.headers['Content-Length']) == len(resp.data) < len(on_disk) / 2
    plain = c.get('/static/' + CHART)
    assert 'Content-Encoding' not in plain.headers and plain.data == on_disk


def test_a_gzipped_file_still_revalidates(app):
    c = app.test_client()
    etag = c.get('/static/' + CHART, headers=GZ).headers['ETag']
    assert etag.startswith('W/')
    assert c.get('/static/' + CHART, headers={**GZ, 'If-None-Match': etag}).status_code == 304


def test_images_are_not_gzipped(app):
    resp = app.test_client().get('/static/vendor/leaflet-1.9.4/images/layers.png', headers=GZ)
    assert resp.status_code == 200 and 'Content-Encoding' not in resp.headers


def test_pages_are_gzipped(app):
    c = app.test_client()
    resp = c.get('/login', headers=GZ)
    assert resp.headers['Content-Encoding'] == 'gzip'
    assert b'<html' in gzip.decompress(resp.data)
    assert 'Content-Encoding' not in c.get('/login').headers


def test_streamed_responses_are_left_alone(app):
    from flask import Response
    from services import web_assets
    with app.test_request_context('/import/upload', headers=GZ):
        resp = web_assets.compress(Response((('x' * 2000) for _ in range(3)), mimetype='text/plain'), app.static_folder)
        assert 'Content-Encoding' not in resp.headers and resp.get_data() == b'x' * 6000
