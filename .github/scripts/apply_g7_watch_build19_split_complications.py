from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Build 19 runs AFTER the complete Build 18 patch chain.
# It finalizes the Apple Watch Ultra home-screen architecture requested by the user:
# - center rectangular complication = graph ONLY, rolling 2 hours, maximum usable area
# - no solid vertical line at the far LEFT
# - solid RIGHT line remains the current-time marker
# - readable time/threshold labels, dashed vertical time grid, clear gap below the 40 line
# - separate selectable xDrip circular complications for BG, delta/trend and last reading time
# - fresh App-Group re-read at least every 5 minutes instead of carrying one state snapshot for 2 hours
# - every changed xDrip BG state reloads all four xDrip complication kinds
# The graph inside the opened xDrip Watch app is NOT modified.


# -----------------------------------------------------------------------------
# 1) Register four separately selectable complications in one WidgetBundle.
# -----------------------------------------------------------------------------
widget = Path("xDrip Watch Complication/XDripWatchComplication.swift")
widget.write_text(r'''//
//  xDripWatchComplication.swift
//  xDrip Watch Complication
//
//  Build 19: separate selectable Watch complications.
//

import WidgetKit
import SwiftUI
import Foundation

// Keep this type as the namespace used by Entry/Provider/EntryView extensions.
struct XDripWatchComplication: Widget {
    let kind: String = "xDripWatchComplication"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: Provider()) { entry in
            XDripWatchComplication.EntryView(entry: entry)
        }
        .configurationDisplayName("xDrip Graph")
        .description("2-hour xDrip glucose graph")
        .supportedFamilies([.accessoryRectangular])
        .contentMarginsDisabled()
    }
}

struct XDripBGComplication: Widget {
    let kind: String = "xDripBGComplication"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: XDripWatchComplication.Provider()) { entry in
            XDripBGCircleView(entry: entry)
        }
        .configurationDisplayName("xDrip BG")
        .description("Current xDrip glucose value")
        .supportedFamilies([.accessoryCircular])
        .contentMarginsDisabled()
    }
}

struct XDripDeltaComplication: Widget {
    let kind: String = "xDripDeltaComplication"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: XDripWatchComplication.Provider()) { entry in
            XDripDeltaCircleView(entry: entry)
        }
        .configurationDisplayName("xDrip Änderung")
        .description("Change since the previous xDrip reading")
        .supportedFamilies([.accessoryCircular])
        .contentMarginsDisabled()
    }
}

struct XDripLastTimeComplication: Widget {
    let kind: String = "xDripLastTimeComplication"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: XDripWatchComplication.Provider()) { entry in
            XDripLastTimeCircleView(entry: entry)
        }
        .configurationDisplayName("xDrip Messzeit")
        .description("Time of the latest xDrip glucose reading")
        .supportedFamilies([.accessoryCircular])
        .contentMarginsDisabled()
    }
}

@main
struct XDripWatchComplicationBundle: WidgetBundle {
    @WidgetBundleBuilder
    var body: some Widget {
        XDripWatchComplication()
        XDripBGComplication()
        XDripDeltaComplication()
        XDripLastTimeComplication()
    }
}


private extension XDripWatchComplication.Entry {
    var build19LatestDate: Date? { widgetState.bgReadingDates?.first }
    var build19LatestValue: Double? { widgetState.bgReadingValues?.first }

    var build19IsFresh: Bool {
        guard let date = build19LatestDate else { return false }
        return date > self.date.addingTimeInterval(-12 * 60)
            && date <= self.date.addingTimeInterval(60)
    }

    var build19ValueColor: Color {
        guard build19IsFresh, let value = build19LatestValue else { return .gray }
        if value >= widgetState.urgentHighLimitInMgDl || value <= widgetState.urgentLowLimitInMgDl {
            return .red
        } else if value >= widgetState.highLimitInMgDl || value <= widgetState.lowLimitInMgDl {
            return .yellow
        } else {
            return .green
        }
    }

    var build19TrendArrow: String {
        guard build19IsFresh else { return "" }
        switch widgetState.slopeOrdinal {
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

    var build19DeltaText: String {
        guard build19IsFresh, let delta = widgetState.deltaValueInUserUnit else { return "--" }
        if widgetState.isMgDl {
            return String(format: "%+.0f", delta)
        }
        return String(format: "%+.1f", delta)
    }
}

private struct XDripBGCircleView: View {
    let entry: XDripWatchComplication.Entry

    var body: some View {
        ZStack {
            Circle()
                .stroke(entry.build19ValueColor.opacity(0.85), lineWidth: 3)

            VStack(spacing: -1) {
                Text(entry.build19IsFresh ? entry.widgetState.bgValueStringInUserChosenUnit() : "---")
                    .font(.system(size: 20, weight: .bold, design: .rounded))
                    .foregroundStyle(entry.build19ValueColor)
                    .minimumScaleFactor(0.55)
                    .lineLimit(1)

                if entry.build19IsFresh {
                    Text(entry.build19TrendArrow)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(entry.build19ValueColor)
                        .lineLimit(1)
                }
            }
            .padding(3)
        }
        .widgetBackground(backgroundView: Color.clear)
    }
}

private struct XDripDeltaCircleView: View {
    let entry: XDripWatchComplication.Entry

    var body: some View {
        ZStack {
            Circle()
                .fill(entry.build19ValueColor.opacity(0.16))
            Circle()
                .stroke(entry.build19ValueColor.opacity(0.55), lineWidth: 2)

            VStack(spacing: -2) {
                Text(entry.build19DeltaText)
                    .font(.system(size: 18, weight: .bold, design: .rounded))
                    .foregroundStyle(entry.build19IsFresh ? Color.colorPrimary : Color.gray)
                    .minimumScaleFactor(0.55)
                    .lineLimit(1)

                Text(entry.build19TrendArrow)
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(entry.build19ValueColor)
                    .lineLimit(1)
            }
            .padding(3)
        }
        .widgetBackground(backgroundView: Color.clear)
    }
}

private struct XDripLastTimeCircleView: View {
    let entry: XDripWatchComplication.Entry

    var body: some View {
        ZStack {
            Circle()
                .stroke(Color.secondary.opacity(0.6), lineWidth: 2)

            VStack(spacing: 0) {
                Text(entry.build19LatestDate?.formatted(date: .omitted, time: .shortened) ?? "--:--")
                    .font(.system(size: 15, weight: .bold, design: .rounded))
                    .foregroundStyle(.colorPrimary)
                    .monospacedDigit()
                    .minimumScaleFactor(0.55)
                    .lineLimit(1)

                Text("xDrip")
                    .font(.system(size: 8, weight: .medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            .padding(3)
        }
        .widgetBackground(backgroundView: Color.clear)
    }
}
''', encoding="utf-8")


