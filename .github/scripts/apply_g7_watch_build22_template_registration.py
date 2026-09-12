from pathlib import Path
import plistlib


def target_block(text: str, start_token: str, end_token: str) -> tuple[int, int, str]:
    start = text.find(start_token)
    if start < 0:
        raise RuntimeError(f"start token not found: {start_token}")
    end = text.find(end_token, start)
    if end < 0:
        raise RuntimeError(f"end token not found: {end_token}")
    return start, end, text[start:end]


def ensure_setting(block: str, anchor: str, setting: str, label: str) -> str:
    if setting in block:
        return block
    if anchor not in block:
        raise RuntimeError(f"{label}: anchor not found: {anchor}")
    return block.replace(anchor, anchor + "\n\t\t\t\t" + setting, 1)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


# Build 22 deliberately removes variables from the registration path.
# Build 21 compiled, signed and embedded correctly, but watchOS/iPhone still did not enumerate
# the complication. This build mirrors a current working watchOS WidgetKit-extension target:
#   - explicit (non-generated) Info.plist
#   - APPLICATION_EXTENSION_API_ONLY = YES
#   - SUPPORTED_PLATFORMS = watchos watchsimulator
#   - one @main Widget using StaticConfiguration (no AppIntent required for discovery)
# The rectangular family remains the 2-hour graph; circular slots show BG.


# -----------------------------------------------------------------------------
# 1) Use the explicit modern WidgetKit extension plist shape.
# -----------------------------------------------------------------------------
info_path = Path("xDrip Watch Complication/Info.plist")
info = {
    "CFBundleDisplayName": "xDrip",
    "CFBundleExecutable": "$(EXECUTABLE_NAME)",
    "CFBundleIdentifier": "$(PRODUCT_BUNDLE_IDENTIFIER)",
    "CFBundleInfoDictionaryVersion": "6.0",
    "CFBundleName": "$(PRODUCT_NAME)",
    "CFBundlePackageType": "$(PRODUCT_BUNDLE_PACKAGE_TYPE)",
    "CFBundleShortVersionString": "$(MARKETING_VERSION)",
    "CFBundleVersion": "$(CURRENT_PROJECT_VERSION)",
    "AppGroupIdentifier": "$(APP_GROUP_IDENTIFIER)",
    "MainAppBundleIdentifier": "$(MAIN_APP_BUNDLE_IDENTIFIER)",
    "NSExtension": {
        "NSExtensionPointIdentifier": "com.apple.widgetkit-extension"
    },
}
with info_path.open("wb") as handle:
    plistlib.dump(info, handle, sort_keys=False)


# -----------------------------------------------------------------------------
# 2) Align the Watch Widget target settings with a current Xcode watchOS Widget target.
# -----------------------------------------------------------------------------
project_path = Path("xdrip.xcodeproj/project.pbxproj")
project = project_path.read_text(encoding="utf-8")

configs = [
    (
        '479359922B88B95B007D3CEE /* Debug */ = {',
        '479359932B88B95B007D3CEE /* Release */ = {',
        "Debug",
    ),
    (
        '479359932B88B95B007D3CEE /* Release */ = {',
        '47A6ABEA2B790CC70047A4BA /* Debug */ = {',
        "Release",
    ),
]

for start_token, end_token, label in configs:
    start, end, block = target_block(project, start_token, end_token)
    block = replace_once(
        block,
        "GENERATE_INFOPLIST_FILE = YES;",
        "GENERATE_INFOPLIST_FILE = NO;",
        f"{label} explicit Info.plist",
    )
    block = ensure_setting(
        block,
        "\t\t\t\tAPP_GROUP_IDENTIFIER = \"group.com.${DEVELOPMENT_TEAM}.loopkit.LoopGroup\";",
        "APPLICATION_EXTENSION_API_ONLY = YES;",
        f"{label} extension API only",
    )
    block = ensure_setting(
        block,
        "\t\t\t\tSKIP_INSTALL = YES;",
        'SUPPORTED_PLATFORMS = "watchos watchsimulator";',
        f"{label} supported platforms",
    )
    if 'INFOPLIST_KEY_CFBundleDisplayName = "$(MAIN_APP_DISPLAY_NAME)";' in block:
        block = block.replace(
            'INFOPLIST_KEY_CFBundleDisplayName = "$(MAIN_APP_DISPLAY_NAME)";',
            "INFOPLIST_KEY_CFBundleDisplayName = xDrip;",
            1,
        )
    project = project[:start] + block + project[end:]

# Make the PBX target metadata match its actual target/product name as well.
project = project.replace(
    'productName = "xDrip Watch ComplicationExtension";',
    'productName = "xDrip Watch Complication Extension";',
    1,
)
project_path.write_text(project, encoding="utf-8")


# -----------------------------------------------------------------------------
# 3) Replace AppIntentConfiguration with the simplest possible discoverable WidgetKit config.
#    Keep the enum because EntryView uses it internally, but it is no longer an AppIntent type.
# -----------------------------------------------------------------------------
widget_path = Path("xDrip Watch Complication/XDripWatchComplication.swift")
widget = widget_path.read_text(encoding="utf-8")
widget = widget.replace("import AppIntents\n", "", 1)

