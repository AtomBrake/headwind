import Foundation
import Testing
@testable import Headwind

private let t0 = Date(timeIntervalSince1970: 1_760_000_000)

private func bytes(_ b: [UInt8]) -> Data { Data(b) }

/// The byte strings are built from the Bluetooth SIG's field layouts, in the shapes real sensors send (a strap with RR intervals after the rate,
/// a power meter with balance and torque before the crank data, a trainer splitting Indoor Bike Data with the "more data" bit).
struct GATTParsingTests {
    @Test func heartRateIn8And16Bits() throws {
        // Flags 0x16: contact supported and detected, RR intervals follow (ignored). 72 bpm.
        let strap = try #require(HeartRateMeasurement(bytes([0x16, 0x48, 0x3A, 0x03])))
        #expect(strap.bpm == 72 && strap.contactDetected == true && strap.isValid)
        // Flags 0x01: 16-bit rate, no contact status. 140 bpm.
        let wide = try #require(HeartRateMeasurement(bytes([0x01, 0x8C, 0x00])))
        #expect(wide.bpm == 140 && wide.contactDetected == nil && wide.isValid)
        // Supported but not touching skin: not a reading.
        let loose = try #require(HeartRateMeasurement(bytes([0x04, 0x50])))
        #expect(!loose.isValid)
        #expect(HeartRateMeasurement(bytes([0x01, 0x8C])) == nil)   // a 16-bit rate cut short
        #expect(HeartRateMeasurement(Data()) == nil)
    }

    @Test func speedAndCadence() throws {
        // Both present: wheel 1000 revolutions at 2048/1024 s, crank 50 at 1024/1024 s.
        let m = try #require(CSCMeasurement(bytes([0x03, 0xE8, 0x03, 0x00, 0x00, 0x00, 0x08, 0x32, 0x00, 0x00, 0x04])))
        #expect(m.wheel == Revolutions(count: 1000, eventTime: 2048))
        #expect(m.crank == Revolutions(count: 50, eventTime: 1024))
        // A cadence-only sensor.
        let cadence = try #require(CSCMeasurement(bytes([0x02, 0x32, 0x00, 0x00, 0x04])))
        #expect(cadence.wheel == nil && cadence.crank?.count == 50)
        #expect(CSCMeasurement(bytes([0x01, 0xE8, 0x03])) == nil)
    }

    @Test func cyclingPowerSkipsTheFieldsBeforeTheCrank() throws {
        // Flags 0x0020: crank data only. 250 W, crank 10 at 1024.
        let plain = try #require(CyclingPowerMeasurement(bytes([0x20, 0x00, 0xFA, 0x00, 0x0A, 0x00, 0x00, 0x04])))
        #expect(plain.power == 250 && plain.crank == Revolutions(count: 10, eventTime: 1024) && plain.wheel == nil)
        // Flags 0x0025: pedal balance (1 byte) and accumulated torque (2) come first.
        let full = try #require(CyclingPowerMeasurement(bytes([0x25, 0x00, 0xFA, 0x00, 0x64, 0x10, 0x27, 0x0A, 0x00, 0x00, 0x04])))
        #expect(full.power == 250 && full.crank?.count == 10)
        // Power alone, and a negative reading (some meters send one when back-pedalling).
        #expect(CyclingPowerMeasurement(bytes([0x00, 0x00, 0x2C, 0x01]))?.power == 300)
        #expect(CyclingPowerMeasurement(bytes([0x00, 0x00, 0xF6, 0xFF]))?.power == -10)
        #expect(CyclingPowerMeasurement(bytes([0x20, 0x00, 0xFA, 0x00, 0x0A])) == nil)
    }

    @Test func indoorBikeData() throws {
        // Flags 0x0044: speed (bit 0 clear), cadence, power. 30 km/h, 90 rpm, 200 W.
        let m = try #require(IndoorBikeData(bytes([0x44, 0x00, 0xB8, 0x0B, 0xB4, 0x00, 0xC8, 0x00])))
        #expect(abs((m.speed ?? 0) - 30 / 3.6) < 0.001)
        #expect(m.cadence == 90 && m.power == 200 && m.distance == nil)
        // Flags 0x0254: and distance (24-bit) and heart rate. 1234 m, 140 bpm.
        let more = try #require(IndoorBikeData(bytes([0x54, 0x02, 0xB8, 0x0B, 0xB4, 0x00, 0xD2, 0x04, 0x00, 0xC8, 0x00, 0x8C])))
        #expect(more.distance == 1234 && more.power == 200 && more.heartRate == 140)
        // "More data" set: no speed in this packet, the rest follows.
        let split = try #require(IndoorBikeData(bytes([0x41, 0x00, 0xC8, 0x00])))
        #expect(split.speed == nil && split.power == 200)
        #expect(IndoorBikeData(bytes([0x44, 0x00, 0xB8, 0x0B])) == nil)
    }

