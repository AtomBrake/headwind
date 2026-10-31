"""Files made in the background for the person to download when they're ready: a request that did the work itself could run past a reverse
proxy's timeout (Cloudflare's is 100 s) on a big database or a slow box. The page starts one, polls status(), and offers the download.

One job per kind at a time. Gunicorn runs a single worker (Dockerfile), so the module-level state is seen by every request, as the import's
is (routes/import_rides._Job). The file is written beside the database in prepared-downloads/ (not the container's /tmp, which may not
have room for a copy of the database), and kept for a day so it can be fetched again, then removed: when the next one of its kind is made,
when it's asked for after that, or at the next start (clear()). A run shows on the Tasks page through services/tasks.run."""
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
_jobs = {}          # kind -> {'state': 'running' | 'ready' | 'failed', 'started', 'finished', 'path', 'name', 'size', 'error'}


def folder(database):
    path = os.path.join(os.path.dirname(os.path.abspath(database)), FOLDER)
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def _spawn(fn):
    threading.Thread(target=fn, daemon=True, name='download').start()


def _remove(job):
    if job and job.get('path'):
        try:
            os.remove(job['path'])
        except FileNotFoundError:
            pass


def start(app, kind, label, make, download_name):
    """Make a file in the background: make(work_dir) writes it under work_dir and returns its path. download_name is what the browser saves
    it as. Returns False when one of this kind is already being made."""
    with _lock:
        if (_jobs.get(kind) or {}).get('state') == 'running':
            return False
        _remove(_jobs.get(kind))                 # the one before: only the newest is kept
        _jobs[kind] = {'state': 'running', 'started': time.time()}
    database = app.config['DATABASE']

    def work():
        from database import get_db
        from services import tasks
        work_dir = os.path.join(folder(database), f'.making-{kind}')
        shutil.rmtree(work_dir, ignore_errors=True)
        os.makedirs(work_dir, mode=0o700)
        job = {'state': 'failed', 'started': _jobs[kind]['started']}
        try:
            with app.app_context(), tasks.run(get_db(), f'download:{kind}', label) as t:
                made = make(work_dir)
                path = os.path.join(folder(database), f'{kind}-{datetime.now():%Y%m%d-%H%M%S}.zip')
                os.replace(made, path)
                size = os.path.getsize(path)
                t.result = f'{size / 2 ** 20:.0f} MB, ready to download for a day'
                job = {**job, 'state': 'ready', 'path': path, 'name': download_name, 'size': size}
        except Exception as e:                  # logged as failed by tasks.run
            job['error'] = str(e)[:300]
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
            job['finished'] = time.time()
            with _lock:
                _jobs[kind] = job
    _spawn(work)
    return True


def status(kind):
    """{'state': 'none' | 'running' | 'ready' | 'failed', ...} for the page: size in bytes and finished (epoch seconds) when ready."""
    with _lock:
        job = _jobs.get(kind)
        if job and job['state'] == 'ready' and (time.time() - job['finished'] > KEEP_SECS or not os.path.exists(job['path'])):
            _remove(job)
            job = _jobs[kind] = None
        if not job:
            return {'state': 'none'}
        return {k: job.get(k) for k in ('state', 'started', 'finished', 'size', 'error')}


def ready(kind):
    """(path, download name) of the finished file, or None."""
    if status(kind)['state'] != 'ready':
        return None
    job = _jobs[kind]
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
