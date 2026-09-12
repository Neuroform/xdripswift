from pathlib import Path
import plistlib


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Build 24 runs after Build 23.
# Goals:
# - keep the rolling 2-hour graph and three full-hour labels
# - restore dashed vertical hour grid lines at the first and middle hour
# - add a visible zero baseline without a numeric 0 label
# - extend the right current-time line down to the zero baseline
# - increase visual separation of 70 and 40 via a piecewise Y scale
# - align the 220 dashed line with the TOP edge of the 220 label
# - add the modern single-target ClockKit metadata/data-source bridge described by
#   Apple's TN3157 so the companion iPhone Watch app can enumerate xDrip as a
#   complication provider while WidgetKit remains the actual renderer.


# -----------------------------------------------------------------------------
# 1) Final Modular Ultra graph geometry.
# -----------------------------------------------------------------------------
graph = Path("xDrip Watch Complication/Views/AccessoryRectangularView.swift")

replace_once(
    graph,
    "private let minimumMgDl = 40.0",
    "private let minimumMgDl = 0.0",
    "Build24 zero-axis minimum",
)

replace_once(
    graph,
    '''            func yPosition(_ value: Double) -> CGFloat {
                let clamped = min(max(value, minimumMgDl), maximumMgDl)
                let fraction = (maximumMgDl - clamped) / (maximumMgDl - minimumMgDl)
                return plotTop + CGFloat(fraction) * plotHeight
            }
''',
    '''            func yPosition(_ value: Double) -> CGFloat {
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
''',
    "Build24 piecewise Y scale",
)

replace_once(
    graph,
    '''                context.stroke(path, with: .color(color), style: StrokeStyle(lineWidth: 0.75, dash: dash))
                drawLabel(String(Int(level)), at: CGPoint(x: plotLeft - 3.0, y: y), anchor: UnitPoint(x: 1, y: 0.5))
            }
''',
    '''                context.stroke(path, with: .color(color), style: StrokeStyle(lineWidth: 0.75, dash: dash))

                // At 220 the dashed axis is aligned with the TOP edge of the text.
                // Other threshold labels remain vertically centered on their axes.
                let labelAnchor = level == 220.0 ? UnitPoint(x: 1, y: 0) : UnitPoint(x: 1, y: 0.5)
                drawLabel(String(Int(level)), at: CGPoint(x: plotLeft - 3.0, y: y), anchor: labelAnchor)
            }

            // Unlabelled zero baseline. This is the bottom edge of the data plot and the
            // endpoint of the solid current-time line at the right.
            let zeroY = yPosition(0)
            var zeroLine = Path()
            zeroLine.move(to: CGPoint(x: plotLeft, y: zeroY))
            zeroLine.addLine(to: CGPoint(x: plotRight, y: zeroY))
            context.stroke(
                zeroLine,
                with: .color(Color.secondary.opacity(0.60)),
                style: StrokeStyle(lineWidth: 0.75, dash: [2.5, 2.5])
            )
''',
    "Build24 zero baseline and 220 label alignment",
)

replace_once(
    graph,
    '''            // Build 23: one center grid line only. The former 30-minute subdivisions are
            // intentionally removed so the tiny Ultra complication is not visually overloaded.
            let centerGridX = plotLeft + plotWidth / 2
            var centerGrid = Path()
            centerGrid.move(to: CGPoint(x: centerGridX, y: plotTop))
            centerGrid.addLine(to: CGPoint(x: centerGridX, y: plotBottom))
            context.stroke(centerGrid, with: .color(Color.secondary.opacity(0.52)), style: StrokeStyle(lineWidth: 0.7, dash: [2.5, 2.5]))
''',
    '''            // Build 24: dashed vertical guides at the first and middle full-hour labels.
            // The right edge remains a SOLID current-time line and is drawn separately below.
            for fraction in [0.0, 0.5] as [CGFloat] {
                let x = plotLeft + plotWidth * fraction
                var hourGrid = Path()
                hourGrid.move(to: CGPoint(x: x, y: plotTop))
                hourGrid.addLine(to: CGPoint(x: x, y: zeroY))
                context.stroke(
                    hourGrid,
                    with: .color(Color.secondary.opacity(0.58)),
                    style: StrokeStyle(lineWidth: 0.75, dash: [2.5, 2.5])
                )
            }
''',
    "Build24 full-hour vertical guides",
)

