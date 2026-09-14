from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# -----------------------------------------------------------------------------
# Build 38: diagnostics ONLY. Applied after accepted Build 37.
#
# Purpose: identify exactly where a new 5-minute BG update stalls:
#   1. iPhone payload prepared
#   2. WatchConnectivity callback received on Watch (+ channel)
#   3. Watch App Group state committed
#   4. Widget reload requested
#   5. Widget provider actually reads the new App Group state
#
# IMPORTANT: do not change any Build 37 complication/widget layout or widget kind.
# Diagnostics are stored in the Watch App Group and displayed only on a fourth page
# inside the xDrip Watch app.
# -----------------------------------------------------------------------------


# 1) iPhone: attach a compact diagnostic envelope to every payload that contains BG.
watch_manager = Path("xDrip/Managers/Watch/WatchManager.swift")
replace_once(
    watch_manager,
    '''        if let userInfo = payload(updateTypes: updateTypes) {''',
    '''        if var userInfo = payload(updateTypes: updateTypes) {
            // Build 38 diagnostics: stamp the exact BG state at the iPhone->Watch boundary.
            // This metadata is diagnostic only and is ignored by normal state processing.
            if let bgDictionary = userInfo["bgReadings"] as? [String: Any] {
                let readingDates = bgDictionary["bgReadingDatesAsDouble"] as? [Double] ?? []
                let readingValues = bgDictionary["bgReadingValues"] as? [Double] ?? []
                userInfo["_xdripRefreshTraceV38"] = [
                    "iphonePreparedAt": Date().timeIntervalSince1970,
                    "bgGeneratedAt": bgDictionary["generatedAt"] as? Double ?? 0,
                    "latestBGDate": readingDates.first ?? 0,
                    "latestBGValue": readingValues.first ?? -1
                ] as [String: Any]
            }''',
    "Build38 iPhone diagnostic payload envelope",
)


# 2) Watch app: record the delivery channel and received time before normal processing.
watch_state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")
replace_once(
    watch_state,
    '''    @Published var lastComplicationUpdateTimeStamp: Date = .distantPast''',
    '''    @Published var lastComplicationUpdateTimeStamp: Date = .distantPast

    // Build 38 end-to-end refresh diagnostics. This is shown only inside the Watch app.
    @Published var refreshDiagnosticsTextV38: String = "Build 38 · waiting for BG update"
    private let refreshDiagnosticsKeyV38 = "xdrip.refreshDiagnostics.v38"''',
    "Build38 diagnostics properties",
)

