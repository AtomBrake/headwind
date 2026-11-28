#!/usr/bin/env python3
"""Build the public demo's database from generated tracks and coordinate-free patterns.

    python3 demo/generate_demo_db.py --patterns ~/headwind-demo-build/patterns.json --out demo/out

No real track goes into it. Every route is drawn by a routing engine (BRouter, demo/brouter.sh) on OpenStreetMap between the public places in
demo/demo_areas.py, or across a lake from OpenStreetMap's outline of it. The athlete's habits come from patterns.json (demo/extract_patterns.py):
how often each sport is done and when, how far, and how speed, heart rate, cadence and power go with the gradient. Those are numbers, with no
position, name, id or date in them. The rest is made up: the rider, a friend, food, weight, sleep, bikes, shoes, goals, routes, coach notes.

Every activity is stored the way an upload is (services/uploads.receive), so its weather (Open-Meteo's archive, for its place and day), best
efforts, segment efforts and records are worked out by Headwind itself. The routes and lake outlines are kept in --cache, so a second build
asks the routing engine and OpenStreetMap nothing new.

Network while building: the routing engine on 127.0.0.1, OpenStreetMap's Overpass API for the lakes (once) and Open-Meteo for the weather.
The output is out/pristine.db and out/bikeimg/. demo/audit_demo_db.py checks it against the real database before it's published.
"""
import argparse
import bisect
import hashlib
import json
import math
import os
import random
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
from demo_areas import AREAS  # noqa: E402  (after the path)

LONDON = ZoneInfo('Europe/London')
UA = 'headwind-demo-builder (https://github.com/AtomBrake/headwind)'

# What the athlete does with a track. src: the sport in patterns.json its habits come from; profile: BRouter's; start: which starts suit it
# (demo_areas); km: the range its routes are drawn in; scale: its distances against src's; pace: its speed against src's at the same gradient;
# rec: seconds between recorded points; per_area: routes drawn in each area (per_lake on each lake).
KINDS = {
    'road':   dict(sport='Ride', src='Ride', profile='fastbike-lowtraffic', start='ride', km=(28, 105), scale=2.2, pace=1.45, cad=(87, 5),
                   power=(0.0045, 0.30), bike='road', rec=2, v=(2.0, 17.0), per_area=14, share=0.5, label='Ride'),
    'gravel': dict(sport='GravelRide', src='Ride', profile='gravel', start='ride', km=(20, 70), scale=1.6, pace=1.15, cad=(82, 6),
                   power=(0.008, 0.38), bike='gravel', rec=2, v=(1.7, 14.0), per_area=10, share=0.3, label='Gravel Ride'),
    'mtb':    dict(sport='MountainBikeRide', src='Ride', profile='mtb', start='mtb', km=(12, 38), scale=1.0, pace=0.9, cad=(76, 8),
                   bike='mtb', rec=2, v=(1.3, 12.0), per_area=7, share=0.2, label='Mountain Bike Ride'),
    'ebike':  dict(sport='EBikeRide', src='EBikeRide', profile='trekking', start='ride', km=(18, 60), scale=1.3, pace=1.0, cad=(70, 8),
                   bike='ebike', rec=2, v=(3.0, 13.0), per_area=6, label='E-Bike Ride'),
    'run':    dict(sport='Run', src='Run', profile='hiking-mountain', start='foot', km=(4.5, 21), scale=1.0, pace=1.0, rec=1,
                   v=(1.3, 5.5), per_area=10, kit='run', label='Run'),
    'walk':   dict(sport='Walk', src='Walk', profile='hiking-mountain', start='foot', km=(2.5, 9), scale=1.3, pace=1.0, rec=2,
                   v=(0.6, 2.0), per_area=8, kit='walk', label='Walk'),
    'hike':   dict(sport='Hike', src='Hike', profile='hiking-mountain', start='foot', km=(7, 22), scale=1.0, pace=1.0, rec=2,
                   v=(0.35, 1.9), per_area=6, kit='walk', summit=True, label='Hike'),
    'sup':    dict(sport='Paddle', src='Stand Up Paddling', water=True, km=(2.5, 9), scale=1.0, pace=1.0, rec=3, v=(0.6, 2.2), per_lake=3,
                   label='Paddle', fallback_speed=1.35),
    'kayak':  dict(sport='Paddle', src='Kayaking', water=True, km=(4, 14), scale=1.4, pace=1.0, rec=3, v=(0.8, 2.8), per_lake=3,
                   label='Kayak', fallback_speed=1.9),
}
# ... and without one: timed sessions (services/manual_activity), indoors or in a pool
SESSIONS = {
    'indoor':   dict(sport='VirtualRide', src='VirtualRide', label='Indoor Ride'),
    'swim':     dict(sport='Swim', src='Swim', label='Swim'),
    'strength': dict(sport='Strength', src='Strength', label='Strength'),
    'hiit':     dict(sport='HIIT', src='Workout', label='Workout'),
    'yoga':     dict(sport='Yoga', src='Yoga', label='Yoga'),
}
MIN_PER_YEAR = {'hike': 8, 'sup': 6, 'kayak': 4, 'swim': 6, 'strength': 6, 'yoga': 6, 'mtb': 12, 'gravel': 16, 'indoor': 10}


