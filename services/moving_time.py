"""Moving times a device got wrong. A Garmin whose battery went flat, or that restarted mid-ride, can write a lap timer of a few seconds for the
whole ride (9 s for 11 km: 2,766 mph), and a TCX import took it as the moving time. services/parser.parse_tcx now works it out from the track
when the device's is under half of that, as Strava does; repair() puts right the activities stored before 0.7.7, from their streams.

The opposite: a device with auto-pause off counts every stop, so a bike park day spent in the uplift queue came in at 7 hours moving where Strava
says 2. FIT and TCX imports now take the track's then too (parser.pick_moving_time); repair_paused() puts right those already stored."""
import json
import logging

from services.parser import PAUSED_SLACK, track_moving_time

log = logging.getLogger(__name__)
_BATCH = 50


def repair(db):
    """Run once (Settings.movingTimeFixDone): every activity whose moving time is under half what its own track shows gets the track's, and the
    average speed that goes with it. Commits. Returns {'ran', 'fixed': [(id, name, old secs, new secs)]}."""
    s = db.execute('SELECT movingTimeFixDone FROM Settings WHERE id=1').fetchone()
    if not s or s['movingTimeFixDone']:
        return {'ran': False}
    fixed = []
    ids = [r[0] for r in db.execute("SELECT id FROM Activity WHERE streams IS NOT NULL AND streams NOT IN ('null', '{}')")]
    for i in range(0, len(ids), _BATCH):
        chunk = ids[i:i + _BATCH]
        for r in db.execute(f"SELECT id, name, distance, movingTime, streams FROM Activity WHERE id IN ({','.join('?' * len(chunk))})", chunk).fetchall():
            try:
                on_track = track_moving_time(json.loads(r['streams']))
            except (TypeError, ValueError):
                continue
            if on_track and (r['movingTime'] or 0) < on_track / 2:
                db.execute('UPDATE Activity SET movingTime=?, averageSpeed=? WHERE id=?',
                           [on_track, round(r['distance'] / on_track, 4) if r['distance'] else None, r['id']])
                fixed.append((r['id'], r['name'], r['movingTime'], on_track))
        db.commit()
    db.execute('UPDATE Settings SET movingTimeFixDone=1 WHERE id=1')
    db.commit()
    if fixed:
        log.warning('Moving times put right from the track: %s', ', '.join(f'{f[0]} ({f[2]} s -> {f[3]} s)' for f in fixed))
    return {'ran': True, 'fixed': fixed}


def repair_paused(db):
    """Run once (Settings.movingTimePausedDone): every activity whose moving time is well over what its own track shows (stopped time counted)
    gets the track's, and the average speed that goes with it. Not on the water (parser.pick_moving_time). Commits.
    Returns {'ran', 'fixed': [(id, name, old secs, new secs)]}."""
    from services.sports import on_water
    s = db.execute('SELECT movingTimePausedDone FROM Settings WHERE id=1').fetchone()
    if not s or s['movingTimePausedDone']:
        return {'ran': False}
    fixed = []
    ids = [r[0] for r in db.execute("SELECT id FROM Activity WHERE streams IS NOT NULL AND streams NOT IN ('null', '{}') AND movingTime > 0")]
    for i in range(0, len(ids), _BATCH):
        chunk = ids[i:i + _BATCH]
        for r in db.execute(f"SELECT id, name, sportType, distance, movingTime, streams FROM Activity WHERE id IN ({','.join('?' * len(chunk))})",
                            chunk).fetchall():
            if on_water(r['sportType']):
                continue
            try:
                on_track = track_moving_time(json.loads(r['streams']))
            except (TypeError, ValueError):
                continue
            if on_track and r['movingTime'] > on_track * PAUSED_SLACK[0] + PAUSED_SLACK[1]:
                db.execute('UPDATE Activity SET movingTime=?, averageSpeed=? WHERE id=?',
                           [on_track, round(r['distance'] / on_track, 4) if r['distance'] else None, r['id']])
                fixed.append((r['id'], r['name'], r['movingTime'], on_track))
        db.commit()
    db.execute('UPDATE Settings SET movingTimePausedDone=1 WHERE id=1')
    db.commit()
    if fixed:
        log.info('Moving times without the stops, from the track: %d activities', len(fixed))
    return {'ran': True, 'fixed': fixed}
