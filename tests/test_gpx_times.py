"""GPX timestamps gpxpy can't read on its own (Trailforks writes a lower-case 'z')."""
import json

from services.parser import parse_gpx


def _gpx(times):
    pts = ''.join(f'<trkpt lat="50.69{i:03d}" lon="-3.48"><ele>12</ele>{f"<time>{t}</time>" if t else ""}</trkpt>'
                  for i, t in enumerate(times))
    return f'<?xml version="1.0"?><gpx version="1.1" creator="Trailforks.com" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>{pts}</trkseg></trk></gpx>'.encode()


def test_lower_case_z_timestamps_import():
    act = parse_gpx(_gpx([f'2026-07-21T12:05:{s:02d}z' for s in range(30)]))
    assert act and act['startDateLocal'].startswith('2026-07-21')
    assert json.loads(act['streams'])['time']['data'][-1] == 29


def test_route_with_no_times_is_still_rejected():
    assert parse_gpx(_gpx([None] * 30)) is None
