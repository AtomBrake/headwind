"""Logging for fault finding: one setup for the whole app, so a bug report can be traced from the logs instead of starting with "what did you click?".

- Level and format from the environment: LOG_LEVEL (default INFO; DEBUG for a fault), LOG_FORMAT=json for one JSON object per line, and
  LOG_CONSOLE_LEVEL to keep stderr quieter than the file (the Windows launcher's console).
- A rotating file beside the database (logs/headwind.log, 5 MB × 5) as well as stderr, so a Pi user can send it without `docker logs`.
  LOG_DIR moves it; LOG_DIR=off turns it off.
- Every line carries an id: the request's (also sent back as X-Request-Id and quoted on the error page) or a background job's (t<TaskLog id>,
  so the Tasks page can point at the lines of a failed run). '-' outside both.
- One line per request (init_app), one per outbound HTTP call (requests is patched once, so Strava, Garmin, the weather, food lookup and Home
  Assistant all show up) and a log of every unhandled error with its request.
- Tokens, keys and passwords are blanked in every line, tracebacks included (redact), as a backstop: nothing should log them in the first place.
  The one exception is the generated first-login password (services/credentials.py), logged with extra={'console_only': True}: it reaches
  stderr (`docker logs`) unredacted and never the file."""
import contextvars
from contextlib import contextmanager
import json
import logging
import logging.handlers
import os
import re
import secrets
import time
from urllib.parse import urlsplit

log = logging.getLogger(__name__)
http_log = logging.getLogger('headwind.http')

FILE_NAME = 'headwind.log'
FILE_BYTES = 5 * 1024 * 1024
FILE_COUNT = 5
SLOW_REQUEST = 1.0          # seconds: a request slower than this is logged at INFO even when it's a plain GET
SLOW_CALL = 3.0             # the same for an outbound call
NOISY = ('urllib3', 'requests', 'garminconnect', 'garth', 'paho', 'httpx', 'httpcore', 'openai', 'anthropic', 'PIL', 'fitparse', 'werkzeug')

_ctx = contextvars.ContextVar('headwind_log_id', default=None)
_handlers = []              # the handlers setup() added, so a second call (a test's create_app) replaces them instead of doubling every line
_file_path = None


# ── Ids ──────────────────────────────────────────────────────────
def current_id():
    return _ctx.get()


def bind(log_id):
    """Every line from this thread carries log_id until reset(token) or bind(None)."""
    return _ctx.set(log_id)


def reset(token):
    try:
        _ctx.reset(token)
    except (ValueError, RuntimeError):      # made in another context (a thread pool): just clear it
        _ctx.set(None)


def new_request_id():
    return secrets.token_hex(4)


