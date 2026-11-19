"""The outside address (services/external_url.py): set in Settings or the setup wizard, else APP_URL, and used by phone pairing, /api/v1/ping,
friend codes and notification links. Full app, throwaway DB."""
import pytest

import app as app_module
import config
import database
from services import credentials, external_url, feed_tokens


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(config.Config, 'APP_URL', 'http://localhost:5000')
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)       # no MQTT / Garmin / friend background loops
    app = app_module.create_app()
    with app.app_context():
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("INSERT INTO Rider (id, name, isDefault) VALUES (1, 'Tom', 1)")
        db.commit()
    return app


def _client(app):
    c = app.test_client()
    with app.app_context():
        av = credentials.auth_version()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['av'] = av
    return c


def _save(c, url):
    return c.post('/settings/address', data={'externalUrl': url})


def _saved(app):
    with app.app_context():
        return database.get_db().execute('SELECT externalUrl FROM Settings WHERE id=1').fetchone()[0]


def test_the_setting_then_app_url_then_nothing(app):
    with app.test_request_context():
        assert (external_url.get(), external_url.source(), external_url.https()) == ('http://localhost:5000', 'APP_URL', '')
        app.config['APP_URL'] = 'https://env.example/'
        assert (external_url.get(), external_url.https()) == ('https://env.example', 'https://env.example')
        database.get_db().execute("UPDATE Settings SET externalUrl='https://set.example' WHERE id=1")
        assert (external_url.get(), external_url.source()) == ('https://set.example', 'setting')
        database.get_db().execute("UPDATE Settings SET externalUrl=NULL WHERE id=1")
        app.config['APP_URL'] = ''
        assert (external_url.get(), external_url.source()) == ('', '')


@pytest.mark.parametrize('typed, saved', [('https://bike.example.com/', 'https://bike.example.com'), ('  https://h.example/headwind  ', 'https://h.example/headwind'),
                                          ('http://192.168.1.5:5001', 'http://192.168.1.5:5001'), ('', None)])
def test_settings_saves_an_address_without_its_trailing_slash(app, typed, saved):
    c = _client(app)
    r = _save(c, typed)
    assert r.status_code == 302 and r.headers['Location'].endswith('/settings#address')
    assert _saved(app) == saved


@pytest.mark.parametrize('typed', ['bike.example.com', 'ftp://bike.example.com', 'https://', 'https://bike example.com', 'https://h.example/?x=1'])
def test_settings_refuses_what_isnt_an_address(app, typed):
    c = _client(app)
    _save(c, 'https://good.example')
    _save(c, typed)
    assert _saved(app) == 'https://good.example'
    assert "That address won" in c.get('/settings/').get_data(as_text=True)


def test_settings_says_which_is_in_use_and_warns_about_http(app):
    c = _client(app)
    page = c.get('/settings/').get_data(as_text=True)
    assert 'id="address"' in page and 'from the <code>APP_URL</code> environment variable' in page and "isn't https" in page
    _save(c, 'http://192.168.1.5')
    assert 'the phone apps only pair over https, so they can' in c.get('/settings/').get_data(as_text=True)
    _save(c, 'https://bike.example.com')
    page = c.get('/settings/').get_data(as_text=True)
    assert 'In use: this one.' in page and 'value="https://bike.example.com"' in page


def test_pairing_and_ping_use_the_saved_address(app):
    c = _client(app)
    r = c.post('/phones/create', json={'name': 'iPhone', 'server_url': 'https://typed.example'})
    assert r.status_code == 400 and 'Settings' in r.get_json()['error'], 'no https address: no pairing, and a typed one is ignored'
    assert 'disabled' in c.get('/phones/').get_data(as_text=True).split('id="phGo"')[1].split('>')[0]
    _save(c, 'https://bike.example.com')
    made = c.post('/phones/create', json={'name': 'iPhone', 'server_url': 'https://typed.example'}).get_json()
    assert made['server_url'] == 'https://bike.example.com' and made['link'].startswith('headwind://pair?u=https%3A%2F%2Fbike.example.com&t=')
    assert 'Change in Settings' in c.get('/phones/').get_data(as_text=True)
    ping = c.get('/api/v1/ping', headers={'Authorization': 'Bearer ' + made['token']}).get_json()
    assert ping['server_url'] == 'https://bike.example.com'
    _save(c, 'http://192.168.1.5')
    assert c.get('/api/v1/ping', headers={'Authorization': 'Bearer ' + made['token']}).get_json()['server_url'] is None


def test_friend_codes_and_the_feed_url_use_it(app):
    c = _client(app)
    page = c.get('/friends').get_data(as_text=True)
    assert 'No https outside address is set' in page and 'Feed URL: <code>http://localhost/api/feed</code>' in page
    _save(c, 'https://bike.example.com')
    page = c.get('/friends').get_data(as_text=True)
    assert 'Codes connect to <code>https://bike.example.com</code>' in page and 'Feed URL: <code>https://bike.example.com/api/feed</code>' in page
    made = c.post('/friends/tokens', data={'name': 'Sam', 'shareRides': '1'}).get_json()
    assert feed_tokens.parse_share_code(made['code']) == ('https://bike.example.com', made['token'])


def test_notification_links_use_it(app, monkeypatch):
    from services import downloads, notify
    sent = []
    monkeypatch.setattr(notify, 'send_notification', lambda *a: sent.append(a))
    _save(_client(app), 'https://bike.example.com')
    downloads._notify(app, {'state': 'failed', 'label': 'Backup', 'page': '/settings#backup'})
    assert sent[0][2] == 'https://bike.example.com/tasks'


def test_the_setup_wizard_asks_for_it(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 'w.db'))
    monkeypatch.setattr(config.Config, 'APP_URL', 'https://env.example')
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    app = app_module.create_app()
    c = _client(app)
    c.post('/setup?step=1', data={'riders[]': 'Tom'})
    assert c.post('/setup?step=2', data={'units': 'metric'}).headers['Location'].endswith('/setup?step=3')
    page = c.get('/setup?step=3').get_data(as_text=True)
    assert 'Step 3 of 7' in page and 'value="https://env.example"' in page, 'pre-filled from an https APP_URL'
    assert 'Step 3 of 7' in c.post('/setup?step=3', data={'externalUrl': 'nope'}).get_data(as_text=True)
    assert c.post('/setup?step=3', data={'externalUrl': 'https://bike.example.com/'}).headers['Location'].endswith('/setup?step=4')
    assert _saved(app) == 'https://bike.example.com'
    assert 'No outside address yet' not in c.get('/setup?step=7').get_data(as_text=True)
    with app.app_context():
        database.get_db().execute('UPDATE Settings SET externalUrl=NULL WHERE id=1')
        database.get_db().commit()
    app.config['APP_URL'] = 'http://localhost:5000'
    assert 'No outside address yet' in c.get('/setup?step=7').get_data(as_text=True), 'skipped: the Done step says so'
