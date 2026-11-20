CREATE TABLE Rider (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            avatarPath TEXT,
            isDefault  INTEGER DEFAULT 0,
            haDevice   TEXT
        , defaultBikeId INTEGER);
CREATE TABLE Settings (
            id               INTEGER PRIMARY KEY,
            aiProvider       TEXT,
            openaiKey        TEXT,
            openaiModel      TEXT,
            ollamaUrl        TEXT,
            ollamaModel      TEXT,
            ntfyUrl          TEXT,
            webhookSubId     TEXT,
            mqttHost         TEXT,
            mqttPort         INTEGER DEFAULT 1883,
            mqttUser         TEXT,
            mqttPassword     TEXT,
            coachingGoals    TEXT,
            coachPersonality TEXT DEFAULT 'default',
            garminEmail      TEXT,
            garminPassword   TEXT,
            garminSyncHours  REAL DEFAULT 0.5
        , mqttTls INTEGER DEFAULT 0, mqttCaFile TEXT, aiAutoAnalyse INTEGER DEFAULT 0, garminSignInNeeded TEXT, friendSyncInterval INTEGER DEFAULT 15, garminActivitySyncDate TEXT, garminSyncMode TEXT DEFAULT 'health', heightCm REAL, sex TEXT, birthYear INTEGER, activityFactor REAL, lossLbPerWeek REAL, stepGoal INTEGER, stepsSource TEXT, goalAuto INTEGER DEFAULT 0, goalAutoLast TEXT, rideKcalWeek REAL, rideGoalWeek INTEGER, goalWeightKg REAL, holidayStart TEXT, holidayEnd TEXT, garminLastOk TEXT, garminLastError TEXT, garminDeviceSync TEXT, garminSweepAt TEXT, garminChangesBefore TEXT, garminFailCount INTEGER DEFAULT 0, garminHistoryFrom TEXT, garminHistoryCursor TEXT, garminHistoryDone INTEGER DEFAULT 0, garminHistoryStatus TEXT, garminHistoryRetryAt TEXT, utcStartFixDone INTEGER DEFAULT 0, awayStartRecheckDone INTEGER DEFAULT 0, localZoneFixDone INTEGER DEFAULT 0, workoutDupCheckDone INTEGER DEFAULT 0, dupNameFixDone INTEGER DEFAULT 0, segmentFamiliesDone INTEGER DEFAULT 0, segmentBikesMergedDone INTEGER DEFAULT 0, movingTimeFixDone INTEGER DEFAULT 0, segmentMatchFixDone INTEGER DEFAULT 0, sportEffortsDone INTEGER DEFAULT 0, movingTimePausedDone INTEGER DEFAULT 0, bestEffortsCleanDone INTEGER DEFAULT 0, sensorTopSpeedDone INTEGER DEFAULT 0, mmDistancesDone INTEGER DEFAULT 0, stravaManualDone INTEGER DEFAULT 0, liveParkedFixDone INTEGER DEFAULT 0, strandedParkedFixDone INTEGER DEFAULT 0, dupMatchFixDone INTEGER DEFAULT 0, sanityAllSportsDone INTEGER DEFAULT 0, segmentClimbFloorDone INTEGER DEFAULT 0, segmentStopsDone INTEGER DEFAULT 0, segmentRouteDone INTEGER DEFAULT 0, segmentLapsDone INTEGER DEFAULT 0, ebikeSportDone INTEGER DEFAULT 0, garminWeightsDone INTEGER DEFAULT 0, garminWeightsRetryAt TEXT, garminWeightsStatus TEXT, haUrl TEXT, haToken TEXT, haEntityMap TEXT, haSyncMinutes INTEGER, haLastSync TEXT, haLastResult TEXT, haWeatherEntity TEXT, haWeatherCondition TEXT, haWeatherTempC REAL, haWeatherUpdatedAt TEXT, installId TEXT, telemetryOptOut INTEGER DEFAULT 0, telemetryPingedAt TEXT, nutritionCalGoal INTEGER, nutritionProteinGoal INTEGER, nutritionCarbGoal INTEGER, nutritionFatGoal INTEGER, nutritionSugarGoal INTEGER, nutritionAlcoholWeekGoal REAL, nutritionWaterGoalMl INTEGER DEFAULT 2500, nutritionBmrKcal INTEGER, units TEXT DEFAULT 'imperial', appearance TEXT DEFAULT 'auto', distanceBackfillDone INTEGER DEFAULT 0, nutritionWeightUnit TEXT DEFAULT 'stlb', nutritionWeightEmaAlpha REAL DEFAULT 0.1, dietStartDate TEXT, weightMilestoneLines INTEGER DEFAULT 1, calorieAdjustPct REAL DEFAULT 0, claudeKey TEXT, claudeModel TEXT, timeZone TEXT, birthDate TEXT, birthDateGuessed INTEGER DEFAULT 0, thunderforestKey TEXT, osMapsKey TEXT, externalUrl TEXT);
