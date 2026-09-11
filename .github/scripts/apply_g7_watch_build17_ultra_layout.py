from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1))


# Build 17 runs AFTER the complete Build 16 patch chain.
# It changes ONLY the Apple Watch home-screen complication layout.
# The opened xDrip Watch app graph and the Build 16 update/timeline logic remain untouched.
#
# Layout goals from the approved Watch Ultra mockup:
# - use the widest possible graph area inside the rectangular complication
# - reduce the right-side value column width
# - keep the large current BG on its own row
# - put a SMALL trend arrow to the RIGHT of the delta value
# - keep measurement time below delta/trend
# - preserve the rolling 2h time axis and right-side current-time line

view = Path("xDrip Watch Complication/Views/AccessoryRectangularView.swift")

replace_once(
    view,
    '''                let sideWidth = max(44.0, min(58.0, geometry.size.width * 0.27))\n\n                HStack(alignment: .center, spacing: 3) {''',
    '''                // Build 17: compact value column so the time axis gets the maximum width.\n                // Ultra-size rectangular complications can safely use a narrower side panel because\n                // the trend arrow no longer shares the BG row.\n                let sideWidth = max(36.0, min(44.0, geometry.size.width * 0.22))\n\n                HStack(alignment: .center, spacing: 1) {''',
    "Build17 compact right column",
)

replace_once(
    view,
    '''            HStack(alignment: .firstTextBaseline, spacing: 1) {\n                Text(glucoseText)\n                    .font(.system(size: entry.widgetState.isSmallScreen() ? 17 : 21, weight: .bold))\n                    .foregroundStyle(displayColor)\n                    .minimumScaleFactor(0.55)\n                    .lineLimit(1)\n\n                Text(trendArrow)\n                    .font(.system(size: entry.widgetState.isSmallScreen() ? 15 : 19, weight: .bold))\n                    .foregroundStyle(displayColor)\n                    .minimumScaleFactor(0.6)\n                    .lineLimit(1)\n            }\n\n            Text(deltaText)\n                .font(.system(size: entry.widgetState.isSmallScreen() ? 12 : 14, weight: .semibold))\n                .foregroundStyle(isFresh ? Color.colorPrimary : Color.gray)\n                .lineLimit(1)\n\n            Text(latestDate?.formatted(date: .omitted, time: .shortened) ?? "--:--")''',
    '''            // Keep the BG value alone so three digits get the full panel width.\n            Text(glucoseText)\n                .font(.system(size: entry.widgetState.isSmallScreen() ? 18 : 23, weight: .bold))\n                .foregroundStyle(displayColor)\n                .minimumScaleFactor(0.50)\n                .lineLimit(1)\n\n            // Delta first, then a deliberately smaller trend arrow as requested.\n            HStack(alignment: .firstTextBaseline, spacing: 2) {\n                Text(deltaText)\n                    .font(.system(size: entry.widgetState.isSmallScreen() ? 11 : 13, weight: .semibold))\n                    .foregroundStyle(isFresh ? Color.colorPrimary : Color.gray)\n                    .lineLimit(1)\n\n                Text(trendArrow)\n                    .font(.system(size: entry.widgetState.isSmallScreen() ? 9 : 11, weight: .bold))\n                    .foregroundStyle(displayColor)\n                    .minimumScaleFactor(0.7)\n                    .lineLimit(1)\n            }\n\n            Text(latestDate?.formatted(date: .omitted, time: .shortened) ?? "--:--")''',
    "Build17 BG delta trend hierarchy",
)

replace_once(
    view,
    '''            let leftMargin: CGFloat = size.width < 115 ? 18 : 21\n            let rightMargin: CGFloat = 1.5''',
    '''            // Build 17: reclaim additional horizontal pixels for the actual 2h plot while\n            // still retaining readable Y-axis labels. The current-time line stays at plotRight.\n            let leftMargin: CGFloat = size.width < 115 ? 16 : 18\n            let rightMargin: CGFloat = 0.5''',
    "Build17 wider plot area",
)

print("Build 17 Ultra home-screen complication layout applied successfully.")
