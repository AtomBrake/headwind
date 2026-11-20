CREATE TABLE Rider (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            avatarPath TEXT,
            isDefault  INTEGER DEFAULT 0,
            haDevice   TEXT
        );
CREATE TABLE Activity (
            id                  TEXT PRIMARY KEY,
            name                TEXT,
            type                TEXT,
            sportType           TEXT,
            startDate           TEXT,
            startDateLocal      TEXT,
            timezone            TEXT,
            distance            REAL,
            movingTime          INTEGER,
            elapsedTime         INTEGER,
            totalElevationGain  REAL,
            averageSpeed        REAL,
            maxSpeed            REAL,
            averageHeartrate    REAL,
            maxHeartrate        REAL,
            averageWatts        REAL,
            maxWatts            REAL,
            weightedAvgWatts    REAL,
            kilojoules          REAL,
            averageCadence      REAL,
            calories            REAL,
            sufferScore         REAL,
            startLat            REAL,
            startLng            REAL,
            city                TEXT,
            country             TEXT,
            summaryPolyline     TEXT,
            kudosCount          INTEGER,
            streams             TEXT,
            rawData             TEXT,
            description         TEXT,
            notes               TEXT,
            riderId             INTEGER REFERENCES Rider(id),
            weatherTempC        REAL,
            weatherWindKph      REAL,
            weatherGustKph      REAL,
            weatherWindDir      INTEGER,
            weatherHumidity     INTEGER,
            weatherRainMm       REAL,
            weatherCode         INTEGER,
            weatherSummary      TEXT,
            weatherWindRel      TEXT,
            aiKudos             TEXT,
            createdAt           TEXT DEFAULT (datetime('now')),
            updatedAt           TEXT DEFAULT (datetime('now'))
        , aiKudosAt TEXT);
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
        , feedToken TEXT, friendSyncInterval INTEGER DEFAULT 15, garminActivitySyncDate TEXT, garminSyncMode TEXT DEFAULT 'health', heightCm REAL, sex TEXT, birthYear INTEGER, activityFactor REAL, lossLbPerWeek REAL, stepGoal INTEGER, goalAuto INTEGER DEFAULT 0, goalAutoLast TEXT, rideKcalWeek REAL, rideGoalWeek INTEGER, goalWeightKg REAL, holidayStart TEXT, holidayEnd TEXT, garminLastOk TEXT, garminLastError TEXT, garminDeviceSync TEXT, garminFailCount INTEGER DEFAULT 0, haUrl TEXT, haToken TEXT, haEntityMap TEXT, haSyncMinutes INTEGER, haLastSync TEXT, haLastResult TEXT, haWeatherEntity TEXT, haWeatherCondition TEXT, haWeatherTempC REAL, haWeatherUpdatedAt TEXT, installId TEXT, telemetryOptOut INTEGER DEFAULT 0, telemetryPingedAt TEXT, nutritionCalGoal INTEGER, nutritionProteinGoal INTEGER, nutritionCarbGoal INTEGER, nutritionFatGoal INTEGER, nutritionWaterGoalMl INTEGER DEFAULT 2500, nutritionBmrKcal INTEGER, units TEXT DEFAULT 'imperial', distanceBackfillDone INTEGER DEFAULT 0, nutritionWeightUnit TEXT DEFAULT 'stlb', nutritionWeightEmaAlpha REAL DEFAULT 0.1, dietStartDate TEXT);
CREATE TABLE GarminDaily (
            date         TEXT PRIMARY KEY,
            restingHR    INTEGER,
            hrv          INTEGER,
            hrvBalanced  INTEGER DEFAULT 0,
            sleepHours   REAL,
            sleepScore   INTEGER,
            bodyBattery  INTEGER,
            steps        INTEGER,
            stressScore  INTEGER
        , hrStream TEXT, bodyBatteryStream TEXT, totalCalories INTEGER, activeCalories INTEGER);
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
        , friendId INTEGER REFERENCES Friend(id), sourceSegId INTEGER);
CREATE TABLE SegmentEffort (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            segmentId    INTEGER NOT NULL REFERENCES Segment(id) ON DELETE CASCADE,
            activityId   TEXT NOT NULL,
            activityDate TEXT,
            elapsedSecs  INTEGER NOT NULL,
            avgSpeedMps  REAL,
            isPR         INTEGER DEFAULT 0,
            createdAt    TEXT DEFAULT (datetime('now')),
            UNIQUE(segmentId, activityId)
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
            accessToken  TEXT,
            refreshToken TEXT,
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
        , mealType TEXT DEFAULT 'uncategorised', source TEXT DEFAULT 'manual', brand TEXT, imageUrl TEXT, nutriScoreGrade TEXT, fibre REAL);
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
        , fibre REAL);
CREATE TABLE WeightLog (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            riderId   INTEGER REFERENCES Rider(id),
            logDate   TEXT NOT NULL,
            weightKg  REAL NOT NULL,
            source    TEXT DEFAULT 'manual',
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
CREATE TABLE Workout (
            id                 TEXT PRIMARY KEY,
            riderId            INTEGER NOT NULL,
            sport              TEXT NOT NULL,
            name               TEXT,
            startDate          TEXT,
            startDateLocal     TEXT NOT NULL,
            distance           REAL, movingTime INTEGER, elapsedTime INTEGER,
            totalElevationGain REAL, averageSpeed REAL, maxSpeed REAL, averageHeartrate REAL,
            calories           REAL,
            steps              INTEGER,
            startLat REAL, startLng REAL,
            streams            TEXT,
            weatherSummary     TEXT,
            source             TEXT,
            createdAt          TEXT DEFAULT (datetime('now'))
        );
CREATE INDEX idx_workout_rider_date ON Workout(riderId, startDateLocal);
CREATE TABLE DeviceToken (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            tokenHash  TEXT NOT NULL UNIQUE,
            createdAt  TEXT DEFAULT (datetime('now')),
            lastUsedAt TEXT,
            revokedAt  TEXT
        );
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
        );