CREATE TABLE Segment (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            name             TEXT NOT NULL,
            startLat         REAL NOT NULL,
            startLng         REAL NOT NULL,
            endLat           REAL NOT NULL,
            endLng           REAL NOT NULL,
            distanceM        REAL,
            elevationGainM   REAL,
            sourceActivityId TEXT,
            polyline         TEXT,
            createdAt        TEXT DEFAULT (datetime('now'))
        , friendId INTEGER REFERENCES Friend(id), sourceSegId INTEGER, matchPending INTEGER, sport TEXT DEFAULT 'ride');
CREATE TABLE SegmentEffort (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        segmentId    INTEGER NOT NULL REFERENCES Segment(id) ON DELETE CASCADE,
        activityId   TEXT NOT NULL,
        activityDate TEXT,
        elapsedSecs  INTEGER NOT NULL,
        avgSpeedMps  REAL,
        isPR         INTEGER DEFAULT 0,
        createdAt    TEXT DEFAULT (datetime('now')),
        approx       INTEGER DEFAULT 0,
        startSecs    INTEGER,
        UNIQUE(segmentId, activityId, startSecs)
    );
CREATE TABLE RideMemory (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            rideId      TEXT UNIQUE NOT NULL,
            rideDate    TEXT,
            rideName    TEXT,
            distanceMi  REAL,
            movingTime  INTEGER,
            elevationFt REAL,
            avgSpeedMph REAL,
            avgPower    REAL,
            normPower   REAL,
            avgHR       REAL,
            calories    REAL,
            userNotes   TEXT,
            aiSummary   TEXT,
            tags        TEXT,
            createdAt   TEXT DEFAULT (datetime('now')),
            updatedAt   TEXT DEFAULT (datetime('now'))
        );
CREATE TABLE Athlete (
            id           INTEGER PRIMARY KEY,
            firstname    TEXT,
            lastname     TEXT,
            profile      TEXT,
            expiresAt    INTEGER
        );
CREATE TABLE BestEffort (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            activityId   TEXT NOT NULL,
            activityDate TEXT NOT NULL,
            distanceMi   REAL NOT NULL,
            elapsedSecs  INTEGER NOT NULL,
            avgSpeedMps  REAL,
            UNIQUE(activityId, distanceMi)
        );
CREATE TABLE FoodLog (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            riderId    INTEGER REFERENCES Rider(id),
            logDate    TEXT NOT NULL,
            barcode    TEXT,
            foodName   TEXT NOT NULL,
            calories   REAL,
            protein    REAL,
            carbs      REAL,
            fat        REAL,
            servingG   REAL,
            quantity   REAL DEFAULT 1,
            createdAt  TEXT DEFAULT (datetime('now'))
        , mealType TEXT DEFAULT 'uncategorised', source TEXT DEFAULT 'manual', brand TEXT, imageUrl TEXT, nutriScoreGrade TEXT, fibre REAL, sugar REAL, alcoholUnits REAL);
CREATE TABLE HydrationLog (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            riderId   INTEGER REFERENCES Rider(id),
            logDate   TEXT NOT NULL,
            ml        INTEGER NOT NULL,
            createdAt TEXT DEFAULT (datetime('now'))
        );
CREATE TABLE Friend (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            url         TEXT NOT NULL,
            token       TEXT,
            riderId     INTEGER REFERENCES Rider(id),
            lastSynced  TEXT,
            createdAt   TEXT DEFAULT (datetime('now'))
        , riderName TEXT, lastFoodSync TEXT);
CREATE TABLE PlannedRoute (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT NOT NULL,
            waypoints TEXT NOT NULL,
            createdAt TEXT DEFAULT (datetime('now'))
        );
CREATE TABLE FoodOverride (
            barcode     TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            brand       TEXT,
            kcal100g    REAL,
            protein100g REAL,
            carbs100g   REAL,
            fat100g     REAL,
            servingG    REAL,
            updatedAt   TEXT DEFAULT (datetime('now'))
        , imageUrl TEXT, nutriScoreGrade TEXT, fibre100g REAL);
CREATE TABLE SavedMeal (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT NOT NULL,
            createdAt TEXT DEFAULT (datetime('now'))
        );
CREATE TABLE SavedMealItem (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            mealId   INTEGER NOT NULL REFERENCES SavedMeal(id) ON DELETE CASCADE,
            foodName TEXT NOT NULL,
            calories REAL,
            protein  REAL,
            carbs    REAL,
            fat      REAL,
            servingG REAL,
            barcode  TEXT
        , fibre REAL, sugar REAL);
CREATE TABLE WeightLog (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            riderId   INTEGER REFERENCES Rider(id),
            logDate   TEXT NOT NULL,
            weightKg  REAL NOT NULL,
            source    TEXT DEFAULT 'manual',
            sourceDetail TEXT,
            createdAt TEXT DEFAULT (datetime('now')),
            UNIQUE(riderId, logDate)
        );
