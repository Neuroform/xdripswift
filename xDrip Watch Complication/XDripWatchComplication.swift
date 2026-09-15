//
//  XDripWatchComplication.swift
//  xDrip Watch Complication
//
//  Build 36: final graph + two circular complications.
//

import WidgetKit
import SwiftUI

// Keep this type as the namespace used by Entry/Provider/EntryView extensions.
struct XDripWatchComplication: Widget {
    let kind: String = "xDripGraphV33"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: Provider()) { entry in
            XDripWatchComplication.EntryView(entry: entry)
        }
        .configurationDisplayName("xDrip Graph")
        .description("xDrip 150-minute glucose graph")
        .supportedFamilies([.accessoryRectangular])
        .contentMarginsDisabled()
    }
}

struct XDripBGComplicationV36: Widget {
    let kind: String = "xDripBGV36"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: XDripWatchComplication.Provider()) { entry in
            XDripBGCircleV36View(entry: entry)
        }
        .configurationDisplayName("xDrip BG")
        .description("Current glucose and trend")
        .supportedFamilies([.accessoryCircular])
        .contentMarginsDisabled()
    }
}

struct XDripDeltaComplicationV36: Widget {
    let kind: String = "xDripDeltaV36"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: XDripWatchComplication.Provider()) { entry in
            XDripDeltaCircleV36View(entry: entry)
        }
        .configurationDisplayName("xDrip Delta")
        .description("Glucose change since the previous reading")
        .supportedFamilies([.accessoryCircular])
        .contentMarginsDisabled()
    }
}

@main
struct XDripWatchComplicationBundleV36: WidgetBundle {
    @WidgetBundleBuilder
    var body: some Widget {
        XDripWatchComplication()
        XDripBGComplicationV36()
        XDripDeltaComplicationV36()
    }
}
