from pathlib import Path


# Build 26 final graph patch runs AFTER Build 25 and the Build 26 WidgetKit
# registration recovery. It changes only the approved Modular Ultra graph geometry.
#
# User-approved geometry:
# - 0...220 mg/dL is spatially proportional
# - 220 is the absolute upper edge of the center complication
# - 160 is 60 mg/dL below 220 and therefore gets twice the vertical gap of 70->40
# - 70 is 30 mg/dL above 40
# - 40 remains near the bottom, with the unlabelled 0 baseline below it
# - 220 label begins at the yellow 220 line and never extends above it
# - all Build 25 colors, dashed/solid styles, full-hour labels and NOW line remain unchanged


def replace_exactly_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


path = Path("xDrip Watch Complication/Views/AccessoryRectangularView.swift")
text = path.read_text(encoding="utf-8")

text = replace_exactly_once(
    text,
    "            let topMargin: CGFloat = 1.5",
    "            let topMargin: CGFloat = 0.0",
    "Build26 yellow 220 line at absolute top edge",
)

old_scale = '''            func yPosition(_ value: Double) -> CGFloat {
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
'''

new_scale = '''            func yPosition(_ value: Double) -> CGFloat {
                let clamped = min(max(value, minimumMgDl), maximumMgDl)

                // Build 26 final: true proportional 0...220 mg/dL monitor scale.
                // Every vertical distance is proportional to the numeric BG difference:
                // 220->160 = 60 mg/dL, 160->70 = 90 mg/dL,
                // 70->40 = 30 mg/dL, 40->0 = 40 mg/dL.
                let fraction = CGFloat(
                    (maximumMgDl - clamped) / (maximumMgDl - minimumMgDl)
                )
                return plotTop + fraction * plotHeight
            }
'''

text = replace_exactly_once(
    text,
    old_scale,
    new_scale,
    "Build26 proportional BG scale",
)

# Verify the approved label anchors and colors are still present after the geometry change.
required = [
    'private let minimumMgDl = 0.0',
    'private let maximumMgDl = 220.0',
    'if level == 220 {',
    'color = .yellow',
    'level == 160 || level == 70',
    'color = .white',
    'color = .red',
    'anchor = UnitPoint(x: 1, y: 0)',
    'anchor = UnitPoint(x: 1, y: 1)',
    'context.stroke(zeroLine, with: .color(.white), lineWidth: 0.85)',
    'currentLine.addLine(to: CGPoint(x: plotRight, y: zeroY))',
]
for token in required:
    if token not in text:
        raise RuntimeError(f"Build26 final graph required token missing: {token}")

path.write_text(text, encoding="utf-8")
print("Build 26 final proportional graph applied: 220/160/70/40/0 spacing is numerically proportional.")
