import Foundation
import Testing
@testable import Headwind

// SensorHub, SensorTally and PairedSensors: what the sensor manager does with parsed notifications, without CoreBluetooth.
// Notifications are built from their GATT layouts (little-endian, fields present by their flag bits).

private let strap = UUID(uuidString: "00000000-0000-0000-0000-00000000000A")!
private let pedals = UUID(uuidString: "00000000-0000-0000-0000-00000000000B")!
private let cadenceSensor = UUID(uuidString: "00000000-0000-0000-0000-00000000000C")!
private let trainer = UUID(uuidString: "00000000-0000-0000-0000-00000000000D")!

private func le16(_ v: Int) -> [UInt8] { [UInt8(v & 0xFF), UInt8((v >> 8) & 0xFF)] }
private func le24(_ v: Int) -> [UInt8] { le16(v) + [UInt8((v >> 16) & 0xFF)] }
private func le32(_ v: Int) -> [UInt8] { le24(v) + [UInt8((v >> 24) & 0xFF)] }

private func heartRate(_ bpm: Int, contact: Bool? = nil) -> HeartRateMeasurement {
    let flags: UInt8 = contact.map { $0 ? 0x06 : 0x04 } ?? 0x00
    return HeartRateMeasurement(Data([flags, UInt8(bpm)]))!
}

private func csc(wheel: (revs: Int, time: Int)? = nil, crank: (revs: Int, time: Int)? = nil) -> CSCMeasurement {
    var bytes: [UInt8] = [(wheel != nil ? 0x01 : 0) | (crank != nil ? 0x02 : 0)]
    if let wheel { bytes += le32(wheel.revs) + le16(wheel.time) }
    if let crank { bytes += le16(crank.revs) + le16(crank.time) }
    return CSCMeasurement(Data(bytes))!
}

private func power(_ watts: Int, crank: (revs: Int, time: Int)? = nil) -> CyclingPowerMeasurement {
    var bytes = le16(crank != nil ? 0x20 : 0) + le16(watts)
    if let crank { bytes += le16(crank.revs) + le16(crank.time) }
    return CyclingPowerMeasurement(Data(bytes))!
}

/// Indoor Bike Data with the fields given; speed in km/h, cadence in rpm, distance in metres.
private func bike(speed: Double? = nil, cadence: Double? = nil, distance: Int? = nil, power: Int? = nil, hr: Int? = nil) -> IndoorBikeData {
    var flags = speed == nil ? 0x0001 : 0                    // bit 0 set: no instantaneous speed
    var fields: [UInt8] = []
    if let speed { fields += le16(Int((speed * 100).rounded())) }
    if let cadence { flags |= 1 << 2; fields += le16(Int(cadence * 2)) }
    if let distance { flags |= 1 << 4; fields += le24(distance) }
    if let power { flags |= 1 << 6; fields += le16(power) }
    if let hr { flags |= 1 << 9; fields.append(UInt8(hr)) }
    return IndoorBikeData(Data(le16(flags) + fields))!
}

struct SensorHubHeartRateTests {
    @Test func latestUntilTheStrapGoesQuiet() {
        var hub = SensorHub()
        #expect(hub.readings(at: 0) == .none)
        hub.add(heartRate(140), from: strap, at: 10)
        hub.add(heartRate(142), from: strap, at: 11)
        #expect(hub.readings(at: 11).heartRate == 142)
        #expect(hub.readings(at: 16).heartRate == 142)
        #expect(hub.readings(at: 16.5).heartRate == nil)           // over 5 s without a word
    }

    @Test func offTheSkinIsIgnored() {
        var hub = SensorHub()
        hub.add(heartRate(140, contact: true), from: strap, at: 0)
        hub.add(heartRate(0, contact: false), from: strap, at: 1)
        #expect(hub.readings(at: 1).heartRate == 140)
    }

    @Test func aStrapBeforeTheTrainersOwn() {
        var hub = SensorHub()
        hub.add(bike(speed: 30, hr: 120), from: trainer, at: 0)
        #expect(hub.readings(at: 0).heartRate == 120)
        hub.add(heartRate(150), from: strap, at: 0.5)
        #expect(hub.readings(at: 1).heartRate == 150)
    }
}

struct SensorHubPowerTests {
    @Test func averagedOverThreeSeconds() {
        var hub = SensorHub()
        hub.add(power(100), from: pedals, at: 0)
        hub.add(power(200), from: pedals, at: 1)
        hub.add(power(300), from: pedals, at: 2)
        #expect(hub.readings(at: 2).power == 200)
        #expect(hub.readings(at: 3.5).power == 250)                 // the reading at 0 is over 3 s old
        hub.add(power(0), from: pedals, at: 4)                      // coasting counts
        #expect(hub.readings(at: 4).power == 150)
    }

    @Test func aMeterSendingLessOftenGivesItsLatest() {
        var hub = SensorHub()
        hub.add(power(180), from: pedals, at: 0)
        #expect(hub.readings(at: 4).power == 180)
        #expect(hub.readings(at: 5.5).power == nil)
    }

