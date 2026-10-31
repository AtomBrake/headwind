import Foundation
import Testing
@testable import Headwind

// Byte strings laid out by hand from the Bluetooth SIG's GATT specifications, little-endian as sent.
// Real sensors' captures should be added beside them once there's a device to capture from.

/// "16 3C 00 04" → Data([0x16, 0x3C, 0x00, 0x04]).
private func hex(_ s: String) -> Data {
    Data(s.split(separator: " ").map { UInt8($0, radix: 16)! })
}

struct HeartRateMeasurementTests {
    @Test func eightBitRateWithNothingElse() throws {
        let m = try #require(HeartRateMeasurement(hex("00 48")))
        #expect(m.bpm == 72)
        #expect(m.skinContact == nil)
        #expect(m.energyExpended == nil)
        #expect(m.rrIntervals.isEmpty)
    }

    @Test func contactAndRRIntervals() throws {
        // Flags 0x16: contact supported and detected, RR intervals present. 0x0400 and 0x0200 in 1/1024 s.
        let m = try #require(HeartRateMeasurement(hex("16 3C 00 04 00 02")))
        #expect(m.bpm == 60)
        #expect(m.skinContact == true)
        #expect(m.rrIntervals == [1.0, 0.5])
    }

    @Test func sixteenBitRateAndEnergy() throws {
        let m = try #require(HeartRateMeasurement(hex("09 B4 00 10 27")))
        #expect(m.bpm == 180)
        #expect(m.energyExpended == 10_000)
    }

    @Test func strapNotTouchingSkin() throws {
        #expect(try #require(HeartRateMeasurement(hex("04 50"))).skinContact == false)
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
        #expect(m.wheel == RevolutionData(revolutions: 10_000, eventTime: 2048))
        #expect(m.crank == RevolutionData(revolutions: 42, eventTime: 1024))
    }

    @Test func cadenceSensorAlone() throws {
        let m = try #require(CSCMeasurement(hex("02 2A 00 00 04")))
        #expect(m.wheel == nil)
        #expect(m.crank == RevolutionData(revolutions: 42, eventTime: 1024))
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
        #expect(m.crank == RevolutionData(revolutions: 43, eventTime: 1024))
    }

    @Test func fieldsInSpecOrder() throws {
        // Flags 0x0835: balance, accumulated torque, wheel, crank, accumulated energy.
        let m = try #require(CyclingPowerMeasurement(hex("35 08 2C 01 64 00 01 E8 03 00 00 00 10 05 00 00 08 0A 00")))
        #expect(m.power == 300)
        #expect(m.pedalBalance == 50)
        #expect(m.wheel == RevolutionData(revolutions: 1000, eventTime: 4096))
        #expect(m.crank == RevolutionData(revolutions: 5, eventTime: 2048))
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
        #expect(m.totalDistance == nil && m.heartRate == nil)
    }

    @Test func distanceHeartRateAndTime() throws {
        // Flags 0x0A50: distance (24-bit), power, heart rate, elapsed time.
        let m = try #require(IndoorBikeData(hex("50 0A E8 03 39 30 00 96 00 8C 2C 01")))
        #expect(abs(try #require(m.speed) - 10 / 3.6) < 1e-9)
        #expect(m.totalDistance == 12_345)
        #expect(m.power == 150)
        #expect(m.heartRate == 140)
        #expect(m.elapsedTime == 300)
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
    }

    @Test func truncatedDoesntParse() {
        #expect(IndoorBikeData(hex("44 00 54 0B B4")) == nil)
        #expect(IndoorBikeData(hex("10 00 E8 03 39 30")) == nil)    // distance is three bytes
    }
}

struct BatteryLevelTests {
    @Test func percent() {
        #expect(BatteryLevel.percent(hex("64")) == 100)
        #expect(BatteryLevel.percent(hex("65")) == nil)
        #expect(BatteryLevel.percent(Data()) == nil)
    }

