from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

# Build 39 is applied after accepted Build 37.
# It does NOT touch RootView, graph/circular views, or widget registration.

# iPhone: stamp the exact BG payload at the transport boundary.
manager = Path("xDrip/Managers/Watch/WatchManager.swift")
replace_once(
    manager,
    '        if let userInfo = payload(updateTypes: updateTypes) {',
    '''        if var userInfo = payload(updateTypes: updateTypes) {
            if let bg = userInfo["bgReadings"] as? [String: Any] {
                let dates = bg["bgReadingDatesAsDouble"] as? [Double] ?? []
                let values = bg["bgReadingValues"] as? [Double] ?? []
                userInfo["_refreshTrace39"] = [
                    "phoneAt": Date().timeIntervalSince1970,
                    "phoneBG": values.first ?? -1,
                    "phoneBGDate": dates.first ?? 0
                ] as [String: Any]
            }''',
    "Build39 iPhone trace",
)

# Watch app: persist each transport/commit/reload stage in the existing App Group.
state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")
replace_once(
    state,
    '    @Published var lastComplicationUpdateTimeStamp: Date = .distantPast',
    '''    @Published var lastComplicationUpdateTimeStamp: Date = .distantPast
    private let refreshTraceKey39 = "xdrip.refreshTrace39"''',
    "Build39 trace key",
)

replace_once(
    state,
    '''    // MARK: - Private functions used to interact with the WCSession and prepare internal data

    private func processWatchPayloadFromDictionary(dictionary: [String: Any]) {''',
    '''    // MARK: - Build 39 refresh trace

    private func recordRefreshTrace39(channel: String, dictionary: [String: Any]) {
        guard dictionary["bgReadings"] != nil,
              let defaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else { return }
        var record = defaults.dictionary(forKey: refreshTraceKey39) ?? [:]
        if let trace = dictionary["_refreshTrace39"] as? [String: Any] {
            for (key, value) in trace { record[key] = value }
        }
        if let bg = dictionary["bgReadings"] as? [String: Any] {
            let values = bg["bgReadingValues"] as? [Double] ?? []
            let dates = bg["bgReadingDatesAsDouble"] as? [Double] ?? []
            record["watchBG"] = values.first ?? -1
            record["watchBGDate"] = dates.first ?? 0
        }
        record["watchAt"] = Date().timeIntervalSince1970
        record["channel"] = channel
        defaults.set(record, forKey: refreshTraceKey39)
    }

    private func updateRefreshTrace39(_ values: [String: Any]) {
        guard let defaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else { return }
        var record = defaults.dictionary(forKey: refreshTraceKey39) ?? [:]
        for (key, value) in values { record[key] = value }
        defaults.set(record, forKey: refreshTraceKey39)
    }

    func refreshTraceSummary39() -> String {
        guard let defaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName),
              let record = defaults.dictionary(forKey: refreshTraceKey39) else {
            return "P-- W-- A-- R-- X--"
        }
        func bg(_ key: String) -> String {
            guard let value = record[key] as? Double, value >= 0 else { return "--" }
            return String(format: "%.0f", value)
        }
        let p = bg("phoneBG")
        let w = bg("watchBG")
        let a = bg("appGroupBG")
        let x = bg("providerBG")
        let r = (record["reloadAt"] as? Double ?? 0) > 0 ? "Y" : "--"
        let c = record["channel"] as? String ?? "--"
        return "P\(p) W\(w) A\(a) R\(r) X\(x) \(c)"
    }

    // MARK: - Private functions used to interact with the WCSession and prepare internal data

    private func processWatchPayloadFromDictionary(dictionary: [String: Any]) {''',
    "Build39 trace helpers",
)

