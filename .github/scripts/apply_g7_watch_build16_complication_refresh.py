from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1))


# Build 16 runs AFTER the complete Build 15 patch chain.
# It changes only the Apple Watch home-screen complication plus the complication
# publication/timeline path. The graph inside the opened xDrip Watch app is not touched.
#
# Goals:
# - rolling 2-hour complication graph, 40...220 mg/dL
# - right edge is always the current timeline-entry time
# - current BG / trend / delta / measurement time on the RIGHT of the graph
# - no xDrip/Dexcom label consuming graph space
# - 5-minute future timeline entries so history moves left with time
# - exact local stale transition 12 minutes after the last BG, even if the app is not opened
# - immediate App-Group write + targeted complication reload for every changed BG state
# - avoid redundant WidgetKit reloads for byte-identical state

entry = Path("xDrip Watch Complication/XDripWatchComplication+Entry.swift")
replace_once(
    entry,
    '''        var hasRecentReading: Bool {
            guard let bgReadingDate else { return false }

            return bgReadingDate > Date().addingTimeInterval(-60 * 7)
        }''',
    '''        var hasRecentReading: Bool {
            guard let bgReadingDate else { return false }

            return bgReadingDate > Date().addingTimeInterval(-60 * 12)
        }''',
    "Build16 12-minute complication freshness",
)

provider = Path("xDrip Watch Complication/XDripWatchComplication+Provider.swift")
provider.write_text(r'''//
//  XDripWatchComplication+Provider.swift
//  xDrip Watch Complication Extension
//
//  Created by Paul Plant on 28/2/24.
//  Copyright © 2024 Johan Degraeve. All rights reserved.
//

import SwiftUI
import WidgetKit
import Foundation

extension XDripWatchComplication {
    struct Provider: TimelineProvider {
        private let timelineStep: TimeInterval = 5 * 60
        private let timelineHorizon: TimeInterval = 2 * 60 * 60
        private let staleAfter: TimeInterval = 12 * 60

        func placeholder(in context: Context) -> Entry {
            .placeholder
        }

        func getSnapshot(in context: Context, completion: @escaping (Entry) -> ()) {
            completion(Entry(date: .now, widgetState: getWidgetStateFromSharedUserDefaults() ?? sampleWidgetStateFromProvider))
        }

        func getTimeline(in context: Context, completion: @escaping (Timeline<Entry>) -> ()) {
            let now = Date()
            let widgetState = getWidgetStateFromSharedUserDefaults() ?? sampleWidgetStateFromProvider
            let horizonDate = now.addingTimeInterval(timelineHorizon)

            // A complication is not a continuously running app. Pre-schedule a lightweight
            // 5-minute rolling timeline so the 2-hour window moves even when xDrip is closed.
            // A newly received BG still causes an immediate targeted reload and replaces this
            // future timeline with one based on the fresh state.
            var entryDates: [Date] = [now]
            var cursor = now.addingTimeInterval(timelineStep)
            while cursor <= horizonDate {
                entryDates.append(cursor)
                cursor = cursor.addingTimeInterval(timelineStep)
            }

            // Guarantee a local transition to stale exactly 12 minutes after the latest BG.
            // This is independent of another phone/Watch transfer.
            if let latestReadingDate = widgetState.bgReadingDate {
                let staleDate = latestReadingDate.addingTimeInterval(staleAfter)
                if staleDate > now, staleDate <= horizonDate,
                   !entryDates.contains(where: { abs($0.timeIntervalSince(staleDate)) < 1 }) {
                    entryDates.append(staleDate)
                }
            }

            let entries = entryDates
                .sorted()
                .map { Entry(date: $0, widgetState: widgetState) }

            completion(Timeline(entries: entries, policy: .atEnd))
        }
    }
}


// MARK: - Helpers

extension XDripWatchComplication.Provider {
    func getWidgetStateFromSharedUserDefaults() -> XDripWatchComplication.Entry.WidgetState? {
        guard let sharedUserDefaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else { return nil }

        guard let encodedLatestReadings = sharedUserDefaults.data(forKey: "complicationSharedUserDefaults.\(Bundle.main.mainAppBundleIdentifier)") else {
            return nil
        }

        let decoder = JSONDecoder()

        do {
            let data = try decoder.decode(ComplicationSharedUserDefaultsModel.self, from: encodedLatestReadings)

            let bgReadingDates: [Date] = data.bgReadingDatesAsDouble.map { date in
                Date(timeIntervalSince1970: date)
            }

            let dataSource = sharedUserDefaults.string(forKey: "complicationDataSource.\(Bundle.main.mainAppBundleIdentifier)")

            return Entry.WidgetState(
                bgReadingValues: data.bgReadingValues,
                bgReadingDates: bgReadingDates,
                isMgDl: data.isMgDl,
                slopeOrdinal: data.slopeOrdinal,
                deltaValueInUserUnit: data.deltaValueInUserUnit,
                urgentLowLimitInMgDl: data.urgentLowLimitInMgDl,
                lowLimitInMgDl: data.lowLimitInMgDl,
                highLimitInMgDl: data.highLimitInMgDl,
                urgentHighLimitInMgDl: data.urgentHighLimitInMgDl,
                keepAliveIsDisabled: data.keepAliveIsDisabled,
                dataSource: dataSource
            )
        } catch {
            print(error.localizedDescription)
        }

        return sampleWidgetStateFromProvider
    }

    private var sampleWidgetStateFromProvider: XDripWatchComplication.Entry.WidgetState {
        Entry.WidgetState(
            bgReadingValues: ConstantsWatchComplication.bgReadingValuesPlaceholderData,
            bgReadingDates: ConstantsWatchComplication.bgReadingDatesPlaceholderData(),
            isMgDl: true,
            slopeOrdinal: 4,
            deltaValueInUserUnit: 0,
            urgentLowLimitInMgDl: 70,
            lowLimitInMgDl: 90,
            highLimitInMgDl: 140,
            urgentHighLimitInMgDl: 180
        )
    }
}
''')