    @Test func uuidStrings() {
        #expect(GATT.uuidString(GATT.heartRateService) == "180D")
        #expect(GATT.uuidString(GATT.indoorBikeData) == "2AD2")
        #expect(GATT.uuidString(0x00AB) == "00AB")
    }
}

struct RevolutionRateTests {
    private func crank(_ revs: UInt32, _ time: UInt16) -> RevolutionData { RevolutionData(revolutions: revs, eventTime: time) }

    @Test func nothingUntilTwoReadings() {
        var r = RevolutionRate.crank()
        #expect(r.rpm(at: 0) == nil)
        r.add(crank(10, 0), at: 0)
        #expect(r.rpm(at: 0.5) == nil)
    }

    @Test func cadenceHoldsThenStops() {
        var r = RevolutionRate.crank()
        r.add(crank(10, 0), at: 0)
        r.add(crank(13, 2048), at: 2)                                 // 3 revolutions in 2 s
        #expect(r.rpm(at: 2) == 90)
        r.add(crank(13, 2048), at: 3)                                 // the same event again: nothing turned
        #expect(r.rpm(at: 3) == 90)
        #expect(r.rpm(at: 5) == 0)                                    // 3 s with no revolution
    }

    @Test func countersWrap() {
        var r = RevolutionRate.crank()
        r.add(crank(65_535, 64_512), at: 0)
        r.add(crank(3, 1536), at: 2.5)                                // 4 revolutions, 2,560 ticks = 2.5 s
        #expect(abs(r.rpm(at: 2.5)! - 96) < 1e-9)

        var w = RevolutionRate.wheel()
        w.add(crank(0xFFFF_FFFE, 0), at: 0)
        w.add(crank(2, 1024), at: 1)
        #expect(w.totalRevolutions == 4)
    }

    @Test func wheelSpeedAndDistance() throws {
        var w = RevolutionRate.wheel()
        w.add(crank(1000, 0), at: 0)
        w.add(crank(1004, 1024), at: 1)
        #expect(abs(try #require(w.speed(at: 1, circumference: 2.105)) - 8.42) < 1e-9)
        w.add(crank(1008, 2048), at: 2)
        #expect(abs(w.distance(circumference: 2.105) - 8 * 2.105) < 1e-9)
    }

    @Test func powerMeterWheelTicksAreFiner() {
        var w = RevolutionRate.wheel(ticksPerSecond: 2048)
        w.add(crank(0, 0), at: 0)
        w.add(crank(4, 2048), at: 1)                                  // 2,048 ticks is 1 s here
        #expect(w.rate(at: 1) == 4)
    }

    @Test func aResetCounterStartsAgain() {
        var r = RevolutionRate.crank()
        r.add(crank(100, 0), at: 0)
        r.add(crank(102, 1024), at: 1)
        #expect(r.rpm(at: 1) == 120)
        r.add(crank(0, 2048), at: 2)                                  // battery changed: 65,434 "revolutions" in 1 s
        #expect(r.rpm(at: 2) == 0)
        #expect(r.totalRevolutions == 2)
        r.add(crank(2, 3072), at: 3)
        #expect(r.rpm(at: 3) == 120)
        #expect(r.totalRevolutions == 4)
    }

    @Test func aLongStopStartsAgain() {
        var r = RevolutionRate.crank()
        r.add(crank(100, 0), at: 0)
        r.add(crank(101, 1024), at: 1)
        r.add(crank(102, 5000), at: 40)                               // the 16-bit clock may have wrapped: unknowable
        #expect(r.rpm(at: 40) == 0)
        #expect(r.totalRevolutions == 1)
        r.add(crank(103, 6024), at: 41)
        #expect(r.rpm(at: 41) == 60)
    }

    @Test func moreRevolutionsAtTheSameInstantAreIgnored() {
        var r = RevolutionRate.crank()
        r.add(crank(10, 1024), at: 0)
        r.add(crank(12, 1024), at: 1)
        #expect(r.rpm(at: 1) == nil)
    }
}
