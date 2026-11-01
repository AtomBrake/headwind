"""Restore must reject incompatible backups before touching live data; a Settings password change must survive the
environment re-supplying the original credentials. Disposable temp files only."""
import json
import os
import sqlite3

import pytest
from flask import Flask

import database
from services import backup, credentials


# ---------- credentials ----------
@pytest.fixture
def creds(tmp_path, monkeypatch):
    monkeypatch.setattr(credentials, '_data_dir', lambda: str(tmp_path))
    monkeypatch.setattr(credentials, '_unsaved', None)
    monkeypatch.setattr(credentials, '_generated', None)
    for k in ('APP_USERNAME', 'APP_PASSWORD'):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def _login_file(tmp_path):
    return json.loads((tmp_path / '.admin_login').read_text())


def test_env_wins_without_saved_file(creds):
    creds.setenv('APP_USERNAME', 'rob'); creds.setenv('APP_PASSWORD', 'compose-pw-1')
    assert credentials.admin_login().username == 'rob'
    assert credentials.check('rob', 'compose-pw-1') and not credentials.check('rob', 'compose-pw-2')
    assert not credentials.check('bob', 'compose-pw-1')


def test_settings_change_survives_env_resupply(creds):
    creds.setenv('APP_USERNAME', 'rob'); creds.setenv('APP_PASSWORD', 'compose-pw-1')
    credentials.save_login(None, 'changed-in-settings')
    # container recreated: Compose supplies the ORIGINAL credentials again
    assert credentials.check('rob', 'changed-in-settings')
    assert not credentials.check('rob', 'compose-pw-1')


def test_operator_editing_env_still_wins(creds):
    creds.setenv('APP_USERNAME', 'rob'); creds.setenv('APP_PASSWORD', 'compose-pw-1')
    credentials.save_login(None, 'changed-in-settings')
    creds.setenv('APP_PASSWORD', 'operator-new-pw')      # the way back in after a forgotten password
    assert credentials.check('rob', 'operator-new-pw')
    assert not credentials.check('rob', 'changed-in-settings')


def test_generated_password_is_stable_and_changeable(creds, tmp_path):
    creds.setenv('APP_PASSWORD', 'changeme')            # placeholder -> generate
    login = credentials.admin_login()
    first = credentials.generated_password()
    assert login.generated and first not in credentials.PLACEHOLDER_PASSWORDS and len(first) >= credentials.MIN_PASSWORD
    assert credentials.check('admin', first) and credentials.generated_password() == first
    assert first not in (tmp_path / '.admin_login').read_text()
    credentials.save_login(None, 'mine-now-123')
    assert credentials.check('admin', 'mine-now-123') and not credentials.check('admin', first)
    assert credentials.generated_password() is None and not credentials.admin_login().generated


def test_only_a_hash_is_saved(creds, tmp_path):
    creds.setenv('APP_PASSWORD', 'compose-pw-1')
    credentials.save_login('rob', 'a-long-password')
    d = _login_file(tmp_path)
    assert set(d) == {'username', 'password_hash', 'env_sig'}
    assert d['username'] == 'rob' and d['password_hash'].startswith('scrypt:')
    assert 'a-long-password' not in (tmp_path / '.admin_login').read_text()
    assert oct((tmp_path / '.admin_login').stat().st_mode & 0o777) == '0o600'


def test_changing_only_the_username_keeps_the_password(creds):
    creds.setenv('APP_PASSWORD', 'compose-pw-1')         # in force from the environment, not yet in the file
    credentials.save_login('rob', '')
    assert credentials.check('rob', 'compose-pw-1')
    credentials.save_login('robert', None)
    assert credentials.check('robert', 'compose-pw-1') and not credentials.check('rob', 'compose-pw-1')


def test_auth_version_changes_with_password(creds):
    creds.setenv('APP_PASSWORD', 'compose-pw-1')
    a = credentials.auth_version(); credentials.save_login(None, 'other-pw-22')
    b = credentials.auth_version()
    assert b != a and credentials.auth_version() == b
    credentials.save_login('someone-else', None)
    assert credentials.auth_version() != b


def test_auth_version_is_no_quick_hash_of_the_password(creds):
    """It goes in the session cookie, which its holder can read."""
    creds.setenv('APP_PASSWORD', 'compose-pw-1')
    assert credentials.auth_version() != credentials._old_av('admin', 'compose-pw-1')
    credentials.save_login(None, 'other-pw-22')
    assert credentials.auth_version() != credentials._old_av('admin', 'other-pw-22')


