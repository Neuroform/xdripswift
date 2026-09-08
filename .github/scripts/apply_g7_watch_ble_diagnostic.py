from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1))


# This patch runs AFTER apply_personal_watch_phase1.py.
# It turns the passive G7 listener proof-of-concept into an automatic direct-G7 glucose path
# for the Watch app while preserving WatchConnectivity as a fallback.

watch_state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")

replace_once(
    watch_state,
    "import Combine\nimport Foundation\n",
    "import Combine\nimport CoreBluetooth\nimport Foundation\n",
    "WatchStateModel CoreBluetooth import",
)

replace_once(
    watch_state,
    '''    // Prevent queued/background WatchConnectivity payloads from replacing a newer glucose state.
    private var latestBgPayloadGeneratedAt: Double = 0''',
    '''    // Prevent queued/background WatchConnectivity payloads from replacing a newer glucose state.
    private var latestBgPayloadGeneratedAt: Double = 0

    // Personal direct-G7 Watch path. The BLE manager subscribes only to existing notifications;
    // it does not start/stop/calibrate the sensor or send Dexcom protocol commands.
    private var directG7Manager: G7DirectBLEManager?
    private var lastDirectG7ReadingDate: Date?

    @Published var bgDataSource: String = "iPhone"
    @Published var directG7Status: String = "initialisiert"
    @Published var directG7DeviceName: String = ""
    @Published var directG7Authenticated: Bool = false
    @Published var directG7LastValue: Double?
    @Published var directG7LastDate: Date?
    @Published var directG7LastTrend: Double?
    @Published var directG7LastSequence: UInt16?
    @Published var directG7ReadingCount: Int = 0''',
    "WatchStateModel direct G7 properties",
)

replace_once(
    watch_state,
    '''        session.delegate = self
        session.activate()
    }''',
    '''        session.delegate = self
        session.activate()

        directG7Manager = G7DirectBLEManager(
            onState: { [weak self] status, deviceName, authenticated in
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.directG7Status = status
                    self.directG7DeviceName = deviceName
                    self.directG7Authenticated = authenticated
                }
            },
            onReading: { [weak self] reading in
                DispatchQueue.main.async {
                    self?.processDirectG7Reading(reading)
                }
            }
        )
        directG7Manager?.start()
    }''',
    "WatchStateModel direct G7 startup",
)

replace_once(
    watch_state,
    '''        let incomingLatestDate = Date(timeIntervalSince1970: incomingLatestTimestamp)
        let incomingGeneratedAt = dictionary["generatedAt"] as? Double ?? incomingLatestTimestamp''',
    '''        let incomingLatestDate = Date(timeIntervalSince1970: incomingLatestTimestamp)
        let incomingGeneratedAt = dictionary["generatedAt"] as? Double ?? incomingLatestTimestamp

        // If the Watch has already received this same G7 sample directly, keep the direct state.
        // A genuinely newer iPhone sample still wins automatically, which preserves fallback.
        if let lastDirectG7ReadingDate,
           abs(lastDirectG7ReadingDate.timeIntervalSince(incomingLatestDate)) < 90 {
            return false
        }''',
    "WatchStateModel direct-vs-iPhone preference",
)

replace_once(
    watch_state,
    '''        updatedDate = Date(timeIntervalSince1970: incomingGeneratedAt)

        if let bgReadingDate = bgReadingDate() {''',
    '''        updatedDate = Date(timeIntervalSince1970: incomingGeneratedAt)
        bgDataSource = "iPhone"

        if let bgReadingDate = bgReadingDate() {''',
    "WatchStateModel iPhone source marker",
)

