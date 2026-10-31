import Foundation
import Testing
@testable import Headwind

// The parsing tests of the second version of the sensors (claude/brave-carson-x2cfo5), on this version's types.
// Byte strings laid out by hand from the Bluetooth SIG's GATT specifications, little-endian as sent.

/// "16 3C 00 04" → Data([0x16, 0x3C, 0x00, 0x04]).
private func hex(_ s: String) -> Data {
    Data(s.split(separator: " ").map { UInt8($0, radix: 16)! })
}

private let t0 = Date(timeIntervalSince1970: 1_760_000_000)
private func at(_ s: Double) -> Date { t0.addingTimeInterval(s) }

struct HeartRateMeasurementTests {
    @Test func eightBitRateWithNothingElse() throws {
        let m = try #require(HeartRateMeasurement(hex("00 48")))
        #expect(m.bpm == 72)
        #expect(m.contactDetected == nil)
        #expect(m.energyExpended == nil)
        #expect(m.rrIntervals.isEmpty)
    }

    @Test func contactAndRRIntervals() throws {
        // Flags 0x16: contact supported and detected, RR intervals present. 0x0400 and 0x0200 in 1/1024 s.
        let m = try #require(HeartRateMeasurement(hex("16 3C 00 04 00 02")))
        #expect(m.bpm == 60)
        #expect(m.contactDetected == true)
        #expect(m.rrIntervals == [1.0, 0.5])
    }

    @Test func sixteenBitRateAndEnergy() throws {
        let m = try #require(HeartRateMeasurement(hex("09 B4 00 10 27")))
        #expect(m.bpm == 180)
        #expect(m.energyExpended == 10_000)
    }

    @Test func strapNotTouchingSkin() throws {
        #expect(try #require(HeartRateMeasurement(hex("04 50"))).contactDetected == false)
    }

    @Test func shortValuesDontParse() {
        #expect(HeartRateMeasurement(Data()) == nil)
        #expect(HeartRateMeasurement(hex("01 48")) == nil)          // says 16-bit, sends one byte
        #expect(HeartRateMeasurement(hex("08 48 10")) == nil)       // energy cut short
    }
}

struct CSCMeasurementTests {
    @Test func wheelAndCrank() throws {
        let m = try #require(CSCMeasurement(hex("03 10 27 00 00 00 08 2A 00 00 04")))
        #expect(m.wheel == Revolutions(count: 10_000, eventTime: 2048))
        #expect(m.crank == Revolutions(count: 42, eventTime: 1024))
    }

    @Test func cadenceSensorAlone() throws {
        let m = try #require(CSCMeasurement(hex("02 2A 00 00 04")))
        #expect(m.wheel == nil)
        #expect(m.crank == Revolutions(count: 42, eventTime: 1024))
    }

    @Test func truncatedDoesntParse() {
        #expect(CSCMeasurement(hex("01 10 27 00 00")) == nil)
        #expect(CSCMeasurement(hex("03 10 27 00 00 00 08 2A 00")) == nil)
    }
}

struct CyclingPowerMeasurementTests {
    @Test func powerOnly() throws {
        let m = try #require(CyclingPowerMeasurement(hex("00 00 C8 00")))
        #expect(m.power == 200)
        #expect(m.crank == nil && m.wheel == nil && m.pedalBalance == nil)
    }

    @Test func powerIsSigned() throws {
        #expect(try #require(CyclingPowerMeasurement(hex("00 00 FE FF"))).power == -2)
    }

    @Test func crankDataForCadence() throws {
        let m = try #require(CyclingPowerMeasurement(hex("20 00 FA 00 2B 00 00 04")))
        #expect(m.power == 250)
        #expect(m.crank == Revolutions(count: 43, eventTime: 1024))
    }

    @Test func fieldsInSpecOrder() throws {
        // Flags 0x0835: balance, accumulated torque, wheel, crank, accumulated energy.
        let m = try #require(CyclingPowerMeasurement(hex("35 08 2C 01 64 00 01 E8 03 00 00 00 10 05 00 00 08 0A 00")))
        #expect(m.power == 300)
        #expect(m.pedalBalance == 50)
        #expect(m.wheel == Revolutions(count: 1000, eventTime: 4096))
        #expect(m.crank == Revolutions(count: 5, eventTime: 2048))
        #expect(m.accumulatedEnergy == 10)
    }

