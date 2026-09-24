//
//  AccessoryRectangularView.swift
//  xDrip Watch Complication Extension
//
//  Final UI: rolling 150-minute maximum-area glucose graph.
//

import Foundation
import SwiftUI

extension XDripWatchComplication.EntryView {
    @ViewBuilder
    var accessoryRectangularView: some View {
        Rolling150MinuteGlucoseGraph(entry: entry)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .widgetBackground(backgroundView: Color.clear)
    }
}

private struct Rolling150MinuteGlucoseGraph: View {
    let entry: XDripWatchComplication.Entry

    private let minimumMgDl = 0.0
    private let maximumMgDl = 200.0
    private let targetLowMgDl = 70.0
    private let targetHighMgDl = 150.0
    private let visibleDuration: TimeInterval = 150 * 60
    private let maximumVisibleReadings = 30

    private static let hourFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "ha"
        return formatter
    }()

    private var windowStart: Date {
        entry.date.addingTimeInterval(-visibleDuration)
    }

    private var readings: [(date: Date, value: Double)] {
        guard let dates = entry.widgetState.bgReadingDates,
              let values = entry.widgetState.bgReadingValues else { return [] }

        let count = min(dates.count, values.count)
        guard count > 0 else { return [] }

        return (0..<count)
            .map { (date: dates[$0], value: values[$0]) }
            .filter { $0.date >= windowStart && $0.date <= entry.date.addingTimeInterval(60) }
            .sorted { $0.date < $1.date }
            .suffix(maximumVisibleReadings)
            .map { $0 }
    }

    private var fullHourTicks: [Date] {
        let calendar = Calendar.autoupdatingCurrent
        guard var tick = calendar.nextDate(
            after: windowStart.addingTimeInterval(-1),
            matching: DateComponents(minute: 0, second: 0),
            matchingPolicy: .nextTime
        ) else { return [] }

        var result: [Date] = []
        while tick <= entry.date {
            result.append(tick)
            guard let next = calendar.date(byAdding: .hour, value: 1, to: tick) else { break }
            tick = next
        }
        return result
    }

    private func pointColor(_ value: Double) -> Color {
        if value < targetLowMgDl { return .red }
        if value > targetHighMgDl { return .yellow }
        return .green
    }

    var body: some View {
        Canvas { context, size in
            // The graph consumes the complete rectangular family width. Only a compact
            // right-side label reserve and bottom hour-label reserve are retained.
            let labelFontSize: CGFloat = size.width >= 150 ? 8.4 : 7.8
            let plotLeft: CGFloat = 1.5
            let plotRight = max(plotLeft + 1, size.width - 1.5)
            let plotTop: CGFloat = 1.5
            let bottomMargin: CGFloat = size.height < 60 ? 11.5 : 13.0
            let plotBottom = max(plotTop + 1, size.height - bottomMargin)
            let plotWidth = max(1, plotRight - plotLeft)
            let plotHeight = max(1, plotBottom - plotTop)

            func yPosition(_ value: Double) -> CGFloat {
                let clamped = min(max(value, minimumMgDl), maximumMgDl)
                let fraction = (maximumMgDl - clamped) / (maximumMgDl - minimumMgDl)
                return plotTop + CGFloat(fraction) * plotHeight
            }

            func xPosition(_ date: Date) -> CGFloat {
                let elapsed = date.timeIntervalSince(windowStart)
                let fraction = min(max(elapsed / visibleDuration, 0), 1)
                return plotLeft + CGFloat(fraction) * plotWidth
            }

            func drawLabel(
                _ text: String,
                at point: CGPoint,
                anchor: UnitPoint,
                color: Color = .white
            ) {
                let label = context.resolve(
                    Text(text)
                        .font(.system(size: labelFontSize, weight: .semibold))
                        .foregroundStyle(color)
                        .monospacedDigit()
                )
                context.draw(label, at: point, anchor: anchor)
            }

            // Target range 70...150 mg/dL. It is deliberately subtle so glucose
            // points and the connecting line remain the dominant visual elements.
            let targetTop = yPosition(targetHighMgDl)
            let targetBottom = yPosition(targetLowMgDl)
            let targetRect = CGRect(
                x: plotLeft,
                y: targetTop,
                width: plotWidth,
                height: max(0, targetBottom - targetTop)
            )
            context.fill(
                Path(roundedRect: targetRect, cornerRadius: 2.0),
                with: .color(Color.white.opacity(0.13))
            )

            // Full-hour guides and labels share the exact same timestamp-to-x transform.
            // As time advances, both move left together. There is intentionally no NOW line.
            let labelY = size.height - 0.5
            for tick in fullHourTicks {
                let x = xPosition(tick)
                var guide = Path()
                guide.move(to: CGPoint(x: x, y: plotTop))
                guide.addLine(to: CGPoint(x: x, y: plotBottom))
                context.stroke(
                    guide,
                    with: .color(Color.white.opacity(0.40)),
                    style: StrokeStyle(lineWidth: 0.75, dash: [2.5, 2.5])
                )

                let text = Self.hourFormatter.string(from: tick).lowercased()
                let edgeInset: CGFloat = 10.0
                let labelX = min(max(x, plotLeft + edgeInset), plotRight - edgeInset)
                drawLabel(text, at: CGPoint(x: labelX, y: labelY), anchor: UnitPoint(x: 0.5, y: 1))
            }

            // Connect readings using their real timestamps. A missing five-minute sample
            // therefore remains a real temporal gap rather than compressing the history.
            if readings.count >= 2 {
                var line = Path()
                for (index, reading) in readings.enumerated() {
                    let point = CGPoint(x: xPosition(reading.date), y: yPosition(reading.value))
                    if index == 0 { line.move(to: point) } else { line.addLine(to: point) }
                }
                context.stroke(line, with: .color(Color.green.opacity(0.78)), lineWidth: 1.15)
            }

            for reading in readings {
                let point = CGPoint(x: xPosition(reading.date), y: yPosition(reading.value))
                let diameter: CGFloat = size.width >= 150 ? 4.0 : 3.5
                let rect = CGRect(
                    x: point.x - diameter / 2,
                    y: point.y - diameter / 2,
                    width: diameter,
                    height: diameter
                )
                context.fill(Path(ellipseIn: rect), with: .color(pointColor(reading.value)))
            }

            // BG scale is deliberately on the right. Labels are inset just enough to remain
            // visible inside the rounded complication while the plot still uses full width.
            let scaleX = plotRight - 1.0
            for level in [200.0, 150.0, 70.0, 0.0] {
                let y = yPosition(level)
                let anchor: UnitPoint
                let adjustedY: CGFloat
                if level == maximumMgDl {
                    anchor = UnitPoint(x: 1, y: 0)
                    adjustedY = y
                } else if level == minimumMgDl {
                    anchor = UnitPoint(x: 1, y: 1)
                    adjustedY = y
                } else {
                    anchor = UnitPoint(x: 1, y: 0.5)
                    adjustedY = y
                }
                drawLabel(
                    String(Int(level)),
                    at: CGPoint(x: scaleX, y: adjustedY),
                    anchor: anchor,
                    color: Color.white.opacity(0.86)
                )
            }
        }
    }
}
