//
//  XDripWatchComplication+Provider.swift
//  xDrip Watch Complication Extension
//
//  Created by Paul Plant on 28/2/24.
//  Copyright © 2024 Johan Degraeve. All rights reserved.
//

import SwiftUI
import WidgetKit
import Foundation

extension XDripWatchComplication {
    struct Provider: TimelineProvider {
        private let timelineStep: TimeInterval = 5 * 60
        private let timelineHorizon: TimeInterval = 2 * 60 * 60
        private let dimAfter: TimeInterval = 7 * 60
        private let staleAfter: TimeInterval = 13 * 60

        func placeholder(in context: Context) -> Entry {
            .placeholder
        }

        func getSnapshot(in context: Context, completion: @escaping (Entry) -> ()) {
            completion(Entry(date: .now, widgetState: getWidgetStateFromSharedUserDefaults() ?? sampleWidgetStateFromProvider))
        }

        func getTimeline(in context: Context, completion: @escaping (Timeline<Entry>) -> ()) {
            let now = Date()
            let widgetState = getWidgetStateFromSharedUserDefaults() ?? sampleWidgetStateFromProvider
            let horizonDate = now.addingTimeInterval(timelineHorizon)

            // A complication is not a continuously running app. Pre-schedule a lightweight
            // 5-minute rolling timeline so the 2-hour window moves even when xDrip is closed.
            // A newly received BG still causes an immediate targeted reload and replaces this
            // future timeline with one based on the fresh state.
            var entryDates: [Date] = [now]
            var cursor = now.addingTimeInterval(timelineStep)
            while cursor <= horizonDate {
                entryDates.append(cursor)
                cursor = cursor.addingTimeInterval(timelineStep)
            }

            // Build 36: exact local visual transitions at 7 and 13 minutes, independent
            // of another phone/Watch transfer.
            if let latestReadingDate = widgetState.bgReadingDate {
                for transitionDate in [
                    latestReadingDate.addingTimeInterval(dimAfter),
                    latestReadingDate.addingTimeInterval(staleAfter)
                ] {
                    if transitionDate > now, transitionDate <= horizonDate,
                       !entryDates.contains(where: { abs($0.timeIntervalSince(transitionDate)) < 1 }) {
                        entryDates.append(transitionDate)
                    }
                }
            }

            let entries = entryDates
                .sorted()
                .map { Entry(date: $0, widgetState: widgetState) }

            completion(Timeline(entries: entries, policy: .atEnd))
        }
    }
}


// MARK: - Helpers

extension XDripWatchComplication.Provider {
    func getWidgetStateFromSharedUserDefaults() -> XDripWatchComplication.Entry.WidgetState? {
        guard let sharedUserDefaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else { return nil }

        guard let encodedLatestReadings = sharedUserDefaults.data(forKey: "complicationSharedUserDefaults.\(Bundle.main.mainAppBundleIdentifier)") else {
            return nil
        }

        let decoder = JSONDecoder()

        do {
            let data = try decoder.decode(ComplicationSharedUserDefaultsModel.self, from: encodedLatestReadings)

            let bgReadingDates: [Date] = data.bgReadingDatesAsDouble.map { date in
                Date(timeIntervalSince1970: date)
            }

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
