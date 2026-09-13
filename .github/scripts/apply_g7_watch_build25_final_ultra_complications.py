from pathlib import Path


# Build 25 runs AFTER the complete Build 24 chain.
# User-approved goals:
# - Modular Ultra center: Martin’s xDrip Graph, maximum usable rectangular area
# - rolling 2-hour graph with exactly three full-hour labels
# - vertical hour guides at the first and middle full hour, 30% brighter than Build 24
# - horizontal scale: 220 yellow solid, 160 white dashed, 70 white dashed, 40 red solid
# - 70 label above its line, 40 label below its line; 0 baseline white and unlabelled
# - solid right NOW line down to the 0 baseline
# - two selectable circular complications only:
#     1) xDrip BG mg/dL: number only + outer elapsed-minute tick ring
#        fresh ring = light turquoise; >12 min = red ring and value becomes ---
#     2) BG Trend + Δ mg/dL: trend arrow + delta; >12 min becomes ---
# - minute-age visualization updates every minute via prebuilt timeline entries
# - ClockKit discovery bridge publishes three descriptors and maps them to the three WidgetKit kinds
# - force descriptor reload when the Watch app launches


# -----------------------------------------------------------------------------
# 1) Widget bundle: one rectangular graph + exactly two circular widgets.
# -----------------------------------------------------------------------------
widget = Path("xDrip Watch Complication/XDripWatchComplication.swift")
widget.write_text(r'''//
//  XDripWatchComplication.swift
//  xDrip Watch Complication
//
//  Build 25: final Modular Ultra graph + two circular xDrip complications.
//

import WidgetKit
import SwiftUI
import Foundation

// Kept because Entry.swift (introduced in Build 21) stores a displayMode field.
// Build 25 exposes separate WidgetKit kinds instead of a third configurable mode.
enum XDripComplicationDisplayMode: String {
    case bg
    case delta
    case lastTime
}

struct XDripWatchComplication: Widget {
    let kind: String = "xDripWatchComplication"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: Provider()) { entry in
            XDripWatchComplication.EntryView(entry: entry)
        }
        .configurationDisplayName("Martin’s xDrip Graph")
        .description("2-Stunden-xDrip-Glukosegraph für Modular Ultra")
        .supportedFamilies([.accessoryRectangular])
        .contentMarginsDisabled()
    }
}

struct XDripBGComplication: Widget {
    let kind: String = "xDripBGComplication"

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
    let kind: String = "xDripTrendComplication"

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


extension XDripWatchComplication.Entry {
    private var build25StaleAfter: TimeInterval { 12 * 60 }

    var build25LatestDate: Date? { widgetState.bgReadingDates?.first }
    var build25LatestValue: Double? { widgetState.bgReadingValues?.first }

    var build25AgeSeconds: TimeInterval {
        guard let date = build25LatestDate else { return .infinity }
        return max(0, self.date.timeIntervalSince(date))
    }

    var build25AgeMinutes: Int {
        guard build25AgeSeconds.isFinite else { return 60 }
        return max(0, Int(floor(build25AgeSeconds / 60.0)))
    }

    var build25IsFresh: Bool {
        guard let date = build25LatestDate else { return false }
        return date <= self.date.addingTimeInterval(60)
            && build25AgeSeconds <= build25StaleAfter
    }

    var build25BGText: String {
        guard build25IsFresh, let value = build25LatestValue else { return "---" }
        if value >= 400 { return "HIGH" }
        if value >= 40 { return String(Int(value.rounded())) }
        if value > 12 { return "LOW" }
        return "---"
    }

    var build25TrendArrow: String {
        guard build25IsFresh else { return "" }
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

    var build25DeltaMgDlText: String {
        guard build25IsFresh, let delta = widgetState.deltaValueInUserUnit else { return "---" }
        let deltaMgDl = widgetState.isMgDl ? delta : delta * 18.0
        return String(format: "%+.0f", deltaMgDl)
    }
}


private struct Build25MinuteRing: View {
    let ageMinutes: Int
    let isFresh: Bool

    private let turquoise = Color(red: 0.30, green: 0.95, blue: 0.95)

    var body: some View {
        GeometryReader { geometry in
            let diameter = min(geometry.size.width, geometry.size.height)
            let activeTicks = min(max(ageMinutes, 0), 60)
            let activeColor: Color = isFresh ? turquoise : .red

            ZStack {
                ForEach(0..<60, id: \.self) { index in
                    Capsule()
                        .fill(index < activeTicks ? activeColor : Color.white.opacity(0.16))
                        .frame(
                            width: index % 5 == 0 ? 1.8 : 1.25,
                            height: index % 5 == 0 ? 5.6 : 4.1
                        )
                        .offset(y: -(diameter / 2 - 4.0))
                        .rotationEffect(.degrees(Double(index) * 6.0))
                }
            }
            .frame(width: geometry.size.width, height: geometry.size.height)
        }
        .allowsHitTesting(false)
    }
}


struct XDripBGMinuteCircleView: View {
    let entry: XDripWatchComplication.Entry

    var body: some View {
        ZStack {
            Build25MinuteRing(
                ageMinutes: entry.build25AgeMinutes,
                isFresh: entry.build25IsFresh
            )

            Text(entry.build25BGText)
                .font(.system(size: 22, weight: .bold, design: .rounded))
                .foregroundStyle(Color.white)
                .monospacedDigit()
                .minimumScaleFactor(0.55)
                .lineLimit(1)
                .padding(8)
        }
        .widgetBackground(backgroundView: Color.clear)
        .accessibilityLabel(entry.build25IsFresh
            ? "Blutzucker \(entry.build25BGText) Milligramm pro Deziliter, \(entry.build25AgeMinutes) Minuten alt"
            : "Kein aktueller Blutzuckerwert")
    }
}


struct XDripTrendDeltaCircleView: View {
    let entry: XDripWatchComplication.Entry

    var body: some View {
        Group {
            if entry.build25IsFresh {
                VStack(spacing: -2) {
                    Text(entry.build25TrendArrow)
                        .font(.system(size: 22, weight: .bold, design: .rounded))
                        .foregroundStyle(Color.white)
                        .lineLimit(1)

                    Text(entry.build25DeltaMgDlText)
                        .font(.system(size: 17, weight: .bold, design: .rounded))
                        .foregroundStyle(Color.white)
                        .monospacedDigit()
                        .minimumScaleFactor(0.55)
                        .lineLimit(1)
                }
            } else {
                Text("---")
                    .font(.system(size: 20, weight: .bold, design: .rounded))
                    .foregroundStyle(Color.secondary)
                    .monospacedDigit()
            }
        }
        .widgetBackground(backgroundView: Color.clear)
        .accessibilityLabel(entry.build25IsFresh
            ? "Trend \(entry.build25TrendArrow), Änderung \(entry.build25DeltaMgDlText) Milligramm pro Deziliter"
            : "Kein aktueller Trendwert")
    }
}
''', encoding="utf-8")


