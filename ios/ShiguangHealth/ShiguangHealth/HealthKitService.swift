import Foundation
import HealthKit

@MainActor
final class HealthKitService: ObservableObject {
    @Published var days: [DailyHealth] = []
    @Published var isLoading = false
    @Published var message = "尚未读取 Apple 健康"

    private let store = HKHealthStore()
    private let calendar = Calendar.current

    private var readTypes: Set<HKObjectType> {
        let identifiers: [HKQuantityTypeIdentifier] = [
            .stepCount, .restingHeartRate, .activeEnergyBurned, .bodyMass
        ]
        var result = Set<HKObjectType>()
        identifiers.compactMap(HKObjectType.quantityType(forIdentifier:)).forEach { result.insert($0) }
        if let sleep = HKObjectType.categoryType(forIdentifier: .sleepAnalysis) { result.insert(sleep) }
        return result
    }

    func authorizeAndLoad(days count: Int = 30) async {
        guard HKHealthStore.isHealthDataAvailable() else {
            message = "这台设备不支持 Apple 健康"; return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            try await store.requestAuthorization(toShare: [], read: readTypes)
            days = try await loadDailyData(days: count)
            message = "已读取 \(days.count) 天数据·只读"
        } catch {
            message = "读取失败：\(error.localizedDescription)"
        }
    }

    private func loadDailyData(days count: Int) async throws -> [DailyHealth] {
        let end = Date()
        let today = calendar.startOfDay(for: end)
        let start = calendar.date(byAdding: .day, value: -(count - 1), to: today)!
        async let steps = cumulative(.stepCount, unit: .count(), start: start, end: end)
        async let energy = cumulative(.activeEnergyBurned, unit: .kilocalorie(), start: start, end: end)
        async let heart = averages(.restingHeartRate, unit: HKUnit.count().unitDivided(by: .minute()), start: start, end: end)
        async let weight = latestPerDay(.bodyMass, unit: .gramUnit(with: .kilo), start: start, end: end)
        async let sleep = sleepMinutes(start: start, end: end)
        let values = try await (steps, energy, heart, weight, sleep)
        return (0..<count).compactMap { offset in
            guard let day = calendar.date(byAdding: .day, value: offset, to: start) else { return nil }
            let key = calendar.startOfDay(for: day)
            return DailyHealth(day: key,
                steps: values.0[key].map { Int($0.rounded()) },
                sleepMinutes: values.4[key],
                restingHeartRate: values.2[key],
                activeEnergy: values.1[key],
                weight: values.3[key])
        }.reversed()
    }

    private func cumulative(_ id: HKQuantityTypeIdentifier, unit: HKUnit, start: Date, end: Date) async throws -> [Date: Double] {
        guard let type = HKQuantityType.quantityType(forIdentifier: id) else { return [:] }
        return try await statistics(type, option: .cumulativeSum, unit: unit, start: start, end: end)
    }

    private func averages(_ id: HKQuantityTypeIdentifier, unit: HKUnit, start: Date, end: Date) async throws -> [Date: Double] {
        guard let type = HKQuantityType.quantityType(forIdentifier: id) else { return [:] }
        return try await statistics(type, option: .discreteAverage, unit: unit, start: start, end: end)
    }

    private func statistics(_ type: HKQuantityType, option: HKStatisticsOptions, unit: HKUnit, start: Date, end: Date) async throws -> [Date: Double] {
        try await withCheckedThrowingContinuation { continuation in
            let anchor = calendar.startOfDay(for: start)
            let query = HKStatisticsCollectionQuery(quantityType: type,
                quantitySamplePredicate: HKQuery.predicateForSamples(withStart: start, end: end),
                options: option, anchorDate: anchor, intervalComponents: DateComponents(day: 1))
            query.initialResultsHandler = { [calendar] _, collection, error in
                if let error { continuation.resume(throwing: error); return }
                var result: [Date: Double] = [:]
                collection?.enumerateStatistics(from: start, to: end) { item, _ in
                    let quantity = option == .cumulativeSum ? item.sumQuantity() : item.averageQuantity()
                    if let quantity { result[calendar.startOfDay(for: item.startDate)] = quantity.doubleValue(for: unit) }
                }
                continuation.resume(returning: result)
            }
            store.execute(query)
        }
    }

    private func latestPerDay(_ id: HKQuantityTypeIdentifier, unit: HKUnit, start: Date, end: Date) async throws -> [Date: Double] {
        guard let type = HKQuantityType.quantityType(forIdentifier: id) else { return [:] }
        return try await withCheckedThrowingContinuation { continuation in
            let query = HKSampleQuery(sampleType: type,
                predicate: HKQuery.predicateForSamples(withStart: start, end: end),
                limit: HKObjectQueryNoLimit,
                sortDescriptors: [NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: true)]) { [calendar] _, samples, error in
                if let error { continuation.resume(throwing: error); return }
                var result: [Date: Double] = [:]
                for sample in (samples as? [HKQuantitySample]) ?? [] {
                    result[calendar.startOfDay(for: sample.startDate)] = sample.quantity.doubleValue(for: unit)
                }
                continuation.resume(returning: result)
            }
            store.execute(query)
        }
    }

    private func sleepMinutes(start: Date, end: Date) async throws -> [Date: Int] {
        guard let type = HKObjectType.categoryType(forIdentifier: .sleepAnalysis) else { return [:] }
        return try await withCheckedThrowingContinuation { continuation in
            let query = HKSampleQuery(sampleType: type,
                predicate: HKQuery.predicateForSamples(withStart: start, end: end),
                limit: HKObjectQueryNoLimit, sortDescriptors: nil) { [calendar] _, samples, error in
                if let error { continuation.resume(throwing: error); return }
                var result: [Date: Int] = [:]
                let asleep = Set([HKCategoryValueSleepAnalysis.asleepUnspecified.rawValue,
                    HKCategoryValueSleepAnalysis.asleepCore.rawValue,
                    HKCategoryValueSleepAnalysis.asleepDeep.rawValue,
                    HKCategoryValueSleepAnalysis.asleepREM.rawValue])
                for sample in (samples as? [HKCategorySample]) ?? [] where asleep.contains(sample.value) {
                    let key = calendar.startOfDay(for: sample.endDate.addingTimeInterval(-1))
                    result[key, default: 0] += Int(sample.endDate.timeIntervalSince(sample.startDate) / 60)
                }
                continuation.resume(returning: result)
            }
            store.execute(query)
        }
    }
}
