//
//  AccessoryCircularView.swift
//  xDrip Watch Complication Extension
//
//  Build 37: Apple-seconds-style minute tick bezel for BG circle.
//

import Foundation
import SwiftUI

private extension XDripWatchComplication.Entry {
    var v37LatestDate: Date? { widgetState.bgReadingDates?.first }
    var v37LatestValue: Double? { widgetState.bgReadingValues?.first }

    var v37Age: TimeInterval {
        guard let date = v37LatestDate else { return .infinity }
        return max(0, self.date.timeIntervalSince(date))
    }

    // Full-minute semantics requested for Build 37:
    // 0...6 min = fresh/white bezel, 7...12 = yellow-transparent bezel,
    // >=13 = stale/red-transparent bezel and BG becomes ---.
    var v37AgeMinutes: Int {
        guard v37Age.isFinite else { return 999 }
        return max(0, Int(floor(v37Age / 60.0)))
    }

    var v37IsDimmed: Bool { v37AgeMinutes >= 7 && v37AgeMinutes <= 12 }
    var v37IsStale: Bool { v37AgeMinutes >= 13 }

    var v37BGColor: Color {
        guard let value = v37LatestValue, !v37IsStale else { return .gray }
        let base: Color
        if value < 70 {
            base = .red
        } else if value < 160 {
            base = .green
        } else {
            base = .yellow
        }
        return v37IsDimmed ? base.opacity(0.38) : base
    }

    var v37TrendArrow: String {
        guard !v37IsStale else { return "" }
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

    var v37Delta: Double? {
        guard !v37IsStale else { return nil }
        return widgetState.deltaValueInUserUnit
    }
}

struct XDripBGCircleV36View: View {
    let entry: XDripWatchComplication.Entry

    private var elapsedMinuteTicks: Int {
        min(max(entry.v37AgeMinutes, 0), 60)
    }

    private var activeTickColor: Color {
        if entry.v37AgeMinutes >= 13 {
            return .red.opacity(0.58)
        }
        if entry.v37AgeMinutes >= 7 {
            return .yellow.opacity(0.58)
        }
        return .white.opacity(0.96)
    }

    private var glucoseText: String {
        guard !entry.v37IsStale else { return "---" }
        return entry.widgetState.bgValueStringInUserChosenUnit()
    }

    var body: some View {
        GeometryReader { geometry in
            let side = min(geometry.size.width, geometry.size.height)
            let outerRadius = side * 0.475
            let shortInnerRadius = side * 0.425
            let longInnerRadius = side * 0.392

            ZStack {
                // Apple-seconds-style bezel: exactly 60 discrete minute marks.
                // The four quarter-hour/cardinal marks (12/9/6/3 positions) are longer.
                Canvas { context, size in
                    let center = CGPoint(x: size.width / 2, y: size.height / 2)

                    for index in 0..<60 {
                        // Start at 12 o'clock; increasing minute index proceeds counter-clockwise.
                        let angle = -Double.pi / 2.0 - Double(index) * (2.0 * Double.pi / 60.0)
                        let isCardinal = index % 15 == 0
                        let innerRadius = isCardinal ? longInnerRadius : shortInnerRadius

                        let start = CGPoint(
                            x: center.x + CGFloat(cos(angle)) * innerRadius,
                            y: center.y + CGFloat(sin(angle)) * innerRadius
                        )
                        let end = CGPoint(
                            x: center.x + CGFloat(cos(angle)) * outerRadius,
                            y: center.y + CGFloat(sin(angle)) * outerRadius
                        )

                        var path = Path()
                        path.move(to: start)
                        path.addLine(to: end)

                        let isElapsed = index < elapsedMinuteTicks
                        let color = isElapsed ? activeTickColor : Color.secondary.opacity(0.30)
                        let width: CGFloat = isCardinal ? max(1.8, side * 0.026) : max(1.05, side * 0.014)

                        context.stroke(
                            path,
                            with: .color(color),
                            style: StrokeStyle(lineWidth: width, lineCap: .round)
                        )
                    }
                }

                HStack(alignment: .firstTextBaseline, spacing: max(1, side * 0.02)) {
                    Text(glucoseText)
                        .font(.system(size: side * 0.34, weight: .bold, design: .rounded))
                        .foregroundStyle(entry.v37BGColor)
                        .minimumScaleFactor(0.50)
                        .lineLimit(1)
                        .monospacedDigit()

                    if !entry.v37TrendArrow.isEmpty {
                        Text(entry.v37TrendArrow)
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
        guard let delta = entry.v37Delta else { return "" }
        return delta < 0 ? "−" : "+"
    }

    private var magnitudeText: String {
        guard let delta = entry.v37Delta else { return "--" }
        if entry.widgetState.isMgDl {
            return String(format: "%.0f", abs(delta))
        }
        return String(format: "%.1f", abs(delta))
    }

    private var magnitudeColor: Color {
        guard let delta = entry.v37Delta else { return .gray }
        let magnitude = abs(delta)
        let base: Color
        if magnitude <= 3 {
            base = .white
        } else if magnitude <= 7 {
            base = .yellow
        } else {
            base = .red
        }
        return entry.v37IsDimmed ? base.opacity(0.38) : base
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

extension XDripWatchComplication.EntryView {
    @ViewBuilder
    var accessoryCircularView: some View {
        XDripBGCircleV36View(entry: entry)
    }
}
