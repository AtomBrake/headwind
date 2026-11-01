"""Sign-in lockout: 8 failures from one address, and 30 from all addresses together, which a client that can claim a new
address on every attempt (X-Forwarded-For through a peer that looks private, e.g. Docker Desktop) can't get around.
Full app, throwaway DB."""
import pytest

import app as app_module
import config
import database
from routes import login
from services import credentials


class _NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass


class _Clock:
    t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.setattr(credentials, '_unsaved', None)
    monkeypatch.setattr(credentials, '_generated', None)
    monkeypatch.setenv('APP_USERNAME', 'rob')
    monkeypatch.setenv('APP_PASSWORD', 'the-right-password')
    monkeypatch.delenv('TRUSTED_PROXIES', raising=False)
    monkeypatch.setattr(login, '_fails', {})
    monkeypatch.setattr(login, '_all_fails', login.deque())
    clock = _Clock()
    monkeypatch.setattr(login.time, 'monotonic', clock)
    a = app_module.create_app()
    with a.app_context():
        db = database.get_db()
        db.execute("INSERT INTO Rider (name, isDefault) VALUES ('Rob', 1)"); db.commit()
    return a.test_client(), clock


def _sign_in(c, password, claimed=None, peer='172.17.0.1'):
    """A sign-in through Docker's bridge address: the default TRUSTED_PROXIES believes its X-Forwarded-For."""
    headers = {'X-Forwarded-For': claimed} if claimed else {}
    return c.post('/login', data={'username': 'rob', 'password': password}, headers=headers,
                  environ_base={'REMOTE_ADDR': peer}).status_code


def test_one_address_is_locked_after_8_failures(client):
    c, _ = client
    assert [_sign_in(c, 'wrong') for _ in range(8)] == [200] * 8
    assert _sign_in(c, 'the-right-password') == 429
    assert _sign_in(c, 'the-right-password', claimed='198.51.100.1') == 302     # a different address isn't


def test_a_new_address_on_every_attempt_still_hits_the_instance_wide_limit(client):
    c, clock = client
    for i in range(login._MAX_ALL_FAILS):
        assert _sign_in(c, 'wrong', claimed=f'198.51.100.{i}') == 200
        clock.t += 1
    assert _sign_in(c, 'wrong', claimed='203.0.113.1') == 429
    assert _sign_in(c, 'the-right-password', claimed='203.0.113.2') == 429     # every sign-in, the owner's too
    assert _sign_in(c, 'the-right-password', peer='127.0.0.1') == 429
    clock.t += login._WINDOW + 1
    assert _sign_in(c, 'the-right-password', claimed='203.0.113.2') == 302


def test_refused_attempts_dont_count(client):
    """While it's locked nothing is checked, so the window drains: about 30 guesses per 5 minutes at most."""
    c, clock = client
    for i in range(login._MAX_ALL_FAILS):
        _sign_in(c, 'wrong', claimed=f'198.51.100.{i}')
    for i in range(50):
        assert _sign_in(c, 'wrong', claimed=f'192.0.2.{i}') == 429
    assert len(login._all_fails) == login._MAX_ALL_FAILS
    clock.t += login._WINDOW + 1
    assert _sign_in(c, 'wrong', claimed='192.0.2.200') == 200


def test_addresses_are_forgotten_once_their_window_has_passed(client):
    c, clock = client
    for i in range(20):
        _sign_in(c, 'wrong', claimed=f'198.51.100.{i}')
    assert len(login._fails) == 20
    clock.t += login._WINDOW + 1
    _sign_in(c, 'wrong', claimed='198.51.100.250')
    assert list(login._fails) == ['198.51.100.250'] and len(login._all_fails) == 1


def test_signing_in_clears_only_that_address(client):
    c, _ = client
    for _ in range(5):
        _sign_in(c, 'wrong', claimed='198.51.100.7')
    _sign_in(c, 'wrong', claimed='198.51.100.8')
    assert _sign_in(c, 'the-right-password', claimed='198.51.100.7') == 302
    assert '198.51.100.7' not in login._fails and '198.51.100.8' in login._fails
    assert len(login._all_fails) == 6