# -----------------------------------------------------------------------------
# 2) Re-read App Group state every ~5 min. New BG events still reload immediately.
#    This removes Build 16's two-hour future timeline carrying one stale state copy.
# -----------------------------------------------------------------------------
provider = Path("xDrip Watch Complication/XDripWatchComplication+Provider.swift")
provider.write_text(r'''//
//  XDripWatchComplication+Provider.swift
//  xDrip Watch Complication Extension
//
//  Build 19 refresh architecture.
//

import SwiftUI
import WidgetKit
import Foundation

extension XDripWatchComplication {
    struct Provider: TimelineProvider {
        private let refreshInterval: TimeInterval = 5 * 60
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
            let nextRefresh = now.addingTimeInterval(refreshInterval)

            // Keep only the current state snapshot for this short interval. At the next refresh
            // the Provider re-reads the App Group. A genuinely new BG also triggers an immediate
            // reload from WatchStateModel, so fresh data does not need to wait for this fallback.
            var entryDates: [Date] = [now]

            // Preserve the exact local stale transition even when no new BG arrives.
            if let latestReadingDate = widgetState.bgReadingDate {
                let staleDate = latestReadingDate.addingTimeInterval(staleAfter)
                if staleDate > now, staleDate < nextRefresh {
                    entryDates.append(staleDate)
                }
            }

            let entries = entryDates
                .sorted()
                .map { Entry(date: $0, widgetState: widgetState) }

            completion(Timeline(entries: entries, policy: .after(nextRefresh)))
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
''', encoding="utf-8")