# -----------------------------------------------------------------------------
# 2) EntryView: the graph widget always renders the rectangular graph.
# -----------------------------------------------------------------------------
entry_view = Path("xDrip Watch Complication/XDripWatchComplication+EntryView.swift")
entry_view.write_text(r'''//
//  XDripWatchComplication+EntryView.swift
//  xDrip Watch Complication Extension
//
//  Build 25: rectangular graph entry view.
//

import SwiftUI
import Foundation
import WidgetKit

extension XDripWatchComplication {
    struct EntryView: View {
        @Environment(\.widgetFamily) private var widgetFamily
        var entry: Entry

        var body: some View {
            switch widgetFamily {
            case .accessoryRectangular:
                accessoryRectangularView
            default:
                XDripBGMinuteCircleView(entry: entry)
            }
        }
    }
}
''', encoding="utf-8")


# -----------------------------------------------------------------------------
# 3) Provider: minute timeline entries + 5-minute App-Group re-read fallback.
# -----------------------------------------------------------------------------
provider = Path("xDrip Watch Complication/XDripWatchComplication+Provider.swift")
provider.write_text(r'''//
//  XDripWatchComplication+Provider.swift
//  xDrip Watch Complication Extension
//
//  Build 25: minute-age timeline + 5-minute App Group re-read.
//

import SwiftUI
import WidgetKit
import Foundation

extension XDripWatchComplication {
    struct Provider: TimelineProvider {
        private let refreshInterval: TimeInterval = 5 * 60
        private let timelineStep: TimeInterval = 60
        private let staleAfter: TimeInterval = 12 * 60

        func placeholder(in context: Context) -> Entry {
            var entry = Entry.placeholder
            entry.displayMode = .bg
            return entry
        }

        func getSnapshot(in context: Context, completion: @escaping (Entry) -> Void) {
            let state = getWidgetStateFromSharedUserDefaults() ?? sampleWidgetStateFromProvider
            completion(Entry(date: .now, widgetState: state, displayMode: .bg))
        }

        func getTimeline(in context: Context, completion: @escaping (Timeline<Entry>) -> Void) {
            let now = Date()
            let state = getWidgetStateFromSharedUserDefaults() ?? sampleWidgetStateFromProvider
            let nextRefresh = now.addingTimeInterval(refreshInterval)
            var entryDates: [Date] = [now]

            // Prebuild one entry per minute. The circular age ring therefore changes every minute
            // without requiring the Watch app to be opened or a new sensor value to arrive.
            var cursor = now.addingTimeInterval(timelineStep)
            while cursor <= nextRefresh {
                entryDates.append(cursor)
                cursor = cursor.addingTimeInterval(timelineStep)
            }

            // At >12 minutes the BG and trend must be hidden. Add an exact stale transition
            // one second after 12:00 so a value that is exactly 12 minutes old is still permitted.
            if let latestReadingDate = state.bgReadingDate {
                let staleSwitch = latestReadingDate.addingTimeInterval(staleAfter + 1)
                if staleSwitch > now, staleSwitch <= nextRefresh {
                    entryDates.append(staleSwitch)
                }
            }

            let uniqueDates = entryDates
                .sorted()
                .reduce(into: [Date]()) { result, date in
                    if result.last.map({ abs($0.timeIntervalSince(date)) > 0.5 }) ?? true {
                        result.append(date)
                    }
                }

            let entries = uniqueDates.map {
                Entry(date: $0, widgetState: state, displayMode: .bg)
            }
            completion(Timeline(entries: entries, policy: .after(nextRefresh)))
        }
    }
}


extension XDripWatchComplication.Provider {
    func getWidgetStateFromSharedUserDefaults() -> XDripWatchComplication.Entry.WidgetState? {
        guard let sharedUserDefaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else { return nil }
        guard let encodedLatestReadings = sharedUserDefaults.data(
            forKey: "complicationSharedUserDefaults.\(Bundle.main.mainAppBundleIdentifier)"
        ) else { return nil }

        do {
            let data = try JSONDecoder().decode(ComplicationSharedUserDefaultsModel.self, from: encodedLatestReadings)
            let bgReadingDates = data.bgReadingDatesAsDouble.map { Date(timeIntervalSince1970: $0) }
            let dataSource = sharedUserDefaults.string(
                forKey: "complicationDataSource.\(Bundle.main.mainAppBundleIdentifier)"
            )

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
            print("Build25 complication state decode failed: \(error.localizedDescription)")
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
            urgentHighLimitInMgDl: 180
        )
    }
}
''', encoding="utf-8")


