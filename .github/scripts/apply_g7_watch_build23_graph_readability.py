from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Build 23 runs AFTER Build 22.
# It changes only the Modular Ultra graph presentation requested after on-watch validation:
# - exactly three x-axis labels
# - labels use full hours (for example 20:00 / 21:00 / 22:00)
# - no 30-minute labels
# - graph axis font +22% versus Build 22 (11 -> 13.4 pt on Ultra; 10 -> 12.2 fallback)
# - all graph axis numbers/times use bold white text for maximum legibility
# - rolling two-hour glucose data and the right-edge current-time marker remain unchanged

path = Path("xDrip Watch Complication/Views/AccessoryRectangularView.swift")

replace_once(
    path,
    "let labelFontSize: CGFloat = size.width >= 150 ? 11.0 : 10.0",
    "let labelFontSize: CGFloat = size.width >= 150 ? 13.4 : 12.2",
    "Build23 22-percent larger axis font",
)

replace_once(
    path,
    "let leftMargin: CGFloat = size.width >= 150 ? 28.0 : 25.0",
    "let leftMargin: CGFloat = size.width >= 150 ? 34.0 : 31.0",
    "Build23 larger left margin for enlarged Y labels",
)

replace_once(
    path,
    "let topMargin: CGFloat = 6.0\n            let bottomMargin: CGFloat = 19.0",
    "let topMargin: CGFloat = 8.5\n            let bottomMargin: CGFloat = 24.0",
    "Build23 margins for enlarged labels",
)

replace_once(
    path,
    '''Text(text)
                        .font(.system(size: fontSize, weight: .semibold))
                        .foregroundStyle(Color.secondary)
                        .monospacedDigit()''',
    '''Text(text)
                        .font(.system(size: fontSize, weight: .bold))
                        .foregroundStyle(Color.white)
                        .monospacedDigit()''',
    "Build23 bold white graph labels",
)

old_axis = '''            // Dashed monitor-style vertical grid at each 30-minute subdivision.
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
'''

new_axis = '''            // Build 23: one center grid line only. The former 30-minute subdivisions are
            // intentionally removed so the tiny Ultra complication is not visually overloaded.
            let centerGridX = plotLeft + plotWidth / 2
            var centerGrid = Path()
            centerGrid.move(to: CGPoint(x: centerGridX, y: plotTop))
            centerGrid.addLine(to: CGPoint(x: centerGridX, y: plotBottom))
            context.stroke(centerGrid, with: .color(Color.secondary.opacity(0.52)), style: StrokeStyle(lineWidth: 0.7, dash: [2.5, 2.5]))

            // Exactly three time labels, always on full hours. Data points still use their exact
            // timestamps in the rolling two-hour window; only the compact axis labels are snapped
            // to clean hour values for readability (for example 20:00 / 21:00 / 22:00).
            let labelY = size.height - 0.5
            let calendar = Calendar.current
            let currentHour = calendar.dateInterval(of: .hour, for: entry.date)?.start ?? entry.date
            let hourLabels = [
                currentHour.addingTimeInterval(-2 * 60 * 60),
                currentHour.addingTimeInterval(-1 * 60 * 60),
                currentHour
            ]
            let hourFractions: [CGFloat] = [0.0, 0.5, 1.0]

            for index in 0..<3 {
                let fraction = hourFractions[index]
                let anchor: UnitPoint = index == 0 ? UnitPoint(x: 0, y: 1) : (index == 2 ? UnitPoint(x: 1, y: 1) : UnitPoint(x: 0.5, y: 1))
                drawLabel(
                    Self.timeFormatter.string(from: hourLabels[index]),
                    at: CGPoint(x: plotLeft + plotWidth * fraction, y: labelY),
                    anchor: anchor
                )
            }
'''

replace_once(path, old_axis, new_axis, "Build23 three full-hour time labels")

print("Build 23 graph readability patch applied: 3 full-hour labels, +22% font, bold white axis text.")