CREATE TABLE FoodFavourite (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            riderId   INTEGER REFERENCES Rider(id),
            barcode   TEXT,
            foodName  TEXT NOT NULL,
            brand     TEXT,
            calories  REAL,
            protein   REAL,
            carbs     REAL,
            fat       REAL,
            servingG  REAL,
            imageUrl  TEXT,
            createdAt TEXT DEFAULT (datetime('now'))
        );
CREATE TABLE CustomFood (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            riderId   INTEGER REFERENCES Rider(id),
            name      TEXT NOT NULL,
            brand     TEXT,
            calories  REAL,
            protein   REAL,
            carbs     REAL,
            fat       REAL,
            servingG  REAL,
            imageUrl  TEXT,
            createdAt TEXT DEFAULT (datetime('now'))
        , fibre100g REAL);
CREATE TABLE RecipeBook (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            riderId   INTEGER REFERENCES Rider(id),
            name      TEXT NOT NULL,
            nameKey   TEXT NOT NULL,
            calories  REAL NOT NULL,
            protein   REAL,
            carbs     REAL,
            fat       REAL,
            createdAt TEXT DEFAULT (datetime('now')),
            updatedAt TEXT DEFAULT (datetime('now'))
        );
CREATE UNIQUE INDEX idx_recipebook_key ON RecipeBook(riderId, nameKey);
CREATE TABLE BodyMetric (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            riderId   INTEGER REFERENCES Rider(id),
            logDate   TEXT NOT NULL,
            metric    TEXT NOT NULL,
            value     REAL NOT NULL,
            unit      TEXT,
            source    TEXT DEFAULT 'homeassistant',
            updatedAt TEXT DEFAULT (datetime('now')),
            UNIQUE(riderId, logDate, metric)
        );
CREATE TABLE FoodImage (
            nameKey   TEXT PRIMARY KEY,
            name      TEXT NOT NULL,
            imageUrl  TEXT NOT NULL,
            updatedAt TEXT DEFAULT (datetime('now'))
        );
CREATE INDEX idx_effort_activity ON SegmentEffort(activityId);
CREATE INDEX idx_foodlog_rider_date ON FoodLog(riderId, logDate);
CREATE INDEX idx_hydration_rider_date ON HydrationLog(riderId, logDate);
CREATE TABLE RideSensor (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            riderId     INTEGER NOT NULL,
            clientId    TEXT NOT NULL UNIQUE,
            startUtc    TEXT NOT NULL,
            endUtc      TEXT NOT NULL,
            data        TEXT NOT NULL,
            summary     TEXT,
            device      TEXT,
            mount       TEXT,
            sensorsOnly INTEGER DEFAULT 0,
            rideKind    TEXT,
            rideId      TEXT,
            createdAt   TEXT DEFAULT (datetime('now'))
        );
CREATE INDEX idx_ridesensor_ride ON RideSensor(rideId);
CREATE TABLE DeviceToken (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            tokenHash  TEXT NOT NULL UNIQUE,
            createdAt  TEXT DEFAULT (datetime('now')),
            lastUsedAt TEXT,
            revokedAt  TEXT
        , parentId INTEGER);
CREATE TABLE ClientOp (
            clientId  TEXT PRIMARY KEY,
            kind      TEXT NOT NULL,
            entryId   INTEGER,
            createdAt TEXT DEFAULT (datetime('now'))
        );
CREATE TABLE SharedFood (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            friendId     INTEGER NOT NULL,
            origin       TEXT,
            kind         TEXT NOT NULL,
            key          TEXT NOT NULL,
            barcode      TEXT,
            name         TEXT NOT NULL,
            brand        TEXT,
            kcal100g     REAL, protein100g REAL, carbs100g REAL, fat100g REAL, fibre100g REAL,
            servingG     REAL,
            imageUrl     TEXT,
            nutriScoreGrade TEXT,
            srcUpdatedAt TEXT,
            syncedAt     TEXT,
            UNIQUE (friendId, kind, key)
        );
CREATE INDEX idx_sharedfood_barcode ON SharedFood(barcode);
CREATE TABLE FoodCache (
            key             TEXT PRIMARY KEY,
            barcode         TEXT,
            name            TEXT NOT NULL,
            brand           TEXT,
            searchText      TEXT NOT NULL,
            kcal100g        REAL NOT NULL,
            protein100g     REAL,
            carbs100g       REAL,
            fat100g         REAL,
            sugars100g      REAL,
            fibre100g       REAL,
            servingG        REAL,
            imageUrl        TEXT,
            nutriScoreGrade TEXT,
            useCount        INTEGER DEFAULT 0,
            lastUsed        TEXT,
            fetchedAt       TEXT DEFAULT (datetime('now'))
        , abv REAL);
CREATE TABLE SportEffort (
        activityId   TEXT NOT NULL,
        activityDate TEXT,
        kind         TEXT NOT NULL,              -- run | swim
        distanceM    REAL NOT NULL,              -- 0: looked, too short for any distance
        elapsedSecs  INTEGER NOT NULL,
        PRIMARY KEY (activityId, kind, distanceM)
    );
