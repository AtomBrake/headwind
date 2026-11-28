"""Feature switches: the parts of Headwind a rider can turn off in Settings → Features, so someone who only wants their activities isn't shown
the food diary, the gear maintenance or the AI coach. A switched-off feature leaves the sidebar and the dashboard, its pages show a "turned off
in Settings" note (templates/feature_off.html), its endpoints answer with a JSON error, its background work stops and its Home Assistant
entities are taken down. Its data is never deleted, so switching it back on brings everything back.

on(name, rider_id=None) is the one check. In a request, rider_id defaults to whose.rider_id(), the rider the request is about. Background work
(the Garmin sync, the part alerts, MQTT, the AI coach's automatic analysis) is handed its rider and passes it in: it never calls whose
(docs/MULTI-USER-PLAN.md, A2), and on() outside a request without a rider raises, so a missed caller fails loudly.

Where they're kept: RiderSettings.featuresOff (database step 13), a JSON list of the switches the rider has turned off. A rider with no row, or
a NULL there, takes the instance's default, Settings.featuresOff (NULL: everything on), which is what a new rider starts with.

Two switches are over others. Health is over Nutrition, Steps, Weight and Recovery, and Gear over Gear maintenance. Turning the upper one off
turns its parts off without changing what they're set to, so turning it back on brings back the same choices: on('steps') is False while
Health is off, whatever 'steps' itself says.

What depends on what (each written where it's decided):
  - The Garmin sync's daily figures feed Recovery, Steps and Nutrition's calorie burn, so they're read while any of those is on; the weigh-ins
    feed Weight and Nutrition's calorie goals, so they're read while either is (app._garmin_heartbeat, services/garmin.py).
  - Nutrition's calorie goals count everyday movement from the step goal. With Steps off they count the exercise allowance only (services/goal_model.profile).
  - Nutrition's page logs weigh-ins too, so the weight endpoints it uses answer while Weight or Nutrition is on; the Weight and backfill pages
    need Weight.
  - The AI coach leaves out recovery (and the steps in it) with Recovery off, and the segments with Segments off (services/context.py). It
    has no nutrition in it today; anything that adds some checks 'nutrition' there too.
  - Gear off: bikes and kit leave the activity page as well; activities keep the bike they had. Gear maintenance off: no parts, service log,
    replace-at or alerts, and the dashboard's due list goes; bikes, kit and their distances stay.
  - Friends off: the Friends page, the dashboard's Friends button and its friends' view, the automatic sync, and the feed a friend's Headwind
    reads from here (they get a JSON error until it's back on).
  - Challenges off: the Challenges page and the dashboard's challenge rows. The friends feed still carries them both ways, so friends' races
    keep us in and switching back on finds them up to date (services/challenges.py). Its own switch since database step 18; Goals
    covered both before.
"""
import json
import logging
from collections import namedtuple

from flask import g, has_request_context, jsonify, render_template, request

log = logging.getLogger(__name__)

Feature = namedtuple('Feature', 'key label hint parent')

FEATURES = (
    Feature('health',      'Health',           'Nutrition, Steps, Weight and Recovery together, and the Health heading in the sidebar.', None),
    Feature('nutrition',   'Nutrition',        'The food diary, water and the calorie goals.', 'health'),
    Feature('steps',       'Steps',            'The Steps page. With it off the calorie goals count your exercise only.', 'health'),
    Feature('weight',      'Weight',           'The Weight page and its backfill page.', 'health'),
    Feature('recovery',    'Recovery',         "The Recovery page, the dashboard's Recovery Today card and the Garmin health sync.", 'health'),
    Feature('gear',        'Gear',             'Bikes, shoes and other kit, and picking them on an activity.', None),
    Feature('maintenance', 'Gear maintenance', "Parts, wear and the service log on a bike, kit's replace-at distance, and the alerts when something "
                                               'is due. Bikes and kit stay.', 'gear'),
    Feature('segments',    'Segments',         "Segments and their leaderboards, and an activity's efforts.", None),
    Feature('routes',      'Routes',           'Saved routes.', None),
    Feature('heatmap',     'Heatmap',          'The map of every track.', None),
    Feature('goals',       'Goals',            'Your weekly, monthly and yearly goals, and their card on the dashboard.', None),
    Feature('challenges',  'Challenges',       "Races with friends over set dates, and their place on the dashboard's Goals card.", None),
    Feature('coach',       'AI coach',         'The coaching notes on an activity, written as it arrives or when asked.', None),
    Feature('friends',     'Friends',          "Friends' activities, the feed they read from here, and the automatic sync.", None),
    Feature('live',        'Live tracking',    'Live tracking links to send while recording, and the contacts they go to.', None),
    Feature('roughness',   'Roughness',        'The road roughness map from the phone.', None),
    Feature('planner',     'Route planner',    'Planning a route on the map.', None),
)
BY_KEY = {f.key: f for f in FEATURES}
NAMES = tuple(BY_KEY)