# -----------------------------------------------------------------------------
# 4) Final maximum-area 2-hour Modular Ultra graph.
# -----------------------------------------------------------------------------
rect = Path("xDrip Watch Complication/Views/AccessoryRectangularView.swift")
rect.write_text(r'''//
//  AccessoryRectangularView.swift
//  xDrip Watch Complication Extension
//
//  Build 25: user-approved maximum-area Modular Ultra 2-hour graph.
//

import Foundation
import SwiftUI

extension XDripWatchComplication.EntryView {
    @ViewBuilder
    var accessoryRectangularView: some View {
        Build25RollingTwoHourGlucoseGraph(entry: entry)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .widgetBackground(backgroundView: Color.clear)
            .accessibilityLabel("Glukoseverlauf der letzten zwei Stunden")
    }
}

private struct Build25RollingTwoHourGlucoseGraph: View {
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
            // Maximum graph footprint while preserving the approved large white labels.
            let labelFontSize: CGFloat = size.width >= 150 ? 13.4 : 12.2
            let leftMargin: CGFloat = size.width >= 150 ? 31.0 : 28.0
            let rightMargin: CGFloat = 0.5
            let topMargin: CGFloat = 1.5
            let bottomMargin: CGFloat = size.width >= 150 ? 20.5 : 19.0

            let plotLeft = leftMargin
            let plotRight = max(plotLeft + 1, size.width - rightMargin)
            let plotTop = topMargin
            let plotBottom = max(plotTop + 1, size.height - bottomMargin)
            let plotWidth = max(1, plotRight - plotLeft)
            let plotHeight = max(1, plotBottom - plotTop)

            func yPosition(_ value: Double) -> CGFloat {
                let clamped = min(max(value, minimumMgDl), maximumMgDl)

                // Monitor-style piecewise scale: keep 70 and 40 clearly separated despite their
                // 30 mg/dL numerical difference, while retaining the full 0...220 range.
                let fraction: CGFloat
                if clamped >= 160 {
                    fraction = CGFloat((220.0 - clamped) / 60.0) * 0.24
                } else if clamped >= 70 {
                    fraction = 0.24 + CGFloat((160.0 - clamped) / 90.0) * 0.34
                } else if clamped >= 40 {
                    fraction = 0.58 + CGFloat((70.0 - clamped) / 30.0) * 0.22
                } else {
                    fraction = 0.80 + CGFloat((40.0 - clamped) / 40.0) * 0.20
                }
                return plotTop + fraction * plotHeight
            }

            func xPosition(_ date: Date) -> CGFloat {
                let start = entry.date.addingTimeInterval(-visibleDuration)
                let elapsed = date.timeIntervalSince(start)
                let fraction = min(max(elapsed / visibleDuration, 0), 1)
                return plotLeft + CGFloat(fraction) * plotWidth
            }

            func drawLabel(_ text: String, at point: CGPoint, anchor: UnitPoint) {
                let label = context.resolve(
                    Text(text)
                        .font(.system(size: labelFontSize, weight: .bold))
                        .foregroundStyle(Color.white)
                        .monospacedDigit()
                )
                context.draw(label, at: point, anchor: anchor)
            }

            // Horizontal scale requested for Build 25.
            for level in [220.0, 160.0, 70.0, 40.0] {
                let y = yPosition(level)
                var line = Path()
                line.move(to: CGPoint(x: plotLeft, y: y))
                line.addLine(to: CGPoint(x: plotRight, y: y))

                let color: Color
                let dash: [CGFloat]
                let lineWidth: CGFloat
                if level == 220 {
                    color = .yellow
                    dash = []
                    lineWidth = 0.85
                } else if level == 160 || level == 70 {
                    color = .white
                    dash = [3.0, 3.0]
                    lineWidth = 0.75
                } else {
                    color = .red
                    dash = []
                    lineWidth = 0.85
                }
                context.stroke(line, with: .color(color), style: StrokeStyle(lineWidth: lineWidth, dash: dash))

                // Preserve the requested label-line geometry:
                // 220: line at the top edge of the text; 70 above its line; 40 below its line.
                let anchor: UnitPoint
                if level == 220 {
                    anchor = UnitPoint(x: 1, y: 0)
                } else if level == 70 {
                    anchor = UnitPoint(x: 1, y: 1)
                } else if level == 40 {
                    anchor = UnitPoint(x: 1, y: 0)
                } else {
                    anchor = UnitPoint(x: 1, y: 0.5)
                }
                drawLabel(String(Int(level)), at: CGPoint(x: plotLeft - 3.0, y: y), anchor: anchor)
            }

            // Unlabelled 0 mg/dL baseline, white from left to right.
            let zeroY = yPosition(0)
            var zeroLine = Path()
            zeroLine.move(to: CGPoint(x: plotLeft, y: zeroY))
            zeroLine.addLine(to: CGPoint(x: plotRight, y: zeroY))
            context.stroke(zeroLine, with: .color(.white), lineWidth: 0.85)

            // Exactly three full-hour labels. Dashed guides are at the first and middle hour.
            let calendar = Calendar.current
            let currentHour = calendar.dateInterval(of: .hour, for: entry.date)?.start ?? entry.date
            let hourLabels = [
                currentHour.addingTimeInterval(-2 * 60 * 60),
                currentHour.addingTimeInterval(-1 * 60 * 60),
                currentHour
            ]
            let hourFractions: [CGFloat] = [0.0, 0.5, 1.0]

            // Build 24 used ~0.58 secondary opacity. Build 25 is about 30% brighter.
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

            let labelY = size.height - 0.5
            for index in 0..<3 {
                let fraction = hourFractions[index]
                let anchor: UnitPoint = index == 0
                    ? UnitPoint(x: 0, y: 1)
                    : (index == 2 ? UnitPoint(x: 1, y: 1) : UnitPoint(x: 0.5, y: 1))
                drawLabel(
                    Self.timeFormatter.string(from: hourLabels[index]),
                    at: CGPoint(x: plotLeft + plotWidth * fraction, y: labelY),
                    anchor: anchor
                )
            }

            // Historical glucose points.
            for reading in readings {
                let center = CGPoint(x: xPosition(reading.date), y: yPosition(reading.value))
                let radius: CGFloat = size.width >= 150 ? 2.25 : 1.95
                let dot = Path(ellipseIn: CGRect(
                    x: center.x - radius,
                    y: center.y - radius,
                    width: radius * 2,
                    height: radius * 2
                ))
                context.fill(dot, with: .color(pointColor(reading.value)))
            }

            // Solid right NOW line reaches the 0 baseline.
            var currentLine = Path()
            currentLine.move(to: CGPoint(x: plotRight, y: plotTop))
            currentLine.addLine(to: CGPoint(x: plotRight, y: zeroY))
            context.stroke(currentLine, with: .color(Color.white.opacity(0.98)), lineWidth: 1.15)

            // Latest-point ring only while the reading is no older than 12 minutes.
            if let latest = readings.last,
               entry.date.timeIntervalSince(latest.date) <= 12 * 60 {
                let center = CGPoint(x: xPosition(latest.date), y: yPosition(latest.value))
                let ringRadius: CGFloat = size.width >= 150 ? 3.6 : 3.0
                let ring = Path(ellipseIn: CGRect(
                    x: center.x - ringRadius,
                    y: center.y - ringRadius,
                    width: ringRadius * 2,
                    height: ringRadius * 2
                ))
                context.stroke(ring, with: .color(Color.white.opacity(0.98)), lineWidth: 1.0)
            }
        }
    }
}
''', encoding="utf-8")