CREATE INDEX idx_sporteffort_kind ON SportEffort(kind, distanceM, elapsedSecs);
CREATE TABLE ActivityDuplicate (
            id        TEXT PRIMARY KEY,                 -- the parked activity's own id
            primaryId TEXT NOT NULL,                    -- the ride kept in its place
            riderId   INTEGER,
            source    TEXT,                             -- 'Garmin' / 'Phone or file' (display only)
            reason    TEXT,                             -- why it lost, shown to the user
            status    TEXT NOT NULL DEFAULT 'parked',   -- parked | kept_both
            rowJson   TEXT NOT NULL,                    -- the full Activity row
            parkedAt  TEXT DEFAULT (datetime('now'))
        , bikeId INTEGER, kitId INTEGER, gearChecked INTEGER, sportType TEXT, sportChecked INTEGER);
CREATE INDEX idx_actdup_primary ON ActivityDuplicate(primaryId);
CREATE TABLE Bike (
        id INTEGER PRIMARY KEY AUTOINCREMENT, riderId INTEGER NOT NULL, name TEXT NOT NULL, kind TEXT DEFAULT 'road', brand TEXT, model TEXT, year INTEGER,
        photo TEXT, boughtOn TEXT, startMeters REAL DEFAULT 0, notes TEXT, archived INTEGER DEFAULT 0, createdAt TEXT DEFAULT (datetime('now')), retiredOn TEXT);
CREATE INDEX idx_bike_rider ON Bike(riderId);
CREATE TABLE Part (
        id INTEGER PRIMARY KEY AUTOINCREMENT, bikeId INTEGER NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, installedOn TEXT NOT NULL, retiredOn TEXT,
        initialMeters REAL DEFAULT 0, checkEveryM REAL, replaceEveryM REAL, checkEveryDays INTEGER, replaceEveryDays INTEGER, notify INTEGER DEFAULT 1,
        cost REAL, notes TEXT, createdAt TEXT DEFAULT (datetime('now')));
CREATE INDEX idx_part_bike ON Part(bikeId);
CREATE TABLE ServiceLog (
        id INTEGER PRIMARY KEY AUTOINCREMENT, bikeId INTEGER NOT NULL, partId INTEGER, date TEXT NOT NULL, action TEXT NOT NULL, odometerM REAL, cost REAL,
        notes TEXT, createdAt TEXT DEFAULT (datetime('now')));
CREATE INDEX idx_svc_bike ON ServiceLog(bikeId, date);
CREATE TABLE PartAlert (
        partId INTEGER NOT NULL, what TEXT NOT NULL, level TEXT NOT NULL, cycle TEXT NOT NULL, notifiedAt TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (partId, what, level, cycle));
CREATE TABLE BikeDefault (
        riderId INTEGER NOT NULL, sport TEXT NOT NULL, bikeId INTEGER NOT NULL, PRIMARY KEY (riderId, sport));
CREATE TABLE Kit (
        id INTEGER PRIMARY KEY AUTOINCREMENT, riderId INTEGER NOT NULL, kind TEXT NOT NULL DEFAULT 'shoes', name TEXT NOT NULL, brand TEXT, model TEXT,
        boughtOn TEXT, startMeters REAL DEFAULT 0, replaceAtM REAL, notes TEXT, retiredOn TEXT, createdAt TEXT DEFAULT (datetime('now')), photo TEXT);
CREATE INDEX idx_kit_rider ON Kit(riderId);
CREATE TABLE KitDefault (
        riderId INTEGER NOT NULL, sport TEXT NOT NULL, kitId INTEGER NOT NULL, PRIMARY KEY (riderId, sport));
CREATE TABLE KitAlert (
        kitId INTEGER NOT NULL, level TEXT NOT NULL, cycle TEXT NOT NULL, notifiedAt TEXT DEFAULT (datetime('now')), PRIMARY KEY (kitId, level, cycle));
CREATE TABLE StravaBike (
        riderId INTEGER NOT NULL,
        name    TEXT NOT NULL,                    -- Strava's name for the bike, exactly as the export writes it
        brand   TEXT, model TEXT,
        sports  TEXT,                             -- bikes.csv 'Bike Default Sport Types', e.g. 'Mountain Bike Ride'
        bikeId  INTEGER,                          -- the Headwind bike it is matched to
        status  TEXT NOT NULL DEFAULT 'new',      -- new (not matched yet) | matched | ignored (its rides get no bike)
        PRIMARY KEY (riderId, name));
CREATE TABLE StravaGear (
        activityId TEXT PRIMARY KEY,
        gear       TEXT NOT NULL);
CREATE INDEX idx_stravagear_gear ON StravaGear(gear);
CREATE TABLE StravaKit (
        riderId INTEGER NOT NULL,
        name    TEXT NOT NULL,                    -- the shoe as activities.csv 'Activity Gear' names it: brand, model (not "Other") and name
        label   TEXT,                             -- what the item is called here: the shoe's name, else brand and model
        brand   TEXT, model TEXT,
        sports  TEXT,                             -- shoes.csv 'Shoe Default Sport Types', e.g. 'Run|Walk|Trail Run'
        kitId   INTEGER,
        status  TEXT NOT NULL DEFAULT 'new',      -- new | matched | ignored (the rider deleted its item)
        PRIMARY KEY (riderId, name));
