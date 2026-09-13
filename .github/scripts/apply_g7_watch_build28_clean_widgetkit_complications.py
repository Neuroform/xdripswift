from pathlib import Path
import plistlib

# Build 28 intentionally does NOT inherit Builds 19-27 complication-registration
# experiments. It starts from the repository's original, known-good watch WidgetKit
# target and changes only the complication source/UI plus targeted timeline reloads.
#
# Structural rule: keep the original xDrip watch widget target exactly as upstream:
# - GENERATE_INFOPLIST_FILE = YES
# - original minimal Info.plist
# - no ClockKit principal class / descriptor bridge
# - no APPLICATION_EXTENSION_API_ONLY/SUPPORTED_PLATFORMS overrides
# - one watchOS WidgetKit extension embedded by the existing project target
#
# Final user requirements:
# - rectangular: "Martin’s xDrip Graph", full-area rolling 2h graph
# - linear/proportional 0...220 mg/dL y-axis
# - 220 yellow solid at the top edge
# - 160 white dashed, 70 white dashed, 40 red solid, 0 white solid unlabelled
# - 220 label begins on the yellow line, 70 above its line, 40 below its line
# - exactly three full-hour labels; vertical guides at first + middle; solid NOW right edge
# - circular 1: current BG only + turquoise elapsed-minute tick ring; >12 min => red + "- - -"
# - circular 2: trend arrow + delta mg/dL; >12 min => "- - -"
# - no third circular xDrip complication
# - new BG state writes to App Group then reloads all three specific WidgetKit kinds
# - minute timeline entries so age ring and stale transition update without opening xDrip


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


# -----------------------------------------------------------------------------
# 1) Assert and preserve the ORIGINAL working WidgetKit target configuration.
# -----------------------------------------------------------------------------
project_path = Path("xdrip.xcodeproj/project.pbxproj")
project = project_path.read_text(encoding="utf-8")

for config_id in ["479359922B88B95B007D3CEE", "479359932B88B95B007D3CEE"]:
    start = project.find(config_id)
    require(start >= 0, f"Build28: target configuration {config_id} not found")
    end = project.find("\n\t\t};", start)
    require(end > start, f"Build28: target configuration {config_id} end not found")
    block = project[start:end]
    require("GENERATE_INFOPLIST_FILE = YES;" in block,
            f"Build28: {config_id} must keep upstream GENERATE_INFOPLIST_FILE=YES")
    require('INFOPLIST_FILE = "xDrip Watch Complication/Info.plist";' in block,
            f"Build28: {config_id} must keep upstream Info.plist")
    require("APPLICATION_EXTENSION_API_ONLY" not in block,
            f"Build28: {config_id} contains legacy Build22 APPLICATION_EXTENSION_API_ONLY override")
    require("SUPPORTED_PLATFORMS" not in block,
            f"Build28: {config_id} contains legacy Build22 SUPPORTED_PLATFORMS override")

require('productName = "xDrip Watch ComplicationExtension";' in project,
        "Build28: original complication target productName is not intact")

# Restore the original minimal WidgetKit-extension plist byte-for-byte in substance.
ext_info_path = Path("xDrip Watch Complication/Info.plist")
ext_info = {
    "AppGroupIdentifier": "$(APP_GROUP_IDENTIFIER)",
    "MainAppBundleIdentifier": "$(MAIN_APP_BUNDLE_IDENTIFIER)",
    "NSExtension": {"NSExtensionPointIdentifier": "com.apple.widgetkit-extension"},
}
with ext_info_path.open("wb") as f:
    plistlib.dump(ext_info, f, sort_keys=False)

# The watch app must NOT register a deprecated ClockKit provider when WidgetKit is present.
watch_info_path = Path("xDrip-Watch-App-Info.plist")
with watch_info_path.open("rb") as f:
    watch_info = plistlib.load(f)
