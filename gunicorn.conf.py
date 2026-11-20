"""Gunicorn reads this from the directory it starts in (/app in the Docker image) as well as its command line (Dockerfile).

Gunicorn's master starts the background worker (services/worker.py) once it's ready, as a process of its own beside the ones serving pages,
and stops it when Gunicorn stops. `--keep` has the worker's process start it again if it stops: the master itself runs no thread, since it
forks the web workers."""
import subprocess
import sys

_worker = {}


def when_ready(server):
    _worker['proc'] = subprocess.Popen([sys.executable, '-m', 'services.worker', '--keep'])


def on_exit(server):
    proc = _worker.get('proc')
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(15)
        except subprocess.TimeoutExpired:
            proc.kill()
