"""Where the demo's made-up athlete goes (demo/generate_demo_db.py): four national parks, and in each only public places to start from (stations,
visitor centres, village car parks, a café), summits to walk up and lakes to paddle on. Nothing here is anyone's home or regular start: the
routes between these places come from a routing engine on OpenStreetMap, not from anyone's recordings.

Each start's kinds say what starts there: 'ride' (road, gravel, e-bike), 'mtb', 'foot' (runs, walks, hikes). A lake's 'launch' is where the
paddle starts, on the shore; its 'osm' name is how OpenStreetMap names the water. Coordinates are WGS84 (lat, lng), to about 50 m.
"""

AREAS = {
    'peak': {
        'label': 'Peak District',
        'starts': [
            ('Edale station', 53.3647, -1.8167, ('ride', 'foot', 'mtb')),
            ('Hathersage station', 53.3257, -1.6508, ('ride', 'foot')),
            ('Castleton visitor centre', 53.3436, -1.7766, ('ride', 'foot', 'mtb')),
            ('Hope station', 53.3458, -1.7299, ('ride', 'foot')),
            ('Bakewell', 53.2141, -1.6722, ('ride', 'foot')),
            ('Fairholmes visitor centre', 53.4045, -1.7413, ('ride', 'mtb', 'foot')),
            ('Monsal Head', 53.2403, -1.7255, ('ride', 'foot')),
            ('Parsley Hay', 53.1688, -1.7656, ('ride', 'foot')),
            ('Hartington', 53.1405, -1.8105, ('ride', 'foot')),
            ('Grindleford station café', 53.3053, -1.6262, ('ride', 'foot')),
        ],
        'summits': [
            ('Kinder Low', 53.3850, -1.8730), ('Mam Tor', 53.3492, -1.8101), ('Win Hill', 53.3626, -1.7215), ('High Neb', 53.3734, -1.6563),
            ('Lose Hill', 53.3618, -1.7641), ('Higger Tor', 53.3330, -1.6230),
        ],
        'climbs': [('Winnats Pass', 53.3410, -1.8040), ('Mam Nick', 53.3530, -1.8130), ('Snake Pass', 53.4290, -1.8600), ('Monsal Dale', 53.2390, -1.7280),
                   ('Curbar Edge', 53.2730, -1.6140), ('Stanage', 53.3570, -1.6400), ('Rowsley Bar', 53.1920, -1.6200)],
        'lakes': [],
    },
    'lakes': {
        'label': 'Lake District',
        'starts': [
            ('Keswick lakeside', 54.5978, -3.1388, ('ride', 'foot')),
            ('Ambleside, Waterhead', 54.4220, -2.9630, ('ride', 'foot')),
            ('Coniston', 54.3690, -3.0760, ('ride', 'foot')),
            ('Grasmere', 54.4573, -3.0240, ('ride', 'foot')),
            ('Windermere station', 54.3797, -2.9038, ('ride', 'foot')),
            ('Glenridding', 54.5446, -2.9497, ('ride', 'foot')),
            ('Buttermere', 54.5412, -3.2775, ('ride', 'foot')),
            ("Staveley, Mill Yard", 54.3756, -2.8180, ('ride', 'foot')),
            ('Grizedale visitor centre', 54.3348, -3.0230, ('mtb', 'foot')),
            ('Whinlatter visitor centre', 54.6080, -3.2270, ('mtb', 'foot')),
        ],
        'summits': [
            ('Scafell Pike', 54.4542, -3.2117), ('Helvellyn', 54.5270, -3.0163), ('Skiddaw', 54.6511, -3.1475), ('Catbells', 54.5683, -3.1700),
            ('Old Man of Coniston', 54.3703, -3.1210), ('Fairfield', 54.4970, -2.9930), ('Loughrigg Fell', 54.4370, -2.9930), ('Blencathra', 54.6400, -3.0500),
        ],
        'climbs': [('Kirkstone Pass', 54.4650, -2.9300), ('Honister Pass', 54.5100, -3.1960), ('Newlands Pass', 54.5500, -3.2400), ('Whinlatter Pass', 54.6070, -3.2200),
                   ('Wrynose Pass', 54.4180, -3.1100), ('The Struggle', 54.4450, -2.9580)],
        'lakes': [
            {'osm': 'Derwent Water', 'launch': ('Keswick lakeside', 54.5955, -3.1395), 'sports': ('sup', 'kayak')},
            {'osm': 'Windermere', 'launch': ('Waterhead', 54.4205, -2.9628), 'sports': ('kayak', 'sup')},
            {'osm': 'Coniston Water', 'launch': ('Coniston boating centre', 54.3660, -3.0670), 'sports': ('sup', 'kayak')},
            {'osm': 'Ullswater', 'launch': ('Glenridding', 54.5450, -2.9440), 'sports': ('kayak',)},
        ],
    },
    'snowdonia': {
        'label': 'Snowdonia',
        'starts': [
            ('Llanberis', 53.1186, -4.1290, ('ride', 'foot')),
            ('Pen-y-Pass', 53.0806, -4.0202, ('foot',)),
            ('Beddgelert', 53.0115, -4.1022, ('ride', 'foot')),
            ('Coed y Brenin visitor centre', 52.8195, -3.8938, ('mtb', 'foot')),
            ('Bala', 52.9085, -3.5970, ('ride', 'foot')),
            ('Ogwen Cottage', 53.1236, -4.0200, ('foot',)),
            ('Rhyd Ddu station', 53.0530, -4.1360, ('foot', 'ride')),
        ],
        'summits': [
            ('Yr Wyddfa', 53.0685, -4.0762), ('Tryfan', 53.1150, -3.9978), ('Glyder Fawr', 53.1010, -4.0290), ('Moel Siabod', 53.0725, -3.9330),
            ('Cadair Idris', 52.6997, -3.9087), ('Y Garn', 53.1145, -4.0475), ('Moel Eilio', 53.1050, -4.1440),
        ],
        'climbs': [('Llanberis Pass', 53.0900, -4.0450), ('Bwlch y Groes', 52.7880, -3.6600), ('Crimea Pass', 53.0200, -3.9200), ('Nant Gwynant', 53.0550, -4.0300),
                   ('Pen-y-Pass', 53.0820, -4.0150)],
        'lakes': [
            {'osm': 'Llyn Padarn', 'launch': ('Llanberis', 53.1205, -4.1270), 'sports': ('sup', 'kayak')},
            {'osm': 'Llyn Tegid', 'launch': ('Bala', 52.9060, -3.6000), 'sports': ('sup', 'kayak')},
            {'osm': 'Llyn Gwynant', 'launch': ('Llyn Gwynant', 53.0430, -4.0350), 'sports': ('sup',)},
        ],
    },
    'dales': {
        'label': 'Yorkshire Dales',
        'starts': [
            ('Hawes', 54.3040, -2.1960, ('ride', 'foot')),
            ('Malham', 54.0610, -2.1530, ('ride', 'foot', 'mtb')),
            ('Grassington', 54.0700, -1.9990, ('ride', 'foot', 'mtb')),
            ('Settle station', 54.0670, -2.2800, ('ride', 'foot')),
            ('Reeth', 54.3880, -1.9430, ('ride', 'foot', 'mtb')),
            ('Ribblehead station', 54.2060, -2.3610, ('foot', 'ride')),
            ('Horton-in-Ribblesdale station', 54.1490, -2.3020, ('foot', 'ride')),
            ('Aysgarth Falls', 54.2930, -1.9840, ('ride', 'foot')),
            ('Kettlewell', 54.1470, -2.0470, ('ride', 'foot', 'mtb')),
            ('Ingleton', 54.1540, -2.4680, ('ride', 'foot')),
        ],
        'summits': [
            ('Pen-y-ghent', 54.1560, -2.2490), ('Ingleborough', 54.1660, -2.3980), ('Whernside', 54.2280, -2.4030), ('Great Whernside', 54.1610, -1.9990),
            ('Buckden Pike', 54.2020, -2.0600), ('Great Shunner Fell', 54.3700, -2.2330), ('Malham Cove', 54.0730, -2.1580),
        ],
        'climbs': [('Buttertubs', 54.3480, -2.2110), ('Fleet Moss', 54.2420, -2.1710), ('Park Rash', 54.1670, -2.0440), ('Kidstones Pass', 54.2200, -2.0700),
                   ('Tan Hill', 54.4560, -2.1620), ('Greenhow Hill', 54.0870, -1.8650), ('Oxnop Scar', 54.3430, -2.1150)],
        'lakes': [
            {'osm': 'Semer Water', 'launch': ('Semer Water', 54.2793, -2.1171), 'sports': ('sup',)},
        ],
    },
}