    @Test func backPedallingIsZero() {
        var hub = SensorHub()
        hub.add(power(-3), from: pedals, at: 0)
        #expect(hub.readings(at: 0).power == 0)
    }

    @Test func aPowerMeterBeforeTheTrainer() {
        var hub = SensorHub()
        hub.add(bike(speed: 30, power: 250), from: trainer, at: 0)
        #expect(hub.readings(at: 0).power == 250)
        hub.add(power(240), from: pedals, at: 0.5)
        #expect(hub.readings(at: 1).power == 240)
        #expect(hub.readings(at: 6).power == nil)                   // both quiet
    }

    @Test func theTrainerOnceTheMeterGoesQuiet() {
        var hub = SensorHub()
        hub.add(power(240), from: pedals, at: 0)
        for t in 1...8 { hub.add(bike(speed: 30, power: 250), from: trainer, at: Double(t)) }
        #expect(hub.readings(at: 8).power == 250)
    }
}

struct SensorHubCadenceTests {
    @Test func fromCrankRevolutions() {
        var hub = SensorHub()
        hub.add(csc(crank: (10, 0)), from: cadenceSensor, at: 0)
        #expect(hub.readings(at: 0).cadence == nil)                 // one reading gives no rate
        hub.add(csc(crank: (11, 640)), from: cadenceSensor, at: 0.7)  // one turn in 0.625 s
        #expect(hub.readings(at: 1).cadence == 96)
        #expect(hub.readings(at: 4).cadence == 0)                   // nothing turned for 3 s
    }

    @Test func aCadenceSensorBeforeAPowerMetersAndTheTrainers() {
        var hub = SensorHub()
        hub.add(bike(speed: 30, cadence: 70), from: trainer, at: 0)
        #expect(hub.readings(at: 0).cadence == 70)
        hub.add(power(200, crank: (0, 0)), from: pedals, at: 0)
        hub.add(power(200, crank: (1, 768)), from: pedals, at: 0.75)  // 80 rpm
        #expect(hub.readings(at: 1).cadence == 80)
        hub.add(csc(crank: (0, 0)), from: cadenceSensor, at: 0)
        hub.add(csc(crank: (1, 683)), from: cadenceSensor, at: 0.7)   // ~90 rpm
        #expect(hub.readings(at: 1).cadence == 90)
    }
}

struct SensorHubSpeedAndDistanceTests {
    @Test func fromAWheelSensor() throws {
        var hub = SensorHub()
        hub.add(csc(wheel: (100, 0)), from: cadenceSensor, at: 0)
        #expect(hub.readings(at: 0).distance == 0)
        hub.add(csc(wheel: (110, 2048)), from: cadenceSensor, at: 2)  // 10 turns in 2 s
        let r = hub.readings(at: 2)
        #expect(abs(try #require(r.speed) - 5 * 2.105) < 1e-9)
        #expect(abs(try #require(r.distance) - 10 * 2.105) < 1e-9)
    }

    @Test func theWheelCircumferenceCounts() throws {
        var hub = SensorHub()
        hub.wheelCircumference = 2
        hub.add(csc(wheel: (0, 0)), from: cadenceSensor, at: 0)
        hub.add(csc(wheel: (5, 1024)), from: cadenceSensor, at: 1)
        #expect(hub.readings(at: 1).speed == 10)
        #expect(hub.readings(at: 1).distance == 10)
    }

    @Test func fromATrainer() throws {
        var hub = SensorHub()
        hub.add(bike(speed: 36, distance: 1000), from: trainer, at: 0)
        #expect(hub.readings(at: 0).distance == 0)                  // the trainer's own count so far isn't this ride's
        hub.add(bike(speed: 36, distance: 1010), from: trainer, at: 1)
        let r = hub.readings(at: 1)
        #expect(abs(try #require(r.speed) - 10) < 1e-9)
        #expect(r.distance == 10)
    }

    @Test func aTrainerStartingAgainCountsOnFromItsNewValue() {
        var hub = SensorHub()
        hub.add(bike(distance: 500), from: trainer, at: 0)
        hub.add(bike(distance: 510), from: trainer, at: 1)
        hub.add(bike(distance: 2), from: trainer, at: 2)            // the trainer restarted its session
        hub.add(bike(distance: 12), from: trainer, at: 3)
        hub.add(bike(distance: 90_000), from: trainer, at: 4)       // garbled: 90 km in a second
        hub.add(bike(distance: 90_008), from: trainer, at: 5)
        #expect(hub.readings(at: 5).distance == 28)
    }