direct_methods = r'''
    // MARK: - Direct Dexcom G7 Watch BLE path

    private func processDirectG7Reading(_ reading: DirectG7Reading) {
        // Never let an old/expired peripheral replace a clearly newer state already on the Watch.
        if let currentLatestDate = bgReadingDates.first,
           currentLatestDate > reading.date.addingTimeInterval(90) {
            return
        }

        // Merge into the existing 12-hour history. Remove the same sample if it already arrived
        // from the iPhone (timestamps can differ by a few seconds between the two paths).
        var merged = Array(zip(bgReadingDates, bgReadingValues))
        merged.removeAll { abs($0.0.timeIntervalSince(reading.date)) < 90 }
        merged.append((reading.date, reading.glucoseMgDl))
        merged = merged
            .filter { $0.0 > Date().addingTimeInterval(-12 * 60 * 60) }
            .sorted { $0.0 > $1.0 }

        bgReadingDates = merged.map { $0.0 }
        bgReadingValues = merged.map { $0.1 }
        bgReadingDatesAsDouble = bgReadingDates.map { $0.timeIntervalSince1970 }

        slopeOrdinal = directSlopeOrdinal(for: reading.trendMgDlPerMinute)

        // Delta is meaningful only when the previous sample is from roughly one G7 interval ago.
        if merged.count > 1 {
            let previousDate = merged[1].0
            let previousMgDl = merged[1].1
            let interval = reading.date.timeIntervalSince(previousDate)

            if interval > 0, interval <= 7.5 * 60 {
                if isMgDl {
                    deltaValueInUserUnit = reading.glucoseMgDl - previousMgDl
                } else {
                    let currentMmol = ((reading.glucoseMgDl / 18.0182) * 10).rounded() / 10
                    let previousMmol = ((previousMgDl / 18.0182) * 10).rounded() / 10
                    deltaValueInUserUnit = currentMmol - previousMmol
                }
            } else {
                deltaValueInUserUnit = 0
            }
        } else {
            deltaValueInUserUnit = 0
        }

        let now = Date()
        latestBgPayloadGeneratedAt = max(latestBgPayloadGeneratedAt, now.timeIntervalSince1970)
        lastDirectG7ReadingDate = reading.date
        updatedDate = now
        bgDataSource = "G7 BLE"

        directG7LastValue = reading.glucoseMgDl
        directG7LastDate = reading.date
        directG7LastTrend = reading.trendMgDlPerMinute
        directG7LastSequence = reading.sequence
        directG7ReadingCount += 1

        lastUpdatedTextString = Texts_WatchApp.lastReading + " "
        lastUpdatedTimeString = reading.date.formatted(date: .omitted, time: .shortened)
        lastUpdatedTimeAgoString = reading.date.daysAndHoursAgo(appendAgo: true)

        // Persist immediately for the WidgetKit complication and ask only the xDrip complication
        // timeline to reload. WidgetKit still controls the exact render timing.
        updateComplicationData()
    }

    private func directSlopeOrdinal(for trend: Double?) -> Int {
        guard let trend else { return 0 }

        if trend >= 3 {
            return 1       // ↑↑
        } else if trend >= 2 {
            return 2       // ↑
        } else if trend >= 1 {
            return 3       // ↗
        } else if trend > -1 {
            return 4       // →
        } else if trend > -2 {
            return 5       // ↘
        } else if trend > -3 {
            return 6       // ↓
        } else {
            return 7       // ↓↓
        }
    }

'''

replace_once(
    watch_state,
    '''    /// once we've process the state update, then save this data to the shared app group so that the complication can read it
    private func updateComplicationData() {''',
    direct_methods + '''    /// once we've process the state update, then save this data to the shared app group so that the complication can read it
    private func updateComplicationData() {''',
    "WatchStateModel direct G7 processing methods",
)