def test_plain_password_from_before_is_hashed_and_its_sessions_stay_signed_in(creds, tmp_path):
    creds.setenv('APP_PASSWORD', 'compose-pw-1')
    (tmp_path / '.admin_login').write_text(json.dumps({'username': 'rob', 'password': 'typed-in-settings',
                                                       'env_sig': credentials._env_sig()}))
    before = credentials._old_av('rob', 'typed-in-settings')     # what sessions signed in then carry
    assert credentials.check('rob', 'typed-in-settings')
    d = _login_file(tmp_path)
    assert 'password' not in d and d['password_hash'].startswith('scrypt:') and d['username'] == 'rob'
    assert 'typed-in-settings' not in (tmp_path / '.admin_login').read_text() and before not in json.dumps(d)
    assert credentials.signed_in_before_hashing(before)
    assert not credentials.signed_in_before_hashing(credentials._old_av('rob', 'an-older-password'))
    assert not credentials.signed_in_before_hashing(None)
    credentials.save_login(None, 'changed-again-1')               # a change still signs those sessions out
    assert 'old_av' not in _login_file(tmp_path) and not credentials.signed_in_before_hashing(before)


def test_sessions_under_the_environment_password_stay_signed_in(creds):
    creds.setenv('APP_USERNAME', 'rob'); creds.setenv('APP_PASSWORD', 'compose-pw-1')
    assert credentials.signed_in_before_hashing(credentials._old_av('rob', 'compose-pw-1'))
    assert not credentials.signed_in_before_hashing(credentials._old_av('rob', 'compose-pw-0'))


def test_generated_password_kept_in_memory_when_it_cant_be_saved(creds):
    creds.setenv('APP_PASSWORD', '')

    def read_only(path, text):
        raise PermissionError(13, 'Read-only file system')
    creds.setattr(credentials, '_write_private', read_only)
    av = credentials.auth_version()
    pw = credentials.generated_password()
    for _ in range(3):                                    # used to be a new password (and a signed-out session) every call
        assert credentials.auth_version() == av and credentials.generated_password() == pw
    assert credentials.check('admin', pw)
    with pytest.raises(OSError):                          # Settings says it couldn't be saved
        credentials.save_login(None, 'mine-now-123')
    assert credentials.check('admin', pw)


def test_plain_file_in_a_read_only_folder_is_hashed_once_in_memory(creds, tmp_path):
    creds.setenv('APP_PASSWORD', '')
    (tmp_path / '.admin_login').write_text(json.dumps({'username': 'admin', 'password': 'typed-in-settings'}))
    creds.setattr(credentials, '_write_private', lambda *a: (_ for _ in ()).throw(OSError(30, 'Read-only file system')))
    av = credentials.auth_version()
    assert credentials.auth_version() == av and credentials.check('admin', 'typed-in-settings')


def test_new_password_for_the_windows_tray(creds):
    creds.setenv('APP_PASSWORD', 'compose-pw-1')
    pw = credentials.new_password()
    assert credentials.check('admin', pw) and credentials.generated_password() == pw and credentials.admin_login().generated


# ---------- Settings and the setup wizard ----------
@pytest.fixture
def app_client(tmp_path, monkeypatch):
    import app as app_module
    import config

    class _NoThread:
        def __init__(self, *a, **kw): pass
        def start(self): pass

    monkeypatch.setattr(config.Config, 'DATABASE', str(tmp_path / 't.db'))
    monkeypatch.setattr(app_module.threading, 'Thread', _NoThread)
    monkeypatch.setattr(credentials, '_unsaved', None)
    monkeypatch.setattr(credentials, '_generated', None)
    for k in ('APP_USERNAME', 'APP_PASSWORD'):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / 'env'
    env.write_text('SECRET_KEY=x\n')
    monkeypatch.setenv('HEADWIND_ENV', str(env))
    a = app_module.create_app()
    c = a.test_client()
    with a.app_context():
        av = credentials.auth_version()
    with c.session_transaction() as s:
        s['logged_in'], s['av'] = True, av
    return a, c, env


def _with_rider(a):
    with a.app_context():
        db = database.get_db()
        db.execute("INSERT INTO Rider (name, isDefault) VALUES ('Alex', 1)"); db.commit()


def _flashes(c):
    with c.session_transaction() as s:
        return [m for _, m in s.pop('_flashes', [])]


def test_settings_password_change_writes_no_env_file(app_client):
    a, c, env = app_client
    _with_rider(a)
    pw = credentials.generated_password()
    c.post('/settings/password', data={'currentPassword': pw, 'newPassword': 'short-pw', 'confirmPassword': 'short-pw'})
    assert _flashes(c) == ['Choose a password of at least 10 characters.'] and credentials.check('admin', pw)
    c.post('/settings/password', data={'currentPassword': 'wrong', 'newPassword': 'a-long-password', 'confirmPassword': 'a-long-password'})
    assert _flashes(c) == ['Current password is incorrect.']
    c.post('/settings/password', data={'currentPassword': pw, 'newUsername': 'rob',
                                       'newPassword': 'a-long-password', 'confirmPassword': 'a-long-password'})
    assert _flashes(c) == ['Login details updated.'] and credentials.check('rob', 'a-long-password')
    assert env.read_text() == 'SECRET_KEY=x\n' and 'APP_PASSWORD' not in os.environ
    assert c.get('/settings/').status_code == 200          # this session stays signed in
    assert 'minlength="10"' in c.get('/settings/').get_data(as_text=True)


