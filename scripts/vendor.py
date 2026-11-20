"""Fetch the browser libraries into static/vendor/, so pages load them from this server and no page asks a CDN for anything.

    python scripts/vendor.py

Each package comes from the npm registry, its tarball checked against the registry's sha512 before anything is unpacked, and only the
files a page uses are kept, with the package's licence. To bump one, change its version in PACKAGES, run this, change the paths in the
templates that load it (grep for static/vendor; tests/test_security_headers.py checks each one is there) and delete the old folder.
"""
import base64
import hashlib
import io
import shutil
import sys
import tarfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / 'static' / 'vendor'

# name, version, the files kept (paths inside the package; a folder keeps everything under it)
PACKAGES = [
    ('chart.js', '4.4.0', ['dist/chart.umd.js', 'LICENSE.md']),
    ('leaflet', '1.9.4', ['dist/leaflet.js', 'dist/leaflet.css', 'dist/images', 'LICENSE']),
    ('html5-qrcode', '2.3.8', ['html5-qrcode.min.js', 'LICENSE']),
]


def fetch(name, version, keep):
    meta = requests.get(f'https://registry.npmjs.org/{name}/{version}', timeout=30)
    meta.raise_for_status()
    dist = meta.json()['dist']
    data = requests.get(dist['tarball'], timeout=60).content
    got = 'sha512-' + base64.b64encode(hashlib.sha512(data).digest()).decode()
    if got != dist['integrity']:
        sys.exit(f'{name}@{version}: the tarball does not match the registry checksum')
    dest = VENDOR / f'{name}-{version}'
    shutil.rmtree(dest, ignore_errors=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for m in tar.getmembers():
            rel = m.name.removeprefix('package/')
            if not m.isfile() or not any(rel == k or rel.startswith(k + '/') for k in keep):
                continue
            out = dest / rel.removeprefix('dist/')
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(tar.extractfile(m).read())
    print(f'{name}@{version} -> {dest.relative_to(ROOT)}')


if __name__ == '__main__':
    for name, version, keep in PACKAGES:
        fetch(name, version, keep)
