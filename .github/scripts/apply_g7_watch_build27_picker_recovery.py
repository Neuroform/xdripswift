from pathlib import Path
import plistlib

# Build 27 runs after Build 26. It restores the ClockKit descriptor bridge that
# made xDrip visible to the iPhone Watch face editor in Build 24, but fixes the
# Build-25 defect by mapping EACH descriptor to its matching WidgetKit kind.
# WidgetKit remains the renderer; ClockKit is only the picker/discovery bridge.

watch_app_path = Path("xDrip Watch App/xDripWatchApp.swift")
text = watch_app_path.read_text(encoding="utf-8")

if "import ClockKit\n" not in text:
    text = text.replace("import SwiftUI\n", "import SwiftUI\nimport ClockKit\n", 1)

# Refresh descriptors when the updated Watch app launches. Apple documents
# reloadComplicationDescriptors() for descriptor-set changes.
needle = "struct xDrip_Watch_AppApp: App {\n    @StateObject var watchState = WatchStateModel()\n    \n    var body: some Scene {"
replacement = "struct xDrip_Watch_AppApp: App {\n    @StateObject var watchState = WatchStateModel()\n\n    init() {\n        CLKComplicationServer.sharedInstance().reloadComplicationDescriptors()\n    }\n    \n    var body: some Scene {"
if needle not in text:
    raise RuntimeError("Build27: Watch App insertion point not found")
text = text.replace(needle, replacement, 1)

bridge = r'''

// MARK: - Build 27 complication picker bridge
final class ComplicationController: NSObject, CLKComplicationDataSource, CLKComplicationWidgetMigrator {
    private static let graphID = "xDrip.graph.v27"
    private static let bgID = "xDrip.bg.v27"
    private static let trendID = "xDrip.trend.v27"

    func getComplicationDescriptors(handler: @escaping ([CLKComplicationDescriptor]) -> Void) {
        handler([
            CLKComplicationDescriptor(
                identifier: Self.graphID,
                displayName: "Martin’s xDrip Graph",
                supportedFamilies: [.graphicRectangular]
            ),
            CLKComplicationDescriptor(
                identifier: Self.bgID,
                displayName: "xDrip BG mg/dL",
                supportedFamilies: [.graphicCircular]
            ),
            CLKComplicationDescriptor(
                identifier: Self.trendID,
                displayName: "BG Trend + Δ mg/dL",
                supportedFamilies: [.graphicCircular]
            )
        ])
    }

    private func template(for complication: CLKComplication) -> CLKComplicationTemplate? {
        switch complication.family {
        case .graphicRectangular:
            return CLKComplicationTemplateGraphicRectangularStandardBody(
                headerTextProvider: CLKSimpleTextProvider(text: "xDrip"),
                body1TextProvider: CLKSimpleTextProvider(text: "Martin’s xDrip Graph"),
                body2TextProvider: nil
            )
        case .graphicCircular:
            if complication.identifier == Self.trendID {
                return CLKComplicationTemplateGraphicCircularStackText(
                    line1TextProvider: CLKSimpleTextProvider(text: "→"),
                    line2TextProvider: CLKSimpleTextProvider(text: "+0")
                )
            }
            return CLKComplicationTemplateGraphicCircularStackText(
                line1TextProvider: CLKSimpleTextProvider(text: "108"),
                line2TextProvider: CLKSimpleTextProvider(text: "xDrip")
            )
        default:
            return nil
        }
    }

    func getPlaceholderTemplate(
        for complication: CLKComplication,
        withHandler handler: @escaping (CLKComplicationTemplate?) -> Void
    ) {
        handler(template(for: complication))
    }

    func getLocalizableSampleTemplate(
        for complication: CLKComplication,
        withHandler handler: @escaping (CLKComplicationTemplate?) -> Void
    ) {
        handler(template(for: complication))
    }

    func getCurrentTimelineEntry(
        for complication: CLKComplication,
        withHandler handler: @escaping (CLKComplicationTimelineEntry?) -> Void
    ) {
        guard let template = template(for: complication) else {
            handler(nil)
            return
        }
        handler(CLKComplicationTimelineEntry(date: Date(), complicationTemplate: template))
    }

    var widgetMigrator: CLKComplicationWidgetMigrator { self }

    func getWidgetConfiguration(
        from complicationDescriptor: CLKComplicationDescriptor,
        completionHandler: @escaping (CLKComplicationWidgetMigrationConfiguration?) -> Void
    ) {
        guard let watchBundleIdentifier = Bundle.main.bundleIdentifier else {
            completionHandler(nil)
            return
        }

        let kind: String
        switch complicationDescriptor.identifier {
        case Self.graphID:
            kind = "xDripGraphV26"
        case Self.bgID:
            kind = "xDripBGV26"
        case Self.trendID:
            kind = "xDripTrendV26"
        default:
            completionHandler(nil)
            return
        }

        completionHandler(
            CLKComplicationStaticWidgetMigrationConfiguration(
                kind: kind,
                extensionBundleIdentifier: watchBundleIdentifier + ".xDripWatchComplication"
            )
        )
    }
}
'''

if "final class ComplicationController" in text:
    raise RuntimeError("Build27: unexpected pre-existing ComplicationController after Build26")
text += bridge
watch_app_path.write_text(text, encoding="utf-8")

# Restore provider metadata. Build 24 proved that this makes xDrip discoverable
# by the companion iPhone Watch editor.
info_path = Path("xDrip-Watch-App-Info.plist")
with info_path.open("rb") as f:
    info = plistlib.load(f)
info["CLKComplicationPrincipalClass"] = "$(PRODUCT_MODULE_NAME).ComplicationController"
info["CLKComplicationSupportedFamilies"] = [
    "CLKComplicationFamilyGraphicCircular",
    "CLKComplicationFamilyGraphicRectangular",
]
with info_path.open("wb") as f:
    plistlib.dump(info, f, sort_keys=False)

# Build 26 WidgetKit bundle/kinds and graph rendering are intentionally untouched.
print("Build 27 applied: restored picker discovery bridge with 3 distinct descriptors and exact WidgetKit mappings.")
