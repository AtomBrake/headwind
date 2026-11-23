# Sport families: a draft tree, and where FIT's sports land in it

Draft for the TODO item **Sport lists in tiers: each family, then its sports**. Nothing here is built yet.

The FIT lists below come from Garmin's FIT SDK **21.222.0** (`Profile['types']['sport']` and `['sub_sport']`). Garmin adds values with each SDK release, so check against a newer SDK before building from this.

## What FIT gives

- **`sport`**: 82 values in one flat list. Most are sports of their own (`cycling`, `kayaking`, `rafting`, `canoeing` and `stand_up_paddleboarding` are separate values). A few are broad buckets added in newer SDKs: `water_sport` (78), `winter_sport` (58), `team_sport` (70), `racket` (64), `motor_sports` (81) and `para_sport` (68). FIT never uses them as parents of the others: kayaking is `sport=kayaking`, not `water_sport` + something. `all` (254) is for goals only.
- **`sub_sport`**: 113 values, also one flat list, valid under any sport. The comment beside each value in the profile names the sport it's meant for (`gravel_cycling  # Cycling`, `amrap  # HIIT`). That comment is the only parent link FIT has, and it isn't enforced.
- **No family level.** FIT has nothing above `sport`. The top tier below is Headwind's own.

So a FIT file names a sport for tier 2 and sometimes a variant (indoor, trail, gravel). Which family it belongs to is up to Headwind.

## The proposed tree

Tier 1 is the family. Tier 2 lists Headwind's sport names (`services/sports.py` `SPORTS`). Names marked *new?* don't exist yet and are open decisions (see the end).