replace_once(
    state,
    '''    func session(_: WCSession, didReceiveApplicationContext applicationContext: [String: Any]) {
        DispatchQueue.main.async {
            self.processWatchPayloadFromDictionary(dictionary: applicationContext)
        }
    }''',
    '''    func session(_: WCSession, didReceiveApplicationContext applicationContext: [String: Any]) {
        DispatchQueue.main.async {
            self.recordRefreshTrace39(channel: "ctx", dictionary: applicationContext)
            self.processWatchPayloadFromDictionary(dictionary: applicationContext)
        }
    }''',
    "Build39 ctx receipt",
)
replace_once(
    state,
    '''    func session(_: WCSession, didReceiveMessage message: [String: Any]) {
        DispatchQueue.main.async {
            self.processWatchPayloadFromDictionary(dictionary: message)''',
    '''    func session(_: WCSession, didReceiveMessage message: [String: Any]) {
        DispatchQueue.main.async {
            self.recordRefreshTrace39(channel: "msg", dictionary: message)
            self.processWatchPayloadFromDictionary(dictionary: message)''',
    "Build39 msg receipt",
)
replace_once(
    state,
    '''    func session(_: WCSession, didReceiveUserInfo userInfo: [String: Any] = [:]) {
        DispatchQueue.main.async {
            self.processWatchPayloadFromDictionary(dictionary: userInfo)
        }
    }''',
    '''    func session(_: WCSession, didReceiveUserInfo userInfo: [String: Any] = [:]) {
        DispatchQueue.main.async {
            self.recordRefreshTrace39(channel: "info", dictionary: userInfo)
            self.processWatchPayloadFromDictionary(dictionary: userInfo)
        }
    }''',
    "Build39 info receipt",
)

replace_once(
    state,
    '''        if stateChanged || sourceChanged {
            // Every genuinely new BG state is already persisted at this point. Reload ONLY the''',
    '''        if stateChanged {
            updateRefreshTrace39([
                "appGroupAt": Date().timeIntervalSince1970,
                "appGroupBG": complicationBgReadingValues.first ?? -1
            ])
        }

        if stateChanged || sourceChanged {
            // Every genuinely new BG state is already persisted at this point. Reload ONLY the''',
    "Build39 App Group stage",
)

replace_once(
    state,
    '''            for complicationKind in [
                "xDripGraphV33",
                "xDripBGV36",
                "xDripDeltaV36"
            ] {
                WidgetCenter.shared.reloadTimelines(ofKind: complicationKind)
            }
            lastComplicationUpdateTimeStamp = .now''',
    '''            for complicationKind in [
                "xDripGraphV33",
                "xDripBGV36",
                "xDripDeltaV36"
            ] {
                WidgetCenter.shared.reloadTimelines(ofKind: complicationKind)
            }
            updateRefreshTrace39(["reloadAt": Date().timeIntervalSince1970])
            lastComplicationUpdateTimeStamp = .now''',
    "Build39 reload stage",
)

# Widget provider: note the state actually read by WidgetKit.
provider = Path("xDrip Watch Complication/XDripWatchComplication+Provider.swift")
replace_once(
    provider,
    '    struct Provider: TimelineProvider {\n        private let timelineStep: TimeInterval = 5 * 60',
    '    struct Provider: TimelineProvider {\n        private let refreshTraceKey39 = "xdrip.refreshTrace39"\n        private let timelineStep: TimeInterval = 5 * 60',
    "Build39 provider key",
)
replace_once(
    provider,
    '        func placeholder(in context: Context) -> Entry {',
    '''        private func recordProviderRead39(_ state: Entry.WidgetState, at date: Date) {
            guard let defaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else { return }
            var record = defaults.dictionary(forKey: refreshTraceKey39) ?? [:]
            record["providerAt"] = date.timeIntervalSince1970
            record["providerBG"] = state.bgReadingValues?.first ?? -1
            defaults.set(record, forKey: refreshTraceKey39)
        }

        func placeholder(in context: Context) -> Entry {''',
    "Build39 provider helper",
)
replace_once(
    provider,
    '''            let widgetState = getWidgetStateFromSharedUserDefaults() ?? sampleWidgetStateFromProvider
            let horizonDate = now.addingTimeInterval(timelineHorizon)''',
    '''            let widgetState = getWidgetStateFromSharedUserDefaults() ?? sampleWidgetStateFromProvider
            recordProviderRead39(widgetState, at: now)
            let horizonDate = now.addingTimeInterval(timelineHorizon)''',
    "Build39 provider stage",
)

# Existing BigNumber page only: reuse its existing footer line to show the trace.
big = Path("xDrip Watch App/Views/BigNumberView/BigNumberView.swift")
replace_once(
    big,
    '                Text(watchState.lastUpdatedMinsAgoString())',
    '                Text(watchState.refreshTraceSummary39())',
    "Build39 trace display",
)

print("Build 39 safe refresh trace applied. RootView and complication layouts untouched.")
