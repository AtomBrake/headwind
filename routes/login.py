import logging
import os
import threading
import time
from collections import deque
from pathlib import Path

from dotenv import load_dotenv
from services import credentials
from flask import Blueprint, redirect, render_template, request, session, url_for

load_dotenv(os.environ.get('HEADWIND_ENV') or Path(__file__).parent.parent / '.env', override=True)

bp = Blueprint('login', __name__)
log = logging.getLogger(__name__)

_fails = {}                 # client address -> times of its recent failed sign-ins
_all_fails = deque()        # every recent failure, whatever address it came from (or claimed, through a proxy header)
_fails_lock = threading.Lock()
_MAX_FAILS, _WINDOW = 8, 300  # 8 failures per 5 minutes from one address, then it's locked out until the window clears
_MAX_ALL_FAILS = 30           # and 30 from all addresses together locks every sign-in, which no header can get around


def _prune(now):
    while _all_fails and now - _all_fails[0] > _WINDOW:
        _all_fails.popleft()
    for ip in [ip for ip, q in _fails.items() if not q or now - q[-1] > _WINDOW]:
        del _fails[ip]      # so the dict holds only addresses still inside the window


def _locked_out(ip):
    now = time.monotonic()
    with _fails_lock:
        _prune(now)
        if len(_all_fails) >= _MAX_ALL_FAILS:
            return True
        q = _fails.get(ip)
        while q and now - q[0] > _WINDOW:
            q.popleft()
        return bool(q) and len(q) >= _MAX_FAILS


def _failed(ip):
    now = time.monotonic()
    with _fails_lock:
        _fails.setdefault(ip, deque()).append(now)
        _all_fails.append(now)
        if len(_all_fails) == _MAX_ALL_FAILS:
            log.warning('%d failed sign-ins in %d minutes from all addresses: sign-in is closed to everyone until they age out',
                        _MAX_ALL_FAILS, _WINDOW // 60)


@bp.route('/login', methods=['GET', 'POST'])
def login_page():
    if session.get('logged_in'):
        return redirect(url_for('dashboard.dashboard'))
    error = None
    if request.method == 'POST':
        ip = request.remote_addr or ''
        if _locked_out(ip):
            return render_template('login.html', error='Too many attempts — try again in a few minutes'), 429
        if credentials.check(request.form.get('username', ''), request.form.get('password', '')):
            session.permanent = True
            session['logged_in'] = True
            session['av'] = credentials.auth_version()
            with _fails_lock:
                _fails.pop(ip, None)
            nxt = request.args.get('next') or ''
            # same-origin relative paths only — no //host or scheme-qualified redirects
            if not nxt.startswith('/') or nxt.startswith('//') or '\\' in nxt:
                nxt = url_for('dashboard.dashboard')
            return redirect(nxt)
        _failed(ip)
        error = 'Invalid username or password'
    return render_template('login.html', error=error)


@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login.login_page'))
