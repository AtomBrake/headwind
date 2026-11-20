"""Captions and order for an activity's photos from the activity page: the caption field and the drag / arrow controls, and the two routes they
post to. Throwaway DB, no network."""
import io

import pytest
from flask import Flask
from PIL import Image

import app as app_module
import config
import database
from services import credentials, logs, photos


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def _jpeg():
    buf = io.BytesIO()
    Image.new('RGB', (30, 30), (10, 200, 30)).save(buf, 'JPEG')
    return buf.getvalue()


@pytest.fixture
def app(tmp_path, monkeypatch):
    path = str(tmp_path / 't.db')
    pre = Flask('pre')
    pre.config['DATABASE'] = path
    with pre.app_context():
        database.migrate_db()
        db = database.get_db()
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Rider', 1)")
        for rid in ('r1', 'r2'):
            db.execute("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal, distance, movingTime, elapsedTime) "
                       "VALUES (?, 'Morning ride', 'Ride', 1, '2026-10-01T08:00:00', 20000, 3600, 3600)", [rid])
        photos.ensure_schema(db)
        for i in range(3):
            photos.save(db, 'r1', _jpeg(), path, caption='Top of the climb' if i == 0 else None, position=i)
        photos.save(db, 'r2', _jpeg(), path)
        db.commit()
    monkeypatch.delenv('LOG_DIR', raising=False)
    monkeypatch.delenv('HEADWIND_DEMO', raising=False)
    monkeypatch.setenv('AVATAR_DIR', str(tmp_path / 'avatars'))
    monkeypatch.setattr(config.Config, 'DATABASE', path)
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    yield app_module.create_app()
    logs.setup()


@pytest.fixture
def client(app):
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _photos(app, rid='r1'):
    with app.app_context():
        return [(p['id'], p['caption']) for p in photos.for_activity(database.get_db(), rid)]


def test_the_page_has_a_caption_field_and_order_controls(client, app):
    page = client.get('/rides/r1').get_data(as_text=True)
    assert page.count('class="photo-caption"') == 3 and 'value="Top of the climb"' in page
    assert page.count('data-click="movePhoto(this, -1)"') == 3 and "The first one is the activity's cover" in page
    one = client.get('/rides/r2').get_data(as_text=True)
    assert 'class="photo-caption"' in one and 'movePhoto(this' not in one             # nothing to put in order


def test_a_caption_is_set_and_cleared(client, app):
    pid = _photos(app)[1][0]
    assert client.post(f'/rides/r1/photos/{pid}/caption', data={'caption': '  Café stop  '}).status_code == 204
    assert _photos(app)[1] == (pid, 'Café stop')
    assert client.post(f'/rides/r1/photos/{pid}/caption', data={'caption': 'x' * 500}).status_code == 204
    assert _photos(app)[1][1] == 'x' * photos.MAX_CAPTION
    assert client.post(f'/rides/r1/photos/{pid}/caption', data={'caption': ''}).status_code == 204
    assert _photos(app)[1] == (pid, None)


def test_a_caption_for_another_activitys_photo_is_refused(client, app):
    other = _photos(app, 'r2')[0][0]
    assert client.post(f'/rides/r1/photos/{other}/caption', data={'caption': 'Mine'}).status_code == 404
    assert _photos(app, 'r2')[0][1] is None


def test_photos_are_put_in_order(client, app):
    a, b, c = [p for p, _ in _photos(app)]
    assert client.post('/rides/r1/photos/order', data={'id': [str(c), str(a), str(b)]}).status_code == 204
    assert [p for p, _ in _photos(app)] == [c, a, b]
    page = client.get('/rides/r1').get_data(as_text=True)
    assert page.index(f'data-pid="{c}"') < page.index(f'data-pid="{a}"') < page.index(f'data-pid="{b}"')


@pytest.mark.parametrize('ids', [lambda a, b, c, o: [a, b], lambda a, b, c, o: [a, b, c, o], lambda a, b, c, o: [a, a, b, c],
                                 lambda a, b, c, o: [a, b, 'x']])
def test_an_order_that_isnt_every_photo_once_is_refused(client, app, ids):
    a, b, c = [p for p, _ in _photos(app)]
    other = _photos(app, 'r2')[0][0]
    before = _photos(app)
    assert client.post('/rides/r1/photos/order', data={'id': [str(i) for i in ids(a, b, c, other)]}).status_code == 409
    assert _photos(app) == before
