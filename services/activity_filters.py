"""More filters for the activity lists (routes/dashboard._activity_list), beside the name, dates, distance, gear and sports: what an activity has
(power, heart rate, cadence, a GPS track), indoors or out, where it came from, and the order of the list. All from the URL (power=1, hr=0, gps=1,
place=indoor, source=garmin, sort=distance, page=2), so a filtered list can be bookmarked and linked. With any of them on, the list is one flat,
paged list rather than the history tree of years and months, which only ever runs newest first."""
from services import sports
from services.sport_filter import speed_sql

# (key, label, SQL for "has it"): power=1 keeps the activities with power, power=0 the ones without
DATA = (('power', 'Power', 'a.averageWatts > 0'),
        ('hr', 'Heart rate', 'a.averageHeartrate > 0'),
        ('cadence', 'Cadence', 'a.averageCadence > 0'),
        ('gps', 'GPS track', 'a.startLat IS NOT NULL'))
PLACES = (('indoor', 'Indoors', sports.virtual_sql('a.sportType')), ('outdoor', 'Outdoors', f"NOT {sports.virtual_sql('a.sportType')}"))
# Where it came from, by its id (services/origin.py: a Garmin sync's garmin_<id>, a Strava export's number, a file's imp_<hash>), or the id it
# had before it was changed into a workout (originId); the phone app and typing one in say so in source.
_PHONE = "('android', 'ios', 'phone', 'sensor-recovery')"
SOURCES = (('garmin', 'Garmin', r"(a.id LIKE 'garmin\_%' ESCAPE '\' OR a.originId LIKE 'garmin\_%' ESCAPE '\')"),
           ('strava', 'Strava', "(a.id GLOB '[0-9]*' OR a.originId GLOB '[0-9]*')"),
           ('file', 'File import', rf"((a.id LIKE 'imp\_%' ESCAPE '\' OR a.originId LIKE 'imp\_%' ESCAPE '\') AND COALESCE(a.source, '') NOT IN {_PHONE})"),
           ('phone', 'Phone app', f'a.source IN {_PHONE}'),
           ('manual', 'Typed in', "a.source = 'manual'"))
SORTS = (('newest', 'Newest first', 'a.startDateLocal DESC'),
         ('oldest', 'Oldest first', 'a.startDateLocal'),
         ('distance', 'Distance', 'a.distance DESC, a.startDateLocal DESC'),
         ('time', 'Moving time', 'a.movingTime DESC, a.startDateLocal DESC'),
         ('climb', 'Climbing', f"{sports.climb_sql('a.totalElevationGain', 'a.sportType')} DESC, a.startDateLocal DESC"),
         ('speed', 'Speed', f"{speed_sql('a.')} IS NULL, {speed_sql('a.')} DESC, a.startDateLocal DESC"))
PAGE = 100


class ActivityFilters:
    data_choices, place_choices, source_choices, sort_choices = DATA, PLACES, SOURCES, SORTS

    def __init__(self, args):
        self.data = {k: args.get(k) for k, _, _ in DATA if args.get(k) in ('1', '0')}
        self.place = args.get('place') if args.get('place') in dict((k, l) for k, l, _ in PLACES) else ''
        self.source = args.get('source') if args.get('source') in dict((k, l) for k, l, _ in SOURCES) else ''
        self.sort = args.get('sort') if args.get('sort') in dict((k, l) for k, l, _ in SORTS) else 'newest'
        try:
            self.page = max(1, int(args.get('page') or 1))
        except ValueError:
            self.page = 1

    @property
    def on(self):
        """How many of the filters here are on (the sort aside): the "More filters" count."""
        return len(self.data) + bool(self.place) + bool(self.source)

    @property
    def flat(self):
        """True when the list is a flat, paged one: a filter here is on, or another order than newest first."""
        return bool(self.on) or self.sort != 'newest'

    def sql(self):
        """[SQL conditions] for the filters that are on (no parameters: every value is one of the fixed choices)."""
        conds = [(sql if self.data[k] == '1' else f'NOT COALESCE({sql}, 0)') for k, _, sql in DATA if k in self.data]
        conds += [sql for k, _, sql in PLACES if k == self.place] + [sql for k, _, sql in SOURCES if k == self.source]
        return conds

    @property
    def order(self):
        return dict((k, o) for k, _, o in SORTS)[self.sort]

    def args(self):
        """The query args that keep these filters and the order on links (not the page)."""
        return list(self.data.items()) + [(k, v) for k, v in (('place', self.place), ('source', self.source)) if v] + \
            ([('sort', self.sort)] if self.sort != 'newest' else [])
