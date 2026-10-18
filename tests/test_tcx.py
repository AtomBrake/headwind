"""TCX import: Strava's leading whitespace, lap totals, extension fields, and streams that stay one value per point."""
import gzip
import json

from services.parser import ACTIVITY_EXTENSIONS, parse_activity_file, parse_tcx

NS = 'xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2" xmlns:ns3="http://www.garmin.com/xmlschemas/ActivityExtension/v2"'


def _tp(s, lat=None, alt=None, dist=None, hr=None, cad=None, watts=None, speed=None):
    pos = f'<Position><LatitudeDegrees>{lat}</LatitudeDegrees><LongitudeDegrees>-3.58</LongitudeDegrees></Position>' if lat is not None else ''
    ext = ''.join(f'<ns3:{k}>{v}</ns3:{k}>' for k, v in (('Speed', speed), ('Watts', watts)) if v is not None)
    return (f'<Trackpoint><Time>2013-11-13T17:54:{s:02d}Z</Time>{pos}'
            + (f'<AltitudeMeters>{alt}</AltitudeMeters>' if alt is not None else '')
            + (f'<DistanceMeters>{dist}</DistanceMeters>' if dist is not None else '')
            + (f'<HeartRateBpm><Value>{hr}</Value></HeartRateBpm>' if hr is not None else '')
            + (f'<Cadence>{cad}</Cadence>' if cad is not None else '')
            + (f'<Extensions><ns3:TPX>{ext}</ns3:TPX></Extensions>' if ext else '') + '</Trackpoint>')


def _tcx(laps, sport='Biking', lead='          '):
    body = ''.join(f'<Lap StartTime="{start}"><TotalTimeSeconds>{secs}</TotalTimeSeconds><DistanceMeters>{dist}</DistanceMeters>'
                   f'<MaximumSpeed>{vmax}</MaximumSpeed><Calories>{kcal}</Calories>'
                   f'<MaximumHeartRateBpm><Value>{hrmax}</Value></MaximumHeartRateBpm><Track>{"".join(pts)}</Track></Lap>'
                   for start, secs, dist, vmax, kcal, hrmax, pts in laps)
    return (f'{lead}<?xml version="1.0" encoding="UTF-8" standalone="no" ?>\n<TrainingCenterDatabase {NS}><Activities>'
            f'<Activity Sport="{sport}"><Id>2013-11-13T17:54:00Z</Id>{body}</Activity></Activities></TrainingCenterDatabase>').encode()


def _outdoor():
    pts = [_tp(s, lat=50.65 + s * 0.0001, alt=200 + s, dist=s * 11.0, hr=120 + s, cad=80) for s in range(10)]
    return [('2013-11-13T17:54:00Z', 600.5, 105.0, 12.5, 30, 150, pts[:5]), ('2013-11-13T17:54:05Z', 300, 50.0, 13.0, 20, 155, pts[5:])]


def _streams(act):
    return json.loads(act['streams'])


def test_strava_leading_whitespace_and_a_bom_parse():
    for lead in ('          ', '﻿', '\n  ﻿'):
        act = parse_tcx(_tcx(_outdoor(), lead=lead).replace('﻿'.encode(), b'\xef\xbb\xbf'))
        assert act and act['startDateLocal'] == '2013-11-13T17:54:00+00:00'


def test_totals_come_from_the_laps():
    act = parse_tcx(_tcx(_outdoor()))
    assert act['distance'] == 155.0                      # lap distances, not the last trackpoint's 99 m
    assert act['movingTime'] == 900                      # lap timer time
    assert act['elapsedTime'] == 9
    assert act['calories'] == 50
    assert act['maxSpeed'] == 13.0 and act['maxHeartrate'] == 155
    assert act['sportType'] == 'Ride' and act['name'] == 'Ride Activity'
    assert act['startLat'] == 50.65 and act['averageCadence'] == 80
    assert act['totalElevationGain'] > 0


def test_a_broken_lap_distance_gives_way_to_the_trackpoints():
    pts = [_tp(s, lat=50.65 + s * 0.001, dist=s * 1000.0) for s in range(5)]
    assert parse_tcx(_tcx([('2013-11-13T17:54:00Z', 4, 42.5, 5, 0, 0, pts)]))['distance'] == 4000.0


def test_every_stream_has_one_value_per_point():
    pts = [_tp(0, lat=50.65, hr=100, dist=0), _tp(1, lat=50.6501, dist=10),                  # heart rate drops out for a point
           _tp(2, dist=20, hr=110),                                                          # no position (a tunnel): dropped outdoors
           _tp(3, lat=50.6503, hr=120, dist=30), _tp(3, lat=50.6503, hr=121, dist=30)]       # repeated timestamp: dropped
    s = _streams(parse_tcx(_tcx([('2013-11-13T17:54:00Z', 3, 30, 5, 1, 120, pts)])))
    assert {len(v['data']) for v in s.values()} == {3}
    assert s['time']['data'] == [0, 1, 3]
    assert s['heartrate']['data'] == [100, 100, 120]      # the gap carries the last reading


def test_indoor_file_keeps_power_and_speed_with_no_gps():
    pts = [_tp(s, dist=s * 7.0, hr=100 + s, cad=85, watts=150 + s, speed=7.0) for s in range(6)]
    act = parse_tcx(_tcx([('2013-11-13T17:54:00Z', 6, 35, 7.5, 10, 106, pts)]))
    s = _streams(act)
    assert 'latlng' not in s and act['startLat'] is None
    assert s['watts']['data'] == [150, 151, 152, 153, 154, 155] and act['averageWatts'] == 152.5
    assert s['velocity_smooth']['data'] == [7.0] * 6
    assert s['distance']['data'][-1] == 35.0


def test_distance_stream_is_worked_out_when_the_file_has_none():
    pts = [_tp(s, lat=50.65 + s * 0.001) for s in range(4)]
    s = _streams(parse_tcx(_tcx([('2013-11-13T17:54:00Z', 3, 0, 5, 0, 0, pts)])))
    assert s['distance']['data'][0] == 0 and 300 < s['distance']['data'][-1] < 340


def test_sports():
    assert parse_tcx(_tcx(_outdoor(), sport='Running'))['sportType'] == 'Run'


def test_no_trackpoints_is_none():
    assert parse_tcx(_tcx([('2013-11-13T17:54:00Z', 0, 0, 0, 0, 0, [])])) is None


def test_dispatch_by_extension():
    data = _tcx(_outdoor())
    assert '.tcx.gz' in ACTIVITY_EXTENSIONS
    assert parse_activity_file('activities/123.TCX.gz', gzip.decompress(gzip.compress(data)))['distance'] == 155.0
    assert parse_activity_file('notes.txt', data) is None
