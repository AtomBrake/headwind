#!/usr/bin/env python3
"""Rebuild the public demo's database and hand it to the running demo: one command, run where the real data is.

    python3 demo/publish_demo.py                 # extract, generate, audit, copy, reset
    python3 demo/publish_demo.py --no-push       # everything but the copy: look at demo/out first
    python3 demo/publish_demo.py --push-only     # copy what was built last (after an audit that passed)

1. demo/extract_patterns.py: the real database -> patterns.json (numbers only).
2. demo/generate_demo_db.py: patterns.json -> pristine.db and bikeimg/, from generated tracks. Needs the routing engine (demo/brouter.sh start).
3. demo/audit_demo_db.py: stops here if any name, id, setting, token or place of the real database got through.
4. The copy: pristine.db (one file, no WAL) and bikeimg/ into the demo's out/ folder, which its container mounts read-only at /demo, swapped in
   whole so the demo never reads half a file.
5. reset.flag in the demo's data volume: its worker resets from the new copy within 30 s, with no restart.

The real database never leaves this machine; the demo's machine gets only the audited output, and builds nothing.

Settings, from the environment or from demo/publish.env (KEY=value lines; ignored by git, as it names your machines):
  HEADWIND_SOURCE_DB    the real database (read-only)                                  required
  DEMO_PUSH_VIA         ssh: straight to the demo's machine; pct: through a Proxmox host into container DEMO_PUSH_CT
  DEMO_PUSH_HOST        the ssh destination (user@host, or a Host from ~/.ssh/config)   required to push
  DEMO_PUSH_CT          the Proxmox container's id                                     with DEMO_PUSH_VIA=pct
  DEMO_PUSH_DIR         the compose file's out/ folder on the demo's machine           default /opt/headwind-demo/out
  DEMO_CONTAINER        the demo's container                                           default headwind-demo
  DEMO_BUILD_DIR        where patterns, routes, weather and the build go               default ~/headwind-demo-build
  DEMO_BROUTER          the routing engine                                             default http://127.0.0.1:17777
  DEMO_AUDIT_ALLOW_NEAR starts (demo/demo_areas.py names, comma-separated) the audit lets near your own places
"""
import argparse
import os
import shlex
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def settings():
    conf = {}
    path = os.path.join(HERE, 'publish.env')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    conf[k.strip()] = v.strip().strip('"\'')
    conf.update({k: v for k, v in os.environ.items() if k.startswith(('DEMO_', 'HEADWIND_SOURCE'))})
    conf.setdefault('DEMO_PUSH_DIR', '/opt/headwind-demo/out')
    conf.setdefault('DEMO_CONTAINER', 'headwind-demo')
    conf.setdefault('DEMO_BUILD_DIR', os.path.expanduser('~/headwind-demo-build'))
    conf.setdefault('DEMO_BROUTER', 'http://127.0.0.1:17777')
    conf.setdefault('DEMO_PUSH_VIA', 'ssh')
    return conf


def run(cmd, **kw):
    print('$', ' '.join(shlex.quote(c) for c in cmd))
    subprocess.run(cmd, check=True, **kw)


def step(title):
    print(f'\n== {title}')


def build(conf, args):
    py = sys.executable
    src = conf.get('HEADWIND_SOURCE_DB')
    if not src or not os.path.isfile(os.path.expanduser(src)):
        raise SystemExit('Set HEADWIND_SOURCE_DB (in the environment or demo/publish.env) to the real database.')
    src = os.path.expanduser(src)
    bdir = os.path.expanduser(conf['DEMO_BUILD_DIR'])
    out = os.path.join(bdir, 'out')
    patterns = os.path.join(bdir, 'patterns.json')
    step('1. patterns from the real database')
    run([py, os.path.join(HERE, 'extract_patterns.py'), '--source', src, '--out', patterns])
    step('2. the demo database, from generated tracks')
    try:
        urllib.request.urlopen(conf['DEMO_BROUTER'] + '/brouter?lonlats=-1.8166,53.3647|-1.7765,53.3436&profile=shortest&format=geojson', timeout=30).read()
    except Exception as ex:
        raise SystemExit(f'The routing engine does not answer at {conf["DEMO_BROUTER"]} ({ex}): demo/brouter.sh start')
    run([py, os.path.join(HERE, 'generate_demo_db.py'), '--patterns', patterns, '--out', out, '--cache', os.path.join(bdir, 'cache'),
         '--brouter', conf['DEMO_BROUTER']] + (['--seed', str(args.seed)] if args.seed is not None else []))
    step('3. the audit')
    allow = [x.strip() for x in conf.get('DEMO_AUDIT_ALLOW_NEAR', '').split(',') if x.strip()]
    run([py, os.path.join(HERE, 'audit_demo_db.py'), '--source', src, '--demo', os.path.join(out, 'pristine.db')] + sum((['--allow-near', a] for a in allow), []))
    with open(os.path.join(out, 'AUDITED'), 'w', encoding='utf-8') as fh:
        fh.write(str(os.path.getmtime(os.path.join(out, 'pristine.db'))))
    return out