# ── Redaction ────────────────────────────────────────────────────
_REDACT = [
    (re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+'), 'Bearer ***'),
    (re.compile(r'\bhw_[A-Za-z0-9_-]{16,}'), 'hw_***'),                         # phone app device tokens
    (re.compile(r'\bsk-[A-Za-z0-9_-]{16,}'), 'sk-***'),                         # OpenAI / Anthropic keys
    # name=value, name: value, "name": "value", ?name=value — garminPassword, claudeKey, access_token, X-Api-Key, appid, ...
    (re.compile(r'(?i)([\w-]*(?:password|passwd|secret|token|api[_-]?key|apikey|appid|key|authorization|cookie)["\']?\s*[=:]\s*["\']?)'
                r'(?!\*\*\*)([^\s"\'&,;}\])]+)'), r'\1***'),
]


def redact(text):
    for rx, sub in _REDACT:
        text = rx.sub(sub, text)
    return text


# ── Formatting ───────────────────────────────────────────────────
class _IdFilter(logging.Filter):
    def filter(self, record):
        record.log_id = _ctx.get() or '-'
        return True


class _NotConsoleOnly(logging.Filter):
    def filter(self, record):
        return not getattr(record, 'console_only', False)


def _redact_unless_console_only(record, text):
    return text if getattr(record, 'console_only', False) else redact(text)


class _TextFormatter(logging.Formatter):
    def __init__(self):
        super().__init__('%(asctime)s %(levelname)s [%(log_id)s] %(name)s: %(message)s')

    def format(self, record):
        return _redact_unless_console_only(record, super().format(record))


class _JsonFormatter(logging.Formatter):
    def format(self, record):
        out = {'time': self.formatTime(record), 'level': record.levelname, 'id': getattr(record, 'log_id', '-'),
               'logger': record.name, 'thread': record.threadName, 'message': record.getMessage()}
        if record.exc_info:
            out['exception'] = self.formatException(record.exc_info)
        return _redact_unless_console_only(record, json.dumps(out, ensure_ascii=False))


def level():
    name = (os.environ.get('LOG_LEVEL') or 'INFO').strip().upper()
    return logging.getLevelName(name) if isinstance(logging.getLevelName(name), int) else logging.INFO


def log_dir(database=None):
    """Where the log files go: LOG_DIR, else logs/ beside the database (/data/logs in Docker). None when LOG_DIR=off."""
    d = (os.environ.get('LOG_DIR') or '').strip()
    if d.lower() in ('off', 'none', '0', 'false'):
        return None
    if d:
        return d
    if database:
        return os.path.join(os.path.dirname(os.path.abspath(database)), 'logs')
    return None


def file_path():
    """The current log file, or None when there isn't one."""
    return _file_path


def files():
    """The log file and its rotated copies, newest first."""
    if not _file_path:
        return []
    out = [_file_path] + [f'{_file_path}.{i}' for i in range(1, FILE_COUNT + 1)]
    return [p for p in out if os.path.exists(p)]


def setup(database=None):
    """Configure the root logger. Safe to call again (each create_app does): it replaces its own handlers, so the file follows the database."""
    global _file_path
    root = logging.getLogger()
    lvl = level()
    root.setLevel(lvl)
    fmt = _JsonFormatter() if (os.environ.get('LOG_FORMAT') or '').lower() == 'json' else _TextFormatter()
    for h in _handlers:
        root.removeHandler(h)
        h.close()
    _handlers.clear()
    for h in list(root.handlers):          # a basicConfig handler from before setup (or a library's): ours replaces it
        if type(h) is logging.StreamHandler:
            root.removeHandler(h)

    stream = logging.StreamHandler()
    console = (os.environ.get('LOG_CONSOLE_LEVEL') or '').strip().upper()
    if isinstance(logging.getLevelName(console), int):
        stream.setLevel(logging.getLevelName(console))
    _handlers.append(stream)
    _file_path = None
    d = log_dir(database)
    if d:
        try:
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, FILE_NAME)
            fh = logging.handlers.RotatingFileHandler(path, maxBytes=FILE_BYTES, backupCount=FILE_COUNT, encoding='utf-8', delay=True)
            fh.addFilter(_NotConsoleOnly())
            _handlers.append(fh)
            _file_path = path
        except OSError as e:
            print(f'Headwind: could not open a log file in {d}: {e}')     # logging isn't set up yet
    for h in _handlers:
        h.setFormatter(fmt)
        h.addFilter(_IdFilter())
        root.addHandler(h)

    for name in NOISY:                     # their DEBUG/INFO chatter only when we ask for DEBUG; urllib3's retry warnings still show
        logging.getLogger(name).setLevel(logging.DEBUG if lvl <= logging.DEBUG else logging.WARNING)
    _install_http()


# ── Outbound calls ───────────────────────────────────────────────
_SERVICES = (('strava', 'Strava'), ('garmin', 'Garmin'), ('open-meteo', 'weather'), ('openfoodfacts', 'food lookup'),
             ('anthropic', 'AI'), ('openai', 'AI'), ('hub.docker.com', 'update check'), ('arcgisonline', 'map tiles'))


def service_of(host):
    host = (host or '').lower()
    for part, name in _SERVICES:
        if part in host:
            return name
    return host or '?'


def call_line(method, url, outcome, seconds):
    """'Garmin GET connectapi.garmin.com/usersummary-service/... → 200 in 0.41s', without the query string (keys often ride in it)."""
    u = urlsplit(url)
    service = service_of(u.hostname)
    return f'{"" if service == u.hostname else service + " "}{method} {u.hostname or ""}{u.path} → {outcome} in {seconds:.2f}s'


def outbound(method, url, started, status=None, error=None):
    """Log one finished outbound call: DEBUG when quick and fine, INFO when slow or refused, WARNING when it didn't complete."""
    took = time.monotonic() - started
    if error is not None:
        http_log.warning(call_line(method, url, f'failed ({type(error).__name__}: {error})', took))
    else:
        lvl = logging.INFO if (isinstance(status, int) and status >= 400) or took > SLOW_CALL else logging.DEBUG
        http_log.log(lvl, call_line(method, url, status, took))


