from pathlib import Path
import plistlib


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Build 30 is deliberately based on the exact Build-24 chain because Build 24 is the
# last build the user has verified as selectable in the iPhone Watch complication picker.
# This post-patch MUST NOT modify the ClockKit discovery bridge, Watch plist metadata,
# WidgetKit kind, target registration, extension plist, or Xcode project settings.
# It changes ONLY the rectangular graph geometry/colors requested after Build 24.

watch_app = Path("xDrip Watch App/xDripWatchApp.swift")
watch_text_before = watch_app.read_text(encoding="utf-8")
required_bridge_tokens = [
    "final class ComplicationController: NSObject, CLKComplicationDataSource, CLKComplicationWidgetMigrator",
    'private static let graphDescriptorIdentifier = "xDrip.graph"',
    'private static let bgDescriptorIdentifier = "xDrip.bg"',
    'displayName: "xDrip Graph"',
    'displayName: "xDrip BG"',
    'kind: "xDripWatchComplication"',
    'extensionBundleIdentifier: watchBundleIdentifier + ".xDripWatchComplication"',
]
for token in required_bridge_tokens:
    if token not in watch_text_before:
        raise RuntimeError(f"Build30: verified Build24 bridge token missing: {token}")

with Path("xDrip-Watch-App-Info.plist").open("rb") as f:
    watch_info_before = plistlib.load(f)
if watch_info_before.get("CLKComplicationPrincipalClass") != "$(PRODUCT_MODULE_NAME).ComplicationController":
    raise RuntimeError("Build30: Build24 CLKComplicationPrincipalClass is not intact")
if watch_info_before.get("CLKComplicationSupportedFamilies") != [
    "CLKComplicationFamilyGraphicCircular",
    "CLKComplicationFamilyGraphicRectangular",
]:
    raise RuntimeError("Build30: Build24 supported families are not intact")

# Only graph file is modified below.
graph = Path("xDrip Watch Complication/Views/AccessoryRectangularView.swift")

piecewise = '''            func yPosition(_ value: Double) -> CGFloat {
                let clamped = min(max(value, minimumMgDl), maximumMgDl)

                // Build 24 uses a piecewise monitor scale. It preserves the clinically
                // important threshold order while giving 70 and 40 substantially more
                // vertical separation in the very small Modular Ultra complication.
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
linear = '''            func yPosition(_ value: Double) -> CGFloat {
                let clamped = min(max(value, minimumMgDl), maximumMgDl)
                // Build 30: true proportional 0...220 mg/dL scale.
                // Therefore 220→160 (60 mg/dL) is exactly twice the vertical distance
                // of 70→40 (30 mg/dL), as requested.
                let fraction = (maximumMgDl - clamped) / (maximumMgDl - minimumMgDl)
                return plotTop + CGFloat(fraction) * plotHeight
            }
'''
replace_once(graph, piecewise, linear, "Build30 proportional y-axis")

# Replace only the threshold loop. Do not depend on the exact preceding comment text,
# because Build 24 inherited that comment from earlier graph builds.
text = graph.read_text(encoding="utf-8")
loop_token = "            for level in [220.0, 160.0, 70.0, 40.0] {\n"
end_token = "            // Unlabelled zero baseline."
start = text.find(loop_token)
end = text.find(end_token, start)
if start < 0 or end < 0:
    raise RuntimeError("Build30: threshold loop or zero-baseline marker not found")

threshold_block = '''            for level in [220.0, 160.0, 70.0, 40.0] {
                let y = yPosition(level)
                var path = Path()
                path.move(to: CGPoint(x: plotLeft, y: y))
                path.addLine(to: CGPoint(x: plotRight, y: y))

                let color: Color
                let dash: [CGFloat]
                switch Int(level) {
                case 220:
                    color = .yellow
                    dash = []
                case 160, 70:
                    color = .white
                    dash = [2.5, 2.5]
                case 40:
                    color = .red
                    dash = []
                default:
                    color = .white
                    dash = []
                }

                context.stroke(path, with: .color(color), style: StrokeStyle(lineWidth: 0.75, dash: dash))

                let labelAnchor: UnitPoint
                switch Int(level) {
                case 220: labelAnchor = UnitPoint(x: 1, y: 0)
                case 70:  labelAnchor = UnitPoint(x: 1, y: 1)
                case 40:  labelAnchor = UnitPoint(x: 1, y: 0)
                default:  labelAnchor = UnitPoint(x: 1, y: 0.5)
                }
                drawLabel(String(Int(level)), at: CGPoint(x: plotLeft - 3.0, y: y), anchor: labelAnchor)
            }

'''
text = text[:start] + threshold_block + text[end:]
graph.write_text(text, encoding="utf-8")

replace_once(
    graph,
    '''            context.stroke(
                zeroLine,
                with: .color(Color.secondary.opacity(0.60)),
                style: StrokeStyle(lineWidth: 0.75, dash: [2.5, 2.5])
            )''',
    '''            context.stroke(
                zeroLine,
                with: .color(Color.white),
                style: StrokeStyle(lineWidth: 0.75)
            )''',
    "Build30 solid white zero baseline",
)

replace_once(
    graph,
    '''                    with: .color(Color.secondary.opacity(0.58)),
                    style: StrokeStyle(lineWidth: 0.75, dash: [2.5, 2.5])''',
    '''                    with: .color(Color.white.opacity(0.75)),
                    style: StrokeStyle(lineWidth: 0.75, dash: [2.5, 2.5])''',
    "Build30 white hour guides",
)

text = graph.read_text(encoding="utf-8")
if "currentLine.addLine(to: CGPoint(x: plotRight, y: zeroY))" not in text:
    raise RuntimeError("Build30: Build24 current-time line geometry missing")
old_now = "context.stroke(currentLine, with: .color(Color.secondary.opacity(0.75)), lineWidth: 0.8)"
if old_now in text:
    text = text.replace(old_now, "context.stroke(currentLine, with: .color(Color.white), lineWidth: 0.8)", 1)
graph.write_text(text, encoding="utf-8")

# Prove that this post-patch did not touch any registration/discovery file.
if watch_app.read_text(encoding="utf-8") != watch_text_before:
    raise RuntimeError("Build30: Watch complication discovery bridge changed unexpectedly")
with Path("xDrip-Watch-App-Info.plist").open("rb") as f:
    watch_info_after = plistlib.load(f)
if watch_info_after != watch_info_before:
    raise RuntimeError("Build30: Watch complication plist metadata changed unexpectedly")

print("Build 30 applied: Build-24 picker registration preserved byte-for-byte; only final graph geometry/styling changed.")