| Family | Sports |
|---|---|
| **Ride** | Ride, GravelRide, MountainBikeRide, EBikeRide, VirtualRide (indoor) |
| **Run** | Run, VirtualRun (indoor); *TrailRun new?* |
| **Walk and hike** | Walk, Hike |
| **Water sports** | Swim, Surf, Kitesurf, Wingfoil, Paddle, Row; *Sail new?*, *Windsurf new?*, *Dive new?*, *WaterSport new?* (the family's catch-all) |
| **Snow and ice** | Ski; *Snowboard / NordicSki new?*, *Snowshoe new?*, *IceSkate new?*, *WinterSport new?* (catch-all) |
| **Gym** | Strength, HIIT, Yoga; *Elliptical new?*, *StairStepper new?*, *Pilates new?* |
| **Other** | Climb, Golf, Skate, Other; *Racket new?*, *TeamSport new?* |

## Every FIT `sport`: where it lands today and where it would go

"Today" is what `from_type(sport, 'generic')` returns now. **Bold** marks a change from today.

### Ride
| FIT sport | Today | Proposed |
|---|---|---|
| cycling (2) | Ride | Ride; the sub-sport picks the variant (table below) |
| e_biking (21) | EBikeRide | EBikeRide |

### Run
| FIT sport | Today | Proposed |
|---|---|---|
| running (1) | Run | Run; `treadmill`, `indoor_running` and `virtual_activity` give VirtualRun |
| wheelchair_push_run (66) | Run | Run |

### Walk and hike
| FIT sport | Today | Proposed |
|---|---|---|
| walking (11) | Walk | Walk |
| wheelchair_push_walk (65) | Walk | Walk |
| hiking (17) | Hike | Hike (`rucking` too) |
| mountaineering (16) | Hike | Hike |
| geocaching (87) | Other | **Walk** |

### Water sports
| FIT sport | Today | Proposed |
|---|---|---|
| swimming (5) | Swim | Swim |
| pool_apnea (85) | Other | **Swim** |
| surfing (38) | Surf | Surf |
| wakesurfing (77) | Surf | Surf |
| kitesurfing (44) | Kitesurf | Kitesurf |
| windsurfing (43) | Surf | Surf, or **Windsurf** *new?* |
| paddling (19) | Paddle | Paddle |
| kayaking (41) | Paddle | Paddle |
| canoeing (88) | Paddle | Paddle |
| rafting (42) | Paddle | Paddle |
| stand_up_paddleboarding (37) | Paddle | Paddle |
| rowing (15) | Row | Row (`indoor_rowing` stays Row, indoors) |
| sailing (32) | Other | **Sail** *new?*, else WaterSport |
| grinding (59) | Other | as sailing (a crew role on a racing yacht) |
| water_skiing (40) | Other | **WaterSport** |
| wakeboarding (39) | Other | **WaterSport** |
| water_tubing (76) | Other | **WaterSport** |
| diving (53) | Other | **Dive** *new?*, else WaterSport |
| snorkeling (82) | Other | as diving |
| water_sport (78) | Other | **WaterSport** |

### Snow and ice
| FIT sport | Today | Proposed |
|---|---|---|
| alpine_skiing (13) | Ski | Ski |
| cross_country_skiing (12) | Ski | Ski, or **NordicSki** *new?* |
| snowboarding (14) | Ski | Ski, or **Snowboard** *new?* |
| snowshoeing (35) | Other | **Snowshoe** *new?*, else Hike |
| ice_skating (33) | Skate | **IceSkate** *new?*, else Skate (but Skate is also inline) |
| winter_sport (58) | Other | **WinterSport** |

### Gym
| FIT sport | Today | Proposed |
|---|---|---|
| hiit (62) | HIIT | HIIT (`amrap`, `emom` and `tabata` too) |
| training (10) | by sub-sport: `strength_training` → Strength, `yoga` → Yoga, `hiit` → HIIT, anything else → Other | as today, plus **`cardio_training` → HIIT** and **`flexibility_training` → Yoga**? |
| fitness_equipment (4) | by sub-sport: `indoor_cycling` → VirtualRide, `treadmill` → VirtualRun, `indoor_rowing` → Row, anything else → Other | as today, plus `elliptical` → **Elliptical** *new?*, `stair_climbing` → **StairStepper** *new?*, `pilates` → **Pilates** *new?* |
| boxing (47) | Other | **HIIT**? or Other |
| mixed_martial_arts (80) | Other | as boxing |
| jump_rope (84) | Other | **HIIT** |
| mobility (86) | Other | **Yoga** |
| meditation (67) | Other | Other |
| dance (83) | Other | Other |

### Other
| FIT sport | Today | Proposed |
|---|---|---|
| rock_climbing (31) | Climb | Climb (`indoor_climbing` and `bouldering` too) |
| floor_climbing (48) | Climb | **StairStepper** *new?* (floors climbed on stairs, not rock) |
| golf (25) | Golf | Golf |
| disc_golf (69) | Golf | Golf |
| inline_skating (30) | Skate | Skate |
| tennis (8) | Other | **Racket** *new?* |
| racket (64) | Other | **Racket** (pickleball, padel, squash, badminton, racquetball, table tennis, platform) |
| basketball (6), soccer (7), american_football (9), baseball (49), cricket (71), rugby (72), hockey (73), lacrosse (74), volleyball (75), team_sport (70) | Other | **TeamSport** *new?* |
| horseback_riding (27), archery (79), shooting (56), hunting (28), fishing (29), tactical (45), para_sport (68), video_gaming (63) | Other | Other |
| generic (0) | Other | Other |

### Not human-powered
These stay Other. Decide whether they should count in totals at all.

| FIT sport | Today |
|---|---|
| motorcycling (22), motor_sports (81), driving (24), snowmobiling (36), boating (23), flying (20), hang_gliding (26), sky_diving (34), jumpmaster (46) | Other |

### Not a sport
| FIT sport | What to do |
|---|---|
| multisport (18) | A triathlon file holds one session per leg, each with its own sport. Read each session's sport, not this one. |
| transition (3) | A T1/T2 session between legs. Fold it into the next leg or drop it; never save it as an activity of its own. |
| all (254) | Only for goals. It never appears in an activity. |

## FIT `sub_sport`s that matter for tier 2

Most sub-sports only matter under their own sport. These are the ones that change which Headwind sport a file becomes. The rest (`navigate`, `track_me`, `map`, the `fly_*` and diving modes, `trucker_workout`, `esport`) change nothing.

| Sub-sport (meant for) | Under | Today | Proposed |
|---|---|---|---|
| road, cyclocross, track_cycling, bmx, recumbent, hand_cycling, commuting, mixed_surface, spin (Cycling) | cycling | Ride | Ride |
| mountain, downhill, enduro (Cycling) | cycling | MountainBikeRide | MountainBikeRide |
| gravel_cycling (Cycling) | cycling | GravelRide | GravelRide |
| e_bike_mountain, e_bike_enduro (Cycling); e_bike_fitness (E-Biking) | cycling / e_biking | EBikeRide | EBikeRide |
| indoor_cycling (Cycling / Fitness Equipment), virtual_activity | cycling | VirtualRide | VirtualRide |
| indoor_cycling | fitness_equipment | VirtualRide | VirtualRide |
| indoor_hand_cycling | cycling | Ride | **VirtualRide** |
| treadmill, indoor_running (Run), virtual_activity | running | VirtualRun | VirtualRun |
| treadmill | fitness_equipment | VirtualRun | VirtualRun |
| trail (Run) | running | Run | Run, or **TrailRun** *new?* |
| street, track, ultra, obstacle | running | Run | Run |
| indoor_walking (Walking / Fitness Equipment) | walking | Walk | Walk |
| strength_training, yoga (Training) | training | Strength / Yoga | Strength / Yoga |
| cardio_training, flexibility_training (Training) | training | Other | HIIT? / Yoga? |
| indoor_rowing (Fitness Equipment) | rowing or fitness_equipment | Row | Row |
| lap_swimming, open_water (Swimming) | swimming | Swim | Swim (pool and open water stay one sport) |
| resort, backcountry (Alpine Skiing / Snowboarding), skate_skiing (XC) | skiing | Ski | Ski, or the split if it's made |
| triathlon, duathlon, brick, swim_run, pool_triathlon, adventure_race (Multisport) | multisport | Other | per session (see above) |

## Fixed in `from_type`, 2026-11-23

These came wrong from a FIT file read directly (an upload or an import; Garmin sync uses Garmin Connect's own type):

1. `training` + `strength_training` / `yoga` (and `hiit`, `amrap`, `emom`, `tabata`) gave Other. They now give Strength, Yoga and HIIT.
2. `fitness_equipment` + `indoor_cycling` / `treadmill` / `indoor_rowing` gave Other. They now give VirtualRide, VirtualRun and Row.
3. `water_skiing` (and jet skis) gave Ski, from the `'ski'` needle. They now give Other until there's a water family.

Still Other although each has an obvious place: `snowshoeing`, `sailing`, `pool_apnea`, `geocaching`. They wait on the decisions below.

## Open decisions

1. **New sports, or keep folding into existing ones?** Each *new?* above. They fall into four groups:
   - Splits that Strava already makes, so Strava imports would keep them: TrailRun, NordicSki, Snowboard, Snowshoe, Sail, Windsurf, Elliptical, StairStepper, Pilates.
   - Catch-alls so FIT's broad sports have a home: WaterSport, WinterSport.
   - New groups: Racket, TeamSport, Dive.
2. **Skate.** Ice skating belongs with snow and ice, inline skating doesn't. Split it into two, or keep one Skate under Other.
3. **Indoor variants.** Today VirtualRide and VirtualRun are separate sports. An indoor row, swim or ski would need the same, or an `indoor` flag on the activity in place of separate sports.
4. **Motorised sports.** Keep them under Other, or give them a family that totals and goals leave out.
5. **Run vs. Walk and hike.** The TODO item splits them; the code's `FAMILIES` has one `foot` family, and segments and PRs use `foot` (`CLASSES`). Families for menus can split while the segment class stays `foot`.
