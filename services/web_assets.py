"""Static files with versioned URLs and long cache lifetimes, and gzip for pages, JSON and static text.

url_for('static', filename=...) gets ?v=<hash of the file>, so a browser keeps a file for a year and fetches it again only when it
changes (static_version). A URL without ?v= (a hand-written /static/... path, the service worker, the manifests) keeps Flask's
default: the browser asks each time and gets a 304 while it hasn't changed.

Gunicorn and Waitress send nothing compressed, so compress() gzips text responses the browser accepts gzip for. Streamed responses
(the import's events, CSV downloads) and files that are already compressed (images, zips) are left alone. Static text files are
compressed once and kept in memory until the file changes.
"""
import gzip
import hashlib
import os
import threading

from flask import request
from werkzeug.security import safe_join

YEAR = 365 * 24 * 3600
MIN_SIZE = 1024             # smaller than this, gzip's header and the work cost more than they save
_TEXT = {'text/html', 'text/css', 'text/plain', 'text/csv', 'text/javascript', 'application/javascript', 'application/json',
         'application/manifest+json', 'application/xml', 'application/gpx+xml', 'image/svg+xml'}
_STATIC_MAX = 4 * 1024 * 1024    # static files bigger than this aren't kept compressed in memory

_lock = threading.Lock()
_versions = {}              # path -> (mtime_ns, size, hash)
_gzipped = {}               # path -> (mtime_ns, size, gzipped bytes)


def static_version(folder, filename):
    """A short hash of the file's contents for its ?v=, or None when there's no such file. Recomputed only when the file changes."""
    path = safe_join(folder, filename)
    if not path:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    hit = _versions.get(path)
    if hit and hit[:2] == key:
        return hit[2]
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 16), b''):
            h.update(chunk)
    v = h.hexdigest()[:10]
    with _lock:
        _versions[path] = key + (v,)
    return v


def cache_static(resp):
    """A static file asked for by its versioned URL can be kept for a year: a new version has a new URL."""
    if request.endpoint == 'static' and request.args.get('v') and resp.status_code in (200, 304):
        resp.headers['Cache-Control'] = f'public, max-age={YEAR}, immutable'
    return resp


def _static_gzipped(folder):
    """The requested static file gzipped, from memory while it hasn't changed, or None (too big, gone, outside the folder)."""
    path = safe_join(folder, (request.view_args or {}).get('filename') or '')
    if not path:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    if st.st_size > _STATIC_MAX:
        return None
    key = (st.st_mtime_ns, st.st_size)
    hit = _gzipped.get(path)
    if hit and hit[:2] == key:
        return hit[2]
    with open(path, 'rb') as f:
        body = gzip.compress(f.read(), compresslevel=9)
    with _lock:
        _gzipped[path] = key + (body,)
    return body


def compress(resp, static_folder):
    if (resp.status_code != 200 or resp.mimetype not in _TEXT or 'Content-Encoding' in resp.headers
            or request.method == 'HEAD' or request.accept_encodings['gzip'] <= 0):
        return resp
    if request.endpoint == 'static':
        body = _static_gzipped(static_folder)
        if body is None:
            return resp
        if hasattr(resp.response, 'close'):
            resp.response.close()     # the open file send_file was going to stream
        resp.direct_passthrough = False
        resp.set_data(body)
    elif resp.is_streamed or resp.direct_passthrough:
        return resp
    else:
        data = resp.get_data()
        if len(data) < MIN_SIZE:
            return resp
        resp.set_data(gzip.compress(data, compresslevel=6))
    resp.headers['Content-Encoding'] = 'gzip'
    resp.vary.add('Accept-Encoding')
    etag, weak = resp.get_etag()
    if etag and not weak:
        resp.set_etag(etag, weak=True)    # the same file, sent another way: a strong ETag would have to differ
    return resp
