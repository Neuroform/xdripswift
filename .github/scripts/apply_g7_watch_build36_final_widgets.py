from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# -----------------------------------------------------------------------------
# Build 36 final complication architecture.
# Base: verified historical Watch chain through Build 18 + Build 34 graph-only patch.
# Goals:
# - rectangular complication: graph ONLY, 150 min, maximum usable area
# - graph scale: 0 white solid / 70 red / 160 yellow / 200 white dashed
# - no 40 / 220 axis levels
# - stronger dashed vertical time guides
# - separate circular BG and Delta complications, no third circular complication
# - BG circle thresholds: <70 red, 70...159 green, >=160 yellow
# - white trend arrow; elapsed-time bezel runs counter-clockwise
# - >6 min dimmed BG; >12 min BG becomes --- and bezel turns red
# - Delta sign always white; magnitude 0...3 white, 4...7 yellow, >=8 red
# - exact 6-minute and 12-minute timeline transition entries
# -----------------------------------------------------------------------------


# 1) Three separately selectable widgets: Graph, BG, Delta.
widget = Path("xDrip Watch Complication/XDripWatchComplication.swift")
widget.write_text(r'''//
//  XDripWatchComplication.swift
//  xDrip Watch Complication
//
//  Build 36: final graph + two circular complications.
//

import WidgetKit
import SwiftUI

// Keep this type as the namespace used by Entry/Provider/EntryView extensions.
struct XDripWatchComplication: Widget {
    let kind: String = "xDripGraphV33"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: Provider()) { entry in
            XDripWatchComplication.EntryView(entry: entry)
        }
        .configurationDisplayName("xDrip Graph")
        .description("xDrip 150-minute glucose graph")
        .supportedFamilies([.accessoryRectangular])
        .contentMarginsDisabled()
    }
}

struct XDripBGComplicationV36: Widget {
    let kind: String = "xDripBGV36"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: XDripWatchComplication.Provider()) { entry in
            XDripBGCircleV36View(entry: entry)
        }
        .configurationDisplayName("xDrip BG")
        .description("Current glucose and trend")
        .supportedFamilies([.accessoryCircular])
        .contentMarginsDisabled()
    }
}

struct XDripDeltaComplicationV36: Widget {
    let kind: String = "xDripDeltaV36"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: XDripWatchComplication.Provider()) { entry in
            XDripDeltaCircleV36View(entry: entry)
        }
        .configurationDisplayName("xDrip Delta")
        .description("Glucose change since the previous reading")
        .supportedFamilies([.accessoryCircular])
        .contentMarginsDisabled()
    }
}

@main
struct XDripWatchComplicationBundleV36: WidgetBundle {
    @WidgetBundleBuilder
    var body: some Widget {
        XDripWatchComplication()
        XDripBGComplicationV36()
        XDripDeltaComplicationV36()
    }
}
''', encoding="utf-8")


