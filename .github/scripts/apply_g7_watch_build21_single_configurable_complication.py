from pathlib import Path
import plistlib


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_in_block(text: str, start_token: str, end_token: str, old: str, new: str, label: str) -> str:
    start = text.find(start_token)
    if start < 0:
        raise RuntimeError(f"{label}: start token not found")
    end = text.find(end_token, start)
    if end < 0:
        raise RuntimeError(f"{label}: end token not found")
    block = text[start:end]
    if block.count(old) != 1:
        raise RuntimeError(f"{label}: expected one value in block, found {block.count(old)}")
    return text[:start] + block.replace(old, new, 1) + text[end:]


# Build 21 is a registration-recovery build after Build 20.
# Empirical evidence: the original single Widget entry point was usable on the face,
# while the Build 19 four-widget WidgetBundle is absent from the iPhone Watch app picker.
# Apple supports configurable watch complications through AppIntentConfiguration, so Build 21
# returns to ONE discoverable xDrip widget kind and makes each circular instance configurable
# as BG / delta+trend / last reading time. The rectangular family is always the 2-hour graph.
# This keeps separate per-slot content without relying on four top-level Widget kinds.


# -----------------------------------------------------------------------------
# 1) Match the current Xcode 26 Widget Extension plist shape.
#    Xcode 26's template contains only com.apple.widgetkit-extension and does NOT add
#    WKAppBundleIdentifier to a WidgetKit extension, so remove Build 20's experimental key.
# -----------------------------------------------------------------------------
info_path = Path("xDrip Watch Complication/Info.plist")
with info_path.open("rb") as handle:
    info = plistlib.load(handle)

extension = info.setdefault("NSExtension", {})
extension["NSExtensionPointIdentifier"] = "com.apple.widgetkit-extension"
extension.pop("NSExtensionAttributes", None)
info["CFBundleDisplayName"] = "xDrip"

with info_path.open("wb") as handle:
    plistlib.dump(info, handle, sort_keys=False)


# Force the packaged extension display name to xDrip instead of MAIN_APP_DISPLAY_NAME.
# Build settings override Info.plist values during packaging, so change only the complication
# target's Debug/Release blocks.
project = Path("xdrip.xcodeproj/project.pbxproj")
project_text = project.read_text(encoding="utf-8")
old_display = 'INFOPLIST_KEY_CFBundleDisplayName = "$(MAIN_APP_DISPLAY_NAME)";'
new_display = 'INFOPLIST_KEY_CFBundleDisplayName = xDrip;'
project_text = replace_in_block(
    project_text,
    '479359922B88B95B007D3CEE /* Debug */ = {',
    '479359932B88B95B007D3CEE /* Release */ = {',
    old_display,
    new_display,
    "Build21 complication Debug display name",
)
project_text = replace_in_block(
    project_text,
    '479359932B88B95B007D3CEE /* Release */ = {',
    '47A6ABEA2B790CC70047A4BA /* Debug */ = {',
    old_display,
    new_display,
    "Build21 complication Release display name",
)
project.write_text(project_text, encoding="utf-8")


