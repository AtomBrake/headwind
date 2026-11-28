#!/usr/bin/env python3
"""Check a demo database against the real one it took patterns from, before it's published. Exit status 0 when clean, 2 when not.

    python3 demo/audit_demo_db.py --source /path/to/bike.db --demo demo/out/pristine.db

It fails when the demo has anything of the real database's in it:
  * a name: a rider's (a word of it, whole), an activity's, a segment's, a bike's, a kit item's, a planned route's, a friend's, a saved meal's;
  * an id: an activity's;
  * a setting, secret or token: any text value of Settings, RiderSettings, Friend, FeedToken, DeviceToken, Contact or LiveShare;
  * a place: a generated point (an activity's start, a sample of each track and of its map summary, a segment, a planned route) within --radius
    of a place the real activities often start or finish at, or of a privacy zone. Only how far, never where, is printed.
It also fails when the demo has a secret of its own, a friend with an address that isn't example.org's, or a device or feed token.
Both databases are opened read-only.
"""
import argparse
import json
import math
import os
import re
import sqlite3
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from services import streams as _streams  # noqa: E402

SECRET_COL = re.compile(r'key|token|pass|secret|mail|url|host|user|topic|webhook|address|name|server|account|device|prefix', re.I)
GENERIC = re.compile(r'^(morning|lunch|afternoon|evening|night)\b|^(imported|untitled|unnamed)\b', re.I)
MIN_NAME = 5            # shorter names (a single short word) are too common to tell anything


