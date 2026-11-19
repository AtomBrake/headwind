"""Favourite sports: each is an item in the sidebar, under Activity, that opens the Activities page with only that sport left in. A favourite is a
stat group ('group:ride': every kind of ride, so an e-bike or gravel ride first done tomorrow is in it too) or one sport ('sport:Run': runs
without the walks). The list opened says what it keeps (group=ride, only=Run: services/sport_filter.py), never what it leaves out.

Kept for the instance in Settings.favouriteSports (a JSON list, in the order picked), chosen in Settings → Display. The phone app gets them from
/api/v1/ping as favourite_sports: {label, icon, group} or {label, icon, sport}, the arguments its activity list (/api/v1/rides) takes."""
import json

from services import sports

GROUP_NAMES = {'ride': 'Cycling', 'foot': 'On foot', 'swim': 'Swimming'}      # the groups of more than one sport; any other is one sport
MAX = 8


def parse(raw):
    """The stored list, without anything unreadable: ['group:ride', 'sport:Run', ...]."""
    try:
        keys = json.loads(raw or '[]')
    except ValueError:
        return []
    return [k for k in keys if isinstance(k, str) and _split(k)][:MAX] if isinstance(keys, list) else []


def _split(key):
    kind, _, value = key.partition(':')
    return (kind, value) if kind in ('group', 'sport') and value and (kind == 'sport' or value in GROUP_NAMES) else None


def describe(key):
    """{key, label, icon, arg: (name, value) for the list's URL}, or None for a key that isn't one."""
    parts = _split(key)
    if not parts:
        return None
    kind, value = parts
    if kind == 'group':
        return {'key': key, 'label': GROUP_NAMES[value], 'icon': sports.STAT_ICONS[value], 'arg': ('group', value)}
    return {'key': key, 'label': sports.label(value), 'icon': sports.icon(value), 'arg': ('only', value)}


def choices(db, rider_id):
    """What can be picked, as describe() dicts: Cycling, On foot and Swimming where the rider has any of them, then each sport they have."""
    have = [r[0] for r in db.execute("SELECT DISTINCT COALESCE(NULLIF(sportType, ''), 'Ride') FROM Activity WHERE riderId=?", [rider_id])]
    groups = sorted({sports.stat_group(s) for s in have} & set(GROUP_NAMES), key=sports.stat_order)
    singles = sorted({sports.canonical(s) for s in have}, key=lambda s: (sports.stat_order(sports.stat_group(s)), sports.label(s)))
    return [describe(f'group:{g}') for g in groups] + [describe(f'sport:{s}') for s in singles]


def save(db, keys):
    """Store the picked keys (anything that isn't one is dropped, as are repeats). Does not commit."""
    keys = [k for k in dict.fromkeys(keys or []) if _split(k)][:MAX]
    db.execute('UPDATE Settings SET favouriteSports=? WHERE id=1', [json.dumps(keys) if keys else None])
    return keys


def sidebar(raw, endpoint, args):
    """The sidebar's items: [{label, icon, url, active}], active while the Activities page shows that filter and nothing else (the rider and
    commute filters aside)."""
    from urllib.parse import urlencode
    shown = endpoint == 'dashboard.activities_page' and \
        {(k, v) for k, v in args.items(multi=True) if v and k not in ('rider', 'commute', 'page')}     # every other filter that's on
    out = []
    for key in parse(raw):
        d = describe(key)
        out.append(dict(d, url='/activities?' + urlencode([d['arg']]), active=shown == {d['arg']}))
    return out