replace_once(
    watch_state,
    '''        if let stateData = try? JSONEncoder().encode(complicationSharedUserDefaultsModel) {
            sharedUserDefaults.set(stateData, forKey: "complicationSharedUserDefaults.\(Bundle.main.mainAppBundleIdentifier)")
        }

        // now that the new data is stored in the app group, try to force the complications to reload
        WidgetCenter.shared.reloadAllTimelines()''',
    '''        if let stateData = try? JSONEncoder().encode(complicationSharedUserDefaultsModel) {
            sharedUserDefaults.set(stateData, forKey: "complicationSharedUserDefaults.\(Bundle.main.mainAppBundleIdentifier)")
        }

        // Keep the transport source separate from the Codable model so existing stored state remains
        // fully backward-compatible with older complication extensions.
        sharedUserDefaults.set(bgDataSource, forKey: "complicationDataSource.\(Bundle.main.mainAppBundleIdentifier)")

        // Ask only the xDrip complication to reload. WidgetKit may still defer the actual render.
        WidgetCenter.shared.reloadTimelines(ofKind: "xDripWatchComplication")''',
    "WatchStateModel direct complication source + targeted reload",
)

manager_code = r'''
// MARK: - Direct G7 BLE manager

private struct DirectG7Reading {
    let glucoseMgDl: Double
    let date: Date
    let trendMgDlPerMinute: Double?
    let sequence: UInt16
    let sensorAgeSeconds: TimeInterval
    let algorithmStateRaw: UInt8
}

private final class G7DirectBLEManager: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    private let advertisementUUID = CBUUID(string: "FEBC")
    private let serviceUUID = CBUUID(string: "F8083532-849E-531C-C594-30F1F86A4EA5")
    private let controlUUID = CBUUID(string: "F8083534-849E-531C-C594-30F1F86A4EA5")
    private let authUUID = CBUUID(string: "F8083535-849E-531C-C594-30F1F86A4EA5")

    private let onState: (String, String, Bool) -> Void
    private let onReading: (DirectG7Reading) -> Void

    private var central: CBCentralManager!
    private var targetPeripheral: CBPeripheral?
    private var enabled = false
    private var authenticated = false
    private var pendingGlucosePacket: Data?
    private var authTimeoutTask: DispatchWorkItem?
    private var reconnectTask: DispatchWorkItem?
    private var lastDeviceName = ""

    init(
        onState: @escaping (String, String, Bool) -> Void,
        onReading: @escaping (DirectG7Reading) -> Void
    ) {
        self.onState = onState
        self.onReading = onReading
        super.init()

        central = CBCentralManager(
            delegate: self,
            queue: .main,
            options: [CBCentralManagerOptionRestoreIdentifierKey: "xDrip.G7.Direct.Central"]
        )
    }

    func start() {
        enabled = true
        if central.state == .poweredOn {
            beginDiscovery()
        }
    }

    private func publish(_ status: String) {
        onState(status, lastDeviceName, authenticated)
    }

    private func beginDiscovery() {
        guard enabled, central.state == .poweredOn, targetPeripheral == nil else { return }

        reconnectTask?.cancel()
        reconnectTask = nil
        publish("suche G7…")

        let connected = central.retrieveConnectedPeripherals(withServices: [serviceUUID])
        if let peripheral = connected.first(where: { ($0.name ?? "").hasPrefix("DX") }) ?? connected.first {
            inspect(peripheral)
            return
        }

        central.scanForPeripherals(
            withServices: [advertisementUUID],
            options: [CBCentralManagerScanOptionAllowDuplicatesKey: false]
        )
    }

    private func inspect(_ peripheral: CBPeripheral) {
        guard enabled, targetPeripheral == nil else { return }

        central.stopScan()
        targetPeripheral = peripheral
        peripheral.delegate = self
        lastDeviceName = peripheral.name ?? "unbekannt"
        authenticated = false
        pendingGlucosePacket = nil
        publish("G7 gefunden; verbinde…")
        central.connect(peripheral, options: nil)
    }

    private func scheduleReconnect() {
        reconnectTask?.cancel()
        let task = DispatchWorkItem { [weak self] in
            guard let self, self.enabled, self.targetPeripheral == nil else { return }
            self.beginDiscovery()
        }
        reconnectTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0, execute: task)
    }

    private func armAuthenticationTimeout(for peripheral: CBPeripheral) {
        authTimeoutTask?.cancel()
        let peripheralID = peripheral.identifier
        let task = DispatchWorkItem { [weak self] in
            guard let self,
                  self.enabled,
                  self.targetPeripheral?.identifier == peripheralID,
                  !self.authenticated else { return }

            self.publish("keine Auth-Freigabe; suche anderen G7…")
            self.central.cancelPeripheralConnection(peripheral)
        }
        authTimeoutTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + 20, execute: task)
    }

    private func parseG7Glucose(_ data: Data) -> DirectG7Reading? {
        guard data.count >= 19, data[0] == 0x4E, data[1] == 0x00 else { return nil }

        let glucoseRaw = littleEndianUInt16(data, offset: 12)
        guard glucoseRaw != 0xFFFF else { return nil }

        let glucose = Double(glucoseRaw & 0x0FFF)
        guard glucose > 0 else { return nil }

        let sequence = littleEndianUInt16(data, offset: 6)
        let messageTimestamp = littleEndianUInt32(data, offset: 2)
        let messageAge = TimeInterval(data[10])
        let sensorAge = TimeInterval(messageTimestamp) + messageAge
        let readingDate = Date().addingTimeInterval(-messageAge)

        let trend: Double?
        if data[15] == 0x7F {
            trend = nil
        } else {
            trend = Double(Int8(bitPattern: data[15])) / 10.0
        }

        return DirectG7Reading(
            glucoseMgDl: glucose,
            date: readingDate,
            trendMgDlPerMinute: trend,
            sequence: sequence,
            sensorAgeSeconds: sensorAge,
            algorithmStateRaw: data[14]
        )
    }

    private func littleEndianUInt16(_ data: Data, offset: Int) -> UInt16 {
        UInt16(data[offset]) | (UInt16(data[offset + 1]) << 8)
    }

    private func littleEndianUInt32(_ data: Data, offset: Int) -> UInt32 {
        UInt32(data[offset])
            | (UInt32(data[offset + 1]) << 8)
            | (UInt32(data[offset + 2]) << 16)
            | (UInt32(data[offset + 3]) << 24)
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        switch central.state {
        case .poweredOn:
            publish("Bluetooth ein")
            beginDiscovery()
        case .poweredOff:
            publish("Bluetooth aus")
        case .unauthorized:
            publish("Bluetooth-Berechtigung fehlt")
        case .unsupported:
            publish("CoreBluetooth nicht unterstützt")
        case .resetting:
            publish("Bluetooth wird zurückgesetzt")
        case .unknown:
            publish("Bluetooth-Status unbekannt")
        @unknown default:
            publish("Bluetooth-Status unbekannt")
        }
    }

    func centralManager(_ central: CBCentralManager, willRestoreState dict: [String : Any]) {
        if let peripherals = dict[CBCentralManagerRestoredStatePeripheralsKey] as? [CBPeripheral],
           let peripheral = peripherals.first {
            enabled = true
            targetPeripheral = peripheral
            peripheral.delegate = self
            lastDeviceName = peripheral.name ?? "unbekannt"
            authenticated = false
            publish("G7-Verbindung wiederhergestellt")

            if peripheral.state == .connected {
                peripheral.discoverServices([serviceUUID])
            } else {
                central.connect(peripheral, options: nil)
            }
        }
    }

    func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String : Any],
        rssi RSSI: NSNumber
    ) {
        let name = peripheral.name ?? (advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? "")
        guard name.hasPrefix("DX") else { return }
        inspect(peripheral)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        lastDeviceName = peripheral.name ?? lastDeviceName
        publish("BLE verbunden; prüfe G7-Service…")
        armAuthenticationTimeout(for: peripheral)
        peripheral.discoverServices([serviceUUID])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        if targetPeripheral?.identifier == peripheral.identifier {
            targetPeripheral = nil
        }
        authenticated = false
        publish("Verbindung fehlgeschlagen; neuer Versuch…")
        scheduleReconnect()
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        guard targetPeripheral?.identifier == peripheral.identifier else { return }

        authTimeoutTask?.cancel()
        authTimeoutTask = nil
        targetPeripheral = nil
        authenticated = false
        pendingGlucosePacket = nil
        publish("G7 getrennt; verbinde erneut…")
        scheduleReconnect()
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        if error != nil {
            publish("G7-Service-Suche fehlgeschlagen")
            central.cancelPeripheralConnection(peripheral)
            return
        }

        guard let service = peripheral.services?.first(where: { $0.uuid == serviceUUID }) else {
            publish("kein G7-Service; suche weiter…")
            central.cancelPeripheralConnection(peripheral)
            return
        }

        publish("G7-Service gefunden; aktiviere Notify…")
        peripheral.discoverCharacteristics(nil, for: service)
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        if error != nil {
            publish("Characteristic-Suche fehlgeschlagen")
            central.cancelPeripheralConnection(peripheral)
            return
        }

        let notifyCharacteristics = (service.characteristics ?? []).filter {
            $0.properties.contains(.notify) || $0.properties.contains(.indicate)
        }

        guard !notifyCharacteristics.isEmpty else {
            publish("keine G7-Notify-Kanäle")
            central.cancelPeripheralConnection(peripheral)
            return
        }

        for characteristic in notifyCharacteristics where !characteristic.isNotifying {
            peripheral.setNotifyValue(true, for: characteristic)
        }

        publish("Notify aktiv; warte auf Dexcom-Auth…")
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?) {
        if let error {
            publish("Notify-Fehler: \(error.localizedDescription)")
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard error == nil, let value = characteristic.value, !value.isEmpty else { return }

        if characteristic.uuid == authUUID, value.count >= 3, value[0] == 0x05 {
            authenticated = value[1] == 0x01 && value[2] != 0x02

            if authenticated {
                authTimeoutTask?.cancel()
                authTimeoutTask = nil
                publish("Dexcom-authentifiziert · Direct aktiv")

                if let pendingGlucosePacket,
                   let reading = parseG7Glucose(pendingGlucosePacket) {
                    self.pendingGlucosePacket = nil
                    onReading(reading)
                }
            } else {
                publish("Dexcom-Auth nicht freigegeben")
            }
            return
        }

        guard characteristic.uuid == controlUUID, value[0] == 0x4E else { return }

        guard authenticated else {
            pendingGlucosePacket = value
            publish("0x4E empfangen; warte auf Auth-Freigabe")
            return
        }

        guard let reading = parseG7Glucose(value) else {
            publish("0x4E empfangen; Parser abgelehnt")
            return
        }

        publish("Direct BG \(Int(reading.glucoseMgDl)) mg/dL")
        onReading(reading)
    }
}

'''

