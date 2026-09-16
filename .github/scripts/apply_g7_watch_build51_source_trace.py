from pathlib import Path

WATCH_STATE = Path("xDrip Watch App/DataModels/WatchStateModel.swift")
ROOT_VIEW = Path("xDrip Watch App/Views/RootView.swift")

text = WATCH_STATE.read_text(encoding="utf-8")


def rep(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


rep(
    "    @Published var directG7ReadingCount: Int = 0\n",
    """    @Published var directG7ReadingCount: Int = 0

    // Build 51: provenance only. This does not feed any widget and never changes BG selection.
    @Published var bgIngressTrace51: String = "noch kein BG-Eingang protokolliert"
    @Published var lastBgIngressSource51: String = "—"
""",
    "published source trace fields",
)

rep(
    """                    self.directG7Status = status
                    self.directG7DeviceName = deviceName
                    self.directG7Authenticated = authenticated
""",
    """                    self.directG7Status = status
                    self.directG7DeviceName = deviceName
                    self.directG7Authenticated = authenticated
                    self.refreshBgIngressTrace51()
""",
    "refresh trace on direct state",
)

rep(
    """        directG7Manager?.start()
    }
""",
    """        directG7Manager?.start()
        refreshBgIngressTrace51()
    }
""",
    "initial provenance refresh",
)

rep(
    "    private func processWatchPayloadFromDictionary(dictionary: [String: Any]) {\n",
    "    private func processWatchPayloadFromDictionary(dictionary: [String: Any], route51: String) {\n",
    "payload route signature",
)

rep(
    "            processedUpdate = processBgReadingsFromDictionary(dictionary: bgReadingsDictionary) || processedUpdate\n",
    "            processedUpdate = processBgReadingsFromDictionary(dictionary: bgReadingsDictionary, route51: route51) || processedUpdate\n",
    "route into BG parser",
)

rep(
    "    private func processBgReadingsFromDictionary(dictionary: [String: Any]) -> Bool {\n",
    "    private func processBgReadingsFromDictionary(dictionary: [String: Any], route51: String) -> Bool {\n",
    "BG parser route signature",
)

rep(
    """        let incomingLatestDate = Date(timeIntervalSince1970: incomingLatestTimestamp)
        let incomingGeneratedAt = dictionary["generatedAt"] as? Double ?? incomingLatestTimestamp
""",
    """        let incomingLatestDate = Date(timeIntervalSince1970: incomingLatestTimestamp)
        let incomingGeneratedAt = dictionary["generatedAt"] as? Double ?? incomingLatestTimestamp
        let previousLatestDate51 = bgReadingDates.first
""",
    "capture previous iPhone latest date",
)

rep(
    """        bgDataSource = "iPhone"

        if let bgReadingDate = bgReadingDate() {
""",
    """        bgDataSource = "iPhone"

        let acceptedValues51 = dictionary["bgReadingValues"] as? [Double] ?? []
        let newSampleCount51: Int
        if let previousLatestDate51 {
            newSampleCount51 = bgReadingDatesFromDictionary.reduce(into: 0) { count, timestamp in
                if Date(timeIntervalSince1970: timestamp) > previousLatestDate51.addingTimeInterval(90) {
                    count += 1
                }
            }
        } else {
            newSampleCount51 = bgReadingDatesFromDictionary.count
        }
        appendBgIngressTrace51(
            source: "IPHONE_WC",
            route: route51,
            sampleDate: incomingLatestDate,
            bg: acceptedValues51.first,
            sequence: nil,
            batchCount: bgReadingDatesFromDictionary.count,
            newCount: newSampleCount51
        )
        refreshBgIngressTrace51()

        if let bgReadingDate = bgReadingDate() {
""",
    "log accepted iPhone BG payload",
)

rep(
    "            self.processWatchPayloadFromDictionary(dictionary: message)\n",
    "            self.processWatchPayloadFromDictionary(dictionary: message, route51: \"MESSAGE\")\n",
    "message route",
)

rep(
    "            self.processWatchPayloadFromDictionary(dictionary: applicationContext)\n",
    "            self.processWatchPayloadFromDictionary(dictionary: applicationContext, route51: \"APPLICATION_CONTEXT\")\n",
    "application context route",
)

rep(
    "            self.processWatchPayloadFromDictionary(dictionary: userInfo)\n",
    "            self.processWatchPayloadFromDictionary(dictionary: userInfo, route51: \"USER_INFO\")\n",
    "user info route",
)

reading_anchor = """private struct DirectG7Reading {
    let glucoseMgDl: Double
    let date: Date
    let trendMgDlPerMinute: Double?
    let sequence: UInt16
    let sensorAgeSeconds: TimeInterval
    let algorithmStateRaw: UInt8
}
"""

if text.count(reading_anchor) != 1:
    raise RuntimeError("DirectG7Reading anchor mismatch")

provenance_helpers = reading_anchor + """

// Build 51: persistent BG provenance log. Diagnostic only; it never participates in glucose
// selection, BLE connection control or WidgetKit rendering.
private let bgIngressTraceKey51 = "xdrip.bgIngressTrace51"

private func appendBgIngressTrace51(
    source: String,
    route: String,
    sampleDate: Date,
    bg: Double?,
    sequence: UInt16?,
    batchCount: Int,
    newCount: Int
) {
    guard let defaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else { return }
    var events = defaults.stringArray(forKey: bgIngressTraceKey51) ?? []
    let bgField = bg.map { String(Int($0.rounded())) } ?? "-"
    let seqField = sequence.map { String($0) } ?? "-"
    let raw = [
        String(Date().timeIntervalSince1970), source, route,
        String(sampleDate.timeIntervalSince1970), bgField, seqField,
        String(batchCount), String(newCount)
    ].joined(separator: "|")
    events.append(raw)
    if events.count > 50 {
        events.removeFirst(events.count - 50)
    }
    defaults.set(events, forKey: bgIngressTraceKey51)
}

private func bgIngressTraceSnapshot51() -> (source: String, text: String) {
    guard let defaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else {
        return ("—", "App Group nicht verfügbar")
    }
    let events = defaults.stringArray(forKey: bgIngressTraceKey51) ?? []
    guard !events.isEmpty else {
        return ("—", "noch kein BG-Eingang protokolliert")
    }

    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "de_AT")
    formatter.dateFormat = "HH:mm:ss"

    let lines = events.suffix(16).compactMap { raw -> String? in
        let parts = raw.split(separator: "|", omittingEmptySubsequences: false).map(String.init)
        guard parts.count == 8,
              let arrivalTS = Double(parts[0]),
              let sampleTS = Double(parts[3]) else { return nil }
        let arrival = formatter.string(from: Date(timeIntervalSince1970: arrivalTS))
        let sample = formatter.string(from: Date(timeIntervalSince1970: sampleTS))
        let seq = parts[5] == "-" ? "" : " seq=\\(parts[5])"
        return "\\(arrival) \\(parts[1])/\\(parts[2]) BG=\\(parts[4]) sample=\\(sample)\\(seq) batch=\\(parts[6]) new=\\(parts[7])"
    }

    let lastParts = events.last?.split(separator: "|", omittingEmptySubsequences: false).map(String.init) ?? []
    let source = lastParts.count > 1 ? lastParts[1] : "—"
    return (source, lines.joined(separator: "\\n"))
}
"""
text = text.replace(reading_anchor, provenance_helpers, 1)

marker = "    // MARK: - Functions to provide context data to populate the views\n"
if text.count(marker) != 1:
    raise RuntimeError("WatchStateModel helper marker mismatch")

model_helper = """    private func refreshBgIngressTrace51() {
        let snapshot = bgIngressTraceSnapshot51()
        lastBgIngressSource51 = snapshot.source
        bgIngressTrace51 = snapshot.text
    }

"""
text = text.replace(marker, model_helper + marker, 1)

direct_anchor = """        guard let reading = parseG7Glucose(value) else {
            publish("0x4E empfangen; Parser abgelehnt")
            return
        }

        // Build 43/46: every valid sensor packet goes directly to the existing widgets.
"""

direct_replacement = """        guard let reading = parseG7Glucose(value) else {
            publish("0x4E empfangen; Parser abgelehnt")
            return
        }

        appendBgIngressTrace51(
            source: "DIRECT_G7",
            route: "CORE_BLUETOOTH_0x4E",
            sampleDate: reading.date,
            bg: reading.glucoseMgDl,
            sequence: reading.sequence,
            batchCount: 1,
            newCount: 1
        )

        // Build 43/46: every valid sensor packet goes directly to the existing widgets.
"""

if text.count(direct_anchor) != 1:
    raise RuntimeError(f"direct provenance anchor expected once, found {text.count(direct_anchor)}")
text = text.replace(direct_anchor, direct_replacement, 1)

WATCH_STATE.write_text(text, encoding="utf-8")

root = ROOT_VIEW.read_text(encoding="utf-8")
root_old = """                row("Direct-Werte", "\\(watchState.directG7ReadingCount)")

                Divider()

                Text("Build 15 G7 Multi-Cycle-Validierung")
"""
root_new = """                row("Direct-Werte", "\\(watchState.directG7ReadingCount)")

                Divider()

                Text("Build 51 BG-Quellenprotokoll")
                    .font(.headline)
                Text("Produktiver Datenpfad · keine Validierung starten. DIRECT_G7 = Sensor direkt; IPHONE_WC = WatchConnectivity vom iPhone. batch/new zeigt insbesondere nachgelieferte Messpunkte.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                row("Letzte Quelle", watchState.lastBgIngressSource51)
                Text(watchState.bgIngressTrace51)
                    .font(.system(size: 9, design: .monospaced))

                Divider()

                Text("Build 15 G7 Multi-Cycle-Validierung")
"""

if root.count(root_old) != 1:
    raise RuntimeError(f"RootView source trace anchor expected once, found {root.count(root_old)}")
root = root.replace(root_old, root_new, 1)
ROOT_VIEW.write_text(root, encoding="utf-8")

print("Build 51 BG source trace patch applied.")