def children(key):
    return [f.key for f in FEATURES if f.parent == key]


def groups():
    """The switches for Settings: [(upper feature, [its parts])], in FEATURES order."""
    return [(f, [BY_KEY[c] for c in children(f.key)]) for f in FEATURES if f.parent is None]


# ── Where they're kept ──────────────────────────────────────────────────────

def _parse(text):
    """A stored JSON list as a frozenset of known names. Anything else (an unknown name from a newer Headwind, junk) is left out."""
    if not text:
        return frozenset()
    try:
        names = json.loads(text)
    except (TypeError, ValueError):
        log.warning('Feature switches: %r is not a JSON list; treated as everything on', text)
        return frozenset()
    return frozenset(n for n in names if n in BY_KEY) if isinstance(names, list) else frozenset()


def _dump(names):
    return json.dumps(sorted(set(names) & set(NAMES)))


def instance_default(db=None):
    """The switches a new rider starts with turned off (Settings.featuresOff)."""
    from services import page_facts
    facts = page_facts.get() if db is None else None
    if facts is not None:
        return _parse(facts['featuresOff'])
    db = db or _db()
    try:
        row = db.execute('SELECT featuresOff FROM Settings WHERE id=1').fetchone()
    except Exception:                                   # a database from before step 13 (the setup wizard's first moments)
        return frozenset()
    return _parse(row[0] if row else None)


def stored(rider_id, db=None):
    """The switches the rider has turned off, as set (an upper switch's parts keep their own setting): their RiderSettings row, else the
    instance default. For the owner in a request, read with the rest of the page's frame (services/page_facts), not on its own."""
    from services import page_facts
    facts = page_facts.get() if db is None else None
    if facts is not None and rider_id is not None and rider_id == facts['ownerId']:
        mine = facts['ownerFeaturesOff']
        return _parse(mine if mine is not None else facts['featuresOff'])
    db = db or _db()
    if rider_id is not None:
        try:
            row = db.execute('SELECT featuresOff FROM RiderSettings WHERE riderId=?', [rider_id]).fetchone()
        except Exception:
            row = None
        if row and row[0] is not None:
            return _parse(row[0])
    return instance_default(db)


def save(db, rider_id, off):
    """Keep the rider's switches: off is the names turned off. Unknown names are dropped. Does not commit."""
    db.execute('INSERT INTO RiderSettings (riderId, featuresOff) VALUES (?, ?) '
               'ON CONFLICT(riderId) DO UPDATE SET featuresOff=excluded.featuresOff', [rider_id, _dump(off)])
    _forget()


def save_default(db, off):
    """The instance default a new rider starts with. Does not commit."""
    db.execute('UPDATE Settings SET featuresOff=? WHERE id=1', [_dump(off)])
    _forget()


def forget_rider(db, rider_id):
    """A rider deleted: their switches go with them. Does not commit."""
    db.execute('DELETE FROM RiderSettings WHERE riderId=?', [rider_id])
    _forget()


def _db():
    from database import get_db
    return get_db()


def _forget():
    """After a save: what this request read before is out of date, the page facts included."""
    if has_request_context():
        g.pop('_features_off', None)
        g.pop('_page_facts', None)


# ── The check ──────────────────────────────────────────────────────────────