replace_once(
    watch_state,
    "\n// MARK: - WCSession delegate to handle communications\n",
    "\n" + manager_code + "// MARK: - WCSession delegate to handle communications\n",
    "WatchStateModel direct G7 BLE manager",
)


# Add a compact diagnostics/status page. The direct collector itself lives in WatchStateModel and
# runs independently of whether this page is visible.
root = Path("xDrip Watch App/Views/RootView.swift")

replace_once(
    root,
    "import SwiftUI\n",
    "import Foundation\nimport SwiftUI\n",
    "RootView Foundation import",
)

replace_once(
    root,
    '''            // large number page
            BigNumberView()
                .tag(WatchAppPage.bigNumber.rawValue)
''',
    '''            // large number page
            BigNumberView()
                .tag(WatchAppPage.bigNumber.rawValue)

            // Personal direct-G7 status page. Collection runs automatically in WatchStateModel.
            G7DirectStatusView()
                .tag(WatchAppPage.g7Direct.rawValue)
''',
    "RootView direct G7 page insertion",
)

replace_once(
    root,
    '''private enum WatchAppPage: Int {
    case main = 0
    case agp = 1
    case bigNumber = 2
}
''',
    '''private enum WatchAppPage: Int {
    case main = 0
    case agp = 1
    case bigNumber = 2
    case g7Direct = 3
}

private struct G7DirectStatusView: View {
    @EnvironmentObject var watchState: WatchStateModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                Text("G7 Direct")
                    .font(.headline)

                Text("Automatischer BLE-Pfad · iPhone bleibt Fallback")
                    .font(.caption2)
                    .foregroundStyle(.secondary)

                row("Status", watchState.directG7Status)

                if !watchState.directG7DeviceName.isEmpty {
                    row("Gerät", watchState.directG7DeviceName)
                }

                row("Authentifiziert", watchState.directG7Authenticated ? "ja" : "nein")
                row("Aktive BG-Quelle", watchState.bgDataSource)

                if let value = watchState.directG7LastValue {
                    row("Letzter Direct-BG", "\(Int(value.rounded())) mg/dL")
                }

                if let date = watchState.directG7LastDate {
                    row("Direct-Zeit", date.formatted(date: .omitted, time: .standard))
                }

                if let trend = watchState.directG7LastTrend {
                    row("Trend", String(format: "%+.1f mg/dL/min", trend))
                }

                if let sequence = watchState.directG7LastSequence {
                    row("Sequenz", "\(sequence)")
                }

                row("Direct-Werte", "\(watchState.directG7ReadingCount)")

                Text("D = Direct-G7. Wenn Direct ausfällt, darf ein neuerer iPhone-Wert automatisch übernehmen.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
        }
    }

    @ViewBuilder
    private func row(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption)
        }
    }
}
''',
    "RootView direct G7 status view",
)


