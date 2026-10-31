import CoreLocation
import Foundation

/// One GPS fix as it goes into the GPX file. Shared by the iPhone and Watch recorders.
struct RidePoint: Codable, Equatable, Sendable {
    var time: Date
    var lat: Double
    var lon: Double
    var ele: Double?
    /// Horizontal accuracy in metres (CLLocation.horizontalAccuracy); used to drop poor fixes, not written to the GPX.
    var accuracy: Double?
    /// m/s as reported by Core Location; nil when the device didn't know.
    var speed: Double?
    /// Beats per minute, from the Watch's heart-rate sensor (or a strap paired with it).
    var hr: Int?
    /// Watts and rpm from a power meter or cadence sensor paired with the Watch (HealthKit's cyclingPower / cyclingCadence).
    var power: Int?
    var cadence: Int?

    init(time: Date, lat: Double, lon: Double, ele: Double? = nil, accuracy: Double? = nil, speed: Double? = nil, hr: Int? = nil,
         power: Int? = nil, cadence: Int? = nil) {
        self.time = time
        self.lat = lat
        self.lon = lon
        self.ele = ele
        self.accuracy = accuracy
        self.speed = speed
        self.hr = hr
        self.power = power
        self.cadence = cadence
    }

    init(_ location: CLLocation, hr: Int? = nil, power: Int? = nil, cadence: Int? = nil) {
        self.init(
            time: location.timestamp,
            lat: location.coordinate.latitude,
            lon: location.coordinate.longitude,
            ele: location.verticalAccuracy >= 0 ? location.altitude : nil,
            accuracy: location.horizontalAccuracy,
            speed: location.speed >= 0 ? location.speed : nil,
            hr: hr,
            power: power,
            cadence: cadence
        )
    }

    var coordinate: CLLocationCoordinate2D { CLLocationCoordinate2D(latitude: lat, longitude: lon) }

    /// Great-circle distance in metres (same formula as the server's services/parser.py _haversine).
    func distance(to other: RidePoint) -> Double {
        let r = 6_371_000.0
        let p1 = lat * .pi / 180, p2 = other.lat * .pi / 180
        let dp = (other.lat - lat) * .pi / 180, dl = (other.lon - lon) * .pi / 180
        let a = sin(dp / 2) * sin(dp / 2) + cos(p1) * cos(p2) * sin(dl / 2) * sin(dl / 2)
        return 2 * r * asin(min(1, sqrt(a)))
    }
}