old_intent_types = '''enum XDripComplicationDisplayMode: String, AppEnum, CaseIterable {
    case bg
    case delta
    case lastTime

    static var typeDisplayRepresentation: TypeDisplayRepresentation = "xDrip Anzeige"
    static var caseDisplayRepresentations: [XDripComplicationDisplayMode: DisplayRepresentation] = [
        .bg: "BG-Wert",
        .delta: "Änderung + Trend",
        .lastTime: "Letzte Messzeit"
    ]
}

struct XDripComplicationConfigurationIntent: WidgetConfigurationIntent {
    static var title: LocalizedStringResource = "xDrip"
    static var description = IntentDescription("Wähle den Inhalt für eine runde xDrip-Komplikation.")

    @Parameter(title: "Anzeige", default: .bg)
    var displayMode: XDripComplicationDisplayMode
}
'''
new_intent_types = '''enum XDripComplicationDisplayMode: String {
    case bg
    case delta
    case lastTime
}
'''
widget = replace_once(widget, old_intent_types, new_intent_types, "remove AppIntent registration dependency")

old_configuration = '''@main
struct XDripWatchComplication: Widget {
    let kind: String = "xDripWatchComplication"

    var body: some WidgetConfiguration {
        AppIntentConfiguration(
            kind: kind,
            intent: XDripComplicationConfigurationIntent.self,
            provider: Provider()
        ) { entry in
            EntryView(entry: entry)
        }
        .configurationDisplayName("xDrip")
        .description("2-Stunden-Glukosegraph oder frei wählbarer xDrip-Wert")
        .supportedFamilies([.accessoryRectangular, .accessoryCircular])
        .contentMarginsDisabled()
    }
}
'''
new_configuration = '''@main
struct XDripWatchComplication: Widget {
    let kind: String = "xDripWatchComplication"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: Provider()) { entry in
            EntryView(entry: entry)
        }
        .configurationDisplayName("xDrip")
        .description("xDrip Glukose auf der Apple Watch")
        .supportedFamilies([.accessoryRectangular, .accessoryCircular])
        .contentMarginsDisabled()
    }
}
'''
widget = replace_once(widget, old_configuration, new_configuration, "StaticConfiguration discovery path")
widget_path.write_text(widget, encoding="utf-8")


# -----------------------------------------------------------------------------
# 4) Use a plain TimelineProvider, so complication discovery has zero AppIntent dependency.
# -----------------------------------------------------------------------------
provider_path = Path("xDrip Watch Complication/XDripWatchComplication+Provider.swift")
provider_path.write_text(r'''//
//  XDripWatchComplication+Provider.swift
//  xDrip Watch Complication Extension
//
//  Build 22: minimal static WidgetKit discovery provider.
//

import SwiftUI
import WidgetKit
import Foundation

extension XDripWatchComplication {
    struct Provider: TimelineProvider {
        private let refreshInterval: TimeInterval = 5 * 60
        private let staleAfter: TimeInterval = 12 * 60

        func placeholder(in context: Context) -> Entry {
            var entry = Entry.placeholder
            entry.displayMode = .bg
            return entry
        }

        func getSnapshot(in context: Context, completion: @escaping (Entry) -> Void) {
            let state = getWidgetStateFromSharedUserDefaults() ?? Entry.placeholder.widgetState
            completion(Entry(date: .now, widgetState: state, displayMode: .bg))
        }

        func getTimeline(in context: Context, completion: @escaping (Timeline<Entry>) -> Void) {
            let now = Date()
            let state = getWidgetStateFromSharedUserDefaults() ?? Entry.placeholder.widgetState
            let nextRefresh = now.addingTimeInterval(refreshInterval)
            var entryDates: [Date] = [now]

            if let latestReadingDate = state.bgReadingDate {
                let staleDate = latestReadingDate.addingTimeInterval(staleAfter)
                if staleDate > now, staleDate < nextRefresh {
                    entryDates.append(staleDate)
                }
            }

            let entries = entryDates
                .sorted()
                .map { Entry(date: $0, widgetState: state, displayMode: .bg) }
            completion(Timeline(entries: entries, policy: .after(nextRefresh)))
        }
    }
}

extension XDripWatchComplication.Provider {
    func getWidgetStateFromSharedUserDefaults() -> XDripWatchComplication.Entry.WidgetState? {
        guard let sharedUserDefaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else { return nil }
        guard let encodedLatestReadings = sharedUserDefaults.data(
            forKey: "complicationSharedUserDefaults.\(Bundle.main.mainAppBundleIdentifier)"
        ) else { return nil }

        do {
            let data = try JSONDecoder().decode(ComplicationSharedUserDefaultsModel.self, from: encodedLatestReadings)
            let bgReadingDates = data.bgReadingDatesAsDouble.map { Date(timeIntervalSince1970: $0) }
            let dataSource = sharedUserDefaults.string(
                forKey: "complicationDataSource.\(Bundle.main.mainAppBundleIdentifier)"
            )

            return Entry.WidgetState(
                bgReadingValues: data.bgReadingValues,
                bgReadingDates: bgReadingDates,
                isMgDl: data.isMgDl,
                slopeOrdinal: data.slopeOrdinal,
                deltaValueInUserUnit: data.deltaValueInUserUnit,
                urgentLowLimitInMgDl: data.urgentLowLimitInMgDl,
                lowLimitInMgDl: data.lowLimitInMgDl,
                highLimitInMgDl: data.highLimitInMgDl,
                urgentHighLimitInMgDl: data.urgentHighLimitInMgDl,
                keepAliveIsDisabled: data.keepAliveIsDisabled,
                dataSource: dataSource
            )
        } catch {
            print("Build22 complication state decode failed: \(error.localizedDescription)")
            return nil
        }
    }
}
''', encoding="utf-8")

print("Build 22 current-template registration + StaticConfiguration patch applied successfully.")
