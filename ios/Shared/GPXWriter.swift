import Foundation

/// Writes a recording as GPX 1.1 in the shape services/parser.py reads: one <trk> whose type is the sport's
/// (Sport.gpxType, e.g. "cycling", mapped to Ride), a <trkseg> per stretch between pauses, heart rate and cadence in the Garmin
/// TrackPointExtension and power as <power> beside it (the parser looks for any element named "hr", "cad" and "power").
enum GPXWriter {
    static func gpx(segments: [[RidePoint]], name: String, type: String = "cycling", creator: String = "Headwind iOS") -> Data {
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime]
        let first = segments.lazy.flatMap { $0 }.first

        var out = """
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" creator="\(escape(creator))" xmlns="http://www.topografix.com/GPX/1/1" \
        xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">

        """
        if let first {
            out += "  <metadata><time>\(iso.string(from: first.time))</time></metadata>\n"
        }
        out += "  <trk>\n    <name>\(escape(name))</name>\n    <type>\(escape(type))</type>\n"
        for segment in segments where !segment.isEmpty {
            out += "    <trkseg>\n"
            for p in segment {
                out += "      <trkpt lat=\"\(coordinate(p.lat))\" lon=\"\(coordinate(p.lon))\">"
                if let ele = p.ele { out += "<ele>\(String(format: "%.1f", ele))</ele>" }
                out += "<time>\(iso.string(from: p.time))</time>"
                if p.hr != nil || p.power != nil || p.cadence != nil {
                    out += "<extensions>"
                    if let power = p.power { out += "<power>\(power)</power>" }
                    if p.hr != nil || p.cadence != nil {
                        out += "<gpxtpx:TrackPointExtension>"
                        if let hr = p.hr { out += "<gpxtpx:hr>\(hr)</gpxtpx:hr>" }
                        if let cad = p.cadence { out += "<gpxtpx:cad>\(cad)</gpxtpx:cad>" }
                        out += "</gpxtpx:TrackPointExtension>"
                    }
                    out += "</extensions>"
                }
                out += "</trkpt>\n"
            }
            out += "    </trkseg>\n"
        }
        out += "  </trk>\n</gpx>\n"
        return Data(out.utf8)
    }

    /// A finished recording, named and typed by its sport.
    static func gpx(segments: [[RidePoint]], summary: RideSummary, creator: String = "Headwind iOS") -> Data {
        gpx(segments: segments, name: rideName(summary), type: summary.sport.gpxType, creator: creator)
    }

    /// "Morning Ride", "Evening Run"… from the local start time, like the names Headwind gives imported rides.
    static func rideName(start: Date, sport: Sport = .ride, calendar: Calendar = .current) -> String {
        let time = switch calendar.component(.hour, from: start) {
        case 5..<12: "Morning"
        case 12..<17: "Afternoon"
        case 17..<21: "Evening"
        default: "Night"
        }
        return "\(time) \(sport.nameWord)"
    }

    static func rideName(_ summary: RideSummary) -> String { rideName(start: summary.start, sport: summary.sport) }

    private static func coordinate(_ value: Double) -> String {
        String(format: "%.7f", value)
    }

    private static func escape(_ s: String) -> String {
        s.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
            .replacingOccurrences(of: "\"", with: "&quot;")
    }
}