def test_setup_wizard_offers_an_own_password_only_while_the_generated_one_is_in_force(app_client):
    a, c, env = app_client
    pw = credentials.generated_password()
    page = c.get('/setup').get_data(as_text=True)
    assert 'name="newPassword" minlength="10"' in page
    r = c.post('/setup', data={'riders[]': 'Alex', 'newPassword': 'too-short', 'confirmPassword': 'too-short'})
    assert 'at least 10 characters' in r.get_data(as_text=True) and credentials.check('admin', pw)
    with a.app_context():
        assert database.query_db('SELECT COUNT(*) FROM Rider', one=True)[0] == 0      # nothing half-done
    r = c.post('/setup', data={'riders[]': 'Alex', 'newPassword': 'my-own-password', 'confirmPassword': 'my-own-password'})
    assert r.headers['Location'].endswith('/setup?step=2')
    assert credentials.check('admin', 'my-own-password') and not credentials.admin_login().generated
    assert c.get('/setup?step=2').status_code == 200        # still signed in


def test_old_sessions_survive_the_upgrade(app_client, tmp_path):
    a, c, env = app_client
    _with_rider(a)
    login = tmp_path / '.admin_login'
    login.write_text(json.dumps({'username': 'admin', 'password': 'typed-in-settings', 'env_sig': credentials._env_sig()}))
    with c.session_transaction() as s:
        s['av'] = credentials._old_av('admin', 'typed-in-settings')
    assert c.get('/settings/').status_code == 200
    with c.session_transaction() as s:
        assert s['av'] == credentials.auth_version()
    with c.session_transaction() as s:
        s['av'] = credentials._old_av('admin', 'an-older-password')   # from before an earlier change: signed out
    assert c.get('/settings/').status_code == 302


# ---------- restore ----------
def _live_db(tmp_path):
    path = str(tmp_path / 'live.db')
    app = Flask('x'); app.config['DATABASE'] = path
    with app.app_context():
        database.migrate_db(); db = database.get_db()
        db.execute("INSERT INTO Rider (name,isDefault) VALUES ('Original',1)"); db.commit()
    return path


def _riders(path):
    return [r[0] for r in sqlite3.connect(path).execute('SELECT name FROM Rider')]


def test_incompatible_backup_rejected_before_anything_changes(tmp_path):
    live = _live_db(tmp_path)
    bad = str(tmp_path / 'bad.db')
    c = sqlite3.connect(bad)   # right table names, wrong shape: passes the old validate()
    c.executescript('CREATE TABLE Rider(x TEXT); CREATE TABLE Activity(y TEXT); CREATE TABLE Settings(z TEXT);'
                    "INSERT INTO Rider VALUES ('a');")
    c.commit(); c.close()
    assert backup.validate(bad) == 1                       # old check lets it through...
    with pytest.raises(backup.BackupError):
        backup.prepare(bad)                                # ...the new one doesn't
    assert _riders(live) == ['Original'] and not os.path.exists(live + '.pre-restore')


def test_older_backup_is_migrated_then_applied(tmp_path):
    live = _live_db(tmp_path)
    other = str(tmp_path / 'other.db')
    app = Flask('y'); app.config['DATABASE'] = other
    with app.app_context():
        database.migrate_db(); db = database.get_db()
        db.execute("INSERT INTO Rider (name,isDefault) VALUES ('FromBackup',1)"); db.commit()
    backup.validate(other); backup.prepare(other)
    backup.apply(live, other, {}, str(tmp_path / 'av'))
    assert _riders(live) == ['FromBackup'] and os.path.exists(live + '.pre-restore')


def test_asset_copy_failure_leaves_live_db_untouched(tmp_path):
    live = _live_db(tmp_path)
    other = str(tmp_path / 'other.db')
    app = Flask('z'); app.config['DATABASE'] = other
    with app.app_context():
        database.migrate_db(); db = database.get_db()
        db.execute("INSERT INTO Rider (name,isDefault) VALUES ('FromBackup',1)"); db.commit()
    avatars = tmp_path / 'staged_av'; avatars.mkdir(); (avatars / 'rider_1.jpg').write_bytes(b'x')
    blocker = tmp_path / 'not_a_dir'; blocker.write_text('file where the avatar dir should be')
    with pytest.raises(Exception):
        backup.apply(live, other, {'avatars': str(avatars)}, str(blocker))
    assert _riders(live) == ['Original']