# Enable CoreBluetooth background-central mode on the Watch app. This is required by Apple's
# watchOS background Bluetooth guidance; runtime and WidgetKit scheduling remain system-controlled.
plist = Path("xDrip-Watch-App-Info.plist")
plist_text = plist.read_text()

if "NSBluetoothAlwaysUsageDescription" not in plist_text:
    plist_text = plist_text.replace(
        "</dict>",
        "\t<key>NSBluetoothAlwaysUsageDescription</key>\n"
        "\t<string>xDrip uses Bluetooth to receive glucose notifications directly from the active Dexcom G7 sensor on Apple Watch.</string>\n"
        "</dict>",
        1,
    )

if "<key>UIBackgroundModes</key>" not in plist_text:
    plist_text = plist_text.replace(
        "</dict>",
        "\t<key>UIBackgroundModes</key>\n"
        "\t<array>\n"
        "\t\t<string>bluetooth-central</string>\n"
        "\t</array>\n"
        "</dict>",
        1,
    )

plist.write_text(plist_text)


# Pass a source marker to the complication using a separate App Group key.
entry = Path("xDrip Watch Complication/XDripWatchComplication+Entry.swift")

replace_once(
    entry,
    '''        var keepAliveIsDisabled: Bool
        
        var bgUnitString: String''',
    '''        var keepAliveIsDisabled: Bool
        var dataSource: String?
        
        var bgUnitString: String''',
    "Complication WidgetState source property",
)

