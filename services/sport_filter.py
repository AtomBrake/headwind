"""The sport filter on the dashboard and the Data page. Every sport is shown by default; the rider unticks the ones to leave out, and the URL lists only
those (skip=…), so a sport that turns up later is shown. Old links with sport=X (one sport, matched on part of its name) still work: they leave out
every sport that doesn't match.

Distances only add up within a stat group (services/sports.stat_group). When everything left is in one group the pages show its distance and its speed
or pace; when it isn't, they show time, calories and climbing, with each group's distance on its own."""
from itertools import cycle
from urllib.parse import urlencode

from services import sports

NO_SPORT = 'Ride'          # a row with no sport counts as a ride (services/sports.is_ride), and is listed and left out as one
COL_SQL = "COALESCE(NULLIF({col}, ''), '" + NO_SPORT + "')"
GROUP_COLOURS = {'ride': '252,76,2', 'foot': '167,139,250', 'swim': '91,184,212'}
OTHER_COLOURS = ('16,185,129', '245,158,11', '236,72,153', '6,182,212', '148,163,184')


def speed_sql(p=''):
    """An activity's average speed in m/s: the stored one, or distance over moving time for a workout saved without one."""
    return (f"(CASE WHEN {p}averageSpeed > 0 THEN {p}averageSpeed "
            f"WHEN {p}movingTime > 0 AND {p}distance > 0 THEN {p}distance * 1.0 / {p}movingTime END)")


def chart_groups(groups):
    """[{key, label, color}] for the stacked charts, one per stat group, in stack order."""
    others = cycle(OTHER_COLOURS)
    return [{'key': g, 'label': sports.stat_label(g), 'color': GROUP_COLOURS.get(g) or next(others)} for g in groups]


class SportFilter:
    def __init__(self, db, rider_id, args):
        rows = db.execute(f"SELECT {COL_SQL.format(col='sportType')} AS s, COUNT(*) FROM Activity WHERE riderId=? GROUP BY s", [rider_id]).fetchall()
        self.sports = sorted(((r[0], r[1]) for r in rows), key=lambda r: (sports.stat_order(sports.stat_group(r[0])), r[0]))
        names = [s for s, _ in self.sports]
        only = (args.get('sport') or '').strip()
        if only:
            self.skip = [s for s in names if only.lower() not in s.lower()]
        else:
            self.skip = [x for x in dict.fromkeys(args.getlist('skip')) if x][:50]
        self.kept = [s for s in names if s not in self.skip]
        self.groups = list(dict.fromkeys(sorted((sports.stat_group(s) for s in self.kept), key=sports.stat_order)))
        self.group = self.groups[0] if len(self.groups) == 1 else None         # None: nothing left, or distances that don't add up
        self.style = sports.rate_style(group=self.group) if self.group else None
        self.has_rides = 'ride' in self.groups
        self.all_groups = list(dict.fromkeys(sorted((sports.stat_group(s) for s in names), key=sports.stat_order)))

    def sql(self, col='sportType'):
        """(SQL condition, params) for the sports left in, on a column holding the sport."""
        if not self.skip:
            return '1=1', []
        return f"{COL_SQL.format(col=col)} NOT IN ({','.join('?' * len(self.skip))})", list(self.skip)

    def args(self, skip=None):
        return [('skip', s) for s in (self.skip if skip is None else skip)]

    @property
    def query(self):
        """skip=…&skip=… for links that keep the filter ('' when every sport is in)."""
        return urlencode(self.args())

    def only(self, group):
        """The skip list that leaves in one stat group."""
        return [s for s, _ in self.sports if sports.stat_group(s) != group]

    def shortcuts(self):
        """(label, icon, skip list, active) for each stat group, when there are several: a one-click "only rides" / "only on foot"."""
        if len(self.all_groups) < 2:
            return []
        return [(sports.stat_label(g), sports.STAT_ICONS.get(g, ''), self.only(g), self.groups == [g]) for g in self.all_groups]
