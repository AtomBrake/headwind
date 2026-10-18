"""Backfill true max speed / heart rate / power on already-imported rides.

Before this fix, file imports stored the AVERAGE speed as the max speed and never stored max heart rate. This recomputes them
from each ride's own streams, touching only rows that carry that signature (max missing, zero, or equal to the average), so
anything a device or Garmin sync recorded properly is left alone."""
import json
import logging

from services.parser import extremes_from_streams

log = logging.getLogger(__name__)


def _blank(v):
    return v is None or v == 0


def backfill(db, apply=False, rewind_wind=False):
    """Returns counts. With apply=False nothing is written. Caller commits."""
    counts = {'rides': 0, 'maxSpeed': 0, 'maxHeartrate': 0, 'maxWatts': 0, 'windRel': 0}
    rows = db.execute("SELECT id, streams, averageSpeed, maxSpeed, maxHeartrate, maxWatts, weatherWindDir, weatherWindKph, weatherWindRel "
                      "FROM Ride WHERE streams IS NOT NULL AND streams NOT IN ('null', '{}')").fetchall()
    for r in rows:
        counts['rides'] += 1
        try:
            ex = extremes_from_streams(json.loads(r['streams']))
        except (ValueError, TypeError):
            continue
        sets = {}
        avg = r['averageSpeed']
        speed_suspect = _blank(r['maxSpeed']) or (avg is not None and abs(r['maxSpeed'] - avg) < 0.001)
        if 'maxSpeed' in ex and speed_suspect and ex['maxSpeed'] >= (avg or 0) and abs(ex['maxSpeed'] - (r['maxSpeed'] or 0)) > 0.001:
            sets['maxSpeed'] = ex['maxSpeed']
        if 'maxHeartrate' in ex and _blank(r['maxHeartrate']):
            sets['maxHeartrate'] = ex['maxHeartrate']
        if 'maxWatts' in ex and _blank(r['maxWatts']):
            sets['maxWatts'] = ex['maxWatts']
        if rewind_wind and r['weatherWindDir'] is not None and r['weatherWindKph'] is not None:
            from services.weather import _wind_exposure, _wind_relative
            rel = _wind_relative(_wind_exposure(r['streams'], r['weatherWindDir']), r['weatherWindKph'])
            if rel and rel != r['weatherWindRel']:
                sets['weatherWindRel'] = rel
        for k, v in sets.items():
            counts['windRel' if k == 'weatherWindRel' else k] += 1
        if sets and apply:
            cols = ', '.join(f'{k}=?' for k in sets)
            db.execute(f'UPDATE Activity SET {cols} WHERE id=?', [*sets.values(), r['id']])
    return counts


def fix_spiky_max_speed(db):
    """Rides whose top speed is one GPS spike (the Garmin sync used to take the raw max of the speed stream: 86-137 mph mountain-bike rides): recompute it from
    the ride's own streams, ignoring impossible values, and re-run the sanity check so a ride flagged only for that drops off the list. Cheap enough for
    every start-up: it only reads rides over the plausible limit, and writes nothing when there are none. Returns the number fixed. Does not commit."""
    from services.parser import _MAX_PLAUSIBLE
    from services import sanity
    fixed = 0
    for r in db.execute('SELECT id, streams FROM Ride WHERE maxSpeed > ?', [_MAX_PLAUSIBLE['speed']]).fetchall():
        try:
            ex = extremes_from_streams(json.loads(r['streams'] or '{}'))
        except (ValueError, TypeError):
            continue
        if 'maxSpeed' not in ex:                    # no usable speed or GPS data: leave it (still flagged, the rider decides)
            continue
        db.execute('UPDATE Activity SET maxSpeed=? WHERE id=?', [ex['maxSpeed'], r['id']])
        sanity.flag(db, r['id'])
        fixed += 1
    if fixed:
        log.warning('Top speed recomputed for %d ride(s) whose stored top speed was a GPS spike', fixed)
    return fixed