    @Test func kindsAndBattery() {
        #expect(SensorKind.main(of: [0x1818, 0x1826, 0x1816]) == .trainer)
        #expect(SensorKind.main(of: [0x180D, 0x180F]) == .heartRate)
        #expect(SensorKind.main(of: [0x1816]) == .speedCadence)
        #expect(SensorKind.main(of: [0x180F]) == nil)
        #expect(BatteryLevel.parse(bytes([0x55])) == 85)
        #expect(BatteryLevel.parse(bytes([0xFF])) == nil)
    }
}

struct RevolutionRateTests {
    @Test func cadenceFromTwoReadings() {
        var crank = RevolutionRate.crank
        crank.update(Revolutions(count: 100, eventTime: 0), at: t0)
        #expect(crank.perSecond(at: t0) == 0)                       // one reading: no rate yet
        crank.update(Revolutions(count: 101, eventTime: 1024), at: t0.addingTimeInterval(1))
        #expect(crank.perSecond(at: t0.addingTimeInterval(1)).map { $0 * 60 } == 60)
        // Two revolutions in the next 1.5 s of events: 80 rpm.
        crank.update(Revolutions(count: 103, eventTime: 1024 + 1536), at: t0.addingTimeInterval(2))
        #expect(abs((crank.perSecond(at: t0.addingTimeInterval(2)) ?? 0) * 60 - 80) < 0.01)
    }

    @Test func countersWrap() {
        var crank = RevolutionRate.crank
        crank.update(Revolutions(count: 65535, eventTime: 65000), at: t0)
        crank.update(Revolutions(count: 0, eventTime: 488), at: t0.addingTimeInterval(1))   // both wrapped: one revolution in 1024 ticks
        #expect(crank.perSecond(at: t0.addingTimeInterval(1)).map { $0 * 60 } == 60)
        #expect(crank.revolutions == 1)

        var wheel = RevolutionRate.wheel()
        wheel.update(Revolutions(count: UInt32.max - 1, eventTime: 100), at: t0)
        wheel.update(Revolutions(count: 2, eventTime: 1124), at: t0.addingTimeInterval(1))
        #expect(wheel.revolutions == 4)
        #expect(wheel.perSecond(at: t0.addingTimeInterval(1)) == 4)
    }

    @Test func stoppedThenGone() {
        var crank = RevolutionRate.crank
        crank.update(Revolutions(count: 1, eventTime: 0), at: t0)
        crank.update(Revolutions(count: 2, eventTime: 1024), at: t0.addingTimeInterval(1))
        // The sensor keeps sending the same count: stopped after 3 s.
        for s in 2...4 { crank.update(Revolutions(count: 2, eventTime: 1024), at: t0.addingTimeInterval(Double(s))) }
        #expect(crank.perSecond(at: t0.addingTimeInterval(3.5)).map { $0 * 60 } == 60)
        #expect(crank.perSecond(at: t0.addingTimeInterval(4.5)) == 0)
        // Then nothing at all for 5 s: no reading.
        #expect(crank.perSecond(at: t0.addingTimeInterval(9.5)) == nil)
    }

    @Test func impossibleJumpsAreNotCounted() {
        var wheel = RevolutionRate.wheel()
        wheel.update(Revolutions(count: 10, eventTime: 0), at: t0)
        wheel.update(Revolutions(count: 5_010, eventTime: 1024), at: t0.addingTimeInterval(1))   // a restarted sensor
        #expect(wheel.revolutions == 0)
        wheel.update(Revolutions(count: 5_014, eventTime: 2048), at: t0.addingTimeInterval(2))
        #expect(wheel.revolutions == 4)
    }
}

struct SensorChannelTests {
    private func csc(wheel: UInt32, wheelTime: UInt16, crank: UInt16, crankTime: UInt16) -> Data {
        var b: [UInt8] = [0x03]
        b += withUnsafeBytes(of: wheel.littleEndian, Array.init)
        b += withUnsafeBytes(of: wheelTime.littleEndian, Array.init)
        b += withUnsafeBytes(of: crank.littleEndian, Array.init)
        b += withUnsafeBytes(of: crankTime.littleEndian, Array.init)
        return Data(b)
    }