# -----------------------------------------------------------------------------
# 3) Final center graph: graph only, no left solid line, large labels.
# -----------------------------------------------------------------------------
rect = Path("xDrip Watch Complication/Views/AccessoryRectangularView.swift")
rect.write_text(r'''//
//  AccessoryRectangularView.swift
//  xDrip Watch Complication Extension
//
//  Build 19: maximum-area 2-hour graph for the center complication.
//

import Foundation
import SwiftUI

extension XDripWatchComplication.EntryView {
    @ViewBuilder
    var accessoryRectangularView: some View {
        RollingTwoHourGlucoseGraph(entry: entry)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .widgetBackground(backgroundView: Color.clear)
            .accessibilityLabel("Glukoseverlauf der letzten zwei Stunden")
    }
}

private struct RollingTwoHourGlucoseGraph: View {
    let entry: XDripWatchComplication.Entry

    private let minimumMgDl = 40.0
    private let maximumMgDl = 220.0
    private let visibleDuration: TimeInterval = 2 * 60 * 60

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
            // Enough left/top room for the now larger labels, while using essentially all
            // remaining rectangular complication pixels for the data plot.
            let labelFontSize: CGFloat = size.width >= 150 ? 9.0 : 8.2
            let leftMargin: CGFloat = size.width >= 150 ? 24.0 : 22.0
            let rightMargin: CGFloat = 0.5
            let topMargin: CGFloat = 6.0
            let bottomMargin: CGFloat = 17.0

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

            func drawLabel(_ text: String, at point: CGPoint, anchor: UnitPoint, size fontSize: CGFloat = labelFontSize) {
                let label = context.resolve(
                    Text(text)
                        .font(.system(size: fontSize, weight: .semibold))
                        .foregroundStyle(Color.secondary)
                        .monospacedDigit()
                )
                context.draw(label, at: point, anchor: anchor)
            }

            // Horizontal glucose scale. 220 is placed below the top edge so it cannot clip.
            for level in [220.0, 160.0, 70.0, 40.0] {
                let y = yPosition(level)
                var path = Path()
                path.move(to: CGPoint(x: plotLeft, y: y))
                path.addLine(to: CGPoint(x: plotRight, y: y))

                let color: Color
                let dash: [CGFloat]
                if level == 160 {
                    color = .yellow.opacity(0.78)
                    dash = []
                } else if level == 70 {
                    color = .red.opacity(0.82)
                    dash = []
                } else {
                    color = .secondary.opacity(0.55)
                    dash = [2.5, 2.5]
                }

                context.stroke(path, with: .color(color), style: StrokeStyle(lineWidth: 0.75, dash: dash))
                drawLabel(String(Int(level)), at: CGPoint(x: plotLeft - 3.0, y: y), anchor: UnitPoint(x: 1, y: 0.5))
            }

            // Dashed monitor-style vertical grid at each 30-minute subdivision.
            for fraction in [0.25, 0.50, 0.75] as [CGFloat] {
                let x = plotLeft + plotWidth * fraction
                var grid = Path()
                grid.move(to: CGPoint(x: x, y: plotTop))
                grid.addLine(to: CGPoint(x: x, y: plotBottom))
                context.stroke(grid, with: .color(Color.secondary.opacity(0.52)), style: StrokeStyle(lineWidth: 0.7, dash: [2.5, 2.5]))
            }

            // Five rolling labels on Ultra-size rectangles (30-minute steps over two hours).
            // Smaller rectangles fall back to start/middle/now to prevent overlaps.
            let labelY = size.height - 0.5
            let startDate = entry.date.addingTimeInterval(-visibleDuration)
            if size.width >= 150 {
                for index in 0...4 {
                    let fraction = CGFloat(index) / 4.0
                    let date = startDate.addingTimeInterval(visibleDuration * Double(fraction))
                    let anchor: UnitPoint = index == 0 ? UnitPoint(x: 0, y: 1) : (index == 4 ? UnitPoint(x: 1, y: 1) : UnitPoint(x: 0.5, y: 1))
                    drawLabel(Self.timeFormatter.string(from: date), at: CGPoint(x: plotLeft + plotWidth * fraction, y: labelY), anchor: anchor)
                }
            } else {
                let middleDate = entry.date.addingTimeInterval(-visibleDuration / 2)
                drawLabel(Self.timeFormatter.string(from: startDate), at: CGPoint(x: plotLeft, y: labelY), anchor: UnitPoint(x: 0, y: 1))
                drawLabel(Self.timeFormatter.string(from: middleDate), at: CGPoint(x: plotLeft + plotWidth / 2, y: labelY), anchor: UnitPoint(x: 0.5, y: 1))
                drawLabel(Self.timeFormatter.string(from: entry.date), at: CGPoint(x: plotRight, y: labelY), anchor: UnitPoint(x: 1, y: 1))
            }

            // Historical BG dots retain their actual timestamps and therefore move left as now advances.
            for reading in readings {
                let center = CGPoint(x: xPosition(reading.date), y: yPosition(reading.value))
                let radius: CGFloat = size.width >= 150 ? 2.2 : 1.9
                let dot = Path(ellipseIn: CGRect(x: center.x - radius, y: center.y - radius, width: radius * 2, height: radius * 2))
                context.fill(dot, with: .color(pointColor(reading.value)))
            }

            // RIGHT edge only: continuous current-time line. There is intentionally NO solid
            // vertical line at plotLeft.
            var currentLine = Path()
            currentLine.move(to: CGPoint(x: plotRight, y: plotTop))
            currentLine.addLine(to: CGPoint(x: plotRight, y: plotBottom))
            context.stroke(currentLine, with: .color(Color.white.opacity(0.95)), lineWidth: 1.15)

            // Ring the newest point only when it is inside this 2-hour window.
            if let latest = readings.last {
                let center = CGPoint(x: xPosition(latest.date), y: yPosition(latest.value))
                let ringRadius: CGFloat = size.width >= 150 ? 3.5 : 3.0
                let ring = Path(ellipseIn: CGRect(x: center.x - ringRadius, y: center.y - ringRadius, width: ringRadius * 2, height: ringRadius * 2))
                context.stroke(ring, with: .color(Color.white.opacity(0.95)), lineWidth: 1.0)
            }
        }
    }
}
''', encoding="utf-8")


# -----------------------------------------------------------------------------
# 4) Every genuinely new BG state refreshes graph + all three xDrip circle widgets.
# -----------------------------------------------------------------------------
watch_state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")
replace_once(
    watch_state,
    '            WidgetCenter.shared.reloadTimelines(ofKind: "xDripWatchComplication")',
    '''            for complicationKind in [
                "xDripWatchComplication",
                "xDripBGComplication",
                "xDripDeltaComplication",
                "xDripLastTimeComplication"
            ] {
                WidgetCenter.shared.reloadTimelines(ofKind: complicationKind)
            }''',
    "Build19 reload all xDrip complication kinds",
)

print("Build 19 split complications, fresh refresh logic and final Ultra 2h graph applied successfully.")