view = Path("xDrip Watch Complication/Views/AccessoryRectangularView.swift")
view.write_text(r'''//
//  AccessoryRectangularView.swift
//  xDrip Watch Complication Extension
//
//  Created by Paul Plant on 4/3/24.
//  Copyright © 2024 Johan Degraeve. All rights reserved.
//

import Foundation
import SwiftUI

extension XDripWatchComplication.EntryView {
    @ViewBuilder
    var accessoryRectangularView: some View {
        ZStack {
            GeometryReader { geometry in
                let sideWidth = max(44.0, min(58.0, geometry.size.width * 0.27))

                HStack(alignment: .center, spacing: 3) {
                    RollingTwoHourGlucoseGraph(entry: entry)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)

                    CurrentGlucosePanel(entry: entry)
                        .frame(width: sideWidth, maxHeight: .infinity, alignment: .leading)
                }
            }

            if entry.widgetState.keepAliveIsDisabled {
                Text(Texts_WatchComplication.keepAliveDisabled)
                    .font(.system(size: entry.widgetState.isSmallScreen() ? 11 : 12, weight: .semibold))
                    .foregroundStyle(.colorPrimary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 5)
                    .background(Color(white: 0.2).opacity(0.95), in: Capsule())
            }
        }
        .widgetBackground(backgroundView: Color.clear)
    }
}


private struct CurrentGlucosePanel: View {
    let entry: XDripWatchComplication.Entry
    private let staleAfter: TimeInterval = 12 * 60

    private var latestDate: Date? {
        entry.widgetState.bgReadingDates?.first
    }

    private var latestValue: Double? {
        entry.widgetState.bgReadingValues?.first
    }

    private var isFresh: Bool {
        guard let latestDate else { return false }
        return latestDate > entry.date.addingTimeInterval(-staleAfter)
            && latestDate <= entry.date.addingTimeInterval(60)
    }

    private var displayColor: Color {
        guard isFresh, let value = latestValue else { return .gray }

        if value >= entry.widgetState.urgentHighLimitInMgDl || value <= entry.widgetState.urgentLowLimitInMgDl {
            return .red
        } else if value >= entry.widgetState.highLimitInMgDl || value <= entry.widgetState.lowLimitInMgDl {
            return .yellow
        } else {
            return .green
        }
    }

    private var glucoseText: String {
        guard isFresh, let value = latestValue else { return "---" }

        if value >= 400 {
            return Texts_Common.HIGH
        } else if value >= 40 {
            return value.mgDlToMmolAndToString(mgDl: entry.widgetState.isMgDl)
        } else if value > 12 {
            return Texts_Common.LOW
        }

        switch value {
        case 0: return "??0"
        case 1: return "?SN"
        case 2: return "??2"
        case 3: return "?NA"
        case 5: return "?NC"
        case 6: return "?CD"
        case 9: return "?AD"
        case 12: return "?RF"
        default: return "???"
        }
    }

    private var trendArrow: String {
        guard isFresh else { return "" }
        switch entry.widgetState.slopeOrdinal {
        case 7: return "↓↓"
        case 6: return "↓"
        case 5: return "↘"
        case 4: return "→"
        case 3: return "↗"
        case 2: return "↑"
        case 1: return "↑↑"
        default: return ""
        }
    }

    private var deltaText: String {
        guard isFresh, let delta = entry.widgetState.deltaValueInUserUnit else { return "--" }
        if delta == 0 {
            return entry.widgetState.isMgDl ? "+0" : "+0.0"
        }

        let number = entry.widgetState.isMgDl
            ? delta.mgDlToMmolAndToString(mgDl: true)
            : delta.mmolToString()
        return delta > 0 ? "+\(number)" : number
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Spacer(minLength: 0)

            HStack(alignment: .firstTextBaseline, spacing: 1) {
                Text(glucoseText)
                    .font(.system(size: entry.widgetState.isSmallScreen() ? 17 : 21, weight: .bold))
                    .foregroundStyle(displayColor)
                    .minimumScaleFactor(0.55)
                    .lineLimit(1)

                Text(trendArrow)
                    .font(.system(size: entry.widgetState.isSmallScreen() ? 15 : 19, weight: .bold))
                    .foregroundStyle(displayColor)
                    .minimumScaleFactor(0.6)
                    .lineLimit(1)
            }

            Text(deltaText)
                .font(.system(size: entry.widgetState.isSmallScreen() ? 12 : 14, weight: .semibold))
                .foregroundStyle(isFresh ? Color.colorPrimary : Color.gray)
                .lineLimit(1)

            Text(latestDate?.formatted(date: .omitted, time: .shortened) ?? "--:--")
                .font(.system(size: entry.widgetState.isSmallScreen() ? 8 : 10, weight: .medium))
                .foregroundStyle(.colorPrimary)
                .monospacedDigit()
                .lineLimit(1)
                .minimumScaleFactor(0.7)

            Spacer(minLength: 0)
        }
    }
}


private struct RollingTwoHourGlucoseGraph: View {
    let entry: XDripWatchComplication.Entry

    private let minimumMgDl = 40.0
    private let maximumMgDl = 220.0
    private let visibleDuration: TimeInterval = 2 * 60 * 60
    private let staleAfter: TimeInterval = 12 * 60

    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter
    }()

    private var readings: [(date: Date, value: Double)] {
        guard let dates = entry.widgetState.bgReadingDates,
              let values = entry.widgetState.bgReadingValues else { return [] }

        let count = min(dates.count, values.count)
        guard count > 0 else { return [] }

        let start = entry.date.addingTimeInterval(-visibleDuration)
        return (0..<count)
            .map { (date: dates[$0], value: values[$0]) }
            .filter { $0.date >= start && $0.date <= entry.date.addingTimeInterval(60) }
            .sorted { $0.date < $1.date }
    }

    private func pointColor(_ value: Double) -> Color {
        if value >= entry.widgetState.urgentHighLimitInMgDl || value <= entry.widgetState.urgentLowLimitInMgDl {
            return .red
        } else if value >= entry.widgetState.highLimitInMgDl || value <= entry.widgetState.lowLimitInMgDl {
            return .yellow
        } else {
            return .green
        }
    }

    var body: some View {
        Canvas { context, size in
            let leftMargin: CGFloat = size.width < 115 ? 18 : 21
            let rightMargin: CGFloat = 1.5
            let topMargin: CGFloat = 2
            let bottomMargin: CGFloat = size.height < 55 ? 10 : 12
            let plotLeft = leftMargin
            let plotRight = max(plotLeft + 1, size.width - rightMargin)
            let plotTop = topMargin
            let plotBottom = max(plotTop + 1, size.height - bottomMargin)
            let plotWidth = max(1, plotRight - plotLeft)
            let plotHeight = max(1, plotBottom - plotTop)

            func yPosition(_ value: Double) -> CGFloat {
                let clamped = min(max(value, minimumMgDl), maximumMgDl)
                let fraction = (maximumMgDl - clamped) / (maximumMgDl - minimumMgDl)
                return plotTop + CGFloat(fraction) * plotHeight
            }

            func xPosition(_ date: Date) -> CGFloat {
                let start = entry.date.addingTimeInterval(-visibleDuration)
                let elapsed = date.timeIntervalSince(start)
                let fraction = min(max(elapsed / visibleDuration, 0), 1)
                return plotLeft + CGFloat(fraction) * plotWidth
            }

            func drawLabel(_ text: String, at point: CGPoint, anchor: UnitPoint, size fontSize: CGFloat) {
                let label = context.resolve(
                    Text(text)
                        .font(.system(size: fontSize, weight: .medium))
                        .foregroundStyle(Color.secondary)
                )
                context.draw(label, at: point, anchor: anchor)
            }

            // Horizontal monitor grid and requested 40...220 mg/dL scale.
            for level in [220.0, 160.0, 70.0, 40.0] {
                let y = yPosition(level)
                var path = Path()
                path.move(to: CGPoint(x: plotLeft, y: y))
                path.addLine(to: CGPoint(x: plotRight, y: y))

                let color: Color
                if level == 160 {
                    color = .yellow.opacity(0.75)
                } else if level == 70 {
                    color = .red.opacity(0.75)
                } else {
                    color = .secondary.opacity(0.5)
                }

                context.stroke(path, with: .color(color), style: StrokeStyle(lineWidth: 0.65, dash: level == 160 || level == 70 ? [] : [2, 2]))
                drawLabel(String(Int(level)), at: CGPoint(x: plotLeft - 2.5, y: y), anchor: UnitPoint(x: 1, y: 0.5), size: 6.5)
            }

            // Interior time grid. There is deliberately NO vertical line on the left edge.
            for fraction in [0.25, 0.50, 0.75] {
                let x = plotLeft + CGFloat(fraction) * plotWidth
                var path = Path()
                path.move(to: CGPoint(x: x, y: plotTop))
                path.addLine(to: CGPoint(x: x, y: plotBottom))
                context.stroke(path, with: .color(.secondary.opacity(0.32)), style: StrokeStyle(lineWidth: 0.55, dash: [2, 2]))
            }

            // The continuous RIGHT vertical line is the current time marker.
            let currentTimeX = plotRight
            var currentTimePath = Path()
            currentTimePath.move(to: CGPoint(x: currentTimeX, y: plotTop))
            currentTimePath.addLine(to: CGPoint(x: currentTimeX, y: plotBottom))
            context.stroke(currentTimePath, with: .color(.white.opacity(0.95)), style: StrokeStyle(lineWidth: 1.0))

            // Plot the last two hours. Every point keeps its measurement timestamp, so
            // future timeline entries naturally push older points to the left.
            for item in readings {
                let x = xPosition(item.date)
                let y = yPosition(item.value)
                let diameter: CGFloat = size.height < 55 ? 2.5 : 3.1
                let rect = CGRect(x: x - diameter / 2, y: y - diameter / 2, width: diameter, height: diameter)
                context.fill(Path(ellipseIn: rect), with: .color(pointColor(item.value)))
            }

            // Highlight the latest point only while it is still current.
            if let latest = readings.last,
               latest.date > entry.date.addingTimeInterval(-staleAfter) {
                let x = xPosition(latest.date)
                let y = yPosition(latest.value)
                let ringDiameter: CGFloat = size.height < 55 ? 4.4 : 5.2
                let ringRect = CGRect(x: x - ringDiameter / 2, y: y - ringDiameter / 2, width: ringDiameter, height: ringDiameter)
                context.stroke(Path(ellipseIn: ringRect), with: .color(.white), lineWidth: 0.9)
            }

            let leftDate = entry.date.addingTimeInterval(-visibleDuration)
            let middleDate = entry.date.addingTimeInterval(-visibleDuration / 2)
            let labelY = size.height - 1
            drawLabel(Self.timeFormatter.string(from: leftDate), at: CGPoint(x: plotLeft, y: labelY), anchor: UnitPoint(x: 0, y: 1), size: 6.5)
            drawLabel(Self.timeFormatter.string(from: middleDate), at: CGPoint(x: plotLeft + plotWidth / 2, y: labelY), anchor: UnitPoint(x: 0.5, y: 1), size: 6.5)
            drawLabel(Self.timeFormatter.string(from: entry.date), at: CGPoint(x: plotRight, y: labelY), anchor: UnitPoint(x: 1, y: 1), size: 6.5)
        }
        .accessibilityLabel("Glukoseverlauf der letzten zwei Stunden")
    }
}
''')

