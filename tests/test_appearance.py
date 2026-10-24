"""Light, dark or Auto (routes/settings.py APPEARANCES, templates/_scheme.html): Settings stores the choice, and every page,
the login and setup pages too, carries it on <html data-theme> for the script that picks the scheme. Full app, throwaway DB."""
import re

import pytest
from flask import Flask

import app as app_module
import config
import database
from services import credentials


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def app(tmp_path, monkeypatch):
    path = str(tmp_path / 't.db')
    pre = Flask('pre')
    pre.config['DATABASE'] = path
    with pre.app_context():
        database.migrate_db()
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        db.commit()
    monkeypatch.setattr(config.Config, 'DATABASE', path)
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    return app_module.create_app()


@pytest.fixture
def client(app):
    with app.app_context():
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _stored(app):
    with app.app_context():
        return database.get_db().execute('SELECT appearance FROM Settings WHERE id=1').fetchone()[0]


def _theme(html):
    return re.search(r'<html lang="en" data-theme="([^"]*)">', html).group(1)


def test_a_new_install_follows_the_device(app, client):
    assert _stored(app) == 'auto'
    page = client.get('/settings/').get_data(as_text=True)
    assert _theme(page) == 'auto'
    assert '<meta name="color-scheme" content="light dark">' in page
    assert re.search(r'name="appearance" value="auto"\s+checked', page)


@pytest.mark.parametrize('choice, meta', [('light', 'light'), ('dark', 'dark'), ('auto', 'light dark')])
def test_settings_saves_the_choice_and_every_page_carries_it(app, client, choice, meta):
    client.post('/settings/', data={'units': 'imperial', 'appearance': choice})
    assert _stored(app) == choice
    for url in ('/settings/', '/dashboard'):
        page = client.get(url).get_data(as_text=True)
        assert _theme(page) == choice, url
        assert f'<meta name="color-scheme" content="{meta}">' in page


def test_a_bad_value_keeps_what_is_saved(app, client):
    client.post('/settings/', data={'units': 'imperial', 'appearance': 'light'})
    for bad in ('purple', '"><script>', ''):
        client.post('/settings/', data={'units': 'imperial', 'appearance': bad})
        assert _stored(app) == 'light'


def test_another_card_saving_leaves_it_alone(app, client):
    client.post('/settings/', data={'units': 'imperial', 'appearance': 'dark'})
    client.post('/settings/', data={'mqttHost': 'broker.local'})        # a card with no Appearance field
    assert _stored(app) == 'dark'


def test_a_bad_stored_value_renders_as_auto(app, client):
    with app.app_context():
        database.get_db().execute("UPDATE Settings SET appearance='neon' WHERE id=1"); database.get_db().commit()
    assert _theme(client.get('/settings/').get_data(as_text=True)) == 'auto'


def test_the_login_page_follows_it_too(app):
    with app.app_context():
        database.get_db().execute("UPDATE Settings SET appearance='light' WHERE id=1"); database.get_db().commit()
    page = app.test_client().get('/login').get_data(as_text=True)
    assert _theme(page) == 'light' and "applyScheme" in page