# ------------------------------------------------------------------ geometry
def dist_m(a, b):
    x = math.radians(b[1] - a[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
    y = math.radians(b[0] - a[0])
    return 6371000.0 * math.hypot(x, y)


def offset(p, bearing_deg, m):
    """The point m metres from p on a bearing (flat earth: fine over a few km)."""
    b = math.radians(bearing_deg)
    return (p[0] + m * math.cos(b) / 111320.0, p[1] + m * math.sin(b) / (111320.0 * math.cos(math.radians(p[0]))))


def cumulative(pts):
    out, d = [0.0], 0.0
    for i in range(1, len(pts)):
        d += dist_m(pts[i - 1], pts[i])
        out.append(d)
    return out


def ascent(eles, threshold=3.0):
    gain, ref = 0.0, eles[0] if eles else 0
    for e in eles[1:]:
        if e - ref >= threshold:
            gain += e - ref
            ref = e
        elif ref - e >= threshold:
            ref = e
    return gain


def inside(pt, rings):
    """Even-odd point in polygon over all rings (outer shores and islands)."""
    y, x = pt
    hit = False
    for ring in rings:
        n = len(ring)
        j = n - 1
        for i in range(n):
            yi, xi = ring[i]
            yj, xj = ring[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
                hit = not hit
            j = i
    return hit


# ------------------------------------------------------------------ the routing engine and OpenStreetMap, cached
class Router:
    def __init__(self, url, cache):
        self.url, self.cache = url.rstrip('/'), os.path.join(cache, 'routes')
        os.makedirs(self.cache, exist_ok=True)
        self.asked = 0

    def route(self, pts, profile):
        """[(lat, lng, ele)], length m, or None when BRouter finds no way through those points."""
        lonlats = '|'.join(f'{p[1]:.5f},{p[0]:.5f}' for p in pts)
        q = urllib.parse.urlencode({'lonlats': lonlats, 'profile': profile, 'alternativeidx': 0, 'format': 'geojson'})
        key = hashlib.sha1(q.encode()).hexdigest()
        path = os.path.join(self.cache, key + '.json')
        if os.path.exists(path):
            with open(path, encoding='utf-8') as fh:
                got = json.load(fh)
        else:
            self.asked += 1
            try:
                with urllib.request.urlopen(f'{self.url}/brouter?{q}', timeout=120) as r:
                    d = json.load(r)
                c = d['features'][0]['geometry']['coordinates']
                got = {'coords': [[round(lat, 6), round(lng, 6), round(e if e is not None else 0, 1)] for lng, lat, *e0 in c for e in [(e0[0] if e0 else None)]]}
            except Exception as ex:
                got = {'coords': None, 'error': str(ex)[:200]}
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(got, fh)
        if not got.get('coords') or len(got['coords']) < 5:
            return None
        return [tuple(c) for c in got['coords']]


def overpass(query, cache_path):
    if os.path.exists(cache_path):
        with open(cache_path, encoding='utf-8') as fh:
            return json.load(fh)
    for attempt in range(6):
        try:
            import requests
            r = requests.post('https://overpass-api.de/api/interpreter', data={'data': query}, headers={'User-Agent': UA}, timeout=180)
            r.raise_for_status()
            d = r.json()
            with open(cache_path, 'w', encoding='utf-8') as fh:
                json.dump(d, fh)
            return d
        except Exception as ex:
            wait = 20 * (attempt + 1)
            print(f'  Overpass: {ex}; again in {wait} s')
            time.sleep(wait)
    raise SystemExit('Overpass did not answer: try again later (the lakes are cached once fetched)')


def join_rings(ways):
    """Ways (lists of (lat, lng)) joined end to end into closed rings."""
    ways = [list(w) for w in ways if len(w) >= 2]
    rings = []
    while ways:
        ring = ways.pop(0)
        changed = True
        while ring[0] != ring[-1] and changed:
            changed = False
            for i, w in enumerate(ways):
                if w[0] == ring[-1]:
                    ring += w[1:]
                elif w[-1] == ring[-1]:
                    ring += w[::-1][1:]
                elif w[-1] == ring[0]:
                    ring = w[:-1] + ring
                elif w[0] == ring[0]:
                    ring = w[::-1][:-1] + ring
                else:
                    continue
                ways.pop(i)
                changed = True
                break
        if len(ring) >= 4:
            rings.append(ring)
    return rings


def lake_rings(lake, cache):
    lat, lng = lake['launch'][1], lake['launch'][2]
    s, w, n, e = lat - 0.15, lng - 0.15, lat + 0.15, lng + 0.15
    name = lake['osm']
    q = f'[out:json][timeout:120];(way["natural"="water"]["name"="{name}"]({s},{w},{n},{e});relation["natural"="water"]["name"="{name}"]({s},{w},{n},{e}););out geom;'
    d = overpass(q, os.path.join(cache, 'lake-' + hashlib.sha1(name.encode()).hexdigest()[:10] + '.json'))
    ways = []
    for el in d.get('elements', []):
        if el['type'] == 'way' and el.get('geometry'):
            ways.append([(round(g['lat'], 6), round(g['lon'], 6)) for g in el['geometry']])
        elif el['type'] == 'relation':
            for m in el.get('members', []):
                if m.get('type') == 'way' and m.get('geometry'):
                    ways.append([(round(g['lat'], 6), round(g['lon'], 6)) for g in m['geometry']])
    return join_rings(ways)


# ------------------------------------------------------------------ routes
def loop(router, start, km, profile, rng, tries=4):
    """A loop of about km from start: three points on a circle through it, the radius corrected after each try."""
    bearing = rng.uniform(0, 360)
    r = km * 1000 / (2 * math.pi) * 0.75
    best = None
    for _ in range(tries):
        centre = offset(start, bearing, r)
        back = (bearing + 180) % 360
        pts = [start] + [offset(centre, (back + a) % 360, r) for a in (95, 180, 265)] + [start]
        c = router.route(pts, profile)
        if c:
            length = cumulative([(p[0], p[1]) for p in c])[-1]
            if best is None or abs(length - km * 1000) < abs(best[1] - km * 1000):
                best = (c, length)
            if abs(length - km * 1000) < km * 1000 * 0.12:
                break
            r *= max(0.5, min(1.8, km * 1000 / length))
        else:
            bearing = rng.uniform(0, 360)
    if best and abs(best[1] - km * 1000) < km * 1000 * 0.4:
        return best[0]
    return None


def summit_route(router, start, summit, profile, rng):
    """Up a summit and back down another way: out by one side, home by the other."""
    d = dist_m(start, summit)
    b = math.degrees(math.atan2((summit[1] - start[1]) * math.cos(math.radians(start[0])), summit[0] - start[0]))
    side = rng.choice((-1, 1))
    via = offset(offset(start, b, d * 0.5), b + 90 * side, d * rng.uniform(0.2, 0.45))
    return router.route([start, summit, via, start], profile) or router.route([start, summit, start], profile)


def lake_route(rings, launch, km, rng, tries=400):
    """Out across the water and back to the launch: a few straight legs, each kept on the water (40 m off the shore at the ends)."""
    if not rings:
        return None
    shore = min((p for ring in rings for p in ring), key=lambda p: dist_m(p, launch[1:]))
    lats = [p[0] for ring in rings for p in ring]
    lngs = [p[1] for ring in rings for p in ring]

    def wet(a, b):
        steps = max(2, int(dist_m(a, b) / 20))
        return all(inside((a[0] + (b[0] - a[0]) * k / steps, a[1] + (b[1] - a[1]) * k / steps), rings) for k in range(1, steps))

    first = None
    for _ in range(200):                        # just off the launch, on the water
        p = offset(shore, rng.uniform(0, 360), 40)
        if inside(p, rings):
            first = p
            break
    if not first:
        return None
    target = km * 1000
    for _ in range(tries):
        legs, here, total = [first], first, 0.0
        while total < target * 0.55:
            for _ in range(60):
                q = (rng.uniform(min(lats), max(lats)), rng.uniform(min(lngs), max(lngs)))
                step = dist_m(here, q)
                if 200 < step < target * 0.35 and inside(q, rings) and wet(here, q):
                    legs.append(q)
                    here, total = q, total + step
                    break
            else:
                break
        back = dist_m(here, first)
        if abs(total + back - target) < target * 0.25 and wet(here, first) and len(legs) >= 2:
            pts = legs + [first]
            dense = []
            for a, b in zip(pts, pts[1:]):
                steps = max(1, int(dist_m(a, b) / 25))
                dense += [(a[0] + (b[0] - a[0]) * k / steps, a[1] + (b[1] - a[1]) * k / steps) for k in range(steps)]
            dense.append(first)
            return [(shore[0], shore[1])] + dense + [(shore[0], shore[1])]
    return None


def near_named(coords, named, within=350):
    """The first of named [(name, lat, lng)] the route passes within `within` metres of, with the index of its closest point."""
    for nm, lat, lng in named:
        best = min(range(0, len(coords), 3), key=lambda i: dist_m(coords[i], (lat, lng)))
        if dist_m(coords[best], (lat, lng)) < within:
            return nm, best
    return None, None


def build_library(router, pat, rng, cache):
    """{(area, kind): [route]}: each route a dict(name, start, coords [(lat, lng, ele)], km, climb)."""
    lib = defaultdict(list)
    for area_key, area in AREAS.items():
        for kind, k in KINDS.items():
            if k.get('water'):
                for lake in area['lakes']:
                    if kind not in lake['sports']:
                        continue
                    rings = lake_rings(lake, cache)
                    ele = None
                    probe = router.route([lake['launch'][1:], offset(lake['launch'][1:], 0, 120)], 'hiking-mountain')
                    if probe:
                        ele = min(p[2] for p in probe)
                    for _ in range(k['per_lake']):
                        km = rng.uniform(*k['km'])
                        r = lake_route(rings, lake['launch'], km, rng)
                        if r:
                            coords = [(p[0], p[1], ele or 0.0) for p in r]
                            lib[(area_key, kind)].append(dict(name=f"{'SUP' if kind == 'sup' else 'Kayak'} on {lake['osm']}", start=lake['launch'][0],
                                                               coords=coords, km=cumulative(coords)[-1] / 1000, climb=0.0, water=lake['osm']))
                continue
            starts = [s for s in area['starts'] if k['start'] in s[3]]
            made, guard = 0, 0
            while made < k['per_area'] and guard < k['per_area'] * 4:
                guard += 1
                st = starts[made % len(starts)] if made < len(starts) else rng.choice(starts)
                start = (st[1], st[2])
                if k.get('summit'):
                    tops = sorted(area['summits'], key=lambda s: dist_m(start, (s[1], s[2])))
                    tops = [s for s in tops if 1500 < dist_m(start, (s[1], s[2])) < k['km'][1] * 1000 / 2.6] or tops[:1]
                    top = rng.choice(tops[:3])
                    c = summit_route(router, start, (top[1], top[2]), k['profile'], rng)
                    name = f'{top[0]} from {st[0]}'
                else:
                    q = pat['sports'].get(k['src'], {}).get('distance_km_q') or [sum(k['km']) / 2]
                    km = min(k['km'][1], max(k['km'][0], rng.choice(q) * k['scale'] * rng.uniform(0.85, 1.2)))
                    c = loop(router, start, km, k['profile'], rng)
                    name = None
                if not c:
                    continue
                d = cumulative(c)
                if d[-1] < k['km'][0] * 600 or d[-1] > k['km'][1] * 1400:
                    continue
                if name is None:
                    climb, _ = near_named(c, area['climbs']) if kind in ('road', 'gravel', 'ebike') else (None, None)
                    top, _ = near_named(c, area['summits'], 250) if kind in ('run', 'walk', 'mtb') else (None, None)
                    name = (f'{st[0]} loop via {climb}' if climb else f'{top} from {st[0]}' if top else f'{st[0]} {round(d[-1] / 1000)} km loop')
                lib[(area_key, kind)].append(dict(name=name, start=st[0], coords=c, km=d[-1] / 1000, climb=ascent([p[2] for p in c])))
                made += 1
        print(f'  {area["label"]:15} ' + ', '.join(f'{kind} {len(lib[(area_key, kind)])}' for kind in KINDS if lib[(area_key, kind)]))
    return lib


# ------------------------------------------------------------------ an activity along a route
class Model:
    """How fast and how hard the athlete goes on a gradient in one sport, from patterns.json."""
    def __init__(self, sp, kind_cfg):
        self.k = kind_cfg
        by = (sp or {}).get('by_grade') or {}
        grades = sorted(int(g) for g in by)
        self.grades = grades
        self.speed = [by[str(g)].get('speed') for g in grades]
        self.hr = [by[str(g)].get('hr') for g in grades]
        self.cad = [by[str(g)].get('cadence') for g in grades]
        self.sp = sp or {}

    def _at(self, arr, g):
        pts = [(gr, v) for gr, v in zip(self.grades, arr) if v]
        if not pts:
            return None
        if g <= pts[0][0]:
            return pts[0][1]
        if g >= pts[-1][0]:
            return pts[-1][1]
        for (g0, v0), (g1, v1) in zip(pts, pts[1:]):
            if g0 <= g <= g1:
                return v0 + (v1 - v0) * (g - g0) / ((g1 - g0) or 1)
        return pts[-1][1]

    def speed_at(self, g):
        v = self._at(self.speed, g)
        if v is None:
            v = self.k.get('fallback_speed', 1.5)
        if self.k.get('src') in ('Run', 'Walk', 'Hike') and g < -8:     # steep descents on foot are careful
            v *= max(0.6, 1 + (g + 8) * 0.03)
        return v * self.k['pace']

    def hr_at(self, g):
        v = self._at(self.hr, g)
        if v is None:
            q = self.sp.get('avg_hr_q')
            v = q[len(q) // 2] if q else 120
        return v

    def cad_at(self, g):
        return self._at(self.cad, g)


def q_pick(q, rng, lo=0.15, hi=0.85):
    """A random value between two quantiles of a list from patterns.json."""
    if not q:
        return None
    i = rng.uniform(lo, hi) * (len(q) - 1)
    a, b = int(i), min(len(q) - 1, int(i) + 1)
    return q[a] + (q[b] - q[a]) * (i - a)


def synth(route, kind, model, start_utc, rng, athlete):
    """[(datetime, lat, lng, ele, hr, cad, watts)] for one go along `route`, recorded every k['rec'] seconds, with stops."""
    k = KINDS[kind]
    pts = [(p[0], p[1]) for p in route]
    d = cumulative(pts)
    total = d[-1]
    ele = [p[2] for p in route]
    sm = [sum(ele[max(0, i - 3): i + 4]) / len(ele[max(0, i - 3): i + 4]) for i in range(len(ele))]

    def at(s):
        i = max(1, min(len(d) - 1, bisect.bisect_left(d, s)))
        f = (s - d[i - 1]) / ((d[i] - d[i - 1]) or 1)
        return i, (pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * f, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * f,
                   sm[i - 1] + (sm[i] - sm[i - 1]) * f)

    def grade(s):
        if k.get('water'):
            return 0.0
        a, b = max(0.0, s - 40), min(total, s + 40)
        if b - a < 20:
            return 0.0
        return max(-25.0, min(25.0, (at(b)[1][2] - at(a)[1][2]) / (b - a) * 100))

    day = max(0.88, min(1.12, q_pick(model.sp.get('day_speed_ratio_q'), rng) or 1.0)) * athlete['form']
    hr_off = max(-12, min(12, q_pick(model.sp.get('day_hr_offset_q'), rng) or 0.0))
    ratio = q_pick(model.sp.get('elapsed_over_moving_q'), rng, 0.1, 0.75) or 1.05
    ratio = min(ratio, {'road': 1.35, 'gravel': 1.35, 'ebike': 1.3, 'mtb': 1.3, 'hike': 1.35}.get(kind, 1.15))
    est_moving = total / max(0.5, model.speed_at(0) * day)
    pause = est_moving * (ratio - 1)
    stops = []
    if kind in ('road', 'gravel', 'ebike') and est_moving > 7200 and pause > 600:
        stops.append((total * rng.uniform(0.4, 0.65), pause * 0.7))           # the café
        pause *= 0.3
    for _ in range(rng.randint(1, 4)):
        stops.append((total * rng.uniform(0.08, 0.92), pause / 4))
    if kind == 'hike':
        stops.append((total * 0.5, rng.uniform(300, 900)))                     # on top (the summit is about half way)
    stops.sort()
    wind = rng.gauss(0, 2.0)
    crr, cda = k.get('power') or (None, None)
    mass = athlete['kg'] + {'road': 8.5, 'gravel': 10, 'mtb': 14, 'ebike': 23}.get(kind, 0)

    out = []
    t, s, v = start_utc, 0.0, 0.5
    hr = athlete['rest'] + 25
    lateral, eoff = 0.0, rng.gauss(0, 3)
    noise = 0.0
    sec = 0
    with_hr = rng.random() < 0.93
    stop_i = 0
    while s < total:
        g = grade(s)
        target_v = model.speed_at(g) * day
        noise = 0.97 * noise + rng.gauss(0, 0.012)
        target_v *= (1 + noise)
        lo, hi = k['v']
        target_v = max(lo, min(hi, target_v))
        dv = max(-1.5, min(0.6, target_v - v))
        v_new = v + dv * 0.5
        a = v_new - v
        v = v_new
        s = min(total, s + v)
        sec += 1
        t += timedelta(seconds=1)
        hr_target = model.hr_at(g) + hr_off + sec / 60 * 0.04
        hr += (hr_target - hr) / (25 if hr_target > hr else 40)
        lateral = 0.985 * lateral + rng.gauss(0, 0.35)
        if sec % k['rec'] == 0 or s >= total:
            i, (la, lo_, el) = at(s)
            b = math.atan2((pts[i][1] - pts[i - 1][1]) * math.cos(math.radians(la)), pts[i][0] - pts[i - 1][0])
            la2, lo2 = offset((la, lo_), math.degrees(b) + 90, lateral)
            cad = None
            if k.get('cad'):
                cad = 0 if (g < -3 and rng.random() < 0.7) or v < 1.0 else max(40, rng.gauss(k['cad'][0] - max(0, g - 4) * 1.5, k['cad'][1]))
            else:
                c0 = model.cad_at(g)
                cad = rng.gauss(c0, 2.5) if c0 else None
            w = None
            if crr is not None:
                air = v + wind
                p = (mass * 9.81 * v * (math.sin(math.atan(g / 100)) + crr) + 0.5 * 1.2 * cda * air * abs(air) * v + mass * a * v) / 0.97
                w = 0 if cad == 0 else max(0, min(1100, p * (1 + rng.gauss(0, 0.06))))
            out.append((t, la2, lo2, el + eoff, (min(athlete['max'], max(athlete['rest'], hr + rng.gauss(0, 1.0))) if with_hr else None), cad, w))
        if stop_i < len(stops) and s >= stops[stop_i][0]:
            dur = max(20, stops[stop_i][1])
            stop_i += 1
            t += timedelta(seconds=int(dur))
            hr = max(athlete['rest'] + 10, hr - dur / 6)
            v = 0.3
            out.append((t, out[-1][1], out[-1][2], out[-1][3], out[-1][4], 0 if k.get('cad') else out[-1][5], 0 if w is not None else None))
    return out


GPX_HEAD = ('<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="Headwind demo" xmlns="http://www.topografix.com/GPX/1/1" '
            'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">\n')


def gpx(points, name, gpx_type):
    rows = [GPX_HEAD, f'<metadata><time>{points[0][0].strftime("%Y-%m-%dT%H:%M:%SZ")}</time></metadata>\n',
            f'<trk><name>{name}</name><type>{gpx_type}</type><trkseg>\n']
    for t, la, lo, el, hr, cad, w in points:
        ext = ''
        tpx = (f'<gpxtpx:hr>{int(round(hr))}</gpxtpx:hr>' if hr else '') + (f'<gpxtpx:cad>{int(round(cad))}</gpxtpx:cad>' if cad is not None else '')
        if tpx or w is not None:
            ext = '<extensions>' + (f'<power>{int(round(w))}</power>' if w is not None else '') + (f'<gpxtpx:TrackPointExtension>{tpx}</gpxtpx:TrackPointExtension>' if tpx else '') + '</extensions>'
        rows.append(f'<trkpt lat="{la:.6f}" lon="{lo:.6f}"><ele>{el:.1f}</ele><time>{t.strftime("%Y-%m-%dT%H:%M:%SZ")}</time>{ext}</trkpt>\n')
    rows.append('</trkseg></trk></gpx>\n')
    return ''.join(rows).encode('utf-8')


GPX_TYPES = {'road': 'Ride', 'gravel': 'GravelRide', 'mtb': 'MountainBikeRide', 'ebike': 'EBikeRide', 'run': 'Run', 'walk': 'Walk', 'hike': 'Hike',
             'sup': 'StandUpPaddling', 'kayak': 'Kayaking'}


# ------------------------------------------------------------------ segments, from the routes
def best_climb(coords, min_gain=40, max_len=6000):
    """(i0, i1, gain) of the biggest climb along a route, or None: from a low point to the next high one, small dips allowed."""
    ele = [p[2] for p in coords]
    sm = [sum(ele[max(0, i - 4): i + 5]) / len(ele[max(0, i - 4): i + 5]) for i in range(len(ele))]
    d = cumulative([(p[0], p[1]) for p in coords])
    best, i = None, 0
    while i < len(sm) - 1:
        j, top = i, i
        while j < len(sm) - 1 and sm[j + 1] >= sm[top] - 4 and d[j + 1] - d[i] < max_len:
            j += 1
            if sm[j] > sm[top]:
                top = j
        low = min(sm[i: top + 1])
        start = max(k for k in range(i, top + 1) if sm[k] <= low + 1.5)     # where it starts going up, not the flat before
        gain = sm[top] - sm[start]
        if gain >= min_gain and d[top] - d[start] >= 500 and (best is None or gain > best[2]):
            best = (start, top, gain)
        i = max(i + 1, top)
    return best


def make_segments(db, lib, per_kind=3):
    """A segment on the biggest climb of each area's most-used routes (the first ones in the library: they're the favourites), named after the
    nearest named climb or summit. Matched by the import from then on, so the athlete's and the friend's efforts make leaderboards."""
    made, taken = 0, []
    for area_key, area in AREAS.items():
        named = area['climbs'] + area['summits']
        for kind, family in (('road', 'ride'), ('gravel', 'ride'), ('mtb', 'ride'), ('ebike', 'ride'), ('run', 'foot'), ('hike', 'foot'), ('walk', 'foot')):
            for r in lib.get((area_key, kind), [])[:per_kind]:
                c = r['coords']
                got = best_climb(c)
                if not got:
                    continue
                i0, i1, gain = got
                pts = c[i0: i1 + 1]
                if any(dist_m(pts[0], t[0]) < 300 and dist_m(pts[-1], t[1]) < 300 and fam == family for t, fam in taken):
                    continue                                        # that climb has a segment already
                taken.append(((pts[0], pts[-1]), family))
                mid = pts[len(pts) // 2]
                near = min(named, key=lambda x: dist_m(mid, (x[1], x[2])))
                if dist_m(mid, (near[1], near[2])) < 1500:
                    name = near[0] if near in area['climbs'] else f'{near[0]} ascent'
                else:
                    name = f'Climb out of {r["start"].split(",")[0].replace(" station", "").replace(" visitor centre", "")}'
                if any(x[0] == name for x in db.execute('SELECT name FROM Segment').fetchall()):
                    name = f'{name} ({"on foot" if family == "foot" else kind})'
                line = [[round(p[0], 6), round(p[1], 6)] for p in pts]
                db.execute('INSERT INTO Segment (name, startLat, startLng, endLat, endLng, distanceM, elevationGainM, sourceActivityId, polyline, sport) '
                           'VALUES (?,?,?,?,?,?,?,NULL,?,?)', [name, line[0][0], line[0][1], line[-1][0], line[-1][1], round(cumulative(line)[-1], 1),
                                                                round(ascent([p[2] for p in pts]), 1), json.dumps(line), family])
                made += 1
    return made

# ------------------------------------------------------------------ when
def yearly(pat, kind, cfg, years_back=4):
    """Activities a year for one kind: the source sport's average over its last few whole years, split between the kinds that share it."""
    sp = pat['sports'].get(cfg['src'])
    n = 0.0
    if sp:
        ys = sorted(int(y) for y in sp['count_by_year'])
        this = date.today().year
        whole = [y for y in ys if y < this][-years_back:]
        if whole:
            n = sum(sp['count_by_year'].get(str(y), 0) for y in whole) / len(whole)
    n *= cfg.get('share', 1.0)
    return max(n, MIN_PER_YEAR.get(kind, 4))


def weights(sp, key, n):
    w = (sp or {}).get(key) or [1] * n
    tot = sum(w) or 1
    return [(x + tot * 0.01) / (tot * 1.01) * n for x in w]          # never quite zero


def schedule(pat, first, last, rng):
    """[(day, area, kind, hour)], areas visited in blocks of two to six weeks."""
    areas = list(AREAS)
    blocks, d, prev = [], first, None
    while d <= last:
        a = rng.choice([x for x in areas if x != prev])
        n = rng.randint(14, 42)
        blocks.append((d, d + timedelta(days=n - 1), a))
        d, prev = d + timedelta(days=n), a
    area_on = lambda day: next(b[2] for b in blocks if b[0] <= day <= b[1])
    plan = []
    cfgs = dict(KINDS, **SESSIONS)
    rates = {kind: yearly(pat, kind, cfg) / 365.0 for kind, cfg in cfgs.items()}
    water_share = {kind: max(0.25, sum(1 for a in areas if any(kind in lake['sports'] for lake in AREAS[a]['lakes'])) / len(areas))
                   for kind, cfg in KINDS.items() if cfg.get('water')}
    d = first
    while d <= last:
        area = area_on(d)
        todays = []
        for kind, cfg in cfgs.items():
            sp = pat['sports'].get(cfg['src'])
            p = rates[kind] * weights(sp, 'month_weights', 12)[d.month - 1] * weights(sp, 'weekday_weights', 7)[d.weekday()]
            if cfg.get('water'):
                if not any(kind in lake['sports'] for lake in AREAS[area]['lakes']):
                    continue
                p /= water_share[kind]
            if rng.random() < p:
                hw = weights(sp, 'hour_weights', 24)
                hour = rng.choices(range(24), weights=[w if 6 <= h <= 20 else 0 for h, w in enumerate(hw)])[0]
                todays.append((d, area, kind, hour))
        todays.sort(key=lambda x: x[3])
        plan += todays[:2]
        d += timedelta(days=1)
    return plan, blocks


def time_name(kind, hour):
    label = (KINDS.get(kind) or SESSIONS.get(kind))['label']
    part = 'Morning' if hour < 11 else 'Lunch' if hour < 14 else 'Afternoon' if hour < 18 else 'Evening'
    return f'{part} {label}'


# ------------------------------------------------------------------ the rest of the made-up life
from build_fiction import make_gear, make_nutrition, make_extras  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--patterns', required=True, help='demo/extract_patterns.py\'s output')
    ap.add_argument('--out', default=os.path.join(HERE, 'out'))
    ap.add_argument('--cache', default=os.path.expanduser('~/headwind-demo-build/cache'), help='routes and lake outlines, kept between builds')
    ap.add_argument('--brouter', default='http://127.0.0.1:17777', help='the routing engine (demo/brouter.sh start)')
    ap.add_argument('--years', type=float, default=2.0, help='how far back the activities go from yesterday')
    ap.add_argument('--seed', type=int, default=11)
    ap.add_argument('--limit', type=int, default=0, help='stop after this many activities (a quick try)')
    ap.add_argument('--no-weather', action='store_true', help='skip Open-Meteo (a quick try)')
    args = ap.parse_args()
    rng = random.Random(args.seed)
    with open(args.patterns, encoding='utf-8') as fh:
        pat = json.load(fh)
    os.makedirs(args.cache, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)

    router = Router(args.brouter, args.cache)
    print('routes:')
    lib = build_library(router, pat, rng, args.cache)
    print(f'  {sum(len(v) for v in lib.values())} routes ({router.asked} asked of the routing engine, the rest from the cache)')

    yesterday = datetime.now(LONDON).date() - timedelta(days=1)
    first = yesterday - timedelta(days=int(args.years * 365))
    plan, blocks = schedule(pat, first, yesterday, rng)
    if args.limit:
        plan = plan[-args.limit:]
    print(f'plan: {len(plan)} activities from {first} to {yesterday}, ' + ', '.join(f'{k} {v}' for k, v in Counter(p[2] for p in plan).most_common()))

    out_db = os.path.join(args.out, 'pristine.db')
    for f in (out_db, out_db + '-wal', out_db + '-shm'):
        if os.path.exists(f):
            os.remove(f)
    shutil.rmtree(os.path.join(args.out, 'bikeimg'), ignore_errors=True)

    if args.no_weather:
        import services.weather as _w
        _w.fetch_weather = lambda *a, **kw: None
    from flask import Flask
    import database
    from services import uploads, streams as _streams
    app = Flask(__name__)
    app.config['DATABASE'] = out_db
    app.secret_key = os.urandom(16)
    with app.app_context(), app.test_request_context('/'):
        database.migrate_db()
        db = database.get_db()
        db.execute("INSERT OR IGNORE INTO Settings (id) VALUES (1)")
        db.execute("UPDATE Settings SET units='metric', heightCm=176, sex='female', birthYear=1988 WHERE id=1")
        rider = db.execute("INSERT INTO Rider (name, avatarPath, isDefault) VALUES ('Alex', 'custard_cream.svg', 1)").lastrowid
        db.commit()
        gear_ids = make_gear(db, out_db, rider, yesterday, rng)
        db.execute("INSERT INTO WeightLog (riderId, logDate, weightKg, source) VALUES (?,?,?,'scale')", [rider, first.isoformat(), 76.0])  # for the rides' calories
        print(f'segments: {make_segments(db, lib)}')
        db.commit()

        athlete = dict(kg=64.0, rest=52, max=186, form=1.0)
        models = {kind: Model(pat['sports'].get(cfg['src']) or pat['sports'].get('Walk'), cfg) for kind, cfg in KINDS.items()}
        if not (pat['sports'].get('Hike') or {}).get('by_grade'):
            models['hike'] = Model(pat['sports'].get('Walk'), dict(KINDS['hike'], pace=0.9))
        made, failed, last_end, done = Counter(), Counter(), None, []
        favourites = {key: [1 / (i + 1) ** 0.7 for i in range(len(v))] for key, v in lib.items()}
        t0 = time.time()
        for n, (day, area, kind, hour) in enumerate(plan):
            start_local = datetime(day.year, day.month, day.day, hour, rng.randint(0, 59), rng.randint(0, 59), tzinfo=LONDON)
            if last_end and start_local < last_end + timedelta(minutes=45):
                start_local = last_end + timedelta(minutes=rng.randint(60, 150))
                if start_local.date() != day or start_local.hour > 21:
                    failed['no time left that day'] += 1
                    continue
            start_utc = start_local.astimezone(timezone.utc)
            if kind in SESSIONS:
                res = make_session(db, uploads, rider, kind, start_local, pat, rng, athlete)
                if res:
                    made[kind] += 1
                    last_end = start_local + timedelta(seconds=res)
                continue
            routes = lib.get((area, kind))
            if not routes:
                failed[f'no {kind} route in {area}'] += 1
                continue
            route = rng.choices(routes, weights=favourites[(area, kind)])[0]
            pts = synth(route['coords'], kind, models[kind], start_utc, rng, athlete)
            name = route['name'] if rng.random() < 0.45 else time_name(kind, hour)
            data = gpx(pts, name, GPX_TYPES[kind])
            try:
                res = uploads.receive(db, rider, gpx=data, filename=f'demo-{n}.gpx', sport=KINDS[kind]['sport'],
                                      bike_id=gear_ids.get(KINDS[kind].get('bike')), name=name)
            except Exception as ex:
                failed[f'{kind}: {ex}'[:80]] += 1
                continue
            made[kind] += 1
            if kind == 'kayak' and res.get('id'):                     # the board is the default for paddles: not on a kayak
                db.execute('UPDATE Activity SET kitId=NULL, kitAuto=0 WHERE id=?', [res['id']])
            done.append((kind, route, start_utc))
            last_end = pts[-1][0].astimezone(LONDON)
            if (n + 1) % 25 == 0:
                db.commit()
                print(f'  {n + 1}/{len(plan)} ({time.time() - t0:.0f} s)')
        db.commit()
        print('made: ' + ', '.join(f'{k} {v}' for k, v in made.most_common()))
        if failed:
            print('not made: ' + '; '.join(f'{k} ({v})' for k, v in failed.most_common()))

        friend_id = make_friend(db, uploads, done, models, rng)
        fill_cadence(db, _streams)
        if not args.no_weather:                                       # the sports whose import doesn't ask (walks, runs, paddles): the app's own backfill
            from services.weather import backfill_missing
            got, missed = backfill_missing(db, pause=0.1)
            print(f'weather for the rest: {got} fetched, {missed} without')
        make_nutrition(db, rider, yesterday, rng)
        make_extras(db, rider, lib, yesterday, rng, out_db, friend_id)
        from services import gear as gear_svc
        gear_svc.evaluate_alerts(db, send=False)
        finish(db)
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        database.close_db()
    c = sqlite3.connect(out_db)                       # one file, no WAL: the demo opens it read-only from a read-only folder
    c.execute('PRAGMA journal_mode=DELETE')
    c.execute('VACUUM')
    c.close()
    print(f'wrote {out_db} ({os.path.getsize(out_db) / 1e6:.1f} MB)')


def finish(db, built_on=None):
    """Last, once nothing changes an activity's streams: every activity's map summary (services/tracks.py), so the heatmap's first visitor after
    a reset doesn't wait while they are all made (a Headwind whose reset makes them itself finds none missing), and the day it was built, which
    the reset moves the dates on from. Commits."""
    from services import tracks
    t0 = time.time()
    n = tracks.fill(db)
    print(f'map summaries: {n} ({time.time() - t0:.0f} s)')
    db.execute('CREATE TABLE IF NOT EXISTS DemoMeta (key TEXT PRIMARY KEY, value TEXT)')
    db.execute("INSERT OR REPLACE INTO DemoMeta (key, value) VALUES ('built_on', ?)", [(built_on or datetime.now(LONDON).date()).isoformat()])
    db.commit()


def make_friend(db, uploads, done, models, rng, share=0.22, recent_share=0.75, recent_days=28):
    """A friend whose activities are stored here as a friend sync would have (services/friend_rides): Sam rides and runs with Alex on some days,
    the same route at the same time, a little faster on the climbs; on most of Alex's rides in the last four weeks, so the segment race
    (build_fiction.make_race) has segments they've both ridden. No sync: the Friend row's address is example.org's."""
    fr = db.execute("INSERT INTO Rider (name, avatarPath, isDefault) VALUES ('Sam', 'custard_cream.svg', 0)").lastrowid
    fid = db.execute("INSERT INTO Friend (name, url, token, riderId, lastSynced) VALUES ('Sam', 'https://sam.example.org', NULL, ?, datetime('now'))", [fr]).lastrowid
    sam = dict(kg=70.0, rest=48, max=191, form=1.04)
    n = 0
    recent = max((d[2] for d in done), default=None)
    recent = recent - timedelta(days=recent_days) if recent else None
    for kind, route, start_utc in done:
        often = recent_share if recent and start_utc >= recent and kind in ('road', 'gravel', 'mtb') else share
        if kind not in ('road', 'gravel', 'mtb', 'run', 'hike') or rng.random() > often:
            continue
        pts = synth(route['coords'], kind, models[kind], start_utc + timedelta(seconds=rng.randint(-40, 40)), rng, sam)
        try:
            uploads.receive(db, fr, gpx=gpx(pts, time_name(kind, start_utc.astimezone(LONDON).hour), GPX_TYPES[kind]), filename='sam.gpx',
                            sport=KINDS[kind]['sport'])
            n += 1
        except Exception as ex:
            print(f'  friend {kind}: {ex}')
    db.commit()
    print(f'friend: {n} activities')
    return fid


def fill_cadence(db, _streams):
    """An activity's average cadence from its stream, while pedalling or stepping, as a FIT file would give it (a GPX import leaves it empty)."""
    rows = db.execute(f"SELECT id, {_streams.sql()} FROM Activity WHERE averageCadence IS NULL AND {_streams.has_sql(key='cadence')}").fetchall()
    for r in rows:
        cad = [c for c in ((json.loads(r['streams'] or '{}').get('cadence') or {}).get('data') or []) if c]
        if cad:
            db.execute('UPDATE Activity SET averageCadence=? WHERE id=?', [round(sum(cad) / len(cad), 1), r['id']])
    db.commit()


def make_session(db, uploads, rider, kind, start_local, pat, rng, athlete):
    """A timed session with no track. Returns its length in seconds, or None."""
    cfg = SESSIONS[kind]
    sp = pat['sports'].get(cfg['src']) or {}
    mins = q_pick(sp.get('moving_min_q'), rng, 0.15, 0.85) or 45
    dist = None
    if kind == 'swim':
        dist = round(rng.uniform(1000, 2600) / 50) * 50
        mins = dist / 1000 * rng.uniform(21, 26)
    elif kind == 'indoor':
        mins = max(30, min(90, mins))
        dist = mins / 60 * rng.uniform(28000, 33000)
    hr = q_pick(sp.get('avg_hr_q'), rng)
    s = dict(start=start_local.strftime('%Y-%m-%dT%H:%M'), duration_s=int(mins * 60), distance_m=dist, avg_hr=round(hr) if hr else None)
    try:
        uploads.receive(db, rider, sport=cfg['sport'], name=time_name(kind, start_local.hour), session=s)
    except Exception as ex:
        print(f'  session {kind}: {ex}')
        return None
    return int(mins * 60)


if __name__ == '__main__':
    main()
