"""Zwift's worlds, so a virtual ride can be drawn over the world it was ridden in rather than over the real map at the same spot. Watopia,
Makuri Islands, France and Crit City sit on open sea near the Solomon Islands and New Caledonia; the others copy a real place (London,
New York, Richmond, ...) and land roughly where it is.

Each world is a fixed box of latitude and longitude, and Zwift's own minimap of it fits that box exactly (it's what ZwiftMap draws with
Leaflet's imageOverlay). The boxes and image names are from zwift-data (https://github.com/andipaetzold/zwift-data, MIT, Andi Pätzold).
The images are Zwift's and are not kept here: map_image fetches one from Zwift's CDN when a page first asks for it, and keeps it in memory.
"""
import logging
import threading

import requests

log = logging.getLogger(__name__)

_CDN = 'https://cdn.zwift.com/static/images/maps/'
CREDIT = 'Map © Zwift'

# slug, name, (south, north, west, east), Zwift's image, made up (on open sea: never a real ride's map)
WORLDS = [
    {'slug': 'watopia',        'name': 'Watopia',        'box': (-11.74087, -11.62597, 166.87747, 167.03255),       'image': 'MiniMap_Watopia_2.png', 'madeUp': True},
    {'slug': 'richmond',       'name': 'Richmond',       'box': (37.5014, 37.5774, -77.48954, -77.394),            'image': 'MiniMap_Richmond.png',  'madeUp': False},
    {'slug': 'london',         'name': 'London',         'box': (51.4601, 51.5362, -0.1776, -0.0555),              'image': 'MiniMap_London.png',    'madeUp': False},
    {'slug': 'new-york',       'name': 'New York',       'box': (40.587913, 40.817257, -74.022655, -73.922165),    'image': 'MiniMap_NewYork_2.png', 'madeUp': False},
    {'slug': 'innsbruck',      'name': 'Innsbruck',      'box': (47.2055, 47.2947, 11.3501, 11.4822),              'image': 'MiniMap_Innsbruck.png', 'madeUp': False},
    {'slug': 'bologna',        'name': 'Bologna',        'box': (44.45463821, 44.5308037, 11.26261748, 11.36991729), 'image': 'MiniMap_Bologna.png', 'madeUp': False},
    {'slug': 'yorkshire',      'name': 'Yorkshire',      'box': (53.9491, 54.0254, -1.632, -1.5022),               'image': 'MiniMap_Yorkshire.png', 'madeUp': False},
    {'slug': 'crit-city',      'name': 'Crit City',      'box': (-10.4038, -10.3657, 165.7824, 165.8207),          'image': 'MiniMap_CritCity.png',  'madeUp': True},
    {'slug': 'makuri-islands', 'name': 'Makuri Islands', 'box': (-10.85234, -10.73746, 165.76591, 165.88222),      'image': 'MiniMap_Japan.png',     'madeUp': True},
    {'slug': 'france',         'name': 'France',         'box': (-21.7564, -21.64155, 166.1384, 166.26125),        'image': 'MiniMap_France.png',    'madeUp': True},
    {'slug': 'paris',          'name': 'Paris',          'box': (48.82945, 48.9058, 2.2561, 2.3722),               'image': 'MiniMap_Champs.png',    'madeUp': False},
    {'slug': 'scotland',       'name': 'Scotland',       'box': (55.61845, 55.67595, -5.2802, -5.17798),           'image': 'MiniMap_Scotland.png',  'madeUp': False},
]
BY_SLUG = {w['slug']: w for w in WORLDS}
SLACK = 0.01            # degrees (about 1 km) a track may stray past its world's box: a GPS point or two, or a box drawn a little tight


def world_of(min_lat, max_lat, min_lng, max_lng):
    """The world whose box holds a track's box (services/tracks: ActivityTrack's minLat ... maxLng), or None. Only ask this of a virtual
    ride (sports.is_virtual): a real ride in London is inside Zwift's London too."""
    if None in (min_lat, max_lat, min_lng, max_lng):
        return None
    for w in WORLDS:
        s, n, west, east = w['box']
        if min_lat >= s - SLACK and max_lat <= n + SLACK and min_lng >= west - SLACK and max_lng <= east + SLACK:
            return w
    return None


def for_page(w):
    """What a page's script needs to draw a world: its name, Leaflet's [[south, west], [north, east]] and the address of its map."""
    s, n, west, east = w['box']
    return {'slug': w['slug'], 'name': w['name'], 'bounds': [[s, west], [n, east]], 'madeUp': w['madeUp'],
            'url': f"/heatmap/zwift/{w['slug']}.png"}


_images = {}
_lock = threading.Lock()


def map_image(slug):
    """A world's minimap as PNG bytes, fetched from Zwift once per run (up to about 3 MB each), or None for an unknown world or a failed fetch."""
    w = BY_SLUG.get(slug)
    if not w:
        return None
    with _lock:
        if slug in _images:
            return _images[slug]
    try:
        r = requests.get(_CDN + w['image'], timeout=20, headers={'User-Agent': 'Headwind/1.0 (self-hosted bike app)'})
    except requests.RequestException:
        log.debug('Zwift map fetch failed for %s', slug, exc_info=True)
        return None
    if r.status_code != 200 or not r.content.startswith(b'\x89PNG'):
        log.debug('Zwift map fetch for %s: HTTP %s', slug, r.status_code)
        return None
    with _lock:
        _images[slug] = r.content
    return r.content
