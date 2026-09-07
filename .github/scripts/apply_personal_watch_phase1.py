from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1))


def replace_all_with_min_count(path: Path, old: str, new: str, minimum: int, label: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count < minimum:
        raise RuntimeError(f"{label}: expected at least {minimum} matches in {path}, found {count}")
    path.write_text(text.replace(old, new))


# 1) iPhone -> Watch: keep a coalesced latest-state channel in addition to the existing
# foreground message / complication-priority transfer paths, and avoid a queue of obsolete BG states.
watch_manager = Path("xDrip/Managers/Watch/WatchManager.swift")
replace_once(
    watch_manager,
    '''        if let userInfo = payload(updateTypes: updateTypes) {
            if session.isReachable {''',
    '''        if let userInfo = payload(updateTypes: updateTypes) {
            // Phase 1 personal build: keep the latest glucose/status state coalesced.
            // updateApplicationContext replaces the previous state instead of building a queue.
            if !updateTypes.contains(.agp) {
                do {
                    try session.updateApplicationContext(userInfo)
                } catch {
                    trace("error updating latest watch state, error = %{public}@", log: log, category: ConstantsLog.categoryWatchManager, type: .error, error.localizedDescription)
                }
            }

            if session.isReachable {''',
    "WatchManager latest-state insertion",
)
replace_once(
    watch_manager,
    '''                    session.transferUserInfo(userInfo)''',
    '''                    // BG payloads represent current state, not an event log. Cancel older queued
                    // BG states so watchOS cannot replay a backlog after a newer reading is available.
                    if userInfo["bgReadings"] != nil {
                        for transfer in session.outstandingUserInfoTransfers where transfer.userInfo["bgReadings"] != nil {
                            transfer.cancel()
                        }
                    }

                    session.transferUserInfo(userInfo)''',
    "WatchManager BG queue coalescing",
)


# 2) Watch app: reject out-of-order BG payloads and accept the coalesced application context.
watch_state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")
replace_once(
    watch_state,
    '''    private var latestAGPRequestID: Double = 0''',
    '''    private var latestAGPRequestID: Double = 0

    // Prevent queued/background WatchConnectivity payloads from replacing a newer glucose state.
    private var latestBgPayloadGeneratedAt: Double = 0''',
    "WatchStateModel BG generation marker",
)
replace_all_with_min_count(
    watch_state,
    'Date().addingTimeInterval(-60 * 20)',
    'Date().addingTimeInterval(-60 * 7)',
    3,
    "WatchStateModel 7-minute freshness",
)
old_bg_processor = '''    private func processBgReadingsFromDictionary(dictionary: [String: Any]) -> Bool {
        let bgReadingDatesFromDictionary: [Double] = dictionary["bgReadingDatesAsDouble"] as? [Double] ?? [0]

        // let's make a quick check to see if the data about to be processed is from within the last hour
        // this is to avoid long delays when re-opening a Watch app for the first time in days and waiting
        // whilst the whole queue of userInfo messages are processed
        if let lastBgReadingDateFromDictionaryReceived = bgReadingDatesFromDictionary.first, Date(timeIntervalSince1970: lastBgReadingDateFromDictionaryReceived) > Date(timeIntervalSinceNow: -60 * 60 * 1) {
            bgReadingDates = bgReadingDatesFromDictionary.map { bgReadingDateAsDouble -> Date in
                return Date(timeIntervalSince1970: bgReadingDateAsDouble)
            }

            bgReadingValues = dictionary["bgReadingValues"] as? [Double] ?? [100]

            slopeOrdinal = dictionary["slopeOrdinal"] as? Int ?? 0
            deltaValueInUserUnit = dictionary["deltaValueInUserUnit"] as? Double ?? 0
            updatedDate = Date(timeIntervalSince1970: dictionary["generatedAt"] as? Double ?? Date().timeIntervalSince1970)

            // check if there is any BG data available before updating the data source info strings accordingly
            if let bgReadingDate = bgReadingDate() {
                lastUpdatedTextString = Texts_WatchApp.lastReading + " "
                lastUpdatedTimeString = bgReadingDate.formatted(date: .omitted, time: .shortened)
                lastUpdatedTimeAgoString = bgReadingDate.daysAndHoursAgo(appendAgo: true)
            } else {
                lastUpdatedTextString = Texts_WatchApp.noSensorData
                lastUpdatedTimeString = ""
                lastUpdatedTimeAgoString = ""
            }

            return true
        }

        return false
    }'''
new_bg_processor = '''    private func processBgReadingsFromDictionary(dictionary: [String: Any]) -> Bool {
        let bgReadingDatesFromDictionary: [Double] = dictionary["bgReadingDatesAsDouble"] as? [Double] ?? []

        guard let incomingLatestTimestamp = bgReadingDatesFromDictionary.first else {
            return false
        }

        let incomingLatestDate = Date(timeIntervalSince1970: incomingLatestTimestamp)
        let incomingGeneratedAt = dictionary["generatedAt"] as? Double ?? incomingLatestTimestamp

        // Ignore very old queued states and, critically, never allow an older BG state to replace
        // a newer value that has already reached the Watch through another delivery channel.
        guard incomingLatestDate > Date(timeIntervalSinceNow: -60 * 60) else {
            return false
        }

        if let currentLatestDate = bgReadingDates.first {
            if incomingLatestDate < currentLatestDate {
                return false
            }

            if incomingLatestDate == currentLatestDate,
               incomingGeneratedAt <= latestBgPayloadGeneratedAt {
                return false
            }
        }

        latestBgPayloadGeneratedAt = incomingGeneratedAt
        bgReadingDates = bgReadingDatesFromDictionary.map { Date(timeIntervalSince1970: $0) }
        bgReadingValues = dictionary["bgReadingValues"] as? [Double] ?? []
        slopeOrdinal = dictionary["slopeOrdinal"] as? Int ?? 0
        deltaValueInUserUnit = dictionary["deltaValueInUserUnit"] as? Double ?? 0
        updatedDate = Date(timeIntervalSince1970: incomingGeneratedAt)

        if let bgReadingDate = bgReadingDate() {
            lastUpdatedTextString = Texts_WatchApp.lastReading + " "
            lastUpdatedTimeString = bgReadingDate.formatted(date: .omitted, time: .shortened)
            lastUpdatedTimeAgoString = bgReadingDate.daysAndHoursAgo(appendAgo: true)
        } else {
            lastUpdatedTextString = Texts_WatchApp.noSensorData
            lastUpdatedTimeString = ""
            lastUpdatedTimeAgoString = ""
        }

        return true
    }'''
replace_once(watch_state, old_bg_processor, new_bg_processor, "WatchStateModel out-of-order BG guard")
replace_once(
    watch_state,
    '''    func session(_: WCSession, didReceiveUserInfo userInfo: [String: Any] = [:]) {''',
    '''    func session(_: WCSession, didReceiveApplicationContext applicationContext: [String: Any]) {
        DispatchQueue.main.async {
            self.processWatchPayloadFromDictionary(dictionary: applicationContext)
        }
    }

    func session(_: WCSession, didReceiveUserInfo userInfo: [String: Any] = [:]) {''',
    "WatchStateModel application-context receiver",
)


# 3) Complication: 7-minute stale threshold and an automatic local timeline transition to stale.
entry = Path("xDrip Watch Complication/XDripWatchComplication+Entry.swift")
replace_once(
    entry,
    'return bgReadingDate > Date().addingTimeInterval(-60 * 20)',
    'return bgReadingDate > Date().addingTimeInterval(-60 * 7)',
    "Complication 7-minute freshness",
)

provider = Path("xDrip Watch Complication/XDripWatchComplication+Provider.swift")
replace_once(
    provider,
    '''        func getTimeline(in context: Context, completion: @escaping (Timeline<Entry>) -> ()) {
            let entry = Entry(date: .now, widgetState: getWidgetStateFromSharedUserDefaults() ?? sampleWidgetStateFromProvider)
                
            completion(.init(entries: [entry], policy: .never))
        }''',
    '''        func getTimeline(in context: Context, completion: @escaping (Timeline<Entry>) -> ()) {
            let now = Date()
            let widgetState = getWidgetStateFromSharedUserDefaults() ?? sampleWidgetStateFromProvider
            var entries = [Entry(date: now, widgetState: widgetState)]

            // Schedule a local stale-state transition at 7 minutes after the latest reading.
            // This does not require another iPhone transfer or another complication-priority update.
            if let latestReadingDate = widgetState.bgReadingDate {
                let staleDate = latestReadingDate.addingTimeInterval((7 * 60) + 1)
                if staleDate > now {
                    entries.append(Entry(date: staleDate, widgetState: widgetState))
                }
            }

            completion(.init(entries: entries, policy: .never))
        }''',
    "Complication stale timeline",
)

view = Path("xDrip Watch Complication/Views/AccessoryRectangularView.swift")
old_header = '''                HStack(alignment: .center) {
                    HStack(alignment: .center, spacing: 4) {
                        Text("\\(entry.widgetState.bgValueStringInUserChosenUnit())\\(entry.widgetState.trendArrow()) ")
                            .font(.system(size: entry.widgetState.isSmallScreen() ? 20 : 24)).bold()
                            .foregroundStyle(entry.widgetState.bgTextColor())

                        Text(entry.widgetState.deltaChangeStringInUserChosenUnit())
                            .font(.system(size: entry.widgetState.isSmallScreen() ? 20 : 24)).fontWeight(.semibold)
                            .foregroundStyle(.colorPrimary)
                            .lineLimit(1)
                    }

                    Spacer()

                    Text("\\(entry.widgetState.bgReadingDate?.formatted(date: .omitted, time: .shortened) ?? "--:--")")
                        .font(.system(size: entry.widgetState.isSmallScreen() ? 15 : 17))
                        .foregroundStyle(.colorPrimary)
                        .minimumScaleFactor(0.2)
                }
                .padding(0)'''
new_header = '''                HStack(alignment: .center) {
                    if entry.widgetState.hasRecentReading {
                        HStack(alignment: .center, spacing: 4) {
                            Text("\\(entry.widgetState.bgValueStringInUserChosenUnit())\\(entry.widgetState.trendArrow()) ")
                                .font(.system(size: entry.widgetState.isSmallScreen() ? 20 : 24)).bold()
                                .foregroundStyle(entry.widgetState.bgTextColor())

                            Text(entry.widgetState.deltaChangeStringInUserChosenUnit())
                                .font(.system(size: entry.widgetState.isSmallScreen() ? 20 : 24)).fontWeight(.semibold)
                                .foregroundStyle(.colorPrimary)
                                .lineLimit(1)
                        }

                        Spacer()

                        Text("\\(entry.widgetState.bgReadingDate?.formatted(date: .omitted, time: .shortened) ?? "--:--")")
                            .font(.system(size: entry.widgetState.isSmallScreen() ? 15 : 17))
                            .foregroundStyle(.colorPrimary)
                            .minimumScaleFactor(0.2)
                    } else {
                        HStack(alignment: .center, spacing: 5) {
                            Text(entry.widgetState.bgValueStringInUserChosenUnit())
                                .font(.system(size: entry.widgetState.isSmallScreen() ? 20 : 24)).bold()
                                .foregroundStyle(.gray)

                            Text("WERT ALT")
                                .font(.system(size: entry.widgetState.isSmallScreen() ? 10 : 11, weight: .semibold))
                                .foregroundStyle(.orange)
                                .lineLimit(1)
                        }

                        Spacer()

                        if let bgReadingDate = entry.widgetState.bgReadingDate {
                            Text(bgReadingDate, style: .relative)
                                .font(.system(size: entry.widgetState.isSmallScreen() ? 12 : 14))
                                .foregroundStyle(.orange)
                                .lineLimit(1)
                                .minimumScaleFactor(0.5)
                        } else {
                            Text("--")
                                .foregroundStyle(.gray)
                        }
                    }
                }
                .padding(0)'''
replace_once(view, old_header, new_header, "Rectangular complication stale UI")

print("Personal Apple Watch Phase 1 patch applied successfully.")
