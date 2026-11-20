"""Files made in the background for the person to download when they're ready: a request that did the work itself could run past a reverse
proxy's timeout (Cloudflare's is 100 s) on a big database or a slow box. The page starts one, polls status(), and offers the download; the
pill at the top of every page (notices(), /tasks/background) says when it's ready, wherever the person has gone meanwhile.

Each is a job (services/jobs.py, kind download:<kind>) the worker runs with the maker its module registered (@maker), one per kind at a time;
how far it's got, and the file once it's made, are in the job's progress, which every process reads. The file is written beside the database
in prepared-downloads/ (not the container's /tmp, which may not have room for a copy of the database), and kept for a day so it can be fetched
again, then removed: when it's next looked at after a day, when the next one of its kind is made, or when the worker starts (clear()). A run
shows on the Tasks page through services/tasks.run."""
import logging
import os
import shutil
import time
from datetime import datetime

from services import jobs as _jobs

log = logging.getLogger(__name__)

FOLDER = 'prepared-downloads'      # nothing else uses the name
KEEP_SECS = 24 * 3600
KINDS = {}                         # kind -> make(args, work_dir, report)


def folder(database):
    path = os.path.join(os.path.dirname(os.path.abspath(database)), FOLDER)
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def size_text(n):
    """1.4 GB, 928 MB, 3.2 MB."""
    if n >= 2 ** 30:
        return f'{n / 2 ** 30:.1f} GB'
    return f'{n / 2 ** 20:.0f} MB' if n >= 10 * 2 ** 20 else f'{max(n / 2 ** 20, 0.1):.1f} MB'


def maker(kind):
    """@downloads.maker('backup') def make(args, work_dir, report): writes the file under work_dir and returns its path, calling report(text,
    pct=None) to say how far it's got; args are what start() was given."""
    def register(fn):
        KINDS[kind] = fn
        _jobs.handler(f'download:{kind}')(lambda job: _make(kind, fn, job))
        return fn
    return register


def start(kind, label, args, download_name, page, url, notify=False):
    """Queue a file to be made: args go to its maker (@maker). download_name is what the browser saves it as; page is where its card is, url
    where it's downloaded. notify: say through ntfy when it's ready or has failed. Returns False when one of this kind is already being made."""
    from database import get_db
    return _jobs.enqueue(get_db(), f'download:{kind}', {'label': label, 'page': page, 'url': url, 'name': download_name, 'notify': notify,
                                                       'make': args}) is not None


def _make(kind, make, job):
    from database import get_db
    from flask import current_app
    from services import tasks
    db = get_db()
    database = current_app.config['DATABASE']
    a = job['args']
    for old in _all(db, kind):                          # only the newest is kept
        if old['id'] != job['id']:
            _remove(old)

    def report(text, pct=None):
        _jobs.progress(db, job['id'], progress=text, pct=pct)

    work_dir = os.path.join(folder(database), f'.making-{kind}')
    shutil.rmtree(work_dir, ignore_errors=True)
    os.makedirs(work_dir, mode=0o700)
    try:
        with tasks.run(db, f'download:{kind}', a['label']) as t:
            made = make(a['make'], work_dir, report)
            path = os.path.join(folder(database), f'{kind}-{datetime.now():%Y%m%d-%H%M%S}.zip')
            os.replace(made, path)
            size = os.path.getsize(path)
            t.result = f'{size_text(size)}, ready to download for a day'
        _jobs.progress(db, job['id'], path=path, size=size, finished=time.time())
    except Exception as e:                              # logged as failed by tasks.run
        if a.get('notify'):
            _notify({**a, 'state': 'failed', 'error': str(e)[:300]})
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    if a.get('notify'):
        _notify({**a, 'state': 'ready', 'size': size})


def _all(db, kind):
    """Every job of this kind there is, newest first, as _jobs rows."""
    return [_jobs.get(db, r[0]) for r in db.execute('SELECT id FROM Job WHERE kind=? ORDER BY id DESC', [f'download:{kind}'])]