CREATE TABLE ActivityPhoto (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        activityId TEXT NOT NULL,
        filename   TEXT NOT NULL,                       -- act_<hex>.jpg; the thumbnail is act_<hex>_t.jpg
        caption    TEXT,
        sourceKey  TEXT UNIQUE,                         -- where it came from ('strava:media/<uuid>.jpg'), or NULL
        position   INTEGER DEFAULT 0,
        createdAt  TEXT DEFAULT (datetime('now'))
    );
CREATE INDEX idx_photo_activity ON ActivityPhoto(activityId, position);
CREATE TABLE FeedToken (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL,
            tokenHash     TEXT NOT NULL UNIQUE,
            shareRides    INTEGER DEFAULT 1,
            shareSegments INTEGER DEFAULT 1,
            shareFoods    INTEGER DEFAULT 1,
            sinceDate     TEXT,
            untilDate     TEXT,
            createdAt     TEXT DEFAULT (datetime('now')),
            lastUsedAt    TEXT,
            revokedAt     TEXT
        );
CREATE TABLE FeedTokenRider (
            tokenId INTEGER NOT NULL,
            riderId INTEGER NOT NULL,
            PRIMARY KEY (tokenId, riderId)
        );
CREATE TABLE TaskLog (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        task       TEXT NOT NULL,               -- e.g. startup:utc_starts, garmin_sync, friend_sync
        label      TEXT NOT NULL,               -- what a person reads: "Start times of imported rides"
        startedAt  TEXT NOT NULL,
        finishedAt TEXT,
        status     TEXT NOT NULL,               -- running | done | failed
        result     TEXT,                        -- one line: what it did
        error      TEXT,
        seen       INTEGER DEFAULT 0            -- start-up repairs: shown in a notice until the Tasks page has been opened
    , logId TEXT);
CREATE INDEX idx_tasklog_task ON TaskLog(task, id);
CREATE TABLE GarminFailure (
        activityId TEXT PRIMARY KEY,                 -- Garmin's id (Activity.id without 'garmin_')
        startDate  TEXT,                             -- its day, so a retry can move the sync's cursor back to it
        name       TEXT,
        kind       TEXT,                             -- download | parse | insert
        error      TEXT,
        tries      INTEGER NOT NULL DEFAULT 0,
        lastAt     TEXT,
        nextAt     TEXT,                             -- not before then (UTC ISO)
        gaveUp     INTEGER NOT NULL DEFAULT 0,
        version    TEXT                              -- the Headwind that gave up on it
    );
CREATE TABLE ImportChange (
        rideId    TEXT PRIMARY KEY,
        riderId   INTEGER,
        rideName  TEXT,
        source    TEXT,
        foundAt   TEXT DEFAULT (datetime('now')),
        diffs     TEXT NOT NULL,             -- [{label, old, new}] for the page
        act       TEXT NOT NULL              -- the imported ride, normalised (startDate / startDateLocal split as _insert stores them)
    );
CREATE TABLE ImportProblem (
        rideId    TEXT PRIMARY KEY,
        riderId   INTEGER,
        rideName  TEXT,
        file      TEXT,                      -- the file the import couldn't read
        problem   TEXT NOT NULL,             -- what was saved instead, for the page
        foundAt   TEXT DEFAULT (datetime('now'))
    );
CREATE TABLE ImportSeen (
        sourceKey   TEXT PRIMARY KEY,        -- 'strava:<activity id>' for an export's row, 'file:<crc>:<size>' for a file in a zip
        activityId  TEXT NOT NULL,           -- what it was saved as, or compared with
        fingerprint TEXT NOT NULL,           -- fingerprint(): the file, its activities.csv row, the rider, reader_version()
        seenAt      TEXT
    );
CREATE TABLE StravaExport (
        riderId       INTEGER PRIMARY KEY,
        keptAt        TEXT NOT NULL,             -- when it was uploaded
        sizeBytes     INTEGER,
        activities    INTEGER,                   -- rows in its activities.csv
        readAt        TEXT,                      -- when it was last imported: the upload, or Import again
        readerVersion TEXT,                      -- services/reimport.reader_version() then: a different one now reads it differently
        segments      INTEGER DEFAULT 0,         -- the options it was last imported with
        photos        INTEGER DEFAULT 1
    );
CREATE TABLE StravaExportRead (
        riderId   INTEGER PRIMARY KEY,
        advised   INTEGER NOT NULL DEFAULT 0,    -- len(REIMPORT_ADVISED) when the rider's export was last imported
        dismissed INTEGER NOT NULL DEFAULT 0,    -- len(REIMPORT_ADVISED) when the advice was put off: shown again for a newer line only
        readAt    TEXT
    );
