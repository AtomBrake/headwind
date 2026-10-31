import Foundation
import Testing
@testable import Headwind

// The combining tests of the second version of the sensors (claude/brave-carson-x2cfo5, its `SensorHub` and `SensorTally`), on this
// version's types: a `Bench` of sensors, each a `SensorChannel` of a kind, read together as `SensorManager.readings` does, and a
// `DistanceFollower` for the distance ridden while recording. Notifications are built from their GATT layouts.

private let strap = UUID(uuidString: "00000000-0000-0000-0000-00000000000A")!
private let pedals = UUID(uuidString: "00000000-0000-0000-0000-00000000000B")!
private let cadenceSensor = UUID(uuidString: "00000000-0000-0000-0000-00000000000C")!
private let trainer = UUID(uuidString: "00000000-0000-0000-0000-00000000000D")!

private let t0 = Date(timeIntervalSince1970: 1_760_000_000)
private func at(_ s: Double) -> Date { t0.addingTimeInterval(s) }

private func le16(_ v: Int) -> [UInt8] { [UInt8(v & 0xFF), UInt8((v >> 8) & 0xFF)] }
private func le24(_ v: Int) -> [UInt8] { le16(v) + [UInt8((v >> 16) & 0xFF)] }
private func le32(_ v: Int) -> [UInt8] { le24(v) + [UInt8((v >> 24) & 0xFF)] }

private func heartRate(_ bpm: Int, contact: Bool? = nil) -> Data {
    let flags: UInt8 = contact.map { $0 ? 0x06 : 0x04 } ?? 0x00
    return Data([flags, UInt8(bpm)])
}

private func csc(wheel: (revs: Int, time: Int)? = nil, crank: (revs: Int, time: Int)? = nil) -> Data {
    var bytes: [UInt8] = [(wheel != nil ? 0x01 : 0) | (crank != nil ? 0x02 : 0)]
    if let wheel { bytes += le32(wheel.revs) + le16(wheel.time & 0xFFFF) }
    if let crank { bytes += le16(crank.revs) + le16(crank.time & 0xFFFF) }
    return Data(bytes)
}

private func power(_ watts: Int, crank: (revs: Int, time: Int)? = nil) -> Data {
    var bytes = le16(crank != nil ? 0x20 : 0) + le16(watts)
    if let crank { bytes += le16(crank.revs) + le16(crank.time) }
    return Data(bytes)
}

/// Indoor Bike Data with the fields given; speed in km/h, cadence in rpm, distance in metres.
private func bike(speed: Double? = nil, cadence: Double? = nil, distance: Int? = nil, power: Int? = nil, hr: Int? = nil) -> Data {
    var flags = speed == nil ? 0x0001 : 0                    // bit 0 set: no instantaneous speed
    var fields: [UInt8] = []
    if let speed { fields += le16(Int((speed * 100).rounded())) }
    if let cadence { flags |= 1 << 2; fields += le16(Int(cadence * 2)) }
    if let distance { flags |= 1 << 4; fields += le24(distance) }
    if let power { flags |= 1 << 6; fields += le16(power) }
    if let hr { flags |= 1 << 9; fields.append(UInt8(hr)) }
    return Data(le16(flags) + fields)
}

/// Paired sensors without Bluetooth: what `SensorManager` keeps per sensor, read the way it reads them.
private struct Bench {
    static let kinds: [UUID: SensorKind] = [strap: .heartRate, pedals: .power, cadenceSensor: .speedCadence, trainer: .trainer]
    var wheel = 2.105
    private var channels: [UUID: SensorChannel] = [:]

    mutating func send(_ data: Data, as characteristic: UInt16, from sensor: UUID, at s: Double) {
        var channel = channels[sensor] ?? SensorChannel()
        channel.receive(characteristic, data, at: at(s))
        channels[sensor] = channel
    }

    mutating func heartRate(_ data: Data, from sensor: UUID = strap, at s: Double) { send(data, as: GATT.heartRateMeasurement, from: sensor, at: s) }
    mutating func csc(_ data: Data, from sensor: UUID = cadenceSensor, at s: Double) { send(data, as: GATT.cscMeasurement, from: sensor, at: s) }
    mutating func power(_ data: Data, from sensor: UUID = pedals, at s: Double) { send(data, as: GATT.cyclingPowerMeasurement, from: sensor, at: s) }
    mutating func bike(_ data: Data, from sensor: UUID = trainer, at s: Double) { send(data, as: GATT.indoorBikeData, from: sensor, at: s) }

    func readings(at s: Double) -> SensorReadings {
        SensorReadings.combine(channels.map { id, channel in
            .init(kind: Self.kinds[id]!, id: id, readings: channel.readings(at: at(s), wheelCircumference: wheel))
        })
    }

    func readings(of sensor: UUID, at s: Double) -> SensorReadings? {
        channels[sensor]?.readings(at: at(s), wheelCircumference: wheel)
    }
}

