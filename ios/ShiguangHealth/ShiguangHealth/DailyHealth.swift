import Foundation

struct DailyHealth: Identifiable, Codable, Hashable {
    let day: Date
    var steps: Int?
    var sleepMinutes: Int?
    var restingHeartRate: Double?
    var activeEnergy: Double?
    var weight: Double?

    var id: Date { day }
    static let dayFormatter: DateFormatter = {
        let value = DateFormatter()
        value.calendar = Calendar(identifier: .gregorian)
        value.locale = Locale(identifier: "en_US_POSIX")
        value.dateFormat = "yyyy-MM-dd"
        return value
    }()
    var dayText: String { Self.dayFormatter.string(from: day) }
}