def _rider(rider_id):
    if rider_id is not None:
        return rider_id
    if not has_request_context():
        raise ValueError('features.on() outside a request needs the rider: background work is handed one and passes it in.')
    from services import whose
    return whose.rider_id()


def off(rider_id=None):
    """Every feature that is off for the rider, counting the parts of an upper switch that's off: a frozenset of names."""
    rid = _rider(rider_id)
    cache = g.setdefault('_features_off', {}) if has_request_context() else None
    if cache is not None and rid in cache:
        return cache[rid]
    raw = stored(rid)
    eff = frozenset(f.key for f in FEATURES if f.key in raw or (f.parent and f.parent in raw))
    if cache is not None:
        cache[rid] = eff
    return eff


def on(name, rider_id=None):
    """Whether the feature is on for the rider (in a request, the request's own rider by default). A part of Health or Gear is off while that
    is. An unknown name raises KeyError, so a typo can't quietly leave something on."""
    if name not in BY_KEY:
        raise KeyError(f'No feature called {name!r}')
    return name not in off(rider_id)


def riders_without(name, db=None):
    """The ids of the riders who have the feature off, for background work that goes over every rider at once (the part alerts)."""
    db = db or _db()
    return {r[0] for r in db.execute('SELECT id FROM Rider').fetchall() if not on(name, r[0])}


def any_on(names, rider_id=None):
    return any(on(n, rider_id) for n in names)


def health_heading(rider_id=None):
    """Whether the sidebar's Health heading shows: Health on and one of the pages under it (Nutrition, Steps, Weight) on."""
    return any_on(('nutrition', 'steps', 'weight'), rider_id)


class Checker:
    """What the templates get as `feature` (a context processor in app.py): feature('nutrition'), feature.any('nutrition', 'weight')."""
    def __call__(self, name):
        try:
            return on(name)
        except Exception as e:                          # never break a page over a switch: before step 13, or no rider yet
            if isinstance(e, KeyError):
                raise
            return True

    def any(self, *names):
        return any(self(n) for n in names)


# ── Pages and endpoints ────────────────────────────────────────────────────
# Which feature each endpoint belongs to: a blueprint as a whole, or one endpoint. A tuple means any of them: the endpoint answers while one
# is on. Endpoints not listed here belong to no feature. tests/test_features.py checks every name here is a real endpoint.

BLUEPRINTS = {
    'garmin_page':   'recovery',
    'gear':          'gear',
    'segments':      'segments',
    'saved_routes':  'routes',
    'heatmap':       'heatmap',
    'goals':         'goals',
    'challenges':    'challenges',
    'ai_page':       'coach',
    'kudos':         'coach',
    'friends':       'friends',
    'roughness':     'roughness',
    'route_builder': 'planner',
    'nutrition':     'nutrition',                      # but for the steps and weight ones below
}

_WEIGHT_SHARED = ('weight', 'nutrition')              # the Nutrition page and Settings' profile card log weigh-ins too

ENDPOINTS = {
    # Steps
    'nutrition.steps_page': 'steps', 'nutrition.steps_list': 'steps', 'nutrition.steps_source': 'steps', 'nutrition.steps_set': 'steps',
    'nutrition.steps_delete': 'steps',
    # Weight
    'nutrition.weight_graph_page': 'weight', 'nutrition.weight_backfill_page': 'weight', 'nutrition.weight_graph_data': 'weight',
    'nutrition.body_metrics': 'weight', 'nutrition.weight_backfill_preview': 'weight', 'nutrition.weight_backfill_confirm': 'weight',
    'nutrition.get_weight_settings': _WEIGHT_SHARED, 'nutrition.save_weight_settings': _WEIGHT_SHARED, 'nutrition.log_weight': _WEIGHT_SHARED,
    'nutrition.delete_weight': _WEIGHT_SHARED, 'nutrition.weight_refresh': _WEIGHT_SHARED,
    # Gear maintenance (the rest of the gear blueprint is Gear's)
    'gear.part_add': 'maintenance', 'gear.part_edit': 'maintenance', 'gear.service_add': 'maintenance', 'gear.log_delete': 'maintenance',
    # Segments found on an activity
    'activities.scan_segments': 'segments',
    # The phone's API
    'api_v1.live_share': 'live', 'api_v1.contacts_list': 'live', 'api_v1.contact_one': 'live',
    'api_v1.sync_nutrition': 'nutrition',
    'api_v1.health_days': ('steps', 'weight', 'recovery'), 'api_v1.health_summary': ('steps', 'weight', 'recovery'),
    'api_v1.friend_token': 'friends', 'api_v1.friend_probe': 'friends', 'api_v1.friend_add': 'friends', 'api_v1.friend_list': 'friends',
    'api_v1.set_bike': 'gear',
    # Settings: the contacts a live link is emailed to
    'settings.add_contact': 'live', 'settings.save_contact': 'live', 'settings.delete_contact': 'live',
}