watch_state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")
replace_once(
    watch_state,
    '''        if let stateData = try? JSONEncoder().encode(complicationSharedUserDefaultsModel) {
            sharedUserDefaults.set(stateData, forKey: "complicationSharedUserDefaults.\\(Bundle.main.mainAppBundleIdentifier)")
        }

        // Keep the transport source separate from the Codable model so existing stored state remains
        // fully backward-compatible with older complication extensions.
        sharedUserDefaults.set(bgDataSource, forKey: "complicationDataSource.\\(Bundle.main.mainAppBundleIdentifier)")

        // Ask only the xDrip complication to reload. WidgetKit may still defer the actual render.
        WidgetCenter.shared.reloadTimelines(ofKind: "xDripWatchComplication")

        lastComplicationUpdateTimeStamp = .now''',
    '''        let stateKey = "complicationSharedUserDefaults.\\(Bundle.main.mainAppBundleIdentifier)"
        let sourceKey = "complicationDataSource.\\(Bundle.main.mainAppBundleIdentifier)"
        var stateChanged = false

        if let stateData = try? JSONEncoder().encode(complicationSharedUserDefaultsModel),
           sharedUserDefaults.data(forKey: stateKey) != stateData {
            sharedUserDefaults.set(stateData, forKey: stateKey)
            stateChanged = true
        }

        // Keep the source key backward-compatible, but don't spend a WidgetKit reload budget
        // when neither the BG payload nor its source actually changed.
        let sourceChanged = sharedUserDefaults.string(forKey: sourceKey) != bgDataSource
        if sourceChanged {
            sharedUserDefaults.set(bgDataSource, forKey: sourceKey)
        }

        if stateChanged || sourceChanged {
            // Every genuinely new BG state is already persisted at this point. Reload ONLY the
            // xDrip complication; the Provider then replaces its rolling/stale future timeline.
            WidgetCenter.shared.reloadTimelines(ofKind: "xDripWatchComplication")
            lastComplicationUpdateTimeStamp = .now
        }''',
    "Build16 deduplicated immediate targeted complication publication",
)

print("Build 16 rolling home-screen complication + refresh logic applied successfully.")
