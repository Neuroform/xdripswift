from pathlib import Path

# Build 29 is a deliberate registration rollback to the last architecture that
# was actually selectable on the user's Watch: ONE @main StaticConfiguration
# with the original xDrip complication kind. The final Build-28 graph/provider
# code remains intact; only the multi-widget registration is removed.

widget_path = Path("xDrip Watch Complication/XDripWatchComplication.swift")
text = widget_path.read_text(encoding="utf-8")

marker = "// MARK: - Freshness helpers shared by the two circular complications"
if marker not in text:
    raise RuntimeError("Build29: Build28 helper marker not found")
helpers = text[text.index(marker):]

single_widget = r'''//
//  XDripWatchComplication.swift
//  xDrip Watch Complication
//
//  Build 29: restore the original single-widget registration path.
//

import WidgetKit
import SwiftUI
import Foundation

@main
struct XDripWatchComplication: Widget {
    let kind: String = "xDripWatchComplication"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: Provider()) { entry in
            EntryView(entry: entry)
        }
        .configurationDisplayName("Martin’s xDrip")
        .description("xDrip Glukose auf der Apple Watch")
        .supportedFamilies([.accessoryRectangular, .accessoryCircular])
        .contentMarginsDisabled()
    }
}

'''
widget_path.write_text(single_widget + helpers, encoding="utf-8")

# Route the circular family of the single, known-good widget to the requested
# BG minute-ring view. This avoids introducing any second Widget registration.
circular_path = Path("xDrip Watch Complication/Views/AccessoryCircularView.swift")
circular_path.write_text(r'''//
//  AccessoryCircularView.swift
//  xDrip Watch Complication Extension
//
//  Build 29: circular rendering for the restored single-widget registration.
//

import Foundation
import SwiftUI

extension XDripWatchComplication.EntryView {
    @ViewBuilder
    var accessoryCircularView: some View {
        if entry.widgetState.keepAliveIsDisabled {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.title2)
                .foregroundStyle(.colorPrimary)
                .widgetBackground(backgroundView: Color.clear)
        } else {
            XDripBGMinuteCircleView(entry: entry)
                .widgetBackground(backgroundView: Color.clear)
        }
    }
}
''', encoding="utf-8")

# New BG values must reload the original kind, not the abandoned Build-28 kinds.
state_path = Path("xDrip Watch App/DataModels/WatchStateModel.swift")
state = state_path.read_text(encoding="utf-8")
old = '''        // The App-Group write above is complete. Reload the three Build-28 complications
        // immediately so a new BG never waits for the minute timeline to advance.
        for complicationKind in ["xDripGraphV28", "xDripBGV28", "xDripTrendV28"] {
            WidgetCenter.shared.reloadTimelines(ofKind: complicationKind)
        }'''
new = '''        // Build 29 restores the original single complication kind used by xDrip.
        // Reload that exact kind immediately after the App-Group write.
        WidgetCenter.shared.reloadTimelines(ofKind: "xDripWatchComplication")'''
if state.count(old) != 1:
    raise RuntimeError(f"Build29: expected one Build28 reload block, found {state.count(old)}")
state_path.write_text(state.replace(old, new, 1), encoding="utf-8")

print("Build 29 applied: original single xDrip complication registration restored.")