# Never refused, whatever the switches: a running live link's page is for whoever it was sent to, and ends by itself (the API above stops new
# ones). Nothing else is exempt: a friend's Headwind reading the feed gets the JSON error.
EXEMPT = frozenset({'live_share.page', 'live_share.data'})


def needs(endpoint):
    """The feature (or tuple of features, any of which will do) the endpoint belongs to, or None."""
    if not endpoint or endpoint in EXEMPT:
        return None
    if endpoint in ENDPOINTS:
        return ENDPOINTS[endpoint]
    return BLUEPRINTS.get(endpoint.split('.', 1)[0]) if '.' in endpoint else None


def _wants_json():
    p = request.path
    return (request.method not in ('GET', 'HEAD') or '/api/' in p or p.startswith('/api') or request.is_json
            or 'application/json' in (request.headers.get('Accept') or '') or request.headers.get('Authorization', '').startswith('Bearer '))


def refusal(feature):
    """The answer for an endpoint of a switched-off feature: a page with the note, or for the API and anything sent by a script, a JSON
    error the app can show."""
    f = BY_KEY[feature]
    if _wants_json():
        return jsonify(error=f'{f.label} is turned off in Settings.', feature_off=feature, settings_url='/settings#features'), 403
    return render_template('feature_off.html', off_feature=f), 403


def gate():
    """A before_request hook (app.py, after the login check): refuses an endpoint whose feature is off for the request's rider."""
    need = needs(request.endpoint)
    if need is None:
        return None
    try:
        names = need if isinstance(need, tuple) else (need,)
        if any(on(n) for n in names):
            return None
    except Exception:                                   # no rider yet, or a database from before step 13: nothing is off
        log.debug('Feature check skipped for %s', request.endpoint, exc_info=True)
        return None
    return refusal(names[0])


# ── Home Assistant ─────────────────────────────────────────────────────────

_SENSOR_FEATURES = {
    'garmin_steps': 'steps',
    'nutrition_steps_today': 'steps', 'nutrition_steps_source': 'steps', 'nutrition_steps_goal': 'steps', 'nutrition_steps_avg_7d': 'steps',
    'nutrition_weight_history': 'weight', 'nutrition_weight_trend_kg': 'weight', 'nutrition_weight_rate_kg_wk': 'weight',
    'nutrition_recovery_history': 'recovery',
    'nutrition_ride_segments': 'segments', 'nutrition_run_segments': 'segments',
}
# Every sport's charts and the Garmin sync's state are about activities, not food, though their ids start nutrition_
_ACTIVITY_SENSORS = {'nutrition_training_weekly', 'nutrition_ride_months', 'nutrition_ride_years', 'nutrition_ride_route', 'nutrition_run_stats',
                     'nutrition_run_route', 'nutrition_activity_weekly', 'nutrition_activity_status', 'nutrition_garmin_last_sync',
                     'nutrition_garmin_status', 'nutrition_garmin_watch_sync'}


def sensor_feature(uid):
    """The feature a Home Assistant entity (services/mqtt.py's uid) belongs to, or None for the activity ones that always stay."""
    if uid in _SENSOR_FEATURES:
        return _SENSOR_FEATURES[uid]
    if uid.startswith('garmin_'):
        return 'recovery'
    if uid.startswith('nutrition_') and uid not in _ACTIVITY_SENSORS:
        return 'nutrition'
    return None