CREATE TABLE SportFix (
        rideId         TEXT PRIMARY KEY,
        riderId        INTEGER NOT NULL,
        name           TEXT,
        startDateLocal TEXT,
        distance       REAL,
        oldSport       TEXT,
        newSport       TEXT NOT NULL,
        typeKey        TEXT,
        status         TEXT NOT NULL DEFAULT 'pending',     -- pending | kept (the rider chose to leave it as it is)
        error          TEXT
    );
CREATE TABLE GarminSeen (
        garminId  TEXT PRIMARY KEY,          -- Garmin's activity id
        summary   TEXT NOT NULL,             -- summary(): Garmin's name, type, distance, length and start, as last accepted
        seenAt    TEXT DEFAULT (datetime('now')),
        cropChecked INTEGER NOT NULL DEFAULT 0    -- 1: the saved activity was read with Garmin's crop, or checked for one missed (_missed_crop)
    );
CREATE TABLE GarminChange (
        rideId    TEXT PRIMARY KEY,
        garminId  TEXT NOT NULL,
        riderId   INTEGER,
        rideName  TEXT,
        kind      TEXT NOT NULL,             -- deleted | edited
        diffs     TEXT NOT NULL DEFAULT '[]',     -- edited: [{field: name | sport, old, new}]
        garmin    TEXT,                      -- edited: Garmin's summary now, the baseline once it's settled
        status    TEXT NOT NULL DEFAULT 'pending',  -- pending | kept (deleted in Garmin, kept here: not flagged again)
        foundAt   TEXT DEFAULT (datetime('now'))
    );
CREATE TABLE GarminMissing (
        garminId  TEXT PRIMARY KEY,          -- Garmin's activity id: in Garmin, not here, and older than the sync's cursor
        riderId   INTEGER,
        name      TEXT,
        typeKey   TEXT,
        startDateLocal TEXT,
        distance  REAL,
        activity  TEXT NOT NULL,             -- the entry in Garmin's list, as garmin.save_activity takes it
        deleted   INTEGER NOT NULL DEFAULT 0,     -- 1: deleted here (or left out), still in Garmin; offered to bring back, never brought in by itself
        foundAt   TEXT DEFAULT (datetime('now'))
    );
CREATE TABLE Goal (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        riderId   INTEGER NOT NULL REFERENCES Rider(id),
        metric    TEXT NOT NULL,                  -- METRICS
        period    TEXT NOT NULL,                  -- PERIODS
        sport     TEXT NOT NULL DEFAULT 'all',    -- GROUPS
        target    REAL NOT NULL,                  -- metres, seconds or a count
        createdAt TEXT DEFAULT (datetime('now'))
    );
CREATE TABLE Challenge (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        uid          TEXT NOT NULL UNIQUE,         -- made where it was started; the same on every instance that has it
        riderId      INTEGER REFERENCES Rider(id), -- the rider here it belongs to
        name         TEXT NOT NULL,
        metric       TEXT NOT NULL,
        sport        TEXT NOT NULL DEFAULT 'all',
        startDate    TEXT NOT NULL,                -- inclusive, local dates
        endDate      TEXT NOT NULL,
        target       REAL,                         -- NULL: the most wins; else the first to it
        mine         INTEGER NOT NULL DEFAULT 0,   -- 1: started here
        joined       INTEGER NOT NULL DEFAULT 0,   -- 1: the rider here is in it (always, for one started here)
        dismissed    INTEGER NOT NULL DEFAULT 0,   -- an invitation the rider turned down
        creatorName  TEXT,                         -- who started it, as their feed named them
        viaFriendId  INTEGER REFERENCES Friend(id),-- whose feed brought it (NULL: started here)
        createdAt    TEXT DEFAULT (datetime('now'))
    );
CREATE TABLE ChallengeMember (
        challengeId INTEGER NOT NULL REFERENCES Challenge(id) ON DELETE CASCADE,
        friendId    INTEGER NOT NULL REFERENCES Friend(id) ON DELETE CASCADE,
        PRIMARY KEY (challengeId, friendId)
    );
CREATE TABLE ChallengeInvite (       -- who a challenge started here goes to: the friends' feed tokens
        challengeId INTEGER NOT NULL REFERENCES Challenge(id) ON DELETE CASCADE,
        tokenId     INTEGER NOT NULL REFERENCES FeedToken(id) ON DELETE CASCADE,
        PRIMARY KEY (challengeId, tokenId)
    );
