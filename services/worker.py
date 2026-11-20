"""The worker: Headwind's background work in a process of its own, beside the web server, so it runs once however many processes serve pages,
and its parsing and matching don't hold up a page behind Python's one lock per process.

It runs the timed loops (app.start_loops: the Garmin and Home Assistant heartbeats, the Garmin history, MQTT commands, the friends' automatic
sync, the track summaries) and the jobs pages queue (services/jobs.py), each in a thread, up to MAX_AT_ONCE jobs at a time and one of each kind.

Started by Gunicorn's master in Docker (gunicorn.conf.py runs `python -m services.worker --keep`, which starts it again if it stops), or as a thread of the
one process by the Windows app and `python app.py` (start_in_process). At its start it marks what the last one left running as stopped."""
import logging
import threading
import time

log = logging.getLogger(__name__)

MAX_AT_ONCE = 4         # jobs running at once (a long import needn't hold up a Garmin check)
_IDLE = 1.0             # seconds between looks for a queued job
BEAT = 30               # seconds between heartbeats (jobs.beat): the Tasks page says when the worker has stopped


def serve(app, stop=None):
    """Run the loops, then jobs as they're queued, until stop (a threading.Event) is set; for ever without one."""
    from database import get_db
    from services import jobs, tasks
    import app as app_module
    jobs.bind(app)
    with app.app_context():
        db = get_db()
        tasks.close_orphans(db)
        jobs.fail_orphans(db)
        db.commit()
    app_module.start_loops(app)
    log.info('Background worker started')
    running = {}                                        # kind -> thread
    beat = 0.0
    while not (stop and stop.is_set()):
        running = {k: t for k, t in running.items() if t.is_alive()}
        try:
            if time.monotonic() - beat >= BEAT:
                with app.app_context():
                    jobs.beat(get_db())
                beat = time.monotonic()
            job = None
            if len(running) < MAX_AT_ONCE:
                with app.app_context():
                    job = jobs.claim(get_db(), skip_kinds=running)
            if job:
                t = threading.Thread(target=jobs.run, args=(app, job), daemon=True, name=f"job-{job['kind']}")
                t.start()
                running[job['kind']] = t
                continue
        except Exception:
            log.warning('The background worker could not read its queue', exc_info=True)
        time.sleep(_IDLE)


def start_in_process(app):
    """The worker as a thread of this process: the Windows app and `python app.py`, which have one process."""
    threading.Thread(target=serve, args=(app,), daemon=True, name='worker').start()


def keep():
    """`python -m services.worker --keep` (gunicorn.conf.py): run the worker as a child process and start it again 5 s after it stops, until
    this one is told to stop (SIGTERM, from Gunicorn stopping), which it passes on."""
    import signal
    import subprocess
    import sys
    state = {'child': None, 'stopping': False}

    def stop(signum, frame):
        state['stopping'] = True
        if state['child'] and state['child'].poll() is None:
            state['child'].terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not state['stopping']:
        state['child'] = subprocess.Popen([sys.executable, '-m', 'services.worker'])
        code = state['child'].wait()
        if state['stopping']:
            break
        log.warning('The background worker stopped (exit %s); starting it again in 5 s', code)
        time.sleep(5)


def main(argv):
    if argv == ['--keep']:
        return keep()
    from app import create_app
    serve(create_app())


if __name__ == '__main__':
    import sys
    from services import worker                     # the module the rest imports, not a second copy of it as __main__
    worker.main(sys.argv[1:])