# 2) Final circular BG + Delta rendering.
circular = Path("xDrip Watch Complication/Views/AccessoryCircularView.swift")
circular.write_text(r'''//
//  AccessoryCircularView.swift
//  xDrip Watch Complication Extension
//
//  Build 36: final separate BG and Delta circles.
//

import Foundation
import SwiftUI

private extension XDripWatchComplication.Entry {
    var v36LatestDate: Date? { widgetState.bgReadingDates?.first }
    var v36LatestValue: Double? { widgetState.bgReadingValues?.first }

    var v36Age: TimeInterval {
        guard let date = v36LatestDate else { return .infinity }
        return max(0, self.date.timeIntervalSince(date))
    }

    var v36IsDimmed: Bool { v36Age > 6 * 60 && v36Age <= 12 * 60 }
    var v36IsStale: Bool { v36Age > 12 * 60 }

    var v36BGColor: Color {
        guard let value = v36LatestValue, !v36IsStale else { return .gray }
        let base: Color
        if value < 70 {
            base = .red
        } else if value < 160 {
            base = .green
        } else {
            base = .yellow
        }
        return v36IsDimmed ? base.opacity(0.38) : base
    }

    var v36TrendArrow: String {
        guard !v36IsStale else { return "" }
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

    var v36Delta: Double? {
        guard !v36IsStale else { return nil }
        return widgetState.deltaValueInUserUnit
    }
}

struct XDripBGCircleV36View: View {
    let entry: XDripWatchComplication.Entry

    private var progress: Double {
        min(max(entry.v36Age / (12 * 60), 0), 1)
    }

    private var bezelColor: Color {
        if entry.v36IsStale { return .red }
        if entry.v36IsDimmed { return .gray }
        return .yellow
    }

    private var glucoseText: String {
        guard !entry.v36IsStale else { return "---" }
        return entry.widgetState.bgValueStringInUserChosenUnit()
    }

    var body: some View {
        GeometryReader { geometry in
            let side = min(geometry.size.width, geometry.size.height)
            let lineWidth = max(2.2, side * 0.065)
            let tickOuter = side * 0.47
            let tickInnerShort = side * 0.425
            let tickInnerLong = side * 0.395

            ZStack {
                Circle()
                    .stroke(Color.secondary.opacity(0.35), lineWidth: lineWidth)
                    .padding(lineWidth / 2)

                // Elapsed-time bezel: starts at 12 o'clock and grows counter-clockwise.
                Circle()
                    .trim(from: 0, to: progress)
                    .stroke(bezelColor, style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                    .scaleEffect(x: -1, y: 1)
                    .padding(lineWidth / 2)

                // Minute ticks; cardinal positions are longer.
                Canvas { context, size in
                    let center = CGPoint(x: size.width / 2, y: size.height / 2)
                    for index in 0..<12 {
                        let angle = Double(index) * .pi / 6.0 - .pi / 2.0
                        let isCardinal = index % 3 == 0
                        let inner = isCardinal ? tickInnerLong : tickInnerShort
                        let start = CGPoint(
                            x: center.x + CGFloat(cos(angle)) * inner,
                            y: center.y + CGFloat(sin(angle)) * inner
                        )
                        let end = CGPoint(
                            x: center.x + CGFloat(cos(angle)) * tickOuter,
                            y: center.y + CGFloat(sin(angle)) * tickOuter
                        )
                        var p = Path()
                        p.move(to: start)
                        p.addLine(to: end)
                        context.stroke(
                            p,
                            with: .color(Color.white.opacity(isCardinal ? 0.78 : 0.38)),
                            lineWidth: isCardinal ? 1.5 : 0.8
                        )
                    }
                }

                HStack(alignment: .firstTextBaseline, spacing: max(1, side * 0.02)) {
                    Text(glucoseText)
                        .font(.system(size: side * 0.34, weight: .bold, design: .rounded))
                        .foregroundStyle(entry.v36BGColor)
                        .minimumScaleFactor(0.50)
                        .lineLimit(1)
                        .monospacedDigit()

                    if !entry.v36TrendArrow.isEmpty {
                        Text(entry.v36TrendArrow)
                            .font(.system(size: side * 0.26, weight: .bold))
                            .foregroundStyle(Color.white)
                            .minimumScaleFactor(0.55)
                            .lineLimit(1)
                    }
                }
                .padding(.horizontal, side * 0.13)
            }
        }
        .widgetBackground(backgroundView: Color.clear)
    }
}

struct XDripDeltaCircleV36View: View {
    let entry: XDripWatchComplication.Entry

    private var signText: String {
        guard let delta = entry.v36Delta else { return "" }
        return delta < 0 ? "−" : "+"
    }

    private var magnitudeText: String {
        guard let delta = entry.v36Delta else { return "--" }
        if entry.widgetState.isMgDl {
            return String(format: "%.0f", abs(delta))
        }
        return String(format: "%.1f", abs(delta))
    }

    private var magnitudeColor: Color {
        guard let delta = entry.v36Delta else { return .gray }
        let magnitude = abs(delta)
        let base: Color
        if magnitude <= 3 {
            base = .white
        } else if magnitude <= 7 {
            base = .yellow
        } else {
            base = .red
        }
        return entry.v36IsDimmed ? base.opacity(0.38) : base
    }

    var body: some View {
        GeometryReader { geometry in
            let side = min(geometry.size.width, geometry.size.height)
            ZStack {
                Circle()
                    .stroke(Color.secondary.opacity(0.45), lineWidth: max(2, side * 0.045))

                HStack(alignment: .firstTextBaseline, spacing: 1) {
                    Text(signText)
                        .font(.system(size: side * 0.27, weight: .bold, design: .rounded))
                        .foregroundStyle(Color.white)
                        .lineLimit(1)

                    Text(magnitudeText)
                        .font(.system(size: side * 0.34, weight: .bold, design: .rounded))
                        .foregroundStyle(magnitudeColor)
                        .minimumScaleFactor(0.55)
                        .lineLimit(1)
                        .monospacedDigit()
                }
                .padding(.horizontal, side * 0.10)
            }
        }
        .widgetBackground(backgroundView: Color.clear)
    }
}

// Legacy EntryView circular path is intentionally unused in Build 36 because BG and Delta
// are separate widgets. Keep a harmless fallback for previews/older family dispatch.
extension XDripWatchComplication.EntryView {
    @ViewBuilder
    var accessoryCircularView: some View {
        XDripBGCircleV36View(entry: entry)
    }
}
''', encoding="utf-8")