# -----------------------------------------------------------------------------
# 2) Single configurable widget entry point.
# -----------------------------------------------------------------------------
widget = Path("xDrip Watch Complication/XDripWatchComplication.swift")
widget.write_text(r'''//
//  XDripWatchComplication.swift
//  xDrip Watch Complication
//
//  Build 21: one discoverable configurable WidgetKit complication.
//

import WidgetKit
import SwiftUI
import Foundation
import AppIntents

enum XDripComplicationDisplayMode: String, AppEnum, CaseIterable {
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

@main
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


extension XDripWatchComplication.Entry {
    var build21LatestDate: Date? { widgetState.bgReadingDates?.first }
    var build21LatestValue: Double? { widgetState.bgReadingValues?.first }

    var build21IsFresh: Bool {
        guard let date = build21LatestDate else { return false }
        return date > self.date.addingTimeInterval(-12 * 60)
            && date <= self.date.addingTimeInterval(60)
    }

    var build21ValueColor: Color {
        guard build21IsFresh, let value = build21LatestValue else { return .gray }
        if value >= widgetState.urgentHighLimitInMgDl || value <= widgetState.urgentLowLimitInMgDl {
            return .red
        } else if value >= widgetState.highLimitInMgDl || value <= widgetState.lowLimitInMgDl {
            return .yellow
        } else {
            return .green
        }
    }

    var build21TrendArrow: String {
        guard build21IsFresh else { return "" }
        switch widgetState.slopeOrdinal {
        case 7: return "↓↓"
        case 6: return "↓"
        case 5: return "↘"
        case 4: return "→"
        case 3: return "↗"
        case 2: return "↑"
        case 1: return "↑↑"
        default: return ""
        }
    }

    var build21DeltaText: String {
        guard build21IsFresh, let delta = widgetState.deltaValueInUserUnit else { return "--" }
        if widgetState.isMgDl {
            return String(format: "%+.0f", delta)
        }
        return String(format: "%+.1f", delta)
    }
}

struct XDripBGCircleView: View {
    let entry: XDripWatchComplication.Entry

    var body: some View {
        ZStack {
            Circle()
                .stroke(entry.build21ValueColor.opacity(0.85), lineWidth: 3)

            VStack(spacing: -1) {
                Text(entry.build21IsFresh ? entry.widgetState.bgValueStringInUserChosenUnit() : "---")
                    .font(.system(size: 20, weight: .bold, design: .rounded))
                    .foregroundStyle(entry.build21ValueColor)
                    .minimumScaleFactor(0.55)
                    .lineLimit(1)

                if entry.build21IsFresh {
                    Text(entry.build21TrendArrow)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(entry.build21ValueColor)
                        .lineLimit(1)
                }
            }
            .padding(3)
        }
        .widgetBackground(backgroundView: Color.clear)
    }
}

struct XDripDeltaCircleView: View {
    let entry: XDripWatchComplication.Entry

    var body: some View {
        ZStack {
            Circle()
                .fill(entry.build21ValueColor.opacity(0.16))
            Circle()
                .stroke(entry.build21ValueColor.opacity(0.55), lineWidth: 2)

            VStack(spacing: -2) {
                Text(entry.build21DeltaText)
                    .font(.system(size: 18, weight: .bold, design: .rounded))
                    .foregroundStyle(entry.build21IsFresh ? Color.colorPrimary : Color.gray)
                    .minimumScaleFactor(0.55)
                    .lineLimit(1)

                Text(entry.build21TrendArrow)
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(entry.build21ValueColor)
                    .lineLimit(1)
            }
            .padding(3)
        }
        .widgetBackground(backgroundView: Color.clear)
    }
}

struct XDripLastTimeCircleView: View {
    let entry: XDripWatchComplication.Entry

    var body: some View {
        ZStack {
            Circle()
                .stroke(Color.secondary.opacity(0.6), lineWidth: 2)

            VStack(spacing: 0) {
                Text(entry.build21LatestDate?.formatted(date: .omitted, time: .shortened) ?? "--:--")
                    .font(.system(size: 15, weight: .bold, design: .rounded))
                    .foregroundStyle(.colorPrimary)
                    .monospacedDigit()
                    .minimumScaleFactor(0.55)
                    .lineLimit(1)

                Text("xDrip")
                    .font(.system(size: 8, weight: .medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            .padding(3)
        }
        .widgetBackground(backgroundView: Color.clear)
    }
}
''', encoding="utf-8")


# -----------------------------------------------------------------------------
# 3) Each installed instance carries its own circular display mode.
# -----------------------------------------------------------------------------
entry_path = Path("xDrip Watch Complication/XDripWatchComplication+Entry.swift")
replace_once(
    entry_path,
    '''        var date: Date = .now\n        var widgetState: WidgetState''',
    '''        var date: Date = .now\n        var widgetState: WidgetState\n        var displayMode: XDripComplicationDisplayMode = .bg''',
    "Build21 add per-instance display mode",
)

entry_view = Path("xDrip Watch Complication/XDripWatchComplication+EntryView.swift")
entry_view.write_text(r'''//
//  XDripWatchComplication+EntryView.swift
//  xDrip Watch Complication Extension
//
//  Build 21: rectangular graph + configurable circular content.
//

import SwiftUI
import Foundation
import WidgetKit

extension XDripWatchComplication {
    struct EntryView: View {
        @Environment(\.widgetFamily) private var widgetFamily
        var entry: Entry

        var body: some View {
            switch widgetFamily {
            case .accessoryRectangular:
                // The center Modular Ultra slot is always the large 2-hour graph.
                accessoryRectangularView

            case .accessoryCircular:
                switch entry.displayMode {
                case .bg:
                    XDripBGCircleView(entry: entry)
                case .delta:
                    XDripDeltaCircleView(entry: entry)
                case .lastTime:
                    XDripLastTimeCircleView(entry: entry)
                }

            default:
                XDripBGCircleView(entry: entry)
            }
        }
    }
}
''', encoding="utf-8")