# The right line already targets plotBottom. With the new zero-axis minimum,
# yPosition(0) == plotBottom, so verify and document it explicitly.
replace_once(
    graph,
    '''            currentLine.move(to: CGPoint(x: plotRight, y: plotTop))
            currentLine.addLine(to: CGPoint(x: plotRight, y: plotBottom))
''',
    '''            currentLine.move(to: CGPoint(x: plotRight, y: plotTop))
            currentLine.addLine(to: CGPoint(x: plotRight, y: zeroY))
''',
    "Build24 current line to zero axis",
)


# -----------------------------------------------------------------------------
# 2) Add modern single-target ClockKit bridge to the Watch app.
#
# Apple's TN3157 says that after moving to a SwiftUI single-target watchOS app,
# complication apps carry CLKComplicationPrincipalClass and
# CLKComplicationSupportedFamilies in the WATCH APP Info.plist. The WidgetKit
# extension remains the renderer. The bridge also provides a WidgetKit migration
# mapping so the legacy descriptor resolves to our current static widget kind.
# -----------------------------------------------------------------------------
watch_app = Path("xDrip Watch App/xDripWatchApp.swift")
watch_text = watch_app.read_text(encoding="utf-8")

if "import ClockKit" not in watch_text:
    watch_text = watch_text.replace(
        "import SwiftUI\n",
        "import SwiftUI\nimport ClockKit\n",
        1,
    )

bridge = r'''

// MARK: - Complication discovery bridge
//
// Build 24: Keep WidgetKit as the rendering system, but publish the metadata that
// the single-target watchOS app model uses for complication discovery/migration.
final class ComplicationController: NSObject, CLKComplicationDataSource, CLKComplicationWidgetMigrator {
    private static let graphDescriptorIdentifier = "xDrip.graph"
    private static let bgDescriptorIdentifier = "xDrip.bg"

    func getComplicationDescriptors(handler: @escaping ([CLKComplicationDescriptor]) -> Void) {
        handler([
            CLKComplicationDescriptor(
                identifier: Self.graphDescriptorIdentifier,
                displayName: "xDrip Graph",
                supportedFamilies: [.graphicRectangular]
            ),
            CLKComplicationDescriptor(
                identifier: Self.bgDescriptorIdentifier,
                displayName: "xDrip BG",
                supportedFamilies: [.graphicCircular]
            )
        ])
    }

    func getCurrentTimelineEntry(
        for complication: CLKComplication,
        withHandler handler: @escaping (CLKComplicationTimelineEntry?) -> Void
    ) {
        // WidgetKit owns rendering/timelines on watchOS 9+. This ClockKit data source
        // exists only so the system can enumerate/migrate the complication provider.
        handler(nil)
    }

    var widgetMigrator: CLKComplicationWidgetMigrator { self }

    func getWidgetConfiguration(
        from complicationDescriptor: CLKComplicationDescriptor,
        completionHandler: @escaping (CLKComplicationWidgetMigrationConfiguration?) -> Void
    ) {
        guard complicationDescriptor.identifier == Self.graphDescriptorIdentifier
                || complicationDescriptor.identifier == Self.bgDescriptorIdentifier,
              let watchBundleIdentifier = Bundle.main.bundleIdentifier else {
            completionHandler(nil)
            return
        }

        completionHandler(
            CLKComplicationStaticWidgetMigrationConfiguration(
                kind: "xDripWatchComplication",
                extensionBundleIdentifier: watchBundleIdentifier + ".xDripWatchComplication"
            )
        )
    }
}
'''

if "final class ComplicationController" not in watch_text:
    watch_text += bridge
watch_app.write_text(watch_text, encoding="utf-8")


# -----------------------------------------------------------------------------
# 3) Publish complication-provider metadata from the Watch app Info.plist.
# -----------------------------------------------------------------------------
watch_info_path = Path("xDrip-Watch-App-Info.plist")
with watch_info_path.open("rb") as handle:
    watch_info = plistlib.load(handle)

watch_info["CLKComplicationPrincipalClass"] = "$(PRODUCT_MODULE_NAME).ComplicationController"
watch_info["CLKComplicationSupportedFamilies"] = [
    "CLKComplicationFamilyGraphicCircular",
    "CLKComplicationFamilyGraphicRectangular",
]

with watch_info_path.open("wb") as handle:
    plistlib.dump(watch_info, handle, sort_keys=False)

print("Build 24 applied: final graph geometry + Watch complication discovery/migration bridge.")
