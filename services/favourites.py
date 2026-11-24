"""Favourite sports: each is an item in the sidebar, under Activity, that opens the Activities page with only that sport left in. A favourite is a
stat group ('group:ride': every kind of ride, so an e-bike or gravel ride first done tomorrow is in it too) or one sport ('sport:Run': runs
without the walks). The list opened says what it keeps (group=ride, only=Run: services/sport_filter.py), never what it leaves out.

Kept for the instance in Settings.favouriteSports (a JSON list, in the order picked), chosen in Settings → Display. The phone app gets them from
/api/v1/ping as favourite_sports: {label, icon, group} or {label, icon, sport}, the arguments its activity list (/api/v1/activities) takes."""
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


def parse_set(raw):
    """A stored set of sports (Settings.aiAutoSports, Goal.sports, Settings.exerciseSports): None for every sport (NULL or ''), else the list of
    keys ('group:ride', 'sport:Run'), anything unreadable dropped. Unlike parse() there's no limit: a goal can count as many sports as it likes."""
    if raw is None or raw == '':
        return None
    try:
        keys = json.loads(raw)
    except ValueError:
        return None
    return list(dict.fromkeys(k for k in keys if isinstance(k, str) and _split(k))) if isinstance(keys, list) else None


def dump_set(keys):
    """parse_set the other way: NULL for every sport (None), else the keys as JSON, repeats and anything that isn't one dropped."""
    return None if keys is None else json.dumps(list(dict.fromkeys(k for k in keys if _split(k))))


def covers(keys, sport):
    """Whether a set of sports (parse_set) takes in this sport. A group is a stat group (services/sports.stat_group); a sport is matched by its
    canonical name, a row with no sport as a ride."""
    if keys is None:
        return True
    sport = sports.canonical(sport or 'Ride')
    return f'group:{sports.stat_group(sport)}' in keys or f'sport:{sport}' in keys


def group_of(key):
    """The stat group a key's distances add to: 'ride', 'foot', 'swim', or the sport itself ('Paddle')."""
    kind, value = _split(key)
    return value if kind == 'group' else sports.stat_group(sports.canonical(value))


_COUNTABLE = ('ride', 'run', 'walk', 'hike', 'swim', 'row', 'paddle', 'surf', 'climb', 'skate', 'session', 'workout')


def noun(key):
    """A key as a plural noun for a sentence: 'rides', 'swims', 'on foot', 'runs', 'indoor rides', 'yoga'."""
    kind, value = _split(key)
    if kind == 'group':
        return sports.stat_label(value).lower()          # 'Rides', 'On foot', 'Swims': the groups' names live in services/sports
    text = sports.label(value).lower()
    return text + 's' if text.split()[-1] in _COUNTABLE else text


def nouns(keys, every='every sport'):
    """A set of sports in words: 'rides', 'rides or runs', 'rides, runs or swims'; `every` for None."""
    if keys is None:
        return every
    words = [noun(k) for k in keys]
    return words[0] if len(words) == 1 else ', '.join(words[:-1]) + ' or ' + words[-1]


def icons(keys):
    """The icons of a set of sports, at most three: '🏅' for every sport."""
    if keys is None:
        return '🏅'
    return ''.join(list(dict.fromkeys(describe(k)['icon'] for k in keys))[:3]) or '🏅'


def choices_with(db, rider_id, keys):
    """choices(), plus any of keys the rider has nothing of now (a sport picked once still shows ticked)."""
    out = choices(db, rider_id)
    have = {c['key'] for c in out}
    return out + [describe(k) for k in keys or [] if k not in have and describe(k)]


def choices(db, rider_id, every_group=False):
    """What can be picked, as describe() dicts: Cycling, On foot and Swimming where the rider has any of them (all three with every_group, for
    a goal of a sport not started yet), then each sport they have."""
    have = [r[0] for r in db.execute("SELECT DISTINCT COALESCE(NULLIF(sportType, ''), 'Ride') FROM Activity WHERE riderId=?", [rider_id])]
    groups = sorted(set(GROUP_NAMES) if every_group else {sports.stat_group(s) for s in have} & set(GROUP_NAMES), key=sports.stat_order)
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