# 3) Final rectangular graph. Use full WidgetKit area, but preserve label clearance.
rect = Path("xDrip Watch Complication/Views/AccessoryRectangularView.swift")
rect.write_text(r'''//
//  AccessoryRectangularView.swift
//  xDrip Watch Complication Extension
//
//  Build 36: maximum-area 150-minute graph.
//

import Foundation
import SwiftUI

extension XDripWatchComplication.EntryView {
    @ViewBuilder
    var accessoryRectangularView: some View {
        RollingTwoHourGlucoseGraph(entry: entry)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .widgetBackground(backgroundView: Color.clear)
    }
}

private struct RollingTwoHourGlucoseGraph: View {
    let entry: XDripWatchComplication.Entry

    private let minimumMgDl = 0.0
    private let maximumMgDl = 200.0
    private let visibleDuration: TimeInterval = 150 * 60

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
        if value < 70 { return .red }
        if value >= 160 { return .yellow }
        return .green
    }

    var body: some View {
        Canvas { context, size in
            // Build 36: minimal but safe label margins. Top and left are deliberately reclaimed
            // versus earlier builds, while labels remain completely inside the rounded widget.
            let labelFontSize: CGFloat = size.width >= 150 ? 9.2 : 8.5
            let leftMargin: CGFloat = size.width >= 150 ? 22.0 : 20.0
            let rightMargin: CGFloat = 1.0
            let topMargin: CGFloat = 2.0
            let bottomMargin: CGFloat = size.height < 60 ? 13.0 : 15.0

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

            func drawLabel(_ text: String, at point: CGPoint, anchor: UnitPoint) {
                let label = context.resolve(
                    Text(text)
                        .font(.system(size: labelFontSize, weight: .semibold))
                        .foregroundStyle(Color.white)
                        .monospacedDigit()
                )
                context.draw(label, at: point, anchor: anchor)
            }

            // Horizontal reference levels requested for Build 36.
            for level in [200.0, 160.0, 70.0, 0.0] {
                let y = yPosition(level)
                let trim: CGFloat = (level == 200.0 || level == 0.0) ? 4.0 : 0.0
                var path = Path()
                path.move(to: CGPoint(x: plotLeft, y: y))
                path.addLine(to: CGPoint(x: max(plotLeft + 1, plotRight - trim), y: y))

                let color: Color
                let dash: [CGFloat]
                switch Int(level) {
                case 200:
                    color = .white
                    dash = [3.0, 2.5]
                case 160:
                    color = .yellow
                    dash = []
                case 70:
                    color = .red
                    dash = []
                default:
                    color = .white
                    dash = []
                }
                context.stroke(path, with: .color(color), style: StrokeStyle(lineWidth: 0.85, dash: dash))

                let anchor: UnitPoint
                if level == 200.0 {
                    anchor = UnitPoint(x: 1, y: 0)
                } else if level == 0.0 {
                    anchor = UnitPoint(x: 1, y: 1)
                } else {
                    anchor = UnitPoint(x: 1, y: 0.5)
                }
                drawLabel(String(Int(level)), at: CGPoint(x: plotLeft - 3.0, y: y), anchor: anchor)
            }

            // Stronger white dashed time guides. Two guides divide the 150-minute window
            // into three clean visual sectors; the right edge remains the solid NOW marker.
            for fraction in [1.0 / 3.0, 2.0 / 3.0] as [CGFloat] {
                let x = plotLeft + plotWidth * fraction
                var guide = Path()
                guide.move(to: CGPoint(x: x, y: plotTop))
                guide.addLine(to: CGPoint(x: x, y: plotBottom))
                context.stroke(
                    guide,
                    with: .color(Color.white.opacity(0.88)),
                    style: StrokeStyle(lineWidth: 0.9, dash: [3.0, 2.5])
                )
            }

            // Solid current-time line at the right edge.
            var nowLine = Path()
            nowLine.move(to: CGPoint(x: plotRight, y: plotTop))
            nowLine.addLine(to: CGPoint(x: plotRight, y: plotBottom))
            context.stroke(nowLine, with: .color(Color.white), lineWidth: 0.95)

            // Three labels across exactly 150 minutes. They remain fully inside the widget.
            let labelY = size.height - 0.5
            let startDate = entry.date.addingTimeInterval(-visibleDuration)
            let middleDate = entry.date.addingTimeInterval(-visibleDuration / 2)
            drawLabel(Self.timeFormatter.string(from: startDate), at: CGPoint(x: plotLeft, y: labelY), anchor: UnitPoint(x: 0, y: 1))
            drawLabel(Self.timeFormatter.string(from: middleDate), at: CGPoint(x: plotLeft + plotWidth / 2, y: labelY), anchor: UnitPoint(x: 0.5, y: 1))
            drawLabel(Self.timeFormatter.string(from: entry.date), at: CGPoint(x: plotRight - 1.0, y: labelY), anchor: UnitPoint(x: 1, y: 1))

            // Connect readings and draw points.
            if readings.count >= 2 {
                var line = Path()
                for (index, reading) in readings.enumerated() {
                    let point = CGPoint(x: xPosition(reading.date), y: yPosition(reading.value))
                    if index == 0 { line.move(to: point) } else { line.addLine(to: point) }
                }
                context.stroke(line, with: .color(Color.green.opacity(0.72)), lineWidth: 1.2)
            }

            for reading in readings {
                let point = CGPoint(x: xPosition(reading.date), y: yPosition(reading.value))
                let diameter: CGFloat = size.width >= 150 ? 4.2 : 3.6
                let rect = CGRect(x: point.x - diameter / 2, y: point.y - diameter / 2, width: diameter, height: diameter)
                context.fill(Path(ellipseIn: rect), with: .color(pointColor(reading.value)))
            }
        }
    }
}
''', encoding="utf-8")