def public_words():
    """The words of every public place in demo/demo_areas.py, and of the generator's own names (loops, sports, gear): a source name made only
    of these says nothing about anyone."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from demo_areas import AREAS
    out = set()
    for a in AREAS.values():
        texts = [a['label']] + [x[0] for k in ('starts', 'summits', 'climbs') for x in a[k]] + [l['osm'] for l in a['lakes']] + [l['launch'][0] for l in a['lakes']]
        for t in texts:
            out |= set(re.findall(r"[^\W\d_]+", t.lower()))
    out |= set('''loop via from to on of out the and climb ascent km ride run walk hike paddle sup kayak swim yoga strength workout gravel road
                 mountain bike ebike e indoor trail shoes boots board roadie morning lunch afternoon evening night centre center station
                 visitor lake lakeside water car park café cafe'''.split())
    return out


def ro(path):
    c = sqlite3.connect(f'file:{os.path.abspath(path)}?mode=ro', uri=True, timeout=60)
    c.row_factory = sqlite3.Row
    _streams.register(c)
    return c


def tables(c):
    return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def column_values(c, table, cols=None):
    if table not in tables(c):
        return []
    have = [r[1] for r in c.execute(f'PRAGMA table_info({table})')]
    out = []
    for col in (cols or have):
        if col in have:
            out += [r[0] for r in c.execute(f'SELECT {col} FROM {table} WHERE {col} IS NOT NULL')]
    return out


def dist_m(a, b):
    x = math.radians(b[1] - a[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
    y = math.radians(b[0] - a[0])
    return 6371000.0 * math.hypot(x, y)


def places(src, min_count=5, cell=0.004):
    """(lat, lng, radius) of the places the source's activities often start or finish at (cells of about 400 m used min_count times or
    more), and of its privacy zones."""
    count = defaultdict(int)
    for r in src.execute(f'SELECT startLat, startLng, {_streams.sql()} FROM Activity'):
        ends = [(r['startLat'], r['startLng'])]
        try:
            ll = (json.loads(r['streams'] or '{}').get('latlng') or {}).get('data') or []
        except ValueError:
            ll = []
        if ll:
            ends += [tuple(ll[0][:2]), tuple(ll[-1][:2])]
        for la, lo in ends:
            if la is not None and lo is not None:
                count[(round(la / cell), round(lo / cell))] += 1
    out = [(k[0] * cell, k[1] * cell, 0) for k, n in count.items() if n >= min_count]
    if 'PrivacyZone' in tables(src):
        cols = [r[1] for r in src.execute('PRAGMA table_info(PrivacyZone)')]
        la = next((c for c in cols if c.lower() in ('lat', 'centrelat', 'centerlat')), None)
        lo = next((c for c in cols if c.lower() in ('lng', 'lon', 'centrelng', 'centerlng')), None)
        rad = next((c for c in cols if 'radius' in c.lower()), None)
        if la and lo:
            for r in src.execute(f'SELECT {la}, {lo}{", " + rad if rad else ""} FROM PrivacyZone'):
                out.append((r[0], r[1], (r[2] or 0) if rad else 1600))
    return out


def track_points(demo):
    """The points of the demo's map summaries (ActivityTrack, services/tracks.py), which the heatmap and segments read instead of the streams:
    every 5th point of each line and every 10th of each HD line (they are already thinned), and the middle of every cell (about 550 by 350 m) a
    track passes through. (A box's corners are no track's points; the line keeps its edges to within 10 m.)"""
    if 'ActivityTrack' not in tables(demo):
        return
    from services.tracks import CELL
    for r in demo.execute('SELECT line, lineHd, cells FROM ActivityTrack'):
        for col, every in (('line', 5), ('lineHd', 10)):
            try:
                pts = json.loads(r[col] or '[]')
            except ValueError:
                pts = []
            yield from (tuple(p[:2]) for p in pts[::every] if p)
        for cell in (r['cells'] or '').split():
            i, j = (int(x) for x in cell.split(':'))
            yield ((i + 0.5) * CELL, (j + 0.5) * CELL)


def demo_points(demo, every=25):
    """The demo's generated points: activity starts, every `every`th track point, the map summaries' (track_points), segments, planned routes."""
    for r in demo.execute(f'SELECT startLat, startLng, {_streams.sql()} FROM Activity'):
        if r['startLat'] is not None:
            yield (r['startLat'], r['startLng'])
        try:
            ll = (json.loads(r['streams'] or '{}').get('latlng') or {}).get('data') or []
        except ValueError:
            ll = []
        yield from (tuple(p) for p in ll[::every] if p)
    yield from track_points(demo)
    for r in demo.execute('SELECT polyline FROM Segment'):
        yield from (tuple(p[:2]) for p in json.loads(r[0] or '[]')[::5])
    if 'PlannedRoute' in tables(demo):
        for r in demo.execute('SELECT track FROM PlannedRoute WHERE track IS NOT NULL'):
            yield from (tuple(p[:2]) for p in json.loads(r[0] or '[]')[::10])


def demo_texts(demo):
    """(table.column, text) for every text value in the demo database."""
    for t in sorted(tables(demo)):
        if t.startswith('sqlite_'):
            continue
        for col, typ in ((r[1], (r[2] or '').upper()) for r in demo.execute(f'PRAGMA table_info({t})')):
            if typ and 'TEXT' not in typ and 'CHAR' not in typ:
                continue
            for (v,) in demo.execute(f'SELECT {col} FROM {t} WHERE typeof({col})=\'text\''):
                yield f'{t}.{col}', v


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--source', required=True)
    ap.add_argument('--demo', required=True)
    ap.add_argument('--radius', type=float, default=3000, help='metres a generated point must keep from a real frequent place')
    ap.add_argument('--allow-near', action='append', default=[], metavar='PLACE',
                    help="a start's name in demo/demo_areas.py: the source's frequent places within --allow-km of it don't count (your decision: "
                         "a public place you use, such as a trail centre; keep it out of the repo)")
    ap.add_argument('--allow-km', type=float, default=5.0)
    args = ap.parse_args()
    src, demo = ro(args.source), ro(args.demo)
    bad = []

    # names, ids and values from the source
    words = {w.lower() for v in column_values(src, 'Rider', ['name']) for w in re.findall(r"[^\W\d_]{3,}", v)}
    names = set()
    for table, cols in (('Activity', ['name']), ('Segment', ['name']), ('Bike', ['name', 'notes']), ('Kit', ['name', 'notes']), ('PlannedRoute', ['name']),
                        ('Friend', ['name']), ('SavedMeal', ['name']), ('Rider', ['name'])):
        names |= {v.strip().lower() for v in column_values(src, table, cols) if isinstance(v, str) and len(v.strip()) >= MIN_NAME and not GENERIC.match(v.strip())}
    ids = {str(v) for v in column_values(src, 'Activity', ['id'])}
    secrets_ = set()
    for table in ('Settings', 'RiderSettings', 'Friend', 'FeedToken', 'DeviceToken', 'Contact', 'LiveShare'):
        if table not in tables(src):
            continue
        cols = [r[1] for r in src.execute(f'PRAGMA table_info({table})')]
        if table in ('Settings', 'RiderSettings'):
            cols = [c for c in cols if SECRET_COL.search(c)]
        for v in column_values(src, table, cols):
            if isinstance(v, str) and len(v) >= 6 and not v.replace('.', '').replace('-', '').isdigit():
                secrets_.add(v)
    public = public_words()
    names = {n for n in names if not set(re.findall(r"[^\W\d_]+", n)) <= public}     # only public place names and plain words: nothing to give away
    by_first = defaultdict(set)
    for n in names:
        by_first[n.split()[0]].add(n)
    word_re = re.compile(r"[^\W\d_]{3,}")
    seen = set()
    for where, v in demo_texts(demo):
        low = v.lower()
        toks = set(word_re.findall(low))
        hits = []
        if toks & words:
            hits.append('a word of a rider\'s name')
        if low.strip() in names or any(n in low for t in toks for n in by_first.get(t, ())):
            hits.append('a name')
        if v in ids or (len(v) <= 64 and v.strip() in ids):
            hits.append('an activity id')
        if any(s in v for s in secrets_):
            hits.append('a setting, secret or token')
        for h in hits:
            if (where, h) not in seen:
                seen.add((where, h))
                bad.append(f'{where} holds {h} from the source')
    demo_ids = {str(v) for v in column_values(demo, 'Activity', ['id'])}
    if demo_ids & ids:
        bad.append(f'{len(demo_ids & ids)} activity ids are the same as the source\'s')

    # places
    spots = places(src)
    if args.allow_near:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from demo_areas import AREAS
        named = {x[0].lower(): (x[1], x[2]) for a in AREAS.values() for x in a['starts']}
        for nm in args.allow_near:
            if nm.lower() not in named:
                raise SystemExit(f'--allow-near {nm!r}: no start of that name in demo/demo_areas.py')
            before = len(spots)
            spots = [s for s in spots if dist_m(s[:2], named[nm.lower()]) > args.allow_km * 1000]
            print(f'allowed near {nm}: {before - len(spots)} of the source\'s places there don\'t count')
    if spots:
        closest = min((dist_m(p, s[:2]) - s[2], i) for i, p in enumerate(demo_points(demo)) for s in spots)
        if closest[0] < args.radius:
            bad.append(f'a generated point is {closest[0] / 1000:.1f} km from a place the source often starts or finishes at (or a privacy zone): '
                       f'keep {args.radius / 1000:.1f} km away (drop the start near it from demo/demo_areas.py)')
        else:
            print(f'places: every generated point is at least {closest[0] / 1000:.1f} km from the source\'s {len(spots)} frequent places and zones')

    # the demo's own
    from services.vault import COLUMNS
    st = demo.execute('SELECT * FROM Settings').fetchone()
    for col in (*COLUMNS['Settings'], 'mqttHost', 'ntfyUrl', 'haUrl', 'smtpHost', 'appUrl'):
        if st is not None and col in st.keys() and st[col]:
            bad.append(f'the demo has a value in Settings.{col}')
    for r in demo.execute('SELECT url, token FROM Friend'):
        if r['token'] or not re.match(r'^https://[a-z0-9.-]*\.example\.org/?$', r['url'] or ''):
            bad.append('a friend in the demo has a token or a real address')
    for t in ('DeviceToken', 'FeedToken', 'Contact', 'LiveShare'):
        if t in tables(demo) and demo.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:
            bad.append(f'the demo has rows in {t}')

    if bad:
        for b in sorted(set(bad)):
            print('AUDIT FAILED:', b)
        sys.exit(2)
    print(f'audit passed: {len(names)} names, {len(ids)} ids and {len(secrets_)} values of the source checked; none is in the demo')


if __name__ == '__main__':
    main()