replace_once(
    entry,
    '''        init(bgReadingValues: [Double]? = nil, bgReadingDates: [Date]? = nil, isMgDl: Bool? = true, slopeOrdinal: Int? = 0, deltaValueInUserUnit: Double? = nil, urgentLowLimitInMgDl: Double? = 60, lowLimitInMgDl: Double? = 80, highLimitInMgDl: Double? = 180, urgentHighLimitInMgDl: Double? = 250, keepAliveIsDisabled: Bool? = false) {''',
    '''        init(bgReadingValues: [Double]? = nil, bgReadingDates: [Date]? = nil, isMgDl: Bool? = true, slopeOrdinal: Int? = 0, deltaValueInUserUnit: Double? = nil, urgentLowLimitInMgDl: Double? = 60, lowLimitInMgDl: Double? = 80, highLimitInMgDl: Double? = 180, urgentHighLimitInMgDl: Double? = 250, keepAliveIsDisabled: Bool? = false, dataSource: String? = nil) {''',
    "Complication WidgetState source initializer",
)

replace_once(
    entry,
    '''            self.keepAliveIsDisabled = keepAliveIsDisabled ?? false
            
            self.bgValueInMgDl''',
    '''            self.keepAliveIsDisabled = keepAliveIsDisabled ?? false
            self.dataSource = dataSource
            
            self.bgValueInMgDl''',
    "Complication WidgetState source assignment",
)