struct BenchHeartRateTests {
    @Test func latestUntilTheStrapGoesQuiet() {
        var bench = Bench()
        #expect(bench.readings(at: 0).isEmpty)
        bench.heartRate(heartRate(140), at: 10)
        bench.heartRate(heartRate(142), at: 11)
        #expect(bench.readings(at: 11).heartRate == 142)
        #expect(bench.readings(at: 15.9).heartRate == 142)
        #expect(bench.readings(at: 16.5).heartRate == nil)            // over 5 s without a word
    }

    @Test func offTheSkinIsIgnored() {
        var bench = Bench()
        bench.heartRate(heartRate(140, contact: true), at: 0)
        bench.heartRate(heartRate(0, contact: false), at: 1)
        #expect(bench.readings(at: 1).heartRate == 140)
    }

    @Test func aStrapBeforeTheTrainersOwn() {
        var bench = Bench()
        bench.bike(bike(speed: 30, hr: 120), at: 0)
        #expect(bench.readings(at: 0).heartRate == 120)
        bench.heartRate(heartRate(150), at: 0.5)
        #expect(bench.readings(at: 1).heartRate == 150)
    }
}

struct BenchPowerTests {
    @Test func averagedOverThreeSeconds() {
        var bench = Bench()
        bench.power(power(100), at: 0)
        bench.power(power(200), at: 1)
        bench.power(power(300), at: 2)
        #expect(bench.readings(at: 2).power == 200)
        #expect(bench.readings(at: 3.5).power == 250)                 // the reading at 0 is over 3 s old
        bench.power(power(0), at: 4)                                  // coasting counts: (200 + 300 + 0) / 3
        #expect(bench.readings(at: 4).power == 167)
    }

    @Test func aMeterSendingLessOftenGivesItsLatest() {
        var bench = Bench()
        bench.power(power(180), at: 0)
        #expect(bench.readings(at: 4).power == 180)
        #expect(bench.readings(at: 5.5).power == nil)
    }

    @Test func backPedallingIsZero() {
        var bench = Bench()
        bench.power(power(-3), at: 0)
        #expect(bench.readings(at: 0).power == 0)
    }

    @Test func aPowerMeterBeforeTheTrainer() {
        var bench = Bench()
        bench.bike(bike(speed: 30, power: 250), at: 0)
        #expect(bench.readings(at: 0).power == 250)
        bench.power(power(240), at: 0.5)
        #expect(bench.readings(at: 1).power == 240)
        #expect(bench.readings(at: 6).power == nil)                   // both quiet
    }

    @Test func theTrainerOnceTheMeterGoesQuiet() {
        var bench = Bench()
        bench.power(power(240), at: 0)
        for t in 1...8 { bench.bike(bike(speed: 30, power: 250), at: Double(t)) }
        #expect(bench.readings(at: 8).power == 250)
    }
}

struct BenchCadenceTests {
    @Test func fromCrankRevolutions() {
        var bench = Bench()
        bench.csc(csc(crank: (10, 0)), at: 0)
        #expect(bench.readings(at: 0).cadence == 0)                   // one reading gives no rate yet
        bench.csc(csc(crank: (11, 640)), at: 0.7)                     // one turn in 0.625 s
        #expect(bench.readings(at: 1).cadence == 96)
        #expect(bench.readings(at: 4).cadence == 0)                   // nothing turned for 3 s
    }

    @Test func aCadenceSensorBeforeAPowerMetersAndTheTrainers() {
        var bench = Bench()
        bench.bike(bike(speed: 30, cadence: 70), at: 0)
        #expect(bench.readings(at: 0).cadence == 70)
        bench.power(power(200, crank: (0, 0)), at: 0)
        bench.power(power(200, crank: (1, 768)), at: 0.75)            // 80 rpm
        #expect(bench.readings(at: 1).cadence == 80)
        bench.csc(csc(crank: (0, 0)), at: 0)
        bench.csc(csc(crank: (1, 683)), at: 0.7)                      // ~90 rpm
        #expect(bench.readings(at: 1).cadence == 90)
    }
}

struct BenchSpeedAndDistanceTests {
    @Test func fromAWheelSensor() throws {
        var bench = Bench()
        bench.csc(csc(wheel: (100, 0)), at: 0)
        #expect(bench.readings(at: 0).distance == 0)
        bench.csc(csc(wheel: (110, 2048)), at: 2)                     // 10 turns in 2 s
        let r = bench.readings(at: 2)
        #expect(abs(try #require(r.speed) - 5 * 2.105) < 1e-9)
        #expect(abs(try #require(r.distance) - 10 * 2.105) < 1e-9)
        #expect(r.distanceSource == cadenceSensor)
    }