    @Test func skipsTheFieldsHeadwindDoesntUse() throws {
        // Flags 0x0FC0: extreme forces (4), torques (4), angles (3), top and bottom dead spots (2 + 2), then energy.
        let m = try #require(CyclingPowerMeasurement(hex("C0 0F 64 00 11 11 22 22 33 33 44 44 55 55 55 66 66 77 77 07 00")))
        #expect(m.power == 100)
        #expect(m.accumulatedEnergy == 7)
    }

    @Test func truncatedDoesntParse() {
        #expect(CyclingPowerMeasurement(hex("00 00 C8")) == nil)
        #expect(CyclingPowerMeasurement(hex("20 00 FA 00 2B 00")) == nil)
    }
}

struct IndoorBikeDataTests {
    @Test func speedCadenceAndPower() throws {
        // Flags 0x0044: cadence and power, and bit 0 clear so speed comes first.
        let m = try #require(IndoorBikeData(hex("44 00 54 0B B4 00 C8 00")))
        #expect(abs(try #require(m.speed) - 29 / 3.6) < 1e-9)
        #expect(m.cadence == 90)
        #expect(m.power == 200)
        #expect(m.distance == nil && m.heartRate == nil)
    }

    @Test func distanceHeartRateAndTime() throws {
        // Flags 0x0A50: distance (24-bit), power, heart rate, elapsed time.
        let m = try #require(IndoorBikeData(hex("50 0A E8 03 39 30 00 96 00 8C 2C 01")))
        #expect(abs(try #require(m.speed) - 10 / 3.6) < 1e-9)
        #expect(m.distance == 12_345)
        #expect(m.power == 150)
        #expect(m.heartRate == 140)
        #expect(m.elapsed == 300)
    }

    @Test func averagesAndRemainingTime() throws {
        // Flags 0x108B: more data (no speed), average speed, average cadence, average power, remaining time.
        let m = try #require(IndoorBikeData(hex("8B 10 B8 0B B4 00 C8 00 58 02")))
        #expect(m.speed == nil)
        #expect(abs(try #require(m.averageSpeed) - 30 / 3.6) < 1e-9)
        #expect(m.averageCadence == 90)
        #expect(m.averagePower == 200)
        #expect(m.remaining == 600)
    }

    @Test func moreDataHasNoSpeed() throws {
        let m = try #require(IndoorBikeData(hex("41 00 C8 00")))
        #expect(m.speed == nil)
        #expect(m.power == 200)
    }

    @Test func energyNotAvailableAndTheFieldsAfterIt() throws {
        // Flags 0x0301: more data, expended energy (all 0xFF: not available), heart rate.
        let m = try #require(IndoorBikeData(hex("01 03 FF FF FF FF FF 78")))
        #expect(m.totalEnergy == nil)
        #expect(m.heartRate == 120)
        #expect(try #require(IndoorBikeData(hex("01 01 2C 01 FF FF FF"))).totalEnergy == 300)
    }

    @Test func truncatedDoesntParse() {
        #expect(IndoorBikeData(hex("44 00 54 0B B4")) == nil)
        #expect(IndoorBikeData(hex("10 00 E8 03 39 30")) == nil)    // distance is three bytes
    }
}

struct BatteryLevelTests {
    @Test func percent() {
        #expect(BatteryLevel.parse(hex("64")) == 100)
        #expect(BatteryLevel.parse(hex("65")) == nil)
        #expect(BatteryLevel.parse(Data()) == nil)
    }

    @Test func uuidStrings() {
        #expect(GATT.uuidString(GATT.heartRateService) == "180D")
        #expect(GATT.uuidString(GATT.indoorBikeData) == "2AD2")
        #expect(GATT.uuidString(0x00AB) == "00AB")
    }
}

/// `RevolutionRate` cases beside the ones in `SensorTests.swift`.
struct RevolutionRateEdgeTests {
    private func revs(_ count: UInt32, _ time: UInt16) -> Revolutions { Revolutions(count: count, eventTime: time) }

    @Test func cadenceHoldsThenStops() {
        var r = RevolutionRate.crank
        r.update(revs(10, 0), at: at(0))
        r.update(revs(13, 2048), at: at(2))                            // 3 revolutions in 2 s
        #expect(r.perSecond(at: at(2)).map { $0 * 60 } == 90)
        r.update(revs(13, 2048), at: at(3))                            // the same event again: nothing turned
        #expect(r.perSecond(at: at(3)).map { $0 * 60 } == 90)
        #expect(r.perSecond(at: at(5)) == 0)                           // 3 s with no revolution
    }

