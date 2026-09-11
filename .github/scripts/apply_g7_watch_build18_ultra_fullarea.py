from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1))


# Build 18 runs AFTER the complete Build 17 patch chain.
# It changes ONLY the Apple Watch home-screen rectangular complication layout.
# The graph inside the opened xDrip Watch app and all Build 16 refresh/stale logic stay untouched.
#
# User-approved Ultra layout goals:
# - consume the complete WidgetKit accessoryRectangular content area Apple makes available
# - remove default WidgetKit content margins
# - use zero horizontal gap between graph and value panel
# - make the right value panel as narrow as practical while retaining readable values
# - current BG is reduced to roughly the visual size of the lower circular value text
# - give every recovered horizontal pixel to the rolling 2-hour graph/time axis
# - preserve 40...220 mg/dL, the right-side NOW line, delta + small trend arrow, and last BG time

widget = Path("xDrip Watch Complication/XDripWatchComplication.swift")
replace_once(
    widget,
    '''        .configurationDisplayName(ConstantsHomeView.applicationName)\n        .description("Show the current blood glucose level")''',
    '''        .configurationDisplayName(ConstantsHomeView.applicationName)\n        .description("Show the current blood glucose level")\n        // Build 18: use every pixel WidgetKit exposes for the middle Ultra complication.\n        .contentMarginsDisabled()''',
    "Build18 disable WidgetKit content margins",
)

view = Path("xDrip Watch Complication/Views/AccessoryRectangularView.swift")

replace_once(
    view,
    '''                // Build 17: compact value column so the time axis gets the maximum width.\n                // Ultra-size rectangular complications can safely use a narrower side panel because\n                // the trend arrow no longer shares the BG row.\n                let sideWidth = max(36.0, min(44.0, geometry.size.width * 0.22))\n\n                HStack(alignment: .center, spacing: 1) {''',
    '''                // Build 18: Ultra full-area layout. Keep only the minimum readable value\n                // column and transfer the recovered width directly to the rolling graph.\n                let sideWidth = max(32.0, min(38.0, geometry.size.width * 0.18))\n\n                HStack(alignment: .center, spacing: 0) {''',
    "Build18 maximum graph width",
)

replace_once(
    view,
    '''            // Keep the BG value alone so three digits get the full panel width.\n            Text(glucoseText)\n                .font(.system(size: entry.widgetState.isSmallScreen() ? 18 : 23, weight: .bold))\n                .foregroundStyle(displayColor)\n                .minimumScaleFactor(0.50)\n                .lineLimit(1)\n\n            // Delta first, then a deliberately smaller trend arrow as requested.\n            HStack(alignment: .firstTextBaseline, spacing: 2) {\n                Text(deltaText)\n                    .font(.system(size: entry.widgetState.isSmallScreen() ? 11 : 13, weight: .semibold))\n                    .foregroundStyle(isFresh ? Color.colorPrimary : Color.gray)\n                    .lineLimit(1)\n\n                Text(trendArrow)\n                    .font(.system(size: entry.widgetState.isSmallScreen() ? 9 : 11, weight: .bold))\n                    .foregroundStyle(displayColor)\n                    .minimumScaleFactor(0.7)\n                    .lineLimit(1)\n            }\n\n            Text(latestDate?.formatted(date: .omitted, time: .shortened) ?? "--:--")''',
    '''            // Build 18: current BG is deliberately smaller so the side panel can shrink\n            // further. It remains bold and high-contrast, but no longer dominates graph width.\n            Text(glucoseText)\n                .font(.system(size: entry.widgetState.isSmallScreen() ? 16 : 20, weight: .bold))\n                .foregroundStyle(displayColor)\n                .minimumScaleFactor(0.58)\n                .lineLimit(1)\n\n            HStack(alignment: .firstTextBaseline, spacing: 1) {\n                Text(deltaText)\n                    .font(.system(size: entry.widgetState.isSmallScreen() ? 10 : 11, weight: .semibold))\n                    .foregroundStyle(isFresh ? Color.colorPrimary : Color.gray)\n                    .lineLimit(1)\n\n                Text(trendArrow)\n                    .font(.system(size: entry.widgetState.isSmallScreen() ? 8 : 9, weight: .bold))\n                    .foregroundStyle(displayColor)\n                    .minimumScaleFactor(0.75)\n                    .lineLimit(1)\n            }\n\n            Text(latestDate?.formatted(date: .omitted, time: .shortened) ?? "--:--")''',
    "Build18 compact readable value panel",
)

replace_once(
    view,
    '''            // Build 17: reclaim additional horizontal pixels for the actual 2h plot while\n            // still retaining readable Y-axis labels. The current-time line stays at plotRight.\n            let leftMargin: CGFloat = size.width < 115 ? 16 : 18\n            let rightMargin: CGFloat = 0.5\n            let topMargin: CGFloat = 2\n            let bottomMargin: CGFloat = size.height < 55 ? 10 : 12''',
    '''            // Build 18: use virtually the complete Canvas. Only reserve enough room for\n            // readable 3-digit Y labels and the moving HH:mm labels. No decorative padding.\n            let leftMargin: CGFloat = size.width < 115 ? 13 : 15\n            let rightMargin: CGFloat = 0\n            let topMargin: CGFloat = 0.5\n            let bottomMargin: CGFloat = size.height < 55 ? 8 : 9''',
    "Build18 maximum graph canvas",
)

replace_once(
    view,
    '''                drawLabel(String(Int(level)), at: CGPoint(x: plotLeft - 2.5, y: y), anchor: UnitPoint(x: 1, y: 0.5), size: 6.5)''',
    '''                drawLabel(String(Int(level)), at: CGPoint(x: plotLeft - 1.5, y: y), anchor: UnitPoint(x: 1, y: 0.5), size: 6.0)''',
    "Build18 compact Y labels",
)

replace_once(
    view,
    '''            drawLabel(Self.timeFormatter.string(from: leftDate), at: CGPoint(x: plotLeft, y: labelY), anchor: UnitPoint(x: 0, y: 1), size: 6.5)\n            drawLabel(Self.timeFormatter.string(from: middleDate), at: CGPoint(x: plotLeft + plotWidth / 2, y: labelY), anchor: UnitPoint(x: 0.5, y: 1), size: 6.5)\n            drawLabel(Self.timeFormatter.string(from: entry.date), at: CGPoint(x: plotRight, y: labelY), anchor: UnitPoint(x: 1, y: 1), size: 6.5)''',
    '''            drawLabel(Self.timeFormatter.string(from: leftDate), at: CGPoint(x: plotLeft, y: labelY), anchor: UnitPoint(x: 0, y: 1), size: 6.0)\n            drawLabel(Self.timeFormatter.string(from: middleDate), at: CGPoint(x: plotLeft + plotWidth / 2, y: labelY), anchor: UnitPoint(x: 0.5, y: 1), size: 6.0)\n            drawLabel(Self.timeFormatter.string(from: entry.date), at: CGPoint(x: plotRight, y: labelY), anchor: UnitPoint(x: 1, y: 1), size: 6.0)''',
    "Build18 expanded moving time axis",
)

print("Build 18 Watch Ultra full-area complication layout applied successfully.")