@contextmanager
def timed(method, url):
    """An outbound call that doesn't go through requests (urllib, paho): with logs.timed('GET', url): ..."""
    t0 = time.monotonic()
    try:
        yield
    except Exception as e:
        outbound(method, url, t0, error=e)
        raise
    outbound(method, url, t0, status='ok')


_http_installed = False


def _install_http():
    """Time every requests call (requests.get/post go through Session.send, and so do garminconnect and garth)."""
    global _http_installed
    if _http_installed:
        return
    try:
        import requests
    except ImportError:
        return
    original = requests.Session.send

    def send(self, request, **kw):
        t0 = time.monotonic()
        try:
            resp = original(self, request, **kw)
        except Exception as e:
            outbound(request.method, request.url, t0, error=e)
            raise
        outbound(request.method, request.url, t0, status=resp.status_code)
        return resp

    requests.Session.send = send
    _http_installed = True


# ── Requests ─────────────────────────────────────────────────────
_API_PREFIXES = ('/api/', '/nutrition/api/', '/gear/api/')
_QUIET_ENDPOINTS = {'static', 'avatar_files'}


def init_app(app):
    """Request ids, one line per request, and a logged, quotable error page for anything unhandled. Call first in create_app, so the id is
    set before the other before_request hooks (the login check) run."""
    from flask import g, jsonify, render_template, request
    from werkzeug.exceptions import HTTPException
    req_log = logging.getLogger('headwind.request')

    @app.before_request
    def _start_request():
        g.log_token = bind(new_request_id())
        g.log_started = time.monotonic()

    @app.after_request
    def _log_request(resp):
        log_id = current_id()
        if log_id:
            resp.headers['X-Request-Id'] = log_id
        took = time.monotonic() - getattr(g, 'log_started', time.monotonic())
        # The user's actions (anything but a GET), errors and slow pages at INFO; quick page loads and static files only at DEBUG.
        if request.endpoint in _QUIET_ENDPOINTS:
            lvl = logging.DEBUG
        elif resp.status_code >= 500:
            lvl = logging.ERROR
        elif request.method not in ('GET', 'HEAD', 'OPTIONS') or resp.status_code >= 400 or took > SLOW_REQUEST:
            lvl = logging.INFO
        else:
            lvl = logging.DEBUG
        if req_log.isEnabledFor(lvl):
            extra = []
            if took > SLOW_REQUEST:
                extra.append('slow')
            if resp.mimetype == 'text/event-stream':          # an import or sync's progress: the work runs after this line
                extra.append('streamed: time to first byte')
            if getattr(g, 'device_name', None):            # the phone app (services/device_auth.verify)
                extra.append(f"device {g.device_name!r}, {request.headers.get('User-Agent', '?')}")
            req_log.log(lvl, '%s %s → %s in %.3fs%s', request.method, request.full_path.rstrip('?'), resp.status_code, took,
                        f" ({'; '.join(extra)})" if extra else '')
        return resp

    @app.teardown_request
    def _end_request(exc):
        token = g.pop('log_token', None)
        if token is not None:
            reset(token)

    @app.errorhandler(Exception)
    def _unhandled(e):
        if isinstance(e, HTTPException):           # 404, 405, abort(...): Flask's own pages
            return e
        log_id = current_id() or '-'
        logging.getLogger('headwind.error').exception('Unhandled error in %s %s (endpoint %s)', request.method, request.full_path.rstrip('?'),
                                                     request.endpoint)
        if app.debug:                               # HEADWIND_DEBUG=1: the interactive debugger as before
            raise e
        msg = f'Something went wrong. The error has been logged as {log_id}: quote that if you report it.'
        if request.path.startswith(_API_PREFIXES) or request.is_json or 'application/json' in (request.headers.get('Accept') or ''):
            return jsonify(error=msg, request_id=log_id), 500
        try:
            return render_template('error.html', log_id=log_id), 500
        except Exception:                           # the page itself failed (the database is gone, say): plain text still gives the id
            return msg, 500, {'Content-Type': 'text/plain; charset=utf-8'}