watch_info.pop("CLKComplicationPrincipalClass", None)
watch_info.pop("CLKComplicationSupportedFamilies", None)
with watch_info_path.open("wb") as f:
    plistlib.dump(watch_info, f, sort_keys=False)

watch_app_path = Path("xDrip Watch App/xDripWatchApp.swift")
watch_app = watch_app_path.read_text(encoding="utf-8")
require("ClockKit" not in watch_app and "CLKComplication" not in watch_app,
        "Build28: ClockKit complication bridge must not exist in clean architecture")


# -----------------------------------------------------------------------------
# 2) Clean WidgetKit bundle: graph + exactly two circular complications.
# -----------------------------------------------------------------------------
widget_path = Path("xDrip Watch Complication/XDripWatchComplication.swift")
widget_path.write_text(r'''//
//  XDripWatchComplication.swift
//  xDrip Watch Complication
//
//  Build 28: clean upstream-target WidgetKit architecture.
//

import WidgetKit
import SwiftUI
import Foundation

struct XDripWatchComplication: Widget {
    let kind: String = "xDripGraphV28"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: Provider()) { entry in
            EntryView(entry: entry)
        }
        .configurationDisplayName("Martin’s xDrip Graph")
        .description("2-Stunden-Glukosegraph für Modular Ultra")
        .supportedFamilies([.accessoryRectangular])
        .contentMarginsDisabled()
    }
}

struct XDripBGComplication: Widget {
    let kind: String = "xDripBGV28"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: XDripWatchComplication.Provider()) { entry in
            XDripBGMinuteCircleView(entry: entry)
        }
        .configurationDisplayName("xDrip BG mg/dL")
        .description("Aktueller BG-Wert mit Minutenalter im äußeren Ring")
        .supportedFamilies([.accessoryCircular])
        .contentMarginsDisabled()
    }
}

struct XDripTrendComplication: Widget {
    let kind: String = "xDripTrendV28"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: XDripWatchComplication.Provider()) { entry in
            XDripTrendDeltaCircleView(entry: entry)
        }
        .configurationDisplayName("BG Trend + Δ mg/dL")
        .description("Trendpfeil und Änderung gegenüber dem vorherigen BG-Wert")
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
        XDripTrendComplication()
    }
}

// MARK: - Freshness helpers shared by the two circular complications

extension XDripWatchComplication.Entry {
    private var build28StaleAfter: TimeInterval { 12 * 60 }

    var build28LatestDate: Date? { widgetState.bgReadingDates?.first }
    var build28LatestValue: Double? { widgetState.bgReadingValues?.first }

    var build28AgeSeconds: TimeInterval {
        guard let readingDate = build28LatestDate else { return .infinity }
        return max(0, date.timeIntervalSince(readingDate))
    }

    var build28AgeMinutes: Int {
        guard build28AgeSeconds.isFinite else { return 60 }
        return max(0, Int(floor(build28AgeSeconds / 60.0)))
    }

    var build28IsFresh: Bool {
        guard let readingDate = build28LatestDate, build28LatestValue != nil else { return false }
        return readingDate <= date.addingTimeInterval(60)
            && build28AgeSeconds <= build28StaleAfter
    }

    var build28BGText: String {
        guard build28IsFresh, let value = build28LatestValue else { return "- - -" }
        if value >= 400 { return "HIGH" }
        if value >= 40 { return String(Int(value.rounded())) }
        if value > 12 { return "LOW" }
        return "- - -"
    }

    var build28TrendArrow: String {
        guard build28IsFresh else { return "" }
        switch widgetState.slopeOrdinal {
        case 7: return "↓↓"
        case 6: return "↓"
        case 5: return "↘"
        case 4: return "→"
        case 3: return "↗"
        case 2: return "↑"
        case 1: return "↑↑"
        default: return "→"
        }
    }

    var build28DeltaMgDlText: String {
        guard build28IsFresh, let delta = widgetState.deltaValueInUserUnit else { return "" }
        let mgDlDelta = widgetState.isMgDl ? delta : delta * 18.0
        return String(format: "%+.0f", mgDlDelta)
    }
}

private struct Build28MinuteRing: View {
    let ageMinutes: Int
    let isFresh: Bool

    private let turquoise = Color(red: 0.20, green: 0.95, blue: 0.92)

    var body: some View {
        Canvas { context, size in
            let center = CGPoint(x: size.width / 2, y: size.height / 2)
            let radius = max(2, min(size.width, size.height) / 2 - 1.4)
            let activeTicks = min(max(ageMinutes, 0), 12)

            for index in 0..<60 {
                let angle = (Double(index) * 6.0 - 90.0) * Double.pi / 180.0
                let major = index % 5 == 0
                let outer = radius
                let inner = radius - (major ? 5.8 : 4.0)
                let p1 = CGPoint(
                    x: center.x + CGFloat(cos(angle)) * inner,
                    y: center.y + CGFloat(sin(angle)) * inner
                )
                let p2 = CGPoint(
                    x: center.x + CGFloat(cos(angle)) * outer,
                    y: center.y + CGFloat(sin(angle)) * outer
                )
                var tick = Path()
                tick.move(to: p1)
                tick.addLine(to: p2)

                let color: Color
                if isFresh {
                    color = index < activeTicks ? turquoise : Color.white.opacity(0.14)
                } else {
                    color = .red
                }

                context.stroke(
                    tick,
                    with: .color(color),
                    style: StrokeStyle(lineWidth: major ? 1.65 : 1.15, lineCap: .round)
                )
            }
        }
        .allowsHitTesting(false)
    }
}

struct XDripBGMinuteCircleView: View {
    let entry: XDripWatchComplication.Entry

    var body: some View {
        ZStack {
            Build28MinuteRing(
                ageMinutes: entry.build28AgeMinutes,
                isFresh: entry.build28IsFresh
            )

            Text(entry.build28BGText)
                .font(.system(size: 22, weight: .bold, design: .rounded))
                .foregroundStyle(entry.build28IsFresh ? Color.white : Color.red)
                .monospacedDigit()
                .minimumScaleFactor(0.42)
                .lineLimit(1)
                .padding(7)
        }
        .widgetBackground(backgroundView: Color.clear)
    }
}

struct XDripTrendDeltaCircleView: View {
    let entry: XDripWatchComplication.Entry

    var body: some View {
        Group {
            if entry.build28IsFresh {
                VStack(spacing: -2) {
                    Text(entry.build28TrendArrow)
                        .font(.system(size: 22, weight: .bold, design: .rounded))
                        .foregroundStyle(Color.white)
                        .lineLimit(1)
                    Text(entry.build28DeltaMgDlText)
                        .font(.system(size: 17, weight: .bold, design: .rounded))
                        .foregroundStyle(Color.white)
                        .monospacedDigit()
                        .minimumScaleFactor(0.50)
                        .lineLimit(1)
                }
            } else {
                Text("- - -")
                    .font(.system(size: 18, weight: .bold, design: .rounded))
                    .foregroundStyle(Color.red)
                    .minimumScaleFactor(0.45)
                    .lineLimit(1)
            }
        }
        .widgetBackground(backgroundView: Color.clear)
    }
}
''', encoding="utf-8")