    @Test func aTrainerAndAWheelSensorDontAddUp() {
        var hub = SensorHub()
        hub.wheelCircumference = 2
        for t in 0...4 {
            hub.add(bike(speed: 36, distance: 10 * t), from: trainer, at: Double(t))
            hub.add(csc(wheel: (5 * t, 1024 * t)), from: cadenceSensor, at: Double(t))
        }
        #expect(hub.readings(at: 4).distance == 40)                 // the trainer's alone
        #expect(abs(hub.readings(at: 4).speed! - 10) < 1e-9)
        // The trainer drops out: once it's quiet for 5 s the wheel sensor counts.
        for t in 5...14 { hub.add(csc(wheel: (5 * t, 1024 * t)), from: cadenceSensor, at: Double(t)) }
        #expect(hub.readings(at: 14).distance == 90)                // and seconds 10 to 14 at 10 m a second
    }

    @Test func distanceStaysThroughADisconnection() {
        var hub = SensorHub()
        hub.add(bike(speed: 36, cadence: 90, distance: 0, power: 200), from: trainer, at: 0)
        hub.add(bike(speed: 36, cadence: 90, distance: 10, power: 200), from: trainer, at: 1)
        hub.disconnected(trainer)
        let r = hub.readings(at: 1)
        #expect(r.power == nil && r.cadence == nil && r.speed == nil)
        #expect(r.distance == 10)
        hub.add(bike(speed: 36, distance: 40), from: trainer, at: 4)  // ridden on meanwhile, and the trainer kept count
        #expect(hub.readings(at: 4).distance == 40)
    }
}

struct SensorHubPerSensorTests {
    @Test func oneSensorsReadings() {
        var hub = SensorHub()
        hub.add(heartRate(130), from: strap, at: 0)
        hub.add(power(210), from: pedals, at: 0)
        #expect(hub.readings(at: 0, of: strap) == SensorReadings(heartRate: 130))
        #expect(hub.readings(at: 0, of: pedals) == SensorReadings(power: 210))
        #expect(hub.readings(at: 0) == SensorReadings(heartRate: 130, power: 210))
    }
}

struct SensorTallyTests {
    @Test func distanceOnlyWhileCounting() {
        var tally = SensorTally()
        tally.update(SensorReadings(distance: 500), counting: true)   // where it stood at Start
        tally.update(SensorReadings(distance: 520), counting: true)
        tally.update(SensorReadings(distance: 530), counting: false)  // paused
        tally.update(SensorReadings(distance: 545), counting: true)
        #expect(tally.distance == 35)
        #expect(tally.latest.distance == 545)
    }

    @Test func aDistanceAppearingMidRideStartsFromThere() {
        var tally = SensorTally()
        tally.update(SensorReadings(heartRate: 120), counting: true)
        tally.update(SensorReadings(heartRate: 121, distance: 3000), counting: true)
        tally.update(SensorReadings(heartRate: 122), counting: true)  // the trainer dropped out for a moment
        tally.update(SensorReadings(distance: 3010), counting: true)
        #expect(tally.distance == 10)
        #expect(tally.latest.heartRate == nil)
    }
}

struct PairedSensorsTests {
    private func store() -> PairedSensors {
        let name = "PairedSensorsTests-\(UUID())"
        let defaults = UserDefaults(suiteName: name)!
        defaults.removePersistentDomain(forName: name)
        return PairedSensors(defaults: defaults)
    }

    @Test func rememberUpdateAndForget() {
        let paired = store()
        #expect(paired.all.isEmpty)
        paired.remember(PairedSensor(id: strap, name: "HRM-Pro", kinds: [.heartRate]))
        paired.remember(PairedSensor(id: trainer, name: "KICKR", kinds: [.trainer]))
        paired.remember(PairedSensor(id: strap, name: "HRM-Pro", kinds: [.heartRate, .speedCadence]))
        #expect(paired.all.map(\.id) == [strap, trainer])
        #expect(paired.all.first?.kinds == [.heartRate, .speedCadence])
        paired.forget(strap)
        #expect(paired.all.map(\.name) == ["KICKR"])
    }

    @Test func kindsFromServices() {
        #expect(SensorKind.kinds(of: [0x1826, 0x1818, 0x180F, 0x180A]) == [.trainer, .power])
        #expect(SensorKind(service: GATT.heartRateService) == .heartRate)
        for kind in SensorKind.allCases { #expect(SensorKind(service: kind.service) == kind) }
    }

    @Test func whatIsReadOnEachService() {
        #expect(GATT.characteristics(toRead: GATT.cyclingPowerService, onTrainer: false) == [GATT.cyclingPowerMeasurement])
        #expect(GATT.characteristics(toRead: GATT.cyclingPowerService, onTrainer: true) == nil)
        #expect(GATT.characteristics(toRead: GATT.cyclingSpeedAndCadenceService, onTrainer: true) == nil)
        #expect(GATT.characteristics(toRead: GATT.fitnessMachineService, onTrainer: true) == [GATT.indoorBikeData])
        #expect(GATT.characteristics(toRead: GATT.heartRateService, onTrainer: true) == [GATT.heartRateMeasurement])
        #expect(GATT.characteristics(toRead: GATT.batteryService, onTrainer: false) == [GATT.batteryLevel])
        #expect(GATT.characteristics(toRead: 0x180A, onTrainer: false) == nil)
    }
}