# Insert diagnostic helpers immediately before the private Watch payload processing section.
replace_once(
    watch_state,
    '''    // MARK: - Private functions used to interact with the WCSession and prepare internal data

    private func processWatchPayloadFromDictionary(dictionary: [String: Any]) {''',
    r'''    // MARK: - Build 38 refresh diagnostics

    private func recordRefreshReceiptV38(channel: String, dictionary: [String: Any]) {
        guard dictionary["bgReadings"] != nil else { return }
        guard let defaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else { return }

        var record = defaults.dictionary(forKey: refreshDiagnosticsKeyV38) ?? [:]
        if let trace = dictionary["_xdripRefreshTraceV38"] as? [String: Any] {
            for (key, value) in trace { record[key] = value }
        }

        if let bg = dictionary["bgReadings"] as? [String: Any] {
            let dates = bg["bgReadingDatesAsDouble"] as? [Double] ?? []
            let values = bg["bgReadingValues"] as? [Double] ?? []
            record["watchPayloadBGDate"] = dates.first ?? 0
            record["watchPayloadBGValue"] = values.first ?? -1
        }

        record["watchReceivedAt"] = Date().timeIntervalSince1970
        record["watchReceiveChannel"] = channel
        defaults.set(record, forKey: refreshDiagnosticsKeyV38)
        refreshDiagnosticsSnapshotV38()
    }

    private func updateRefreshDiagnosticV38(_ values: [String: Any]) {
        guard let defaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else { return }
        var record = defaults.dictionary(forKey: refreshDiagnosticsKeyV38) ?? [:]
        for (key, value) in values { record[key] = value }
        defaults.set(record, forKey: refreshDiagnosticsKeyV38)
        refreshDiagnosticsSnapshotV38()
    }

    func refreshDiagnosticsSnapshotV38() {
        guard let defaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName),
              let record = defaults.dictionary(forKey: refreshDiagnosticsKeyV38) else {
            refreshDiagnosticsTextV38 = "Build 38 · waiting for BG update"
            return
        }

        func timeText(_ key: String) -> String {
            guard let value = record[key] as? Double, value > 0 else { return "--:--:--" }
            let formatter = DateFormatter()
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.dateFormat = "HH:mm:ss"
            return formatter.string(from: Date(timeIntervalSince1970: value))
        }

        func valueText(_ key: String) -> String {
            if let value = record[key] as? Double, value >= 0 { return String(format: "%.0f", value) }
            return "--"
        }

        let channel = record["watchReceiveChannel"] as? String ?? "--"
        let phoneBG = valueText("latestBGValue")
        let watchBG = valueText("watchPayloadBGValue")
        let committedBG = valueText("committedBGValue")
        let providerBG = valueText("providerBGValue")

        refreshDiagnosticsTextV38 = [
            "BUILD 38 · REFRESH TRACE",
            "iPhone  \(phoneBG)  \(timeText("iphonePreparedAt"))",
            "Watch   \(watchBG)  \(timeText("watchReceivedAt"))",
            "via \(channel)",
            "AppGrp  \(committedBG)  \(timeText("appGroupCommittedAt"))",
            "Reload       \(timeText("widgetReloadRequestedAt"))",
            "Widget  \(providerBG)  \(timeText("providerReadAt"))"
        ].joined(separator: "\n")
    }

    // MARK: - Private functions used to interact with the WCSession and prepare internal data

    private func processWatchPayloadFromDictionary(dictionary: [String: Any]) {''',
    "Build38 Watch diagnostic helpers",
)

# Record each WatchConnectivity delivery path separately.
replace_once(
    watch_state,
    '''    func session(_: WCSession, didReceiveApplicationContext applicationContext: [String: Any]) {
        DispatchQueue.main.async {
            self.processWatchPayloadFromDictionary(dictionary: applicationContext)
        }
    }''',
    '''    func session(_: WCSession, didReceiveApplicationContext applicationContext: [String: Any]) {
        DispatchQueue.main.async {
            self.recordRefreshReceiptV38(channel: "applicationContext", dictionary: applicationContext)
            self.processWatchPayloadFromDictionary(dictionary: applicationContext)
        }
    }''',
    "Build38 applicationContext receipt",
)
replace_once(
    watch_state,
    '''    func session(_: WCSession, didReceiveMessage message: [String: Any]) {
        DispatchQueue.main.async {
            self.processWatchPayloadFromDictionary(dictionary: message)''',
    '''    func session(_: WCSession, didReceiveMessage message: [String: Any]) {
        DispatchQueue.main.async {
            self.recordRefreshReceiptV38(channel: "message", dictionary: message)
            self.processWatchPayloadFromDictionary(dictionary: message)''',
    "Build38 message receipt",
)
replace_once(
    watch_state,
    '''    func session(_: WCSession, didReceiveUserInfo userInfo: [String: Any] = [:]) {
        DispatchQueue.main.async {
            self.processWatchPayloadFromDictionary(dictionary: userInfo)
        }
    }''',
    '''    func session(_: WCSession, didReceiveUserInfo userInfo: [String: Any] = [:]) {
        DispatchQueue.main.async {
            self.recordRefreshReceiptV38(channel: "userInfo", dictionary: userInfo)
            self.processWatchPayloadFromDictionary(dictionary: userInfo)
        }
    }''',
    "Build38 userInfo receipt",
)

# Record the exact state written into the App Group. Do this after stateChanged is known.
replace_once(
    watch_state,
    '''        if stateChanged || sourceChanged {
            // Every genuinely new BG state is already persisted at this point. Reload ONLY the''',
    '''        if stateChanged {
            updateRefreshDiagnosticV38([
                "appGroupCommittedAt": Date().timeIntervalSince1970,
                "committedBGDate": complicationBgReadingDates.first?.timeIntervalSince1970 ?? 0,
                "committedBGValue": complicationBgReadingValues.first ?? -1
            ])
        }

        if stateChanged || sourceChanged {
            // Every genuinely new BG state is already persisted at this point. Reload ONLY the''',
    "Build38 App Group commit marker",
)

