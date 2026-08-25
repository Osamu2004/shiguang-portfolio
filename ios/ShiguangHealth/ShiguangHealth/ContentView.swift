import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @StateObject private var health = HealthKitService()
    @State private var exportPresented = false
    @State private var range = 30

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Picker("读取范围", selection: $range) {
                        Text("近 7 天").tag(7); Text("近 30 天").tag(30); Text("近 90 天").tag(90)
                    }.pickerStyle(.segmented)
                    Button {
                        Task { await health.authorizeAndLoad(days: range) }
                    } label: {
                        Label(health.isLoading ? "正在读取…" : "授权并读取 Apple 健康", systemImage: "heart.text.square")
                    }.disabled(health.isLoading)
                    Button { exportPresented = true } label: {
                        Label("导出到桌面拾光", systemImage: "square.and.arrow.up")
                    }.disabled(health.days.isEmpty)
                    Text(health.message).font(.caption).foregroundStyle(.secondary)
                } header: { Text("私人健康数据") }

                Section("按日汇总") {
                    ForEach(health.days) { row in
                        VStack(alignment: .leading, spacing: 7) {
                            Text(row.dayText).font(.headline)
                            HStack {
                                metric("步数", row.steps.map(String.init) ?? "—")
                                metric("睡眠", row.sleepMinutes.map { "\($0) 分" } ?? "—")
                                metric("静息心率", row.restingHeartRate.map { String(format: "%.0f", $0) } ?? "—")
                            }
                        }.padding(.vertical, 4)
                    }
                }
            }
            .navigationTitle("拾光健康")
            .fileExporter(isPresented: $exportPresented,
                document: HealthCSVDocument(rows: health.days), contentType: .commaSeparatedText,
                defaultFilename: "shiguang-health-\(DailyHealth.dayFormatter.string(from: Date()))") { _ in }
        }
    }

    private func metric(_ name: String, _ value: String) -> some View {
        VStack(alignment: .leading) {
            Text(name).font(.caption2).foregroundStyle(.secondary)
            Text(value).font(.subheadline).monospacedDigit()
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
}