    @Test func theWheelCircumferenceCounts() {
        var bench = Bench()
        bench.wheel = 2
        bench.csc(csc(wheel: (0, 0)), at: 0)
        bench.csc(csc(wheel: (5, 1024)), at: 1)
        #expect(bench.readings(at: 1).speed == 10)
        #expect(bench.readings(at: 1).distance == 10)
    }

    @Test func fromATrainer() throws {
        var bench = Bench()
        bench.bike(bike(speed: 36, distance: 1000), at: 0)
        #expect(bench.readings(at: 0).distance == 0)                  // the trainer's own count so far isn't this ride's
        bench.bike(bike(speed: 36, distance: 1010), at: 1)
        let r = bench.readings(at: 1)
        #expect(abs(try #require(r.speed) - 10) < 1e-9)
        #expect(r.distance == 10)
    }

    @Test func aTrainerStartingAgainCountsOnFromItsNewValue() {
        var bench = Bench()
        var ridden = DistanceFollower()
        for (t, metres) in [500, 510, 2, 12, 90_000, 90_008].enumerated() {
            bench.bike(bike(distance: metres), at: Double(t))           // restarted at 2 s; garbled at 4 s (90 km in a second)
            ridden.update(bench.readings(at: Double(t)))
        }
        #expect(ridden.total == 28)
    }

    @Test func aTrainerAndAWheelSensorDontAddUp() {
        var bench = Bench()
        bench.wheel = 2
        var ridden = DistanceFollower()
        for t in 0...4 {
            bench.bike(bike(speed: 36, distance: 10 * t), at: Double(t))
            bench.csc(csc(wheel: (5 * t, 1024 * t)), at: Double(t))
            ridden.update(bench.readings(at: Double(t)))
        }
        #expect(ridden.total == 40)                                   // the trainer's alone
        #expect(abs(bench.readings(at: 4).speed! - 10) < 1e-9)
        // The trainer drops out: once it's quiet for 5 s the wheel sensor counts.
        for t in 5...14 {
            bench.csc(csc(wheel: (5 * t, 1024 * t)), at: Double(t))
            ridden.update(bench.readings(at: Double(t)))
        }
        #expect(ridden.total == 90)                                   // and seconds 10 to 14 at 10 m a second
    }

    @Test func distanceCarriesOnThroughAQuietSpell() {
        var bench = Bench()
        var ridden = DistanceFollower()
        bench.bike(bike(speed: 36, cadence: 90, distance: 0, power: 200), at: 0)
        ridden.update(bench.readings(at: 0))
        bench.bike(bike(speed: 36, cadence: 90, distance: 10, power: 200), at: 1)
        ridden.update(bench.readings(at: 1))
        ridden.update(bench.readings(at: 3))                           // nothing new: the trainer has dropped
        let quiet = bench.readings(at: 6.5)
        #expect(quiet.power == nil && quiet.cadence == nil && quiet.speed == nil)
        bench.bike(bike(speed: 36, distance: 40), at: 7)               // back, having kept count
        ridden.update(bench.readings(at: 7))
        #expect(bench.readings(at: 7).distance == 40)
        #expect(ridden.total == 40)
    }
}

struct BenchPerSensorTests {
    @Test func oneSensorsReadings() {
        var bench = Bench()
        bench.heartRate(heartRate(130), at: 0)
        bench.power(power(210), at: 0)
        #expect(bench.readings(of: strap, at: 0) == SensorReadings(heartRate: 130))
        #expect(bench.readings(of: pedals, at: 0) == SensorReadings(power: 210))
        #expect(bench.readings(at: 0) == SensorReadings(heartRate: 130, power: 210))
    }
}

/// What the second version's `SensorTally` did, by `DistanceFollower`.
struct DistanceWhileRecordingTests {
    @Test func distanceOnlyWhileCounting() {
        var ridden = DistanceFollower()
        ridden.update(SensorReadings(distance: 500, distanceSource: trainer))   // where it stood at Start
        ridden.update(SensorReadings(distance: 520, distanceSource: trainer))
        ridden.pause()
        ridden.update(SensorReadings(distance: 530, distanceSource: trainer))   // the first reading after resuming
        ridden.update(SensorReadings(distance: 545, distanceSource: trainer))
        #expect(ridden.total == 35)
    }

    @Test func aDistanceAppearingMidRideStartsFromThere() {
        var ridden = DistanceFollower()
        #expect(ridden.update(SensorReadings(heartRate: 120)) == nil)
        #expect(ridden.update(SensorReadings(heartRate: 121, distance: 3000, distanceSource: trainer)) == 0)
        // The trainer drops out for a moment: what it counted meanwhile isn't added, the count starts again from its next reading.
        ridden.update(SensorReadings(heartRate: 122))
        ridden.update(SensorReadings(distance: 3010, distanceSource: trainer))
        #expect(ridden.update(SensorReadings(distance: 3015, distanceSource: trainer)) == 5)
    }
}
