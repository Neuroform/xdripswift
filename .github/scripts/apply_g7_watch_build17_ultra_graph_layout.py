from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1))


# Build 17 runs AFTER the complete Build 16 patch chain.
# It changes ONLY the Apple Watch home-screen rectangular complication layout.
# The graph inside the opened xDrip Watch app and the Build 16 update/stale logic stay untouched.
#
# Layout goals from the approved Watch Ultra mock-up:
# - maximize graph width/height inside the complication bounds
# - shrink the right value column
# - put the BG value on its own line so all available width can be used for the number
# - move a smaller trend arrow next to the delta (+0 / -4 / ...)
# - keep measurement time below delta/trend
# - keep the 2-hour rolling axis and the continuous RIGHT-side current-time line

view = Path("xDrip Watch Complication/Views/AccessoryRectangularView.swift")

replace_once(
    view,
    '''                let sideWidth = max(44.0, min(58.0, geometry.size.width * 0.27))

                HStack(alignment: .center, spacing: 3) {''',
    '''                // Build 17: narrow value panel so the graph/time axis gets the largest
                // possible share of the rectangular complication, especially on Watch Ultra.
                let sideWidth = max(36.0, min(44.0, geometry.size.width * 0.21))

                HStack(alignment: .center, spacing: 1.5) {''',
    "Build17 maximize graph width",
)

replace_once(
    view,
    '''            HStack(alignment: .firstTextBaseline, spacing: 1) {
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
                .font(.system(size: entry.widgetState.isSmallScreen() ? 8 : 10, weight: .medium))''',
    '''            // BG gets the full width of the narrow right panel. The trend arrow is
            // deliberately moved to the delta row so it no longer steals space from BG.
            Text(glucoseText)
                .font(.system(size: entry.widgetState.isSmallScreen() ? 19 : 23, weight: .bold))
                .foregroundStyle(displayColor)
                .minimumScaleFactor(0.48)
                .lineLimit(1)

            HStack(alignment: .firstTextBaseline, spacing: 2) {
                Text(deltaText)
                    .font(.system(size: entry.widgetState.isSmallScreen() ? 11 : 13, weight: .semibold))
                    .foregroundStyle(isFresh ? Color.colorPrimary : Color.gray)
                    .lineLimit(1)

                Text(trendArrow)
                    .font(.system(size: entry.widgetState.isSmallScreen() ? 9 : 11, weight: .bold))
                    .foregroundStyle(displayColor)
                    .minimumScaleFactor(0.65)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Text(latestDate?.formatted(date: .omitted, time: .shortened) ?? "--:--")
                .font(.system(size: entry.widgetState.isSmallScreen() ? 8 : 9, weight: .medium))''',
    "Build17 trend beside delta",
)

replace_once(
    view,
    '''            let leftMargin: CGFloat = size.width < 115 ? 18 : 21
            let rightMargin: CGFloat = 1.5
            let topMargin: CGFloat = 2
            let bottomMargin: CGFloat = size.height < 55 ? 10 : 12''',
    '''            // Build 17: use almost the full available rectangle for the monitor graph.
            // Keep only the minimum room needed for scale and moving time labels.
            let leftMargin: CGFloat = size.width < 115 ? 16 : 18
            let rightMargin: CGFloat = 0.5
            let topMargin: CGFloat = 0.5
            let bottomMargin: CGFloat = size.height < 55 ? 9 : 10''',
    "Build17 maximize graph canvas",
)

replace_once(
    view,
    '''                drawLabel(String(Int(level)), at: CGPoint(x: plotLeft - 2.5, y: y), anchor: UnitPoint(x: 1, y: 0.5), size: 6.5)''',
    '''                drawLabel(String(Int(level)), at: CGPoint(x: plotLeft - 2.0, y: y), anchor: UnitPoint(x: 1, y: 0.5), size: 6.2)''',
    "Build17 compact Y labels",
)

replace_once(
    view,
    '''            drawLabel(Self.timeFormatter.string(from: leftDate), at: CGPoint(x: plotLeft, y: labelY), anchor: UnitPoint(x: 0, y: 1), size: 6.5)
            drawLabel(Self.timeFormatter.string(from: middleDate), at: CGPoint(x: plotLeft + plotWidth / 2, y: labelY), anchor: UnitPoint(x: 0.5, y: 1), size: 6.5)
            drawLabel(Self.timeFormatter.string(from: entry.date), at: CGPoint(x: plotRight, y: labelY), anchor: UnitPoint(x: 1, y: 1), size: 6.5)''',
    '''            drawLabel(Self.timeFormatter.string(from: leftDate), at: CGPoint(x: plotLeft, y: labelY), anchor: UnitPoint(x: 0, y: 1), size: 6.2)
            drawLabel(Self.timeFormatter.string(from: middleDate), at: CGPoint(x: plotLeft + plotWidth / 2, y: labelY), anchor: UnitPoint(x: 0.5, y: 1), size: 6.2)
            drawLabel(Self.timeFormatter.string(from: entry.date), at: CGPoint(x: plotRight, y: labelY), anchor: UnitPoint(x: 1, y: 1), size: 6.2)''',
    "Build17 compact moving time axis",
)

print("Build 17 Watch Ultra maximum-graph complication layout applied successfully.")