# -----------------------------------------------------------------------------
# 5) Reload all three Build 25 WidgetKit kinds immediately on every changed BG state.
# -----------------------------------------------------------------------------
watch_state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")
watch_text = watch_state.read_text(encoding="utf-8")
old_reload = '            WidgetCenter.shared.reloadTimelines(ofKind: "xDripWatchComplication")'
new_reload = '''            for complicationKind in [
                "xDripWatchComplication",
                "xDripBGComplication",
                "xDripTrendComplication"
            ] {
                WidgetCenter.shared.reloadTimelines(ofKind: complicationKind)
            }'''
if watch_text.count(old_reload) != 1:
    raise RuntimeError(f"Build25 reload patch expected one match, found {watch_text.count(old_reload)}")
watch_state.write_text(watch_text.replace(old_reload, new_reload, 1), encoding="utf-8")


# -----------------------------------------------------------------------------
# 6) ClockKit discovery bridge: publish all three selectable descriptors, provide
#    non-nil picker samples/current entries, and map each descriptor to its WidgetKit kind.
# -----------------------------------------------------------------------------
watch_app = Path("xDrip Watch App/xDripWatchApp.swift")
app_text = watch_app.read_text(encoding="utf-8")
marker = "\n// MARK: - Complication discovery bridge"
if marker in app_text:
    app_text = app_text.split(marker, 1)[0].rstrip() + "\n"