# -----------------------------------------------------------------------------
# 3) Graph entry view: rectangular widget only. No AppIntent/ClockKit routing.
# -----------------------------------------------------------------------------
entry_view_path = Path("xDrip Watch Complication/XDripWatchComplication+EntryView.swift")
entry_view_path.write_text(r'''//
//  XDripWatchComplication+EntryView.swift
//  xDrip Watch Complication Extension
//
//  Build 28: rectangular graph entry view.
//

import SwiftUI
import Foundation
import WidgetKit

extension XDripWatchComplication {
    struct EntryView: View {
        var entry: Entry

        var body: some View {
            accessoryRectangularView
        }
    }
}
''', encoding="utf-8")


# -----------------------------------------------------------------------------
# 4) Timeline: one entry per minute, with exact >12-minute stale transition.
# -----------------------------------------------------------------------------
provider_path = Path("xDrip Watch Complication/XDripWatchComplication+Provider.swift")
provider_path.write_text(r'''//
//  XDripWatchComplication+Provider.swift
//  xDrip Watch Complication Extension
//
//  Build 28: clean minute timeline with App-Group state.
//

import SwiftUI
import WidgetKit
import Foundation

extension XDripWatchComplication {
    struct Provider: TimelineProvider {
        private let timelineStep: TimeInterval = 60
        private let timelineHorizon: TimeInterval = 20 * 60
        private let staleAfter: TimeInterval = 12 * 60

        func placeholder(in context: Context) -> Entry {
            .placeholder
        }

        func getSnapshot(in context: Context, completion: @escaping (Entry) -> Void) {
            completion(Entry(
                date: .now,
                widgetState: getWidgetStateFromSharedUserDefaults() ?? sampleWidgetStateFromProvider
            ))
        }

        func getTimeline(in context: Context, completion: @escaping (Timeline<Entry>) -> Void) {
            let now = Date()
            let state = getWidgetStateFromSharedUserDefaults() ?? sampleWidgetStateFromProvider
            let horizon = now.addingTimeInterval(timelineHorizon)
            var dates: [Date] = [now]

            var cursor = now.addingTimeInterval(timelineStep)
            while cursor <= horizon {
                dates.append(cursor)
                cursor = cursor.addingTimeInterval(timelineStep)
            }

            // User requirement: exactly 12:00 old is still allowed; once it is OVER 12
            // minutes old the BG/trend disappear. Add a transition one second later.
            if let latest = state.bgReadingDate {
                let staleSwitch = latest.addingTimeInterval(staleAfter + 1)
                if staleSwitch > now, staleSwitch <= horizon {
                    dates.append(staleSwitch)
                }
            }

            let uniqueDates = dates.sorted().reduce(into: [Date]()) { result, candidate in
                if result.last.map({ abs($0.timeIntervalSince(candidate)) > 0.5 }) ?? true {
                    result.append(candidate)
                }
            }

            let entries = uniqueDates.map { Entry(date: $0, widgetState: state) }
            completion(Timeline(entries: entries, policy: .atEnd))
        }
    }
}

extension XDripWatchComplication.Provider {
    func getWidgetStateFromSharedUserDefaults() -> XDripWatchComplication.Entry.WidgetState? {
        guard let shared = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else { return nil }
        guard let encoded = shared.data(
            forKey: "complicationSharedUserDefaults.\(Bundle.main.mainAppBundleIdentifier)"
        ) else { return nil }

        do {
            let data = try JSONDecoder().decode(ComplicationSharedUserDefaultsModel.self, from: encoded)
            let dates = data.bgReadingDatesAsDouble.map { Date(timeIntervalSince1970: $0) }
            return Entry.WidgetState(
                bgReadingValues: data.bgReadingValues,
                bgReadingDates: dates,
                isMgDl: data.isMgDl,
                slopeOrdinal: data.slopeOrdinal,
                deltaValueInUserUnit: data.deltaValueInUserUnit,
                urgentLowLimitInMgDl: data.urgentLowLimitInMgDl,
                lowLimitInMgDl: data.lowLimitInMgDl,
                highLimitInMgDl: data.highLimitInMgDl,
                urgentHighLimitInMgDl: data.urgentHighLimitInMgDl,
                keepAliveIsDisabled: data.keepAliveIsDisabled
            )
        } catch {
            print("Build28 complication state decode failed: \(error.localizedDescription)")
            return nil
        }
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
            urgentHighLimitInMgDl: 180,
            keepAliveIsDisabled: false
        )
    }
}
''', encoding="utf-8")


