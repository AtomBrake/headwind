"""Map tiles the server fetches: the heatmap's HD export draws on a canvas, which needs them same-origin. The browser's own maps load tiles
straight from each provider (static/js/maps.js holds the full list, with attribution); this is the server's half of it.

Each provider's terms, checked 2026-10:
- Esri (World Imagery, gray canvases, World Topo): keyless, as before.
- OpenTopoMap, CyclOSM (OpenStreetMap France) and Waymarked Trails: free with attribution, no bulk downloading, a user agent that says
  who we are. An export is a screen's worth of tiles, fetched once.
- OS Maps API (Ordnance Survey): a key from the OS Data Hub. Only zooms 7-16 (Open Zoomstack), which are free and unlimited on the OpenData
  plan; 17-20 are Premium and charged past a monthly allowance, so the maps scale zoom 16 up instead. OS Leisure (the 1:25,000 Explorer
  maps, with rights of way) is only published in British National Grid (EPSG:27700), not the Web Mercator every map here uses.
- Thunderforest: a key from thunderforest.com (Hobby: 150,000 tiles a month free). Its terms forbid proxies, so it isn't here: the export
  loads its tiles straight from the browser, as the maps do."""
import io
import logging

import requests

log = logging.getLogger(__name__)

USER_AGENT = 'Headwind (self-hosted activity app; https://github.com/lordmaa/headwind)'

_ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/{}/MapServer/tile/{{z}}/{{y}}/{{x}}'
# name -> (tile URL, native max zoom or None, min zoom, the key it needs (KEYS) or None). Past the native zoom the parent tile is
# enlarged, as Leaflet does on screen (maxNativeZoom in maps.js), instead of the provider's "no tiles here" picture. CARTO's basemaps need
# an API key from 2026, so dark/light are Esri's keyless gray canvases (each a base and a place-name overlay, exported as two layers).
LAYERS = {
    'satellite':   (_ESRI.format('World_Imagery'), None, 0, None),
    'labels':      (_ESRI.format('Reference/World_Boundaries_and_Places'), None, 0, None),
    'dark':        (_ESRI.format('Canvas/World_Dark_Gray_Base'), 16, 0, None),
    'dark_ref':    (_ESRI.format('Canvas/World_Dark_Gray_Reference'), 16, 0, None),
    'light':       (_ESRI.format('Canvas/World_Light_Gray_Base'), 16, 0, None),
    'light_ref':   (_ESRI.format('Canvas/World_Light_Gray_Reference'), 16, 0, None),
    'topo':        (_ESRI.format('World_Topo_Map'), None, 0, None),
    'opentopo':    ('https://a.tile.opentopomap.org/{z}/{x}/{y}.png', 17, 0, None),
    'cyclosm':     ('https://a.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png', 20, 0, None),
    'os':          ('https://api.os.uk/maps/raster/v1/zxy/Outdoor_3857/{z}/{x}/{y}.png?key={key}', 16, 7, 'os'),
    'wmt_mtb':     ('https://tile.waymarkedtrails.org/mtb/{z}/{x}/{y}.png', 18, 0, None),
    'wmt_cycling': ('https://tile.waymarkedtrails.org/cycling/{z}/{x}/{y}.png', 18, 0, None),
}
# The keys a map type needs, by the name maps.js knows them by -> Settings column (sealed by services/vault.py)
KEYS = {'thunderforest': 'thunderforestKey', 'os': 'osMapsKey'}


def keys(db):
    """{'thunderforest': key, 'os': key} for the maps in the browser: the ones entered in Settings, blank for the rest."""
    try:
        s = db.execute(f"SELECT {', '.join(KEYS.values())} FROM Settings WHERE id=1").fetchone()
    except Exception:                          # before the migration has run
        s = None
    return {name: ((s[col] if s else None) or '') for name, col in KEYS.items()}


def fetch(db, name, z, x, y):
    """(bytes, mimetype) of one tile of the layer, or None: an unknown layer, one whose key isn't set, a zoom it doesn't cover, or the
    provider failing."""
    if name not in LAYERS:
        return None
    url, native, min_zoom, needs = LAYERS[name]
    key = keys(db)[needs] if needs else ''
    if (needs and not key) or z < min_zoom:
        return None
    dz = z - native if native and z > native else 0
    try:
        r = requests.get(url.format(z=z - dz, x=x >> dz, y=y >> dz, key=key), timeout=8, headers={'User-Agent': USER_AGENT})
        if r.status_code != 200:
            return None
        if not dz:
            return r.content, r.headers.get('Content-Type', 'image/png')
        # Past the layer's native zoom: the right quarter / sixteenth / ... of the parent tile, enlarged
        from PIL import Image
        img = Image.open(io.BytesIO(r.content)).convert('RGBA')
        size = img.width >> dz
        left, top = (x & ((1 << dz) - 1)) * size, (y & ((1 << dz) - 1)) * size
        out = io.BytesIO()
        img.crop((left, top, left + size, top + size)).resize((256, 256), Image.LANCZOS).save(out, 'PNG')
        return out.getvalue(), 'image/png'
    except Exception:
        log.debug('Map tile fetch failed (%s)', name, exc_info=True)
        return None