if "import ClockKit" not in app_text:
    app_text = app_text.replace("import SwiftUI\n", "import SwiftUI\nimport ClockKit\n", 1)

# Force ClockKit to ask again for the descriptors after installing Build 25.
app_anchor = "    @StateObject var watchState = WatchStateModel()\n    \n    var body: some Scene {"
if app_anchor in app_text:
    app_text = app_text.replace(
        app_anchor,
        '''    @StateObject var watchState = WatchStateModel()

    init() {
        CLKComplicationServer.sharedInstance().reloadComplicationDescriptors()
    }
    
    var body: some Scene {''',
        1,
    )
elif "reloadComplicationDescriptors()" not in app_text:
    raise RuntimeError("Build25 could not find Watch App init anchor")

app_text += r'''

// MARK: - Complication discovery bridge
// Build 25 publishes three explicit selectable complication descriptors. ClockKit supplies
// picker metadata/placeholders; WidgetKit remains the real renderer and timeline engine.
final class ComplicationController: NSObject, CLKComplicationDataSource, CLKComplicationWidgetMigrator {
    private static let graphDescriptorIdentifier = "xDrip.graph"
    private static let bgDescriptorIdentifier = "xDrip.bg"
    private static let trendDescriptorIdentifier = "xDrip.trend"

    func getComplicationDescriptors(handler: @escaping ([CLKComplicationDescriptor]) -> Void) {
        handler([
            CLKComplicationDescriptor(
                identifier: Self.graphDescriptorIdentifier,
                displayName: "Martin’s xDrip Graph",
                supportedFamilies: [.graphicRectangular]
            ),
            CLKComplicationDescriptor(
                identifier: Self.bgDescriptorIdentifier,
                displayName: "xDrip BG mg/dL",
                supportedFamilies: [.graphicCircular]
            ),
            CLKComplicationDescriptor(
                identifier: Self.trendDescriptorIdentifier,
                displayName: "BG Trend + Δ mg/dL",
                supportedFamilies: [.graphicCircular]
            )
        ])
    }

    private func template(for complication: CLKComplication) -> CLKComplicationTemplate? {
        switch complication.family {
        case .graphicRectangular:
            return CLKComplicationTemplateGraphicRectangularStandardBody(
                headerTextProvider: CLKSimpleTextProvider(text: "Martin’s xDrip Graph"),
                body1TextProvider: CLKSimpleTextProvider(text: "112 →"),
                body2TextProvider: CLKSimpleTextProvider(text: "2 h Glukose")
            )

        case .graphicCircular:
            if complication.identifier == Self.trendDescriptorIdentifier {
                return CLKComplicationTemplateGraphicCircularStackText(
                    line1TextProvider: CLKSimpleTextProvider(text: "→"),
                    line2TextProvider: CLKSimpleTextProvider(text: "+6")
                )
            }
            return CLKComplicationTemplateGraphicCircularStackText(
                line1TextProvider: CLKSimpleTextProvider(text: "112"),
                line2TextProvider: CLKSimpleTextProvider(text: "2m")
            )

        default:
            return nil
        }
    }

    func getLocalizableSampleTemplate(
        for complication: CLKComplication,
        withHandler handler: @escaping (CLKComplicationTemplate?) -> Void
    ) {
        handler(template(for: complication))
    }

    func getCurrentTimelineEntry(
        for complication: CLKComplication,
        withHandler handler: @escaping (CLKComplicationTimelineEntry?) -> Void
    ) {
        guard let template = template(for: complication) else {
            handler(nil)
            return
        }
        handler(CLKComplicationTimelineEntry(date: Date(), complicationTemplate: template))
    }

    var widgetMigrator: CLKComplicationWidgetMigrator { self }

    func getWidgetConfiguration(
        from complicationDescriptor: CLKComplicationDescriptor,
        completionHandler: @escaping (CLKComplicationWidgetMigrationConfiguration?) -> Void
    ) {
        guard let watchBundleIdentifier = Bundle.main.bundleIdentifier else {
            completionHandler(nil)
            return
        }

        let kind: String
        switch complicationDescriptor.identifier {
        case Self.graphDescriptorIdentifier:
            kind = "xDripWatchComplication"
        case Self.bgDescriptorIdentifier:
            kind = "xDripBGComplication"
        case Self.trendDescriptorIdentifier:
            kind = "xDripTrendComplication"
        default:
            completionHandler(nil)
            return
        }

        completionHandler(
            CLKComplicationStaticWidgetMigrationConfiguration(
                kind: kind,
                extensionBundleIdentifier: watchBundleIdentifier + ".xDripWatchComplication"
            )
        )
    }
}
'''
watch_app.write_text(app_text, encoding="utf-8")

print("Build 25 applied: final graph, minute-age BG ring, trend/delta complication and picker descriptors.")
