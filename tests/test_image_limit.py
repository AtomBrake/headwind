"""A picture over the pixel limit (limits.limit_images, set once at start-up) is refused with a message saying so, at every upload that
decodes one, and is never decoded. The limit is shrunk to 1,000 pixels here so the pictures stay small: 30x30 fits, 40x40 is over it
(Pillow alone would only warn up to twice its limit), 50x50 is over twice it."""
import io

import pytest
from flask import Flask
from PIL import Image

import app as app_module
import config
import database
from services import credentials, gear, limits, logs, photos

LIMIT = 1000


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


def _png(side):
    buf = io.BytesIO()
    Image.new('RGB', (side, side), (10, 200, 30)).save(buf, 'PNG')
    return buf.getvalue()


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(Image, 'MAX_IMAGE_PIXELS', Image.MAX_IMAGE_PIXELS)      # put back after the test
    monkeypatch.setattr(limits, 'MAX_IMAGE_PIXELS', LIMIT)
    path = str(tmp_path / 't.db')
    pre = Flask('pre')
    pre.config['DATABASE'] = path
    with pre.app_context():
        database.migrate_db()
        db = database.get_db()
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Rider', 1)")
        db.execute("INSERT INTO Activity (id, name, sportType, riderId, startDateLocal, distance, movingTime, elapsedTime) "
                   "VALUES ('r1', 'Morning ride', 'Ride', 1, '2026-10-01T08:00:00', 20000, 3600, 3600)")
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


def test_start_up_sets_the_limit(app):
    assert Image.MAX_IMAGE_PIXELS == LIMIT


@pytest.mark.parametrize('side', [40, 50])
def test_services_refuse_with_a_clear_message(app, side):
    with app.app_context():
        db, path = database.get_db(), app.config['DATABASE']
        assert photos.save(db, 'r1', _png(30), path)
        with pytest.raises(ValueError, match='too large'):
            photos.save(db, 'r1', _png(side), path)
        bike = gear.create_bike(db, 1, 'A')
        assert gear.save_photo(db, bike, _png(30), path)
        with pytest.raises(ValueError, match='too large'):
            gear.save_photo(db, bike, _png(side), path)
        with pytest.raises(ValueError, match='not look like a picture'):
            gear.save_photo(db, bike, b'not an image', path)


def test_activity_photo_upload(client):
    r = client.post('/rides/r1/photos', data={'photos': [(io.BytesIO(_png(40)), 'big.png'), (io.BytesIO(_png(30)), 'small.png')]},
                    content_type='multipart/form-data', follow_redirects=True)
    assert r.status_code == 200
    page = r.get_data(as_text=True)
    assert 'big.png: that picture is too large (over 50 megapixels)' in page and 'Added 1 photo' in page


def test_bike_photo_upload(client, app):
    with app.app_context():
        bike = gear.create_bike(database.get_db(), 1, 'A')
        database.get_db().commit()
    r = client.post(f'/gear/bike/{bike}/photo', data={'photo': (io.BytesIO(_png(40)), 'big.png')}, content_type='multipart/form-data')
    assert r.status_code == 302 and 'error=that%20picture%20is%20too%20large' in r.headers['Location']


def test_avatar_upload(client):
    r = client.post('/riders/1/avatar', data={'avatar': (io.BytesIO(_png(40)), 'big.png')}, content_type='multipart/form-data')
    assert r.status_code == 302
    with client.session_transaction() as s:
        assert ('error', 'That picture is too large (over 50 megapixels).') in s.get('_flashes', [])


def test_food_photo_upload(client):
    r = client.post('/nutrition/api/food-image/upload', data={'photo': (io.BytesIO(_png(40)), 'big.png'), 'name': 'Toast'},
                    content_type='multipart/form-data')
    assert r.status_code == 400 and 'too large' in r.get_json()['error']


def test_meal_photo_is_checked_before_the_ai(client, monkeypatch):
    from services import food_vision
    calls = []
    monkeypatch.setattr(food_vision, 'get_chat', lambda: lambda *a, **kw: calls.append(1))
    r = client.post('/nutrition/api/estimate-meal', data={'photo': (io.BytesIO(_png(40)), 'meal.png')}, content_type='multipart/form-data')
    assert r.status_code == 400 and 'too large' in r.get_json()['error'] and not calls
    with pytest.raises(ValueError, match='too large'):
        food_vision.extract_foods([_png(40)])
