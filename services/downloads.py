"""Files made in the background for the person to download when they're ready: a request that did the work itself could run past a reverse
proxy's timeout (Cloudflare's is 100 s) on a big database or a slow box. The page starts one, polls status(), and offers the download; the
pill at the top of every page (notices(), /tasks/background) says when it's ready, wherever the person has gone meanwhile.

One job per kind at a time. Gunicorn runs a single worker (Dockerfile), so the module-level state is seen by every request, as the import's
is (routes/import_rides._Job). The file is written beside the database in prepared-downloads/ (not the container's /tmp, which may not
have room for a copy of the database), and kept for a day so it can be fetched again, then removed: a day after it was made, when the
next one of its kind is made, or at the next start (clear()). A run shows on the Tasks page through services/tasks.run."""
import logging
import os
import shutil
import threading
import time
from datetime import datetime

log = logging.getLogger(__name__)

FOLDER = 'prepared-downloads'      # removed whole at start: a name nothing else uses
KEEP_SECS = 24 * 3600

_lock = threading.Lock()
# kind -> {'state': 'running' | 'ready' | 'failed', 'label', 'page', 'url', 'started', 'finished', 'progress', 'path', 'name', 'size',
#          'error', 'dismissed'}
_jobs = {}


def folder(database):
    path = os.path.join(os.path.dirname(os.path.abspath(database)), FOLDER)
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def size_text(n):
    """1.4 GB, 928 MB, 3.2 MB."""
    if n >= 2 ** 30:
        return f'{n / 2 ** 30:.1f} GB'
    return f'{n / 2 ** 20:.0f} MB' if n >= 10 * 2 ** 20 else f'{max(n / 2 ** 20, 0.1):.1f} MB'


def _spawn(fn):
    threading.Thread(target=fn, daemon=True, name='download').start()


def _expire_later(kind, path):
    def wait():
        time.sleep(KEEP_SECS)
        _expire(kind, path)
    threading.Thread(target=wait, daemon=True, name='download-expiry').start()


def _expire(kind, path):
    with _lock:
        job = _jobs.get(kind)
        if job and job.get('path') == path and job['state'] != 'running':
            _remove(job)
            _jobs[kind] = None


def _remove(job):
    if job and job.get('path'):
        try:
            os.remove(job['path'])
        except FileNotFoundError:
            pass


def start(app, kind, label, make, download_name, page, url, notify=False):
    """Make a file in the background: make(work_dir, report) writes it under work_dir and returns its path, calling report(text, pct=None)
    to say how far it's got. download_name is what the browser saves it as; page is where its card is, url where it's downloaded. notify: say
    through ntfy when it's ready or has failed. Returns False when one of this kind is already being made."""
    with _lock:
        if (_jobs.get(kind) or {}).get('state') == 'running':
            return False
        _remove(_jobs.get(kind))                 # the one before: only the newest is kept
        about = {'label': label, 'page': page, 'url': url, 'started': time.time()}
        _jobs[kind] = {**about, 'state': 'running', 'progress': None}
    database = app.config['DATABASE']

    def report(text, pct=None):
        with _lock:
            if (_jobs.get(kind) or {}).get('state') == 'running':
                _jobs[kind].update(progress=text, pct=pct)

    def work():
        from database import get_db
        from services import tasks
        work_dir = os.path.join(folder(database), f'.making-{kind}')
        shutil.rmtree(work_dir, ignore_errors=True)
        os.makedirs(work_dir, mode=0o700)
        job = {**about, 'state': 'failed'}
        try:
            with app.app_context(), tasks.run(get_db(), f'download:{kind}', label) as t:
                made = make(work_dir, report)
                path = os.path.join(folder(database), f'{kind}-{datetime.now():%Y%m%d-%H%M%S}.zip')
                os.replace(made, path)
                size = os.path.getsize(path)
                t.result = f'{size_text(size)}, ready to download for a day'
                job = {**job, 'state': 'ready', 'path': path, 'name': download_name, 'size': size}
        except Exception as e:                  # logged as failed by tasks.run
            job['error'] = str(e)[:300]
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
            job['finished'] = time.time()
            with _lock:
                _jobs[kind] = job
        if job['state'] == 'ready':
            _expire_later(kind, job['path'])
        if notify:
            _notify(app, job)
    _spawn(work)
    return True


def _notify(app, job):
    try:
        from services.notify import send_notification
        with app.app_context():
            app_url = (app.config.get('APP_URL') or '').rstrip('/')
            if job['state'] == 'ready':
                send_notification(f"{job['label']} ready", f"{size_text(job['size'])}, kept for a day.", f"{app_url}{job['page']}" if app_url else None)
            else:
                send_notification(f"{job['label']} failed", job.get('error') or 'See the Tasks page.', f'{app_url}/tasks' if app_url else None)
    except Exception:
        log.warning('Notification of a finished download failed', exc_info=True)


def _current(kind):
    """The job, or None once its file has gone (a day old, or deleted by hand). Called with _lock held."""
    job = _jobs.get(kind)
    if job and job['state'] == 'ready' and (time.time() - job['finished'] > KEEP_SECS or not os.path.exists(job['path'])):
        _remove(job)
        job = _jobs[kind] = None
    return job


def _public(job):
    out = {k: job.get(k) for k in ('state', 'label', 'page', 'url', 'started', 'finished', 'progress', 'pct', 'size', 'error')}
    if job.get('size') is not None:
        out['size_text'] = size_text(job['size'])
    return out


def status(kind):
    """{'state': 'none' | 'running' | 'ready' | 'failed', ...} for the page: progress while running, size in bytes (and as size_text) and
    finished (epoch seconds) when ready."""
    with _lock:
        job = _current(kind)
        return _public(job) if job else {'state': 'none'}


def jobs(dismissed=True):
    """{kind: status} of every job there is (for the Tasks page). dismissed=False leaves out a finished one whose notice has been seen."""
    with _lock:
        current = {kind: _current(kind) for kind in list(_jobs)}
        return {kind: _public(job) for kind, job in current.items() if job and (dismissed or not job.get('dismissed'))}


def notices():
    """The jobs to show in the pill at the top of the page: running, or finished and not yet dismissed."""
    return jobs(dismissed=False)


def dismiss(kind):
    """The pill's notice has been seen (or its file fetched). The file stays."""
    with _lock:
        job = _jobs.get(kind)
        if job and job['state'] != 'running':
            job['dismissed'] = True


def ready(kind):
    """(path, download name) of the finished file, or None."""
    with _lock:
        job = _current(kind)
        if not job or job['state'] != 'ready':
            return None
        return job['path'], job['name']


def discard(kind):
    with _lock:
        job = _jobs.get(kind)
        if job and job['state'] != 'running':
            _remove(job)
            _jobs[kind] = None


def clear(database):
    """At start: what the last run left (its jobs went with the process)."""
    path = os.path.join(os.path.dirname(os.path.abspath(database)), FOLDER)
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