    @Test func wheelSpeedAndDistance() {
        var channel = SensorChannel()
        // 4 wheel revolutions and 1.5 crank revolutions a second (90 rpm), 11 packets a second apart.
        for s in 0...10 {
            let data = csc(wheel: UInt32(4 * s), wheelTime: UInt16(1024 * s), crank: UInt16(3 * s), crankTime: UInt16(2048 * s))
            let understood = channel.receive(GATT.cscMeasurement, data, at: t0.addingTimeInterval(Double(s)))
            #expect(understood)
        }
        let r = channel.readings(at: t0.addingTimeInterval(10.2), wheelCircumference: 2.105)
        #expect(abs((r.speed ?? 0) - 8.42) < 0.001)
        #expect(r.cadence == 90)
        #expect(abs((r.distance ?? 0) - 84.2) < 0.001)
        #expect(r.heartRate == nil && r.power == nil)
        // Out of range: nothing, rather than the last speed.
        #expect(channel.readings(at: t0.addingTimeInterval(20), wheelCircumference: 2.105).isEmpty)
    }

    @Test func powerIsA3SecondAverage() {
        var channel = SensorChannel()
        for (s, watts) in [(0.0, 100), (1, 200), (2, 300), (3, 400)] {
            let w = UInt16(watts)
            channel.receive(GATT.cyclingPowerMeasurement, Data([0x00, 0x00, UInt8(w & 0xFF), UInt8(w >> 8)]), at: t0.addingTimeInterval(s))
        }
        // The readings at 1, 2 and 3 s.
        #expect(channel.readings(at: t0.addingTimeInterval(3.5), wheelCircumference: 2.105).power == 300)
        // Then the latest alone, until the meter has been quiet for 5 s.
        #expect(channel.readings(at: t0.addingTimeInterval(7), wheelCircumference: 2.105).power == 400)
        #expect(channel.readings(at: t0.addingTimeInterval(8), wheelCircumference: 2.105).power == nil)
    }

    @Test func aTrainersDistanceCarriesOnWhenItRestarts() {
        var channel = SensorChannel()
        func ibd(distance: UInt32) -> Data {
            Data([0x10, 0x00, 0xB8, 0x0B, UInt8(distance & 0xFF), UInt8(distance >> 8 & 0xFF), UInt8(distance >> 16)])
        }
        channel.receive(GATT.indoorBikeData, ibd(distance: 5000), at: t0)
        channel.receive(GATT.indoorBikeData, ibd(distance: 5010), at: t0.addingTimeInterval(1))
        channel.receive(GATT.indoorBikeData, ibd(distance: 0), at: t0.addingTimeInterval(2))   // switched off and on
        channel.receive(GATT.indoorBikeData, ibd(distance: 8), at: t0.addingTimeInterval(3))
        let r = channel.readings(at: t0.addingTimeInterval(3), wheelCircumference: 2.105)
        #expect(r.distance == 18)
        #expect(abs((r.speed ?? 0) - 30 / 3.6) < 0.001)
    }

    @Test func aStrapWithNoContactIsNoHeartRate() {
        var channel = SensorChannel()
        channel.receive(GATT.heartRateMeasurement, Data([0x04, 0x50]), at: t0)
        #expect(channel.readings(at: t0, wheelCircumference: 2.105).heartRate == nil)
        channel.receive(GATT.heartRateMeasurement, Data([0x06, 0x50]), at: t0.addingTimeInterval(1))
        #expect(channel.readings(at: t0.addingTimeInterval(1), wheelCircumference: 2.105).heartRate == 80)
        let battery = channel.receive(GATT.batteryLevel, Data([0x50]), at: t0)
        #expect(!battery)                      // the sensor manager reads battery itself
    }
}

struct SensorCombiningTests {
    @Test func eachValueFromTheBestSensor() {
        let strap = UUID(), meter = UUID(), trainer = UUID(), wheel = UUID()
        let r = SensorReadings.combine([
            .init(kind: .trainer, id: trainer, readings: SensorReadings(heartRate: 140, power: 240, cadence: 88, speed: 9, distance: 500)),
            .init(kind: .power, id: meter, readings: SensorReadings(power: 250, cadence: 90)),
            .init(kind: .speedCadence, id: wheel, readings: SensorReadings(cadence: 91, speed: 8.5, distance: 480)),
            .init(kind: .heartRate, id: strap, readings: SensorReadings(heartRate: 150)),
        ])
        #expect(r.heartRate == 150 && r.power == 250 && r.cadence == 91 && r.speed == 8.5)
        #expect(r.distance == 500 && r.distanceSource == trainer)
    }