# Record when reloadTimelines requests have actually been issued.
replace_once(
    watch_state,
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
            updateRefreshDiagnosticV38(["widgetReloadRequestedAt": Date().timeIntervalSince1970])
            lastComplicationUpdateTimeStamp = .now''',
    "Build38 WidgetKit reload marker",
)


# 3) Widget extension: record every Provider read, including the BG state it actually decoded.
provider = Path("xDrip Watch Complication/XDripWatchComplication+Provider.swift")
replace_once(
    provider,
    '''    struct Provider: TimelineProvider {
        private let timelineStep: TimeInterval = 5 * 60''',
    r'''    struct Provider: TimelineProvider {
        private let refreshDiagnosticsKeyV38 = "xdrip.refreshDiagnostics.v38"
        private let timelineStep: TimeInterval = 5 * 60''',
    "Build38 provider diagnostics key",
)
replace_once(
    provider,
    '''        func placeholder(in context: Context) -> Entry {''',
    r'''        private func recordProviderReadV38(widgetState: Entry.WidgetState, at date: Date) {
            guard let defaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else { return }
            var record = defaults.dictionary(forKey: refreshDiagnosticsKeyV38) ?? [:]
            record["providerReadAt"] = date.timeIntervalSince1970
            record["providerBGDate"] = widgetState.bgReadingDates?.first?.timeIntervalSince1970 ?? 0
            record["providerBGValue"] = widgetState.bgReadingValues?.first ?? -1
            defaults.set(record, forKey: refreshDiagnosticsKeyV38)
        }

        func placeholder(in context: Context) -> Entry {''',
    "Build38 provider read helper",
)
replace_once(
    provider,
    '''            let widgetState = getWidgetStateFromSharedUserDefaults() ?? sampleWidgetStateFromProvider
            let horizonDate = now.addingTimeInterval(timelineHorizon)''',
    '''            let widgetState = getWidgetStateFromSharedUserDefaults() ?? sampleWidgetStateFromProvider
            recordProviderReadV38(widgetState: widgetState, at: now)
            let horizonDate = now.addingTimeInterval(timelineHorizon)''',
    "Build38 provider getTimeline marker",
)


# 4) Watch app: add a fourth diagnostics page. No complication layout is touched.
root_view = Path("xDrip Watch App/Views/RootView.swift")
replace_once(
    root_view,
    '''            // large number page
            BigNumberView()
                .tag(WatchAppPage.bigNumber.rawValue)''',
    '''            // large number page
            BigNumberView()
                .tag(WatchAppPage.bigNumber.rawValue)

            // Build 38 diagnostic page. This page is temporary and exists only to observe
            // the five-stage BG -> Watch -> App Group -> WidgetKit refresh chain.
            RefreshDiagnosticsV38View()
                .tag(WatchAppPage.refreshDiagnostics.rawValue)''',
    "Build38 diagnostics tab",
)
replace_once(
    root_view,
    '''private enum WatchAppPage: Int {
    case main = 0
    case agp = 1
    case bigNumber = 2
}''',
    r'''private enum WatchAppPage: Int {
    case main = 0
    case agp = 1
    case bigNumber = 2
    case refreshDiagnostics = 3
}

private struct RefreshDiagnosticsV38View: View {
    @EnvironmentObject var watchState: WatchStateModel

    var body: some View {
        ScrollView {
            Text(watchState.refreshDiagnosticsTextV38)
                .font(.system(size: 11, weight: .medium, design: .monospaced))
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 4)
        }
        .onAppear { watchState.refreshDiagnosticsSnapshotV38() }
        .onReceive(watchState.timer) { _ in
            watchState.refreshDiagnosticsSnapshotV38()
        }
    }
}''',
    "Build38 diagnostics view",
)

print("Build 38 applied: end-to-end refresh diagnostics added; Build 37 widget layouts untouched.")