CREATE TABLE "Activity" ("id" TEXT PRIMARY KEY, "name" TEXT, "type" TEXT, "sportType" TEXT, "startDate" TEXT, "startDateLocal" TEXT, "timezone" TEXT, "distance" REAL, "movingTime" INTEGER, "elapsedTime" INTEGER, "totalElevationGain" REAL, "averageSpeed" REAL, "maxSpeed" REAL, "averageHeartrate" REAL, "maxHeartrate" REAL, "averageWatts" REAL, "maxWatts" REAL, "weightedAvgWatts" REAL, "kilojoules" REAL, "averageCadence" REAL, "calories" REAL, "sufferScore" REAL, "startLat" REAL, "startLng" REAL, "city" TEXT, "country" TEXT, "kudosCount" INTEGER, "riderId" INTEGER REFERENCES Rider(id), "weatherTempC" REAL, "weatherWindKph" REAL, "weatherGustKph" REAL, "weatherWindDir" INTEGER, "weatherHumidity" INTEGER, "weatherRainMm" REAL, "weatherCode" INTEGER, "weatherSummary" TEXT, "weatherWindRel" TEXT, "createdAt" TEXT DEFAULT (datetime('now')), "updatedAt" TEXT DEFAULT (datetime('now')), "weatherSource" TEXT, "flagReason" TEXT, "flagDismissed" INTEGER, "aiKudosAt" TEXT, "caloriesRaw" REAL, "originId" TEXT, "steps" INTEGER, "source" TEXT, "commute" INTEGER, "srcUpdatedAt" TEXT, "bikeId" INTEGER, "bikeAuto" INTEGER, "sportBeforeBike" TEXT, "kitId" INTEGER, "kitAuto" INTEGER, "summaryPolyline" TEXT, "description" TEXT, "notes" TEXT, "aiKudos" TEXT, "rawData" TEXT, "streams" TEXT, "laps" TEXT);
CREATE INDEX idx_activity_rider_date ON Activity(riderId, startDateLocal);
CREATE INDEX idx_activity_bike ON Activity(bikeId);
CREATE INDEX idx_activity_kit ON Activity(kitId);
CREATE TRIGGER Activity_touch AFTER UPDATE OF name, type, sportType, startDate, startDateLocal, distance, movingTime, elapsedTime, totalElevationGain, averageSpeed, maxSpeed, averageHeartrate, maxHeartrate, averageWatts, weightedAvgWatts, averageCadence, startLat, startLng, streams, weatherTempC, weatherWindKph, weatherGustKph, weatherWindDir, weatherHumidity, weatherRainMm, weatherCode, weatherSummary, weatherWindRel, steps, riderId ON Activity WHEN NEW.updatedAt IS OLD.updatedAt AND (NEW.name IS NOT OLD.name OR NEW.type IS NOT OLD.type OR NEW.sportType IS NOT OLD.sportType OR NEW.startDate IS NOT OLD.startDate OR NEW.startDateLocal IS NOT OLD.startDateLocal OR NEW.distance IS NOT OLD.distance OR NEW.movingTime IS NOT OLD.movingTime OR NEW.elapsedTime IS NOT OLD.elapsedTime OR NEW.totalElevationGain IS NOT OLD.totalElevationGain OR NEW.averageSpeed IS NOT OLD.averageSpeed OR NEW.maxSpeed IS NOT OLD.maxSpeed OR NEW.averageHeartrate IS NOT OLD.averageHeartrate OR NEW.maxHeartrate IS NOT OLD.maxHeartrate OR NEW.averageWatts IS NOT OLD.averageWatts OR NEW.weightedAvgWatts IS NOT OLD.weightedAvgWatts OR NEW.averageCadence IS NOT OLD.averageCadence OR NEW.startLat IS NOT OLD.startLat OR NEW.startLng IS NOT OLD.startLng OR NEW.streams IS NOT OLD.streams OR NEW.weatherTempC IS NOT OLD.weatherTempC OR NEW.weatherWindKph IS NOT OLD.weatherWindKph OR NEW.weatherGustKph IS NOT OLD.weatherGustKph OR NEW.weatherWindDir IS NOT OLD.weatherWindDir OR NEW.weatherHumidity IS NOT OLD.weatherHumidity OR NEW.weatherRainMm IS NOT OLD.weatherRainMm OR NEW.weatherCode IS NOT OLD.weatherCode OR NEW.weatherSummary IS NOT OLD.weatherSummary OR NEW.weatherWindRel IS NOT OLD.weatherWindRel OR NEW.steps IS NOT OLD.steps OR NEW.riderId IS NOT OLD.riderId) BEGIN UPDATE Activity SET updatedAt = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = NEW.id; END;
CREATE TABLE "GarminDaily" ("date" TEXT PRIMARY KEY, "restingHR" INTEGER, "hrv" INTEGER, "hrvBalanced" INTEGER DEFAULT (0), "sleepHours" REAL, "sleepScore" INTEGER, "bodyBattery" INTEGER, "steps" INTEGER, "stressScore" INTEGER, "totalCalories" INTEGER, "activeCalories" INTEGER, "totalCaloriesRaw" REAL, "activeCaloriesRaw" REAL, "hrStream" TEXT, "bodyBatteryStream" TEXT);
CREATE VIEW Ride AS SELECT * FROM Activity WHERE (sportType IS NULL OR sportType = '' OR lower(sportType) LIKE '%ride%' OR lower(sportType) LIKE '%cycl%')
/* Ride(id,name,type,sportType,startDate,startDateLocal,timezone,distance,movingTime,elapsedTime,totalElevationGain,averageSpeed,maxSpeed,averageHeartrate,maxHeartrate,averageWatts,maxWatts,weightedAvgWatts,kilojoules,averageCadence,calories,sufferScore,startLat,startLng,city,country,kudosCount,riderId,weatherTempC,weatherWindKph,weatherGustKph,weatherWindDir,weatherHumidity,weatherRainMm,weatherCode,weatherSummary,weatherWindRel,createdAt,updatedAt,weatherSource,flagReason,flagDismissed,aiKudosAt,caloriesRaw,originId,steps,source,commute,srcUpdatedAt,bikeId,bikeAuto,sportBeforeBike,kitId,kitAuto,summaryPolyline,description,notes,aiKudos,rawData,streams,laps) */;
CREATE VIEW SegActivity AS SELECT id, name, riderId, startDateLocal, sportType, bikeId,
            CASE WHEN (sportType IS NULL OR sportType = '' OR lower(sportType) LIKE '%ride%' OR lower(sportType) LIKE '%cycl%') THEN 'activity' ELSE 'workout' END AS kind FROM Activity
