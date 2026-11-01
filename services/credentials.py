"""Per-install signing key and admin login. Anything unset or still a publicly-known placeholder (the old
Compose / .env.example values) is replaced by a random value generated once and kept beside the database, so a
default install is never reachable with a guessable key or password. Real values from the environment win."""
import hashlib
import hmac
import json
import logging
import os
import secrets
from collections import namedtuple

from werkzeug.security import check_password_hash, generate_password_hash

log = logging.getLogger(__name__)

PLACEHOLDER_KEYS = {'', 'dev-secret', 'change-me-please', 'change-me-to-a-random-string'}
PLACEHOLDER_PASSWORDS = {'', 'changeme', 'password', 'admin'}


def _data_dir():
    from config import Config
    return os.path.dirname(os.path.abspath(Config.DATABASE.replace('sqlite:///', '')))


def _path(name):
    return os.path.join(_data_dir(), name)


def _write_private(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(text)


def secret_key(env_value, db_path):
    """Env value if it's a real secret, else a persisted random key. Takes the db path explicitly because the
    Config class calls this while it is still being defined."""
    if env_value not in PLACEHOLDER_KEYS:
        return env_value
    path = os.path.join(os.path.dirname(os.path.abspath(db_path)), '.secret_key')
    try:
        with open(path) as f:
            key = f.read().strip()
        if key:
            return key
    except FileNotFoundError:
        pass
    key = secrets.token_hex(32)
    try:
        _write_private(path, key)
    except OSError as e:
        log.warning('Could not persist signing key (%s) — sessions will reset on restart', e)
    return key


def _login_file():
    return _path('.admin_login')


# The saved login (.admin_login) is JSON: {username, password_hash, env_sig}, plus "generated" while the password is the
# one made for first login, and "old_av" after the upgrade from a plain password. password_hash is werkzeug's
# "scrypt:...$salt$hash" string, so a future User table can take username and password_hash over as they are.
Login = namedtuple('Login', 'username password_hash env_password generated old_av')
Login.__doc__ = ('The login in force: password_hash when it comes from .admin_login, else env_password (the environment\'s, '
                 'which is plain there anyway).')

MIN_PASSWORD = 10

_unsaved = None      # the login file's contents when the data folder wouldn't take them: kept for the life of the process
_generated = None    # the generated password in plain, while it's in force and this process made it (Windows tray, console)


def _env_sig():
    """Fingerprint of the credentials currently supplied through the environment (Compose / .env)."""
    return hashlib.sha256(f"{os.environ.get('APP_USERNAME', '')}\0{os.environ.get('APP_PASSWORD', '')}".encode()).hexdigest()[:16]


def _env_user():
    return os.environ.get('APP_USERNAME', '').strip() or 'admin'


def _old_av(username, password):
    """auth_version as it was while the password was kept plain."""
    return hashlib.sha256(f'{username}\0{password}'.encode()).hexdigest()[:16]


def _read_login_file():
    if _unsaved is not None:
        return _unsaved
    try:
        with open(_login_file()) as f:
            d = json.load(f)
        return d if isinstance(d, dict) and (d.get('password_hash') or d.get('password')) else None
    except (FileNotFoundError, ValueError, OSError):
        return None


def _save(d):
    """Write the login file. If the data folder won't take it (read-only), keep it in memory until Headwind restarts."""
    global _unsaved
    try:
        _write_private(_login_file(), json.dumps(d))
        _unsaved = None
        return True
    except OSError as e:
        _unsaved = d
        log.warning('Could not save the admin login to %s (%s): it is kept in memory until Headwind restarts', _login_file(), e)
        return False


def _saved_login():
    """The login file, with a plain password from before hashing replaced by its hash (start-up does this first)."""
    d = _read_login_file()
    if d and not d.get('password_hash'):
        pw = d.pop('password')
        d['password_hash'] = generate_password_hash(pw)
        d['old_av'] = generate_password_hash(_old_av(d.get('username') or _env_user(), pw))   # sessions from before stay signed in
        if _save(d):
            log.info('The admin password in %s is now stored as a hash', _login_file())
    return d


def admin_login():
    """The Login in force. One rule: the saved login (first-boot generated, or changed in Settings) wins for as long as
    the environment credentials are the same ones it was saved against; if the operator edits the environment/.env to
    something new, that wins instead. So a Settings password change survives container recreation even when Compose
    keeps supplying the original credentials, but editing .env still takes effect (the way back in after a forgotten
    password)."""
    env_user = _env_user()
    env_pw = os.environ.get('APP_PASSWORD', '')
    env_real = env_pw not in PLACEHOLDER_PASSWORDS
    d = _saved_login()
    if d:
        recorded = d.get('env_sig')
        # files written before env_sig existed: honour them only in the old situation (placeholder env)
        if recorded == _env_sig() or (recorded is None and not env_real):
            return Login(d.get('username') or env_user, d['password_hash'], None, bool(d.get('generated')), d.get('old_av'))
    if env_real:
        return Login(env_user, None, env_pw, False, None)
    return _generate(env_user)


def _generate(username):
    global _generated
    pw = secrets.token_urlsafe(12)
    d = {'username': username, 'password_hash': generate_password_hash(pw), 'env_sig': _env_sig(), 'generated': True}
    kept = (f'Only a hash of it is kept, in {_login_file()}.' if _save(d)
            else "It couldn't be saved, so it works until Headwind restarts.")
    _generated = pw
    log.warning('\n%s\n  No admin password configured — generated one for first login:\n    username: %s\n    password: %s\n'
                '  Change it under Settings; this one stops working then. %s\n%s', '=' * 64, username, pw, kept, '=' * 64,
                extra={'console_only': True})         # shown in `docker logs` as is, never written to the log file (services/logs.py)
    return Login(username, d['password_hash'], None, True, None)


def generated_password():
    """The generated first-login password, while it's still the one in force and this process made it; else None."""
    return _generated if _generated and admin_login().generated else None


def check_password(password):
    login = admin_login()
    if login.password_hash:
        return check_password_hash(login.password_hash, password)
    return hmac.compare_digest(password.encode(), login.env_password.encode())


def check(username, password):
    ok_u = hmac.compare_digest(username.encode(), admin_login().username.encode())
    ok_p = check_password(password)      # checked whatever the username, so a wrong one takes as long
    return ok_u and ok_p


def save_login(username, password, generated=False):
    """Persist changed login details: blank keeps the current one. Records the environment credentials in force, so
    the saved login keeps winning until the operator changes the environment. Raises OSError if it can't be written."""
    global _unsaved, _generated
    cur = admin_login()
    if password:
        pw_hash = generate_password_hash(password)
    else:
        pw_hash = cur.password_hash or generate_password_hash(cur.env_password)
    d = {'username': username or cur.username, 'password_hash': pw_hash, 'env_sig': _env_sig()}
    if generated or (cur.generated and not password):
        d['generated'] = True
    _write_private(_login_file(), json.dumps(d))
    _unsaved = None
    if password:
        _generated = password if generated else None


def new_password():
    """A new random password in place of the current one, for someone at the server who has lost theirs (Windows tray)."""
    pw = secrets.token_urlsafe(12)
    save_login(None, pw, generated=True)
    return pw


def auth_version():
    """Changes whenever the login username/password changes, so existing sessions stop being valid. Built from the
    salted hash (or, for the environment's password, keyed with SECRET_KEY): it goes in the session cookie, which
    anyone holding it can read, so it mustn't be a quick hash of the password itself."""
    login = admin_login()
    if login.password_hash:
        return hashlib.sha256(f'{login.username}\0{login.password_hash}'.encode()).hexdigest()[:16]
    from config import Config
    return hmac.new(str(Config.SECRET_KEY).encode(), f'{login.username}\0{login.env_password}'.encode(),
                    hashlib.sha256).hexdigest()[:16]


def signed_in_before_hashing(av):
    """True when `av` is the session version a sign-in gave before passwords were hashed, for the login still in force,
    so check_login can move that session to the new version instead of signing it out."""
    if not av:
        return False
    login = admin_login()
    if login.password_hash:
        return bool(login.old_av) and check_password_hash(login.old_av, av)
    return hmac.compare_digest(av, _old_av(login.username, login.env_password))