# 4) Guarantee exact 6-minute dim transition plus 12-minute stale transition.
provider = Path("xDrip Watch Complication/XDripWatchComplication+Provider.swift")
provider_text = provider.read_text(encoding="utf-8")
old_decl = '''        private let timelineStep: TimeInterval = 5 * 60\n        private let timelineHorizon: TimeInterval = 2 * 60 * 60\n        private let staleAfter: TimeInterval = 12 * 60'''
new_decl = '''        private let timelineStep: TimeInterval = 5 * 60\n        private let timelineHorizon: TimeInterval = 2 * 60 * 60\n        private let dimAfter: TimeInterval = 6 * 60\n        private let staleAfter: TimeInterval = 12 * 60'''
if provider_text.count(old_decl) != 1:
    raise RuntimeError("Build36: expected Build16 provider timing declarations not found")
provider_text = provider_text.replace(old_decl, new_decl, 1)

old_transition = '''            // Guarantee a local transition to stale exactly 12 minutes after the latest BG.\n            // This is independent of another phone/Watch transfer.\n            if let latestReadingDate = widgetState.bgReadingDate {\n                let staleDate = latestReadingDate.addingTimeInterval(staleAfter)\n                if staleDate > now, staleDate <= horizonDate,\n                   !entryDates.contains(where: { abs($0.timeIntervalSince(staleDate)) < 1 }) {\n                    entryDates.append(staleDate)\n                }\n            }'''
new_transition = '''            // Build 36: exact local visual transitions at 6 and 12 minutes, independent\n            // of another phone/Watch transfer.\n            if let latestReadingDate = widgetState.bgReadingDate {\n                for transitionDate in [\n                    latestReadingDate.addingTimeInterval(dimAfter),\n                    latestReadingDate.addingTimeInterval(staleAfter)\n                ] {\n                    if transitionDate > now, transitionDate <= horizonDate,\n                       !entryDates.contains(where: { abs($0.timeIntervalSince(transitionDate)) < 1 }) {\n                        entryDates.append(transitionDate)\n                    }\n                }\n            }'''
if provider_text.count(old_transition) != 1:
    raise RuntimeError("Build36: expected Build16 stale transition block not found")
provider_text = provider_text.replace(old_transition, new_transition, 1)
provider.write_text(provider_text, encoding="utf-8")


# 5) Every changed BG state reloads the exact Build 36 kinds.
watch_state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")
watch_text = watch_state.read_text(encoding="utf-8")
old_reload = '            WidgetCenter.shared.reloadTimelines(ofKind: "xDripWatchComplication")'
new_reload = '''            for complicationKind in [\n                "xDripGraphV33",\n                "xDripBGV36",\n                "xDripDeltaV36"\n            ] {\n                WidgetCenter.shared.reloadTimelines(ofKind: complicationKind)\n            }'''
if watch_text.count(old_reload) != 1:
    raise RuntimeError(f"Build36: expected exactly one original reload call, found {watch_text.count(old_reload)}")
watch_state.write_text(watch_text.replace(old_reload, new_reload, 1), encoding="utf-8")

print("Build 36 applied: 150-minute maximum-area graph + separate BG/Delta circular widgets + exact 6/12-minute transitions.")