/* SegActivity(id,name,riderId,startDateLocal,sportType,bikeId,kind) */;
CREATE TABLE ActivityTrack (
        activityId TEXT PRIMARY KEY,
        minLat REAL, maxLat REAL, minLng REAL, maxLng REAL,     -- NULL: no GPS track
        line   TEXT,                                            -- JSON [[lat, lng], ...], SAMPLE points at 4 places, or NULL
        lineHd TEXT,                                            -- the same at SAMPLE_HD points and 5 places
        cells  TEXT,                                            -- the cells (cell_of) of every point, space-separated; NULL: unknown
        outOfStep INTEGER                                       -- how many more times than positions (stored before 0.7.7); 0 in step
    );
CREATE TRIGGER ActivityTrack_insert AFTER INSERT ON Activity
                  BEGIN DELETE FROM ActivityTrack WHERE activityId = NEW.id; END;
CREATE TRIGGER ActivityTrack_update AFTER UPDATE OF streams, id ON Activity
                  BEGIN DELETE FROM ActivityTrack WHERE activityId = OLD.id; END;
CREATE TRIGGER ActivityTrack_delete AFTER DELETE ON Activity
                  BEGIN DELETE FROM ActivityTrack WHERE activityId = OLD.id; END;
CREATE TABLE DataVersion (id INTEGER PRIMARY KEY CHECK (id = 1), n INTEGER NOT NULL DEFAULT 0);
CREATE TRIGGER DataVersion_Activity_insert AFTER INSERT ON Activity BEGIN UPDATE DataVersion SET n = n + 1 WHERE id = 1; END;
CREATE TRIGGER DataVersion_Activity_update AFTER UPDATE ON Activity BEGIN UPDATE DataVersion SET n = n + 1 WHERE id = 1; END;
CREATE TRIGGER DataVersion_Activity_delete AFTER DELETE ON Activity BEGIN UPDATE DataVersion SET n = n + 1 WHERE id = 1; END;
CREATE TRIGGER DataVersion_Segment_insert AFTER INSERT ON Segment BEGIN UPDATE DataVersion SET n = n + 1 WHERE id = 1; END;
CREATE TRIGGER DataVersion_Segment_update AFTER UPDATE ON Segment BEGIN UPDATE DataVersion SET n = n + 1 WHERE id = 1; END;
CREATE TRIGGER DataVersion_Segment_delete AFTER DELETE ON Segment BEGIN UPDATE DataVersion SET n = n + 1 WHERE id = 1; END;
CREATE TRIGGER DataVersion_SegmentEffort_insert AFTER INSERT ON SegmentEffort BEGIN UPDATE DataVersion SET n = n + 1 WHERE id = 1; END;
CREATE TRIGGER DataVersion_SegmentEffort_update AFTER UPDATE ON SegmentEffort BEGIN UPDATE DataVersion SET n = n + 1 WHERE id = 1; END;
CREATE TRIGGER DataVersion_SegmentEffort_delete AFTER DELETE ON SegmentEffort BEGIN UPDATE DataVersion SET n = n + 1 WHERE id = 1; END;
CREATE TRIGGER DataVersion_Bike_insert AFTER INSERT ON Bike BEGIN UPDATE DataVersion SET n = n + 1 WHERE id = 1; END;
CREATE TRIGGER DataVersion_Bike_update AFTER UPDATE ON Bike BEGIN UPDATE DataVersion SET n = n + 1 WHERE id = 1; END;
CREATE TRIGGER DataVersion_Bike_delete AFTER DELETE ON Bike BEGIN UPDATE DataVersion SET n = n + 1 WHERE id = 1; END;
CREATE TRIGGER DataVersion_SportEffort_insert AFTER INSERT ON SportEffort BEGIN UPDATE DataVersion SET n = n + 1 WHERE id = 1; END;
CREATE TRIGGER DataVersion_SportEffort_update AFTER UPDATE ON SportEffort BEGIN UPDATE DataVersion SET n = n + 1 WHERE id = 1; END;
CREATE TRIGGER DataVersion_SportEffort_delete AFTER DELETE ON SportEffort BEGIN UPDATE DataVersion SET n = n + 1 WHERE id = 1; END;
