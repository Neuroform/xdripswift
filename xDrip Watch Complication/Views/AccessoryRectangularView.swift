//
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