# -----------------------------------------------------------------------------
# 5) Final user-approved Modular Ultra graph, with TRUE proportional y spacing.
# -----------------------------------------------------------------------------
rect_path = Path("xDrip Watch Complication/Views/AccessoryRectangularView.swift")
rect_path.write_text(r'''//
//  AccessoryRectangularView.swift
//  xDrip Watch Complication Extension
//
//  Build 28: final Modular Ultra 2-hour graph.
//

import Foundation
import SwiftUI

extension XDripWatchComplication.EntryView {
    @ViewBuilder
    var accessoryRectangularView: some View {
        Build28RollingTwoHourGlucoseGraph(entry: entry)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .widgetBackground(backgroundView: Color.clear)
            .accessibilityLabel("Glukoseverlauf der letzten zwei Stunden")
    }
}

private struct Build28RollingTwoHourGlucoseGraph: View {
    let entry: XDripWatchComplication.Entry

    private let minimumMgDl = 0.0
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
            let axisFont: CGFloat = size.width >= 150 ? 13.4 : 12.0
            let timeFont: CGFloat = size.width >= 150 ? 12.5 : 11.2
            let leftMargin: CGFloat = size.width >= 150 ? 31.0 : 28.0
            let rightMargin: CGFloat = 0.5
            let topMargin: CGFloat = 0.5
            let bottomMargin: CGFloat = size.width >= 150 ? 19.5 : 18.0

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

            func drawLabel(_ text: String, at point: CGPoint, anchor: UnitPoint, fontSize: CGFloat) {
                let resolved = context.resolve(
                    Text(text)
                        .font(.system(size: fontSize, weight: .bold))
                        .foregroundStyle(Color.white)
                        .monospacedDigit()
                )
                context.draw(resolved, at: point, anchor: anchor)
            }

            // True linear geometry: 220->160 = 60 mg/dL, 70->40 = 30 mg/dL.
            // The second distance is therefore exactly half of the first.
            for level in [220.0, 160.0, 70.0, 40.0] {
                let y = yPosition(level)
                var line = Path()
                line.move(to: CGPoint(x: plotLeft, y: y))
                line.addLine(to: CGPoint(x: plotRight, y: y))

                let color: Color
                let dash: [CGFloat]
                let width: CGFloat
                switch level {
                case 220:
                    color = .yellow
                    dash = []
                    width = 0.9
                case 160, 70:
                    color = .white
                    dash = [3.0, 3.0]
                    width = 0.78
                default:
                    color = .red
                    dash = []
                    width = 0.9
                }
                context.stroke(line, with: .color(color), style: StrokeStyle(lineWidth: width, dash: dash))

                let anchor: UnitPoint
                if level == 220 {
                    // Top edge of 220 text is exactly on the yellow top border; text extends inward.
                    anchor = UnitPoint(x: 1, y: 0)
                } else if level == 70 {
                    // 70 above its horizontal line.
                    anchor = UnitPoint(x: 1, y: 1)
                } else if level == 40 {
                    // 40 below the red line.
                    anchor = UnitPoint(x: 1, y: 0)
                } else {
                    anchor = UnitPoint(x: 1, y: 0.5)
                }
                drawLabel(String(Int(level)), at: CGPoint(x: plotLeft - 3.0, y: y), anchor: anchor, fontSize: axisFont)
            }

            // Solid white, unlabelled 0 mg/dL baseline.
            let zeroY = yPosition(0)
            var zero = Path()
            zero.move(to: CGPoint(x: plotLeft, y: zeroY))
            zero.addLine(to: CGPoint(x: plotRight, y: zeroY))
            context.stroke(zero, with: .color(.white), lineWidth: 0.9)

            // Exactly three full-hour labels; first and middle have dashed guides.
            let calendar = Calendar.current
            let currentHour = calendar.dateInterval(of: .hour, for: entry.date)?.start ?? entry.date
            let labels = [
                currentHour.addingTimeInterval(-2 * 60 * 60),
                currentHour.addingTimeInterval(-1 * 60 * 60),
                currentHour
            ]
            let fractions: [CGFloat] = [0.0, 0.5, 1.0]

            for fraction in [0.0, 0.5] as [CGFloat] {
                let x = plotLeft + plotWidth * fraction
                var grid = Path()
                grid.move(to: CGPoint(x: x, y: plotTop))
                grid.addLine(to: CGPoint(x: x, y: zeroY))
                context.stroke(
                    grid,
                    with: .color(Color.white.opacity(0.75)),
                    style: StrokeStyle(lineWidth: 0.75, dash: [3.0, 3.0])
                )
            }

            let timeY = size.height - 0.5
            for index in 0..<3 {
                let anchor: UnitPoint = index == 0
                    ? UnitPoint(x: 0, y: 1)
                    : (index == 2 ? UnitPoint(x: 1, y: 1) : UnitPoint(x: 0.5, y: 1))
                drawLabel(
                    Self.timeFormatter.string(from: labels[index]),
                    at: CGPoint(x: plotLeft + plotWidth * fractions[index], y: timeY),
                    anchor: anchor,
                    fontSize: timeFont
                )
            }

            for reading in readings {
                let center = CGPoint(x: xPosition(reading.date), y: yPosition(reading.value))
                let radius: CGFloat = size.width >= 150 ? 2.25 : 1.9
                let dot = Path(ellipseIn: CGRect(
                    x: center.x - radius,
                    y: center.y - radius,
                    width: radius * 2,
                    height: radius * 2
                ))
                context.fill(dot, with: .color(pointColor(reading.value)))
            }

            // Solid current-time edge from the yellow top border to the 0 baseline.
            var nowLine = Path()
            nowLine.move(to: CGPoint(x: plotRight, y: plotTop))
            nowLine.addLine(to: CGPoint(x: plotRight, y: zeroY))
            context.stroke(nowLine, with: .color(.white), lineWidth: 1.1)

            // Highlight only a current reading; never mark anything older than 12 minutes.
            if let latest = readings.last,
               latest.date <= entry.date.addingTimeInterval(60),
               entry.date.timeIntervalSince(latest.date) <= 12 * 60 {
                let center = CGPoint(x: xPosition(latest.date), y: yPosition(latest.value))
                let ringRadius: CGFloat = size.width >= 150 ? 3.6 : 3.0
                let ring = Path(ellipseIn: CGRect(
                    x: center.x - ringRadius,
                    y: center.y - ringRadius,
                    width: ringRadius * 2,
                    height: ringRadius * 2
                ))
                context.stroke(ring, with: .color(.white), lineWidth: 1.0)
            }
        }
    }
}
''', encoding="utf-8")


# -----------------------------------------------------------------------------
# 6) New BG publication: write first, then reload exactly these three kinds.
# -----------------------------------------------------------------------------
watch_state_path = Path("xDrip Watch App/DataModels/WatchStateModel.swift")
watch_state = watch_state_path.read_text(encoding="utf-8")
old_reload = '''        // now that the new data is stored in the app group, try to force the complications to reload\n        WidgetCenter.shared.reloadAllTimelines()'''
new_reload = '''        // The App-Group write above is complete. Reload the three Build-28 complications\n        // immediately so a new BG never waits for the minute timeline to advance.\n        for complicationKind in ["xDripGraphV28", "xDripBGV28", "xDripTrendV28"] {\n            WidgetCenter.shared.reloadTimelines(ofKind: complicationKind)\n        }'''
require(watch_state.count(old_reload) == 1,
        "Build28: expected the original reloadAllTimelines publication block exactly once")
watch_state = watch_state.replace(old_reload, new_reload, 1)
watch_state_path.write_text(watch_state, encoding="utf-8")

print("Build 28 applied: clean upstream WidgetKit target + three final complications + proportional graph.")