provider = Path("xDrip Watch Complication/XDripWatchComplication+Provider.swift")

replace_once(
    provider,
    '''            return Entry.WidgetState(bgReadingValues: data.bgReadingValues, bgReadingDates: bgReadingDates, isMgDl: data.isMgDl, slopeOrdinal: data.slopeOrdinal, deltaValueInUserUnit: data.deltaValueInUserUnit, urgentLowLimitInMgDl: data.urgentLowLimitInMgDl, lowLimitInMgDl: data.lowLimitInMgDl, highLimitInMgDl: data.highLimitInMgDl, urgentHighLimitInMgDl: data.urgentHighLimitInMgDl, keepAliveIsDisabled: data.keepAliveIsDisabled)''',
    '''            let dataSource = sharedUserDefaults.string(forKey: "complicationDataSource.\(Bundle.main.mainAppBundleIdentifier)")

            return Entry.WidgetState(bgReadingValues: data.bgReadingValues, bgReadingDates: bgReadingDates, isMgDl: data.isMgDl, slopeOrdinal: data.slopeOrdinal, deltaValueInUserUnit: data.deltaValueInUserUnit, urgentLowLimitInMgDl: data.urgentLowLimitInMgDl, lowLimitInMgDl: data.lowLimitInMgDl, highLimitInMgDl: data.highLimitInMgDl, urgentHighLimitInMgDl: data.urgentHighLimitInMgDl, keepAliveIsDisabled: data.keepAliveIsDisabled, dataSource: dataSource)''',
    "Complication provider source marker",
)

# Add a very small green D in the rectangular complication when the visible value came directly
# from the G7. This is diagnostic and lets the user verify the new path without opening the app.
view = Path("xDrip Watch Complication/Views/AccessoryRectangularView.swift")

replace_once(
    view,
    '''            if entry.widgetState.keepAliveIsDisabled {
                Text(Texts_WatchComplication.keepAliveDisabled)
                    .font(.system(size: entry.widgetState.isSmallScreen() ? 11 : 12, weight: .semibold))
                    .foregroundStyle(.colorPrimary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 5)
                    .background(Color(white: 0.2).opacity(0.95), in: Capsule())
            }
        }''',
    '''            if entry.widgetState.keepAliveIsDisabled {
                Text(Texts_WatchComplication.keepAliveDisabled)
                    .font(.system(size: entry.widgetState.isSmallScreen() ? 11 : 12, weight: .semibold))
                    .foregroundStyle(.colorPrimary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 5)
                    .background(Color(white: 0.2).opacity(0.95), in: Capsule())
            }

            if entry.widgetState.dataSource == "G7 BLE" {
                VStack {
                    Spacer()
                    HStack {
                        Spacer()
                        Text("D")
                            .font(.system(size: 8, weight: .bold))
                            .foregroundStyle(.green)
                    }
                }
            }
        }''',
    "Rectangular complication direct source marker",
)

print("Personal G7 Watch direct glucose integration patch applied successfully.")
