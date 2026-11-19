"""The sport filter on the dashboard and the Data page. Every sport is shown by default; the rider unticks the ones to leave out, and the URL lists only
those (skip=…), so a sport that turns up later is shown. Old links with sport=X (one sport, matched on part of its name) still work: they leave out
every sport that doesn't match.

A link can also say what's kept: group=ride (a stat group: every kind of ride, a kind first ridden tomorrow too) or only=Run (one sport). Each
request turns it into the skip list for the sports there are now, and links made from that page keep the group= or only= rather than the list,
so a favourite in the sidebar (services/favourites.py) or a saved "only rides" link never goes stale.

The commute filter sits beside it: commute=only leaves in the activities ticked as a commute (Activity.commute), commute=no the rest (unticked, or
never said). It's offered once the rider has a commute, or while it's on.

Distances only add up within a stat group (services/sports.stat_group). When everything left is in one group the pages show its distance and its speed
or pace; when it isn't, or the group is a timed-only sport (sports.NO_DISTANCE), they show time, calories and climbing, with each group's distance
on its own."""
from itertools import cycle
from urllib.parse import urlencode

from services import sports

NO_SPORT = 'Ride'          # a row with no sport counts as a ride (services/sports.is_ride), and is listed and left out as one
COL_SQL = "COALESCE(NULLIF({col}, ''), '" + NO_SPORT + "')"
# Colour variables from static/css/style.css; the page reads them with cssVar()
GROUP_COLOURS = {'ride': '--accent', 'foot': '--c-violet', 'swim': '--c-sky'}
OTHER_COLOURS = ('--success', '--warning', '--c-pink', '--c-cyan', '--c-grey')
COMMUTE_SQL = {'only': '{p}commute = 1', 'no': 'COALESCE({p}commute, 0) != 1'}
COMMUTE_LABELS = (('', 'Every activity'), ('only', 'Commutes'), ('no', 'Not commutes'))


def speed_sql(p=''):
    """An activity's average speed in m/s: the stored one, or distance over moving time for a workout saved without one."""
    return (f"(CASE WHEN {p}averageSpeed > 0 THEN {p}averageSpeed "
            f"WHEN {p}movingTime > 0 AND {p}distance > 0 THEN {p}distance * 1.0 / {p}movingTime END)")


def chart_groups(groups):
    """[{key, label, color}] for the stacked charts, one per stat group, in stack order; color is a CSS variable name."""
    others = cycle(OTHER_COLOURS)
    return [{'key': g, 'label': sports.stat_label(g), 'color': GROUP_COLOURS.get(g) or next(others)} for g in groups]


class SportFilter:
    commute_labels = COMMUTE_LABELS

    def __init__(self, db, rider_id, args):
        rows = db.execute(f"SELECT {COL_SQL.format(col='sportType')} AS s, COUNT(*), SUM(commute = 1) FROM Activity WHERE riderId=? GROUP BY s",
                          [rider_id]).fetchall()
        self.sports = sorted(((r[0], r[1]) for r in rows), key=lambda r: (sports.stat_order(sports.stat_group(r[0])), r[0]))
        self.commutes = sum(r[2] or 0 for r in rows)
        self.commute = args.get('commute') if args.get('commute') in COMMUTE_SQL else ''
        left = {r[0] for r in rows if (r[2] or 0) > 0} if self.commute == 'only' else \
               {r[0] for r in rows if r[1] > (r[2] or 0)} if self.commute == 'no' else {r[0] for r in rows}    # sports with an activity the commute filter keeps
        names = [s for s, _ in self.sports]
        part = (args.get('sport') or '').strip()
        self.keep = None                                # ('group', 'ride') or ('only', 'Run'): kept on links instead of the skip list
        if part:
            self.skip = [s for s in names if part.lower() not in s.lower()]
        elif (args.get('group') or '').strip():
            self.keep = ('group', args['group'].strip())
            self.skip = self.only(self.keep[1])
        elif (args.get('only') or '').strip():
            self.keep = ('only', sports.canonical(args['only'].strip()))
            self.skip = [s for s in names if s != self.keep[1]]
        else:
            self.skip = [x for x in dict.fromkeys(args.getlist('skip')) if x][:50]
        self.kept = [s for s in names if s not in self.skip]
        self.groups = list(dict.fromkeys(sorted((sports.stat_group(s) for s in self.kept if s in left), key=sports.stat_order)))
        self.group = self.groups[0] if len(self.groups) == 1 and self.groups[0] not in sports.NO_DISTANCE else None     # None: nothing left,
        # distances that don't add up, or a sport that has none (yoga, strength): the pages count its time
        self.style = sports.rate_style(group=self.group) if self.group else None
        self.has_rides = 'ride' in self.groups
        self.all_groups = list(dict.fromkeys(sorted((sports.stat_group(s) for s in names), key=sports.stat_order)))

    @property
    def show_commute(self):
        return bool(self.commutes or self.commute)

    def sql(self, col='sportType'):
        """(SQL condition, params) for the sports left in and the commute filter, on a column holding the sport ('a.sportType': the commute
        column is read from the same table)."""
        conds, params = [], []
        if self.skip:
            conds.append(f"{COL_SQL.format(col=col)} NOT IN ({','.join('?' * len(self.skip))})")
            params = list(self.skip)
        if self.commute:
            conds.append(COMMUTE_SQL[self.commute].format(p=col[:col.rfind('.') + 1]))
        return ' AND '.join(conds) or '1=1', params

    def args(self, skip=None, group=None):
        """The query args that keep the filter, with another skip list or a stat group when given (the commute filter is kept either way)."""
        if group is not None:
            sport = [('group', group)]
        elif skip is None and self.keep:
            sport = [self.keep]
        else:
            sport = [('skip', s) for s in (self.skip if skip is None else skip)]
        return sport + ([('commute', self.commute)] if self.commute else [])

    @property
    def query(self):
        """skip=…&skip=…&commute=… for links that keep the filter ('' when nothing is filtered)."""
        return urlencode(self.args())

    def only(self, group):
        """The skip list that leaves in one stat group."""
        return [s for s, _ in self.sports if sports.stat_group(s) != group]

    def shortcuts(self):
        """(label, icon, group, active) for each stat group, when there are several: a one-click "only rides" / "only on foot"."""
        if len(self.all_groups) < 2:
            return []
        return [(sports.stat_label(g), sports.STAT_ICONS.get(g, ''), g, self.groups == [g]) for g in self.all_groups]
