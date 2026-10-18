"""GPX files that use an XML namespace prefix without declaring it (Avinox e-bike exports)."""
import json

from services.parser import _declare_missing_prefixes, parse_gpx


def _avinox_gpx(n=30):
    pts = ''.join(f'<trkpt lat="52.97{i:03d}" lon="-3.166"><time>2026-09-06T14:18:{i:02d}.000Z</time><ele>196.0</ele></trkpt>'
                  for i in range(n))
    return ('<?xml version="1.0" encoding="UTF-8"?><gpx version="1.0" creator="Avinox">'
            '<metadata><name>Avinox</name><time>2026-10-17T20:39:29.243662Z</time></metadata>'
            '<trk><name>ebike</name><extensions><avinox:totalDistance>13936.0</avinox:totalDistance>'
            '<avinox:totalAscent>477.0</avinox:totalAscent></extensions>'
            f'<trkseg>{pts}</trkseg></trk></gpx>').encode()


def test_undeclared_prefix_imports():
    act = parse_gpx(_avinox_gpx())
    assert act and act['startDateLocal'].startswith('2026-09-06')
    assert act['name'] == 'ebike'
    assert json.loads(act['streams'])['time']['data'][-1] == 29


def test_declared_prefixes_are_left_alone():
    text = ('<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1" '
            'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">'
            '<trk><trkseg><trkpt lat="1" lon="1"><extensions><gpxtpx:hr>120</gpxtpx:hr></extensions></trkpt></trkseg></trk></gpx>')
    assert _declare_missing_prefixes(text) == text


def test_undeclared_attribute_prefix_is_declared():
    text = '<gpx version="1.1" xsi:schemaLocation="x y"><trk/></gpx>'
    assert 'xmlns:xsi="urn:undeclared:xsi"' in _declare_missing_prefixes(text)
