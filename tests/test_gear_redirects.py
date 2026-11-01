"""After setting a default bike, the gear routes go back to the form's 'next' page, checked as routes/login.py checks it (a path on this
server only), never to the Referer. Full app, throwaway DB."""
import pytest
from flask import Flask

import app as app_module
import config
import database
from services import credentials, gear, logs


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = str(tmp_path / 't.db')
    pre = Flask('pre')
    pre.config['DATABASE'] = path
    with pre.app_context():
        database.migrate_db()
        db = database.get_db()
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Rider', 1)")
        gear.create_bike(db, 1, 'Road bike')
        db.commit()
    monkeypatch.delenv('LOG_DIR', raising=False)
    monkeypatch.setattr(config.Config, 'DATABASE', path)
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    yield c
    logs.setup()


@pytest.mark.parametrize('url, fallback', [('/gear/default', '/gear/'), ('/gear/bike/1/default', '/gear/bike/1')])
def test_next_or_the_fallback_never_the_referer(client, url, fallback):
    form = {'rider': '1', 'bike': '1'}
    evil = {'Referer': 'https://evil.example/'}
    assert client.post(url, data={**form, 'next': '/riders/1'}, headers=evil).headers['Location'] == '/riders/1'
    for bad in ('https://evil.example/', '//evil.example/', '/\\evil.example', 'riders/1', ''):
        assert client.post(url, data={**form, 'next': bad}, headers=evil).headers['Location'] == fallback, bad
    assert client.post(url, data=form, headers=evil).headers['Location'] == fallback


def test_rider_page_form_sends_next(client):
    page = client.get('/riders/1').get_data(as_text=True)
    assert '<input type="hidden" name="next" value="/riders/1">' in page