# -----------------------------------------------------------------------------
# 4) AppIntent timeline provider: same 5-minute fallback and exact 12-minute stale switch.
# -----------------------------------------------------------------------------
provider = Path("xDrip Watch Complication/XDripWatchComplication+Provider.swift")
provider.write_text(r'''//
//  XDripWatchComplication+Provider.swift
//  xDrip Watch Complication Extension
//
//  Build 21 configurable complication provider.
//

import SwiftUI
import WidgetKit
import Foundation
import AppIntents

extension XDripWatchComplication {
    struct Provider: AppIntentTimelineProvider {
        typealias Intent = XDripComplicationConfigurationIntent

        private let refreshInterval: TimeInterval = 5 * 60
        private let staleAfter: TimeInterval = 12 * 60

        func placeholder(in context: Context) -> Entry {
            var entry = Entry.placeholder
            entry.displayMode = .bg
            return entry
        }

        func snapshot(for configuration: Intent, in context: Context) async -> Entry {
            Entry(
                date: .now,
                widgetState: getWidgetStateFromSharedUserDefaults() ?? sampleWidgetStateFromProvider,
                displayMode: configuration.displayMode
            )
        }

        func timeline(for configuration: Intent, in context: Context) async -> Timeline<Entry> {
            let now = Date()
            let widgetState = getWidgetStateFromSharedUserDefaults() ?? sampleWidgetStateFromProvider
            let nextRefresh = now.addingTimeInterval(refreshInterval)
            var entryDates: [Date] = [now]

            if let latestReadingDate = widgetState.bgReadingDate {
                let staleDate = latestReadingDate.addingTimeInterval(staleAfter)
                if staleDate > now, staleDate < nextRefresh {
                    entryDates.append(staleDate)
                }
            }

            let entries = entryDates
                .sorted()
                .map { Entry(date: $0, widgetState: widgetState, displayMode: configuration.displayMode) }

            return Timeline(entries: entries, policy: .after(nextRefresh))
        }

        // These presets also make the three useful circular modes explicit to WidgetKit.
        // On current watchOS versions the same intent can be configured per installed slot.
        func recommendations() -> [AppIntentRecommendation<Intent>] {
            var bg = Intent()
            bg.displayMode = .bg
            var delta = Intent()
            delta.displayMode = .delta
            var lastTime = Intent()
            lastTime.displayMode = .lastTime

            return [
                AppIntentRecommendation(intent: bg, description: "xDrip BG"),
                AppIntentRecommendation(intent: delta, description: "xDrip Änderung"),
                AppIntentRecommendation(intent: lastTime, description: "xDrip Messzeit")
            ]
        }
    }
}


extension XDripWatchComplication.Provider {
    func getWidgetStateFromSharedUserDefaults() -> XDripWatchComplication.Entry.WidgetState? {
        guard let sharedUserDefaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else { return nil }

        guard let encodedLatestReadings = sharedUserDefaults.data(forKey: "complicationSharedUserDefaults.\(Bundle.main.mainAppBundleIdentifier)") else {
            return nil
        }

        let decoder = JSONDecoder()

        do {
            let data = try decoder.decode(ComplicationSharedUserDefaultsModel.self, from: encodedLatestReadings)
            let bgReadingDates = data.bgReadingDatesAsDouble.map { Date(timeIntervalSince1970: $0) }
            let dataSource = sharedUserDefaults.string(forKey: "complicationDataSource.\(Bundle.main.mainAppBundleIdentifier)")

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
            print(error.localizedDescription)
        }

        return sampleWidgetStateFromProvider
    }

    private var sampleWidgetStateFromProvider: XDripWatchComplication.Entry.WidgetState {
        Entry.WidgetState(
            bgReadingValues: ConstantsWatchComplication.bgReadingValuesPlaceholderData,
            bgReadingDates: ConstantsWatchComplication.bgReadingDatesPlaceholderData(),
            isMgDl: true,
            slopeOrdinal: 4,
            deltaValueInUserUnit: 0,
            urgentLowLimitInMgDl: 70,
            lowLimitInMgDl: 90,
            highLimitInMgDl: 140,
            urgentHighLimitInMgDl: 180
        )
    }
}
''', encoding="utf-8")


# -----------------------------------------------------------------------------
# 5) One kind reloads every configured instance (graph and all circular modes).
# -----------------------------------------------------------------------------
watch_state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")
old_reload = '''            for complicationKind in [\n                "xDripWatchComplication",\n                "xDripBGComplication",\n                "xDripDeltaComplication",\n                "xDripLastTimeComplication"\n            ] {\n                WidgetCenter.shared.reloadTimelines(ofKind: complicationKind)\n            }'''
new_reload = '            WidgetCenter.shared.reloadTimelines(ofKind: "xDripWatchComplication")'
replace_once(
    watch_state,
    old_reload,
    new_reload,
    "Build21 reload single configurable complication kind",
)

print("Build 21 single configurable xDrip complication registration architecture applied successfully.")