    @Test func countersWrap() throws {
        var r = RevolutionRate.crank
        r.update(revs(65_535, 64_512), at: at(0))
        r.update(revs(3, 1536), at: at(2.5))                           // 4 revolutions, 2,560 ticks = 2.5 s
        #expect(abs(try #require(r.perSecond(at: at(2.5))) * 60 - 96) < 1e-9)

        var w = RevolutionRate.wheel()
        w.update(revs(0xFFFF_FFFE, 0), at: at(0))
        w.update(revs(2, 1024), at: at(1))
        #expect(w.revolutions == 4)
    }

    @Test func wheelSpeedAndDistance() throws {
        var w = RevolutionRate.wheel()
        w.update(revs(1000, 0), at: at(0))
        w.update(revs(1004, 1024), at: at(1))
        #expect(abs(try #require(w.perSecond(at: at(1))) * 2.105 - 8.42) < 1e-9)
        w.update(revs(1008, 2048), at: at(2))
        #expect(abs(Double(w.revolutions) * 2.105 - 8 * 2.105) < 1e-9)
    }

    @Test func powerMeterWheelTicksAreFiner() {
        var w = RevolutionRate.wheel(ticksPerSecond: 2048)
        w.update(revs(0, 0), at: at(0))
        w.update(revs(4, 2048), at: at(1))                             // 2,048 ticks is 1 s here
        #expect(w.perSecond(at: at(1)) == 4)
    }

    @Test func aResetCounterStartsAgain() {
        var r = RevolutionRate.crank
        r.update(revs(100, 0), at: at(0))
        r.update(revs(102, 1024), at: at(1))
        #expect(r.perSecond(at: at(1)).map { $0 * 60 } == 120)
        r.update(revs(0, 2048), at: at(2))                             // battery changed: 65,434 "revolutions" in 1 s
        #expect(r.perSecond(at: at(2)) == 0)
        #expect(r.revolutions == 2)
        r.update(revs(2, 3072), at: at(3))
        #expect(r.perSecond(at: at(3)).map { $0 * 60 } == 120)
        #expect(r.revolutions == 4)
    }

    @Test func aLongStopStartsAgain() {
        var r = RevolutionRate.crank
        r.update(revs(100, 0), at: at(0))
        r.update(revs(101, 1024), at: at(1))
        #expect(r.perSecond(at: at(1)).map { $0 * 60 } == 60)
        // Over a minute later: the 16-bit clock may have wrapped, so the time between can't be known. The revolution counts; no rate yet,
        // and not the cadence from before the stop.
        r.update(revs(102, 5000), at: at(71))
        #expect(r.perSecond(at: at(71)) == 0)
        #expect(r.revolutions == 2)
        r.update(revs(103, 6024), at: at(72))
        #expect(r.perSecond(at: at(72)).map { $0 * 60 } == 60)
    }

    @Test func moreRevolutionsAtTheSameInstantGiveNoRate() {
        var r = RevolutionRate.crank
        r.update(revs(10, 1024), at: at(0))
        r.update(revs(12, 1024), at: at(1))
        #expect(r.perSecond(at: at(1)) == 0)
    }
}

struct SensorKindAndServiceTests {
    @Test func kindsFromServices() {
        #expect(SensorKind.kinds(of: [0x1826, 0x1818, 0x180F, 0x180A]) == [.trainer, .power])
        #expect(SensorKind(service: GATT.heartRateService) == .heartRate)
        #expect(SensorKind(service: GATT.batteryService) == nil)
        for kind in SensorKind.allCases { #expect(SensorKind(service: kind.service) == kind) }
    }

    @Test func whatIsReadOnEachService() {
        #expect(GATT.characteristics(toRead: GATT.cyclingPowerService, onTrainer: false) == [GATT.cyclingPowerMeasurement])
        #expect(GATT.characteristics(toRead: GATT.cyclingPowerService, onTrainer: true) == nil)
        #expect(GATT.characteristics(toRead: GATT.cyclingSpeedCadenceService, onTrainer: false) == [GATT.cscMeasurement])
        #expect(GATT.characteristics(toRead: GATT.cyclingSpeedCadenceService, onTrainer: true) == nil)
        #expect(GATT.characteristics(toRead: GATT.fitnessMachineService, onTrainer: true) == [GATT.indoorBikeData])
        #expect(GATT.characteristics(toRead: GATT.heartRateService, onTrainer: true) == [GATT.heartRateMeasurement])
        #expect(GATT.characteristics(toRead: GATT.batteryService, onTrainer: false) == [GATT.batteryLevel])
        #expect(GATT.characteristics(toRead: 0x180A, onTrainer: false) == nil)
    }
}