    @Test func fallsBackWhenTheBestHasNone() {
        let trainer = UUID()
        let r = SensorReadings.combine([
            .init(kind: .heartRate, id: UUID(), readings: SensorReadings()),
            .init(kind: .trainer, id: trainer, readings: SensorReadings(heartRate: 140, power: 240)),
        ])
        #expect(r.heartRate == 140 && r.power == 240 && r.distance == nil)
        #expect(SensorReadings.combine([]).isEmpty)
    }
}

struct DistanceFollowerTests {
    @Test func countsOnlyStepsOfOneSensorWhileRecording() {
        let a = UUID(), b = UUID()
        var f = DistanceFollower()
        #expect(f.update(SensorReadings()) == nil)                     // no sensor gives distance
        #expect(f.update(SensorReadings(distance: 100, distanceSource: a)) == 0)
        f.update(SensorReadings(distance: 105, distanceSource: a))
        #expect(f.update(SensorReadings(distance: 112, distanceSource: a)) == 12)
        f.pause()
        f.update(SensorReadings(distance: 200, distanceSource: a))    // ridden while paused: not counted
        #expect(f.update(SensorReadings(distance: 203, distanceSource: a)) == 15)
        f.update(SensorReadings(distance: 210, distanceSource: b))    // another sensor took over
        #expect(f.update(SensorReadings(distance: 214, distanceSource: b)) == 19)
        f.update(SensorReadings(distance: 900, distanceSource: b))    // a jump
        #expect(f.update(SensorReadings(distance: 905, distanceSource: b)) == 24)
        #expect(f.update(SensorReadings()) == 24)                       // gone quiet: the distance so far stays
        f.update(SensorReadings(distance: 950, distanceSource: b))
        #expect(f.update(SensorReadings(distance: 951, distanceSource: b)) == 25)
    }
}

struct SessionTrackTests {
    @Test func averagesAndDistance() {
        var track = SessionTrack()
        for s in 0..<10 {
            track.add(SessionSample(time: t0.addingTimeInterval(Double(s)), hr: 140, power: s.isMultiple(of: 2) ? 200 : 0,
                                    cadence: s.isMultiple(of: 2) ? 90 : 0, speed: 8, distance: Double(s) * 8))
        }
        let again = track.add(SessionSample(time: t0.addingTimeInterval(9), hr: 200))
        #expect(!again)                        // the same second again
        #expect(track.averageHeartRate == 140)
        #expect(track.averagePower == 100)      // coasting counts
        #expect(track.averageCadence == 90)     // coasting doesn't
        #expect(track.distance == 72)
        #expect(track.maxSpeed == 8)
    }

    @Test func anIndoorRidesJournalKeepsItsSensorSamples() throws {
        let journal = RideJournal(url: FileManager.default.temporaryDirectory.appending(path: "sensors-\(UUID().uuidString).jsonl"))
        defer { journal.clear() }
        journal.begin(start: t0, sport: .indoorRide, bikeId: 3)
        for s in 1...120 {
            journal.append(SessionSample(time: t0.addingTimeInterval(Double(s)), hr: 150, power: 220, cadence: 85, speed: 9,
                                         distance: Double(s) * 9))
        }
        journal.note(.init(at: t0.addingTimeInterval(90), active: 90, distance: 810))
        let recovered = try #require(journal.load())
        #expect(recovered.samples.count == 120)
        let summary = RideJournal.summary(of: recovered)
        #expect(summary.sport == .indoorRide && summary.bikeId == 3)
        #expect(summary.movingTime == 90)
        #expect(summary.distance == 1080)
        #expect(summary.averageHeartRate == 150 && summary.averagePower == 220 && summary.averageCadence == 85)
    }

    @Test func aStrengthSessionKeepsHeartRateButNoDistance() {
        var track = SessionTrack()
        track.add(SessionSample(time: t0, hr: 150, distance: 40))
        let summary = RideSummary.session(start: t0, elapsed: 600, sport: .strength, track: track)
        #expect(summary.distance == 0 && summary.averageHeartRate == 150)
    }

    @Test func wheelSizeDefaultsAndLimits() throws {
        let defaults = try #require(UserDefaults(suiteName: "wheel-\(UUID().uuidString)"))
        let wheel = WheelSize(defaults: defaults)
        #expect(wheel.millimetres == 2105)
        wheel.millimetres = 2136
        #expect(wheel.metres == 2.136)
        wheel.millimetres = 50
        #expect(wheel.millimetres == 1000)
    }
}
