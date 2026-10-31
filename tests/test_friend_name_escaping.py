"""Names a friend's server or a public food database controls never reach an inline JavaScript handler: the friends page reads the friend's
name from a data- attribute, and nutrition.html's escHtml escapes quotes for its uses inside attribute values. Full app, throwaway DB."""
import html
import re

import pytest

import app as app_module
import config
import database
from services import credentials

EVIL = "x'); fetch('/phones/create'); ('"


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.setattr('services.mqtt.push_update', lambda *a, **k: None)
    monkeypatch.setattr('services.mqtt.push_update_nutrition', lambda *a, **k: None)
    app = app_module.create_app()
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1), (2, 'Sam', 0)")
        db.execute("INSERT INTO Friend (id, name, url, token, riderId) VALUES (1, ?, 'https://sam.example', 't', 2)", [EVIL])
        db.commit()
        av = credentials.auth_version()
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def handlers(page):
    """Every inline on…= handler as the browser's JavaScript sees it (entities decoded)."""
    return [html.unescape(m) for m in re.findall(r'\son[a-z]+="([^"]*)"', page)]


def test_a_friends_name_is_in_no_inline_handler(client):
    page = client.get('/friends').get_data(as_text=True)
    assert [h for h in handlers(page) if 'phones/create' in h] == []
    prompts = [html.unescape(m) for m in re.findall(r'data-prompt="([^"]*)"', page)]
    assert prompts == [f'New feed token from {EVIL}:']


def test_nutrition_eschtml_escapes_quotes(client):
    r = client.get('/nutrition/')
    assert r.status_code == 200
    fn = next(l for l in r.get_data(as_text=True).splitlines() if l.startswith('function escHtml('))
    assert '"\'"' in fn and '&quot;' in fn and '&#39;' in fn
