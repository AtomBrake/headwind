"""How the AI coach talks about each sport (services/ai.py) and which past activities it compares one with (services/context.py).

A ride is coached as a ride, a run as a run, a swim as a swim: the session's name ("ride", "run", "strength session"), who did it ("cyclist",
"runner"), how its speed reads (speed, pace per mile or km, or pace per 100 m: services/sports.rate_style), whether its climbing means anything
(not on the water: services/sports.has_climbing), its cadence's unit, and whether it has a distance at all (strength, HIIT and yoga don't:
services/sports.NO_DISTANCE).

Its history is the same kind of activity only (history_sql): every ride (indoor and e-bike too, as the coach always had), every run (trail and
treadmill too, services/sport_records), and otherwise the same sport. Everything else in the weeks before is "other training", so a ride's notes
know about the runs and gym sessions around it, and a run's about the rides."""
from dataclasses import dataclass

from services import sports

# Per sport: (the sport as a coach names it, the session, who does it). Rides and runs are matched by family below, the rest by sport.
_WORDS = {
    'Walk': ('walking', 'walk', 'walker'),
    'Hike': ('hiking', 'hike', 'hiker'),
    'Swim': ('swimming', 'swim', 'swimmer'),
    'Surf': ('surfing', 'surf session', 'surfer'),
    'Kitesurf': ('kitesurfing', 'kitesurf session', 'kitesurfer'),
    'Wingfoil': ('wing foiling', 'wing foil session', 'wing foiler'),
    'Paddle': ('paddling', 'paddle', 'paddler'),
    'Row': ('rowing', 'row', 'rower'),
    'Ski': ('skiing', 'ski day', 'skier'),
    'Skate': ('skating', 'skate', 'skater'),
    'Golf': ('golf', 'round of golf', 'golfer'),
    'Climb': ('climbing', 'climbing session', 'climber'),
    'Strength': ('strength', 'strength session', 'athlete'),
    'HIIT': ('HIIT', 'HIIT session', 'athlete'),
    'Yoga': ('yoga', 'yoga session', 'athlete'),
}
_STROKES = ('swim', 'row', 'paddl', 'kayak', 'canoe')      # a cadence in strokes a minute
_RUNS = ('run', 'trailrun', 'virtualrun')                    # as services/sport_records._RUNS


def _squash(sport):
    return ''.join(c for c in (sport or '').lower() if c.isalpha())


@dataclass(frozen=True)
class Profile:
    sport: str              # the activity's own sportType ('' for none: counted as a ride)
    family: str             # 'ride', 'run', or the sport itself: what history_sql matches
    sport_word: str         # 'cycling', 'running', 'swimming', ...
    noun: str               # 'ride', 'run', 'swim', 'strength session', ...
    athlete: str            # 'cyclist', 'runner', 'swimmer', 'athlete', ...
    icon: str
    rate: str | None        # 'speed', 'pace' or 'swim' (services/units.fmt_rate); None without a distance
    climbing: bool          # whether its elevation gain means anything
    climb_limit_m: float | None     # the climbing worth a section of its own
    cadence: tuple | None   # (unit, factor): a watch counts one foot, so a run's steps a minute are twice its cadence
    indoor: bool

    @property
    def distance(self):
        return self.rate is not None

    @property
    def nouns(self):
        """'rides', 'runs', 'strength sessions', 'rounds of golf'."""
        n = self.noun
        return n.replace('round of', 'rounds of') if n.startswith('round of') else n + 's'

    def count(self, n):
        """'1 run', '3 runs'."""
        return f'{n} {self.noun if n == 1 else self.nouns}'

    @property
    def label(self):
        return sports.label(self.sport or None)

    def history_sql(self, col='sportType'):
        """SQL (with its params) keeping the activities this one is compared with: the same family."""
        if self.family == 'ride':
            return sports.RIDE_SQL.replace('sportType', col), []
        if self.family == 'run':
            from services.sport_records import kind_sql
            return f"COALESCE({kind_sql(col)}, '') = 'run'", []       # never NULL, so NOT (...) keeps everything else
        return f"COALESCE({col}, '') = ?", [self.sport]


def profile(sport):
    s = _squash(sport)
    indoor = sports.is_virtual(sport)
    climbing = sports.has_climbing(sport) and not indoor
    if sports.is_ride(sport):
        return Profile(sport or '', 'ride', 'cycling', 'ride', 'cyclist', '🚴', 'speed', climbing, 800 / 3.28084, ('rpm', 1), indoor)
    if s in _RUNS:
        return Profile(sport, 'run', 'running', 'run', 'runner', '🏃', 'pace', climbing, 500 / 3.28084, ('steps/min', 2), indoor)
    word, noun, athlete = _WORDS.get(sports.canonical(sport), ((sports.label(sport) or 'fitness').lower(), 'session', 'athlete'))
    if sport in sports.GENERIC:
        word = 'fitness'
    if sport in sports.NO_DISTANCE:
        rate, climbing = None, False
    else:
        rate = sports.rate_style(sport)
    foot = sports.stat_group(sport) == 'foot'
    cadence = ('steps/min', 2) if foot else ('strokes/min', 1) if any(k in s for k in _STROKES) else None
    return Profile(sport, sport, word, noun, athlete, sports.icon(sport), rate, climbing,
                   500 / 3.28084 if foot and climbing else None, cadence, indoor)