def _remove(job):
    path = ((job or {}).get('progress') or {}).get('path')
    if path:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def _notify(job):
    try:
        from services import external_url
        from services.notify import send_notification
        app_url = external_url.get()
        if job['state'] == 'ready':
            send_notification(f"{job['label']} ready", f"{size_text(job['size'])}, kept for a day.", f"{app_url}{job['page']}" if app_url else None)
        else:
            send_notification(f"{job['label']} failed", job.get('error') or 'See the Tasks page.', f'{app_url}/tasks' if app_url else None)
    except Exception:
        log.warning('Notification of a finished download failed', exc_info=True)


def _view(job):
    """The page's view of a job: {'state': 'running' | 'ready' | 'failed', ...}, or None once its file has gone (a day old, deleted by hand,
    or discarded), when the file is removed too."""
    if not job:
        return None
    p, a = job['progress'] or {}, job['args']
    if p.get('discarded'):
        return None
    out = {'label': a['label'], 'page': a['page'], 'url': a['url'], 'progress': p.get('progress'), 'pct': p.get('pct'), 'size': None,
           'error': None, 'started': _epoch(job['createdAt']), 'finished': p.get('finished'), 'dismissed': bool(p.get('dismissed'))}
    if job['state'] in ('queued', 'running'):
        return {**out, 'state': 'running'}
    if job['state'] == 'failed':
        return {**out, 'state': 'failed', 'error': job['error'], 'finished': _epoch(job['finishedAt'])}
    if time.time() - (p.get('finished') or 0) > KEEP_SECS or not os.path.exists(p.get('path') or ''):
        _remove(job)
        return None
    return {**out, 'state': 'ready', 'size': p['size'], 'size_text': size_text(p['size']), 'path': p['path'], 'name': a['name']}


def _epoch(iso):
    return datetime.fromisoformat(iso).timestamp() if iso else None


def _latest(kind):
    from database import get_db
    return _jobs.last(get_db(), f'download:{kind}')


def _public(view):
    return {k: v for k, v in view.items() if k not in ('path', 'name', 'dismissed')}


def status(kind):
    """{'state': 'none' | 'running' | 'ready' | 'failed', ...} for the page: progress while running, size in bytes (and as size_text) and
    finished (epoch seconds) when ready."""
    v = _view(_latest(kind))
    return _public(v) if v else {'state': 'none'}


def jobs(dismissed=True):
    """{kind: status} of every kind that has one (for the Tasks page). dismissed=False leaves out a finished one whose notice has been seen."""
    out = {}
    for kind in KINDS:
        v = _view(_latest(kind))
        if v and (dismissed or not v['dismissed']):
            out[kind] = _public(v)
    return out


def notices():
    """The jobs to show in the pill at the top of the page: running, or finished and not yet dismissed."""
    return jobs(dismissed=False)


def _mark(kind, **fields):
    """Fields into the latest finished job's progress, and that job; None when there's none (or it's still running)."""
    from database import get_db
    job = _latest(kind)
    if not job or job['state'] in ('queued', 'running'):
        return None
    _jobs.progress(get_db(), job['id'], **fields)
    return job


def dismiss(kind):
    """The pill's notice has been seen (or its file fetched). The file stays."""
    _mark(kind, dismissed=True)


def ready(kind):
    """(path, download name) of the finished file, or None."""
    v = _view(_latest(kind))
    if not v or v['state'] != 'ready':
        return None
    return v['path'], v['name']


def discard(kind):
    job = _mark(kind, discarded=True)
    if job:
        _remove(job)


def clear(db, database):
    """When the worker starts: what's in the folder that no finished job offers (half-made files of one cut short, ones of a day ago). Only
    the worker writes there, so a web process starting while it makes one leaves it alone."""
    path = os.path.join(os.path.dirname(os.path.abspath(database)), FOLDER)
    if not os.path.isdir(path):
        return
    keep = {(j['progress'] or {}).get('path') for kind in KINDS for j in _all(db, kind)
            if j['state'] == 'done' and _view(j) is not None}
    for name in os.listdir(path):
        full = os.path.join(path, name)
        if full not in keep:
            shutil.rmtree(full, ignore_errors=True) if os.path.isdir(full) else os.remove(full)
