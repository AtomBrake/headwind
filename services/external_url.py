"""The address this Headwind is reached on from outside the house: what the phone apps pair with, what a friend's instance syncs from, and
where notification links point. It's set in Settings (Settings.externalUrl). An install from before the setting keeps working from the
APP_URL environment variable until the setting is filled in."""
from urllib.parse import urlsplit

from flask import current_app

from database import query_db


def saved():
    """The address saved in Settings, or ''."""
    try:
        row = query_db('SELECT externalUrl FROM Settings WHERE id=1', one=True)
    except Exception:                                   # no Settings row or column yet (a fresh database before migrate_db)
        return ''
    return ((row['externalUrl'] if row else '') or '').strip().rstrip('/')


def _env():
    return (current_app.config.get('APP_URL') or '').strip().rstrip('/')


def get():
    """The saved address, else APP_URL, else ''. No trailing slash."""
    return saved() or _env()


def source():
    """'setting', 'APP_URL', or '' for none: which one get() returns, for Settings to say."""
    return 'setting' if saved() else ('APP_URL' if _env() else '')


def https():
    """get() when it's an https address, else '': the phone apps only talk https, and a friend's instance needs a public address."""
    url = get()
    return url if url.startswith('https://') else ''


def describe(settings=None):
    """{'url', 'saved', 'source', 'https'} at once, from the Settings row when the caller already has it (one query otherwise)."""
    if settings is None:
        saved_url = saved()
    else:
        saved_url = ((settings['externalUrl'] if 'externalUrl' in settings.keys() else '') or '').strip().rstrip('/')
    url = saved_url or _env()
    return {'url': url, 'saved': saved_url, 'source': 'setting' if saved_url else ('APP_URL' if url else ''),
            'https': url if url.startswith('https://') else ''}


def clean(value):
    """A typed address as it's saved: an absolute http(s) address with no trailing slash, or '' to clear it. Raises ValueError with the reason."""
    url = (value or '').strip().rstrip('/')
    if not url:
        return ''
    if any(c.isspace() for c in url):
        raise ValueError('an address has no spaces in it')
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise ValueError('give the whole address, starting https:// (for example https://headwind.example.com)')
    if parts.query or parts.fragment:
        raise ValueError('give the address on its own, without anything after a ? or #')
    return url
