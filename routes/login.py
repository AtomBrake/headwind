import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from database import get_db
from services import credentials
from flask import Blueprint, redirect, render_template, request, session, url_for

load_dotenv(os.environ.get('HEADWIND_ENV') or Path(__file__).parent.parent / '.env', override=True)

bp = Blueprint('login', __name__)
log = logging.getLogger(__name__)

_MAX_FAILS, _WINDOW = 8, 300  # 8 failures per 5 minutes from one address, then it's locked out until the window clears
_MAX_ALL_FAILS = 30           # and 30 from all addresses together locks every sign-in, which no header can get around
# Each failure is a SignInFail row, not this process's memory: with more than one web process, a limit kept in each would multiply.


def _locked_out(db, ip):
    """Reads only, so a sign-in never waits on the write lock behind an import."""
    since = time.time() - _WINDOW
    if db.execute('SELECT COUNT(*) FROM SignInFail WHERE at >= ?', [since]).fetchone()[0] >= _MAX_ALL_FAILS:
        return True
    return db.execute('SELECT COUNT(*) FROM SignInFail WHERE ip=? AND at >= ?', [ip, since]).fetchone()[0] >= _MAX_FAILS


def _failed(db, ip):
    now = time.time()
    db.execute('DELETE FROM SignInFail WHERE at < ?', [now - _WINDOW])     # so the table holds only failures still inside the window
    db.execute('INSERT INTO SignInFail (ip, at) VALUES (?, ?)', [ip, now])
    db.commit()
    if db.execute('SELECT COUNT(*) FROM SignInFail').fetchone()[0] == _MAX_ALL_FAILS:
        log.warning('%d failed sign-ins in %d minutes from all addresses: sign-in is closed to everyone until they age out',
                    _MAX_ALL_FAILS, _WINDOW // 60)


@bp.route('/login', methods=['GET', 'POST'])
def login_page():
    if session.get('logged_in'):
        return redirect(url_for('dashboard.dashboard'))
    error = None
    if request.method == 'POST':
        ip = request.remote_addr or ''
        db = get_db()
        if _locked_out(db, ip):
            return render_template('login.html', error='Too many attempts — try again in a few minutes'), 429
        if credentials.check(request.form.get('username', ''), request.form.get('password', '')):
            session.permanent = True
            session['logged_in'] = True
            session['av'] = credentials.auth_version()
            if db.execute('SELECT 1 FROM SignInFail WHERE ip=?', [ip]).fetchone():
                db.execute('UPDATE SignInFail SET ip=NULL WHERE ip=?', [ip])        # that address starts again; they still count towards all
                db.commit()
            nxt = request.args.get('next') or ''
            # same-origin relative paths only — no //host or scheme-qualified redirects
            if not nxt.startswith('/') or nxt.startswith('//') or '\\' in nxt:
                nxt = url_for('dashboard.dashboard')
            return redirect(nxt)
        _failed(db, ip)
        error = 'Invalid username or password'
    return render_template('login.html', error=error)


@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login.login_page'))
