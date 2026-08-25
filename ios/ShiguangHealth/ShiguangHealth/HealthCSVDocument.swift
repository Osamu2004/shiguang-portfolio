import SwiftUI
import UniformTypeIdentifiers

struct HealthCSVDocument: FileDocument {
    static var readableContentTypes: [UTType] { [.commaSeparatedText] }
    var rows: [DailyHealth]

    init(rows: [DailyHealth]) { self.rows = rows }
    init(configuration: ReadConfiguration) throws { rows = [] }

    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        let header = "day,steps,sleep_minutes,resting_heart_rate,active_energy,weight,source"
        let body = rows.reversed().map { row in
            [row.dayText, text(row.steps), text(row.sleepMinutes), text(row.restingHeartRate),
             text(row.activeEnergy), text(row.weight), "apple-health"].joined(separator: ",")
        }
        return FileWrapper(regularFileWithContents: ([header] + body).joined(separator: "\n").data(using: .utf8)!)
    }

    private func text<T>(_ value: T?) -> String { value.map(String.init(describing:)) ?? "" }
}