def single_file(db):
    """No WAL: the demo opens it read-only from a read-only folder, which a WAL database can't be. Read from the file's header, not written."""
    with open(db, 'rb') as fh:
        head = fh.read(20)
    if head[18:20] != b'\x01\x01' or any(os.path.exists(db + ext) for ext in ('-wal', '-shm')):
        raise SystemExit(f'{db} is in WAL mode or has a -wal or -shm file beside it: build it again (demo/generate_demo_db.py leaves one file).')


def push(conf, out):
    host = conf.get('DEMO_PUSH_HOST')
    if not host:
        raise SystemExit('Set DEMO_PUSH_HOST (and DEMO_PUSH_VIA, DEMO_PUSH_CT for Proxmox) to push; --no-push builds only.')
    db = os.path.join(out, 'pristine.db')
    stamp = os.path.join(out, 'AUDITED')
    if not os.path.exists(stamp):
        raise SystemExit('That build has not passed the audit: run without --push-only.')
    with open(stamp, encoding='utf-8') as fh:
        if fh.read().strip() != str(os.path.getmtime(db)):
            raise SystemExit('pristine.db changed after its audit: build again.')
    single_file(db)
    dest, ct, box = conf['DEMO_PUSH_DIR'].rstrip('/'), conf.get('DEMO_PUSH_CT'), conf['DEMO_CONTAINER']
    q = shlex.quote
    with tempfile.TemporaryDirectory() as tmp:
        tarball = os.path.join(tmp, 'bikeimg.tar.gz')
        with tarfile.open(tarball, 'w:gz') as tf:
            if os.path.isdir(os.path.join(out, 'bikeimg')):
                tf.add(os.path.join(out, 'bikeimg'), arcname='bikeimg')
        step('4. the copy')
        if conf['DEMO_PUSH_VIA'] == 'pct':
            if not ct:
                raise SystemExit('DEMO_PUSH_VIA=pct needs DEMO_PUSH_CT, the container id.')
            run(['scp', '-q', db, f'{host}:/tmp/headwind-demo-pristine.db'])
            run(['scp', '-q', tarball, f'{host}:/tmp/headwind-demo-bikeimg.tar.gz'])
            inner = (f'pct push {q(ct)} /tmp/headwind-demo-pristine.db {q(dest + "/pristine.db.new")} --perms 644'
                     f' && pct push {q(ct)} /tmp/headwind-demo-bikeimg.tar.gz /tmp/headwind-demo-bikeimg.tar.gz'
                     f' && pct exec {q(ct)} -- sh -c {q(f"cd {q(dest)} && rm -rf bikeimg.new && mkdir bikeimg.new && tar -xzf /tmp/headwind-demo-bikeimg.tar.gz -C bikeimg.new --strip-components=1; rm -f /tmp/headwind-demo-bikeimg.tar.gz; rm -rf bikeimg.old; [ -d bikeimg ] && mv bikeimg bikeimg.old; mv bikeimg.new bikeimg && rm -rf bikeimg.old && mv pristine.db.new pristine.db")}'
                     f'; rm -f /tmp/headwind-demo-pristine.db /tmp/headwind-demo-bikeimg.tar.gz')
            run(['ssh', host, inner])
            reset = f'pct exec {q(ct)} -- docker exec -u headwind {q(box)} touch /data/reset.flag'
        else:
            run(['scp', '-q', db, f'{host}:{dest}/pristine.db.new'])
            run(['scp', '-q', tarball, f'{host}:/tmp/headwind-demo-bikeimg.tar.gz'])
            inner = (f'cd {q(dest)} && chmod 644 pristine.db.new && rm -rf bikeimg.new && mkdir bikeimg.new && tar -xzf /tmp/headwind-demo-bikeimg.tar.gz -C bikeimg.new --strip-components=1'
                     f' && rm -f /tmp/headwind-demo-bikeimg.tar.gz && rm -rf bikeimg.old && {{ [ ! -d bikeimg ] || mv bikeimg bikeimg.old; }} && mv bikeimg.new bikeimg'
                     f' && rm -rf bikeimg.old && mv pristine.db.new pristine.db')
            run(['ssh', host, inner])
            reset = f'docker exec -u headwind {q(box)} touch /data/reset.flag'
        step('5. the reset')
        run(['ssh', host, reset])
    print('\nDone: the demo resets from the new data within 30 s.')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--no-push', action='store_true', help='build and audit only')
    ap.add_argument('--push-only', action='store_true', help='copy the last build that passed its audit')
    ap.add_argument('--seed', type=int, help="the generator's seed (a different athlete's year)")
    args = ap.parse_args()
    conf = settings()
    out = os.path.join(os.path.expanduser(conf['DEMO_BUILD_DIR']), 'out') if args.push_only else build(conf, args)
    if args.no_push:
        single_file(os.path.join(out, 'pristine.db'))
        print(f'\nBuilt and audited: {out}. Not copied anywhere (--no-push).')
        return
    push(conf, out)


if __name__ == '__main__':
    main()
