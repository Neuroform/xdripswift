from pathlib import Path

root = Path("xDrip Watch App/Views/RootView.swift")
text = root.read_text()

if "G7BLEDiagnosticView" in text:
    raise RuntimeError("G7 BLE diagnostic patch already appears to be applied")

text = text.replace("import SwiftUI\n", "import SwiftUI\nimport CoreBluetooth\n", 1)

text = text.replace(
'''            // large number page
            BigNumberView()
                .tag(WatchAppPage.bigNumber.rawValue)
''',
'''            // large number page
            BigNumberView()
                .tag(WatchAppPage.bigNumber.rawValue)

            // Personal diagnostic page: 10-minute passive G7 notify listener.
            // It subscribes to BLE notifications but sends no Dexcom protocol commands.
            G7BLEDiagnosticView()
                .tag(WatchAppPage.g7BLEDiagnostic.rawValue)
''',
1)

text = text.replace(
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
    case g7BLEDiagnostic = 3
}

// MARK: - Personal G7 10-minute notify listener

private struct G7BLEDiagnosticView: View {
    @StateObject private var diagnostic = G7BLEDiagnosticModel()

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                Text("G7 Notify Test")
                    .font(.headline)

                Text("10 Min. passiv – keine Dexcom-Befehle")
                    .font(.caption2)
                    .foregroundStyle(.secondary)

                diagnosticRow("Bluetooth", diagnostic.bluetoothState)
                diagnosticRow("Status", diagnostic.status)

                if diagnostic.listenerStarted {
                    diagnosticRow("Restzeit", diagnostic.remainingTimeString)
                }

                if !diagnostic.deviceName.isEmpty {
                    diagnosticRow("Gerät", diagnostic.deviceName)
                }

                if let rssi = diagnostic.rssi {
                    diagnosticRow("RSSI", "\\(rssi) dBm")
                }

                diagnosticRow("G7 Service", diagnostic.g7ServiceFound ? "gefunden" : "—")

                if !diagnostic.channels.isEmpty {
                    Divider()
                    Text("Notify-Kanäle")
                        .font(.caption)
                        .fontWeight(.semibold)

                    ForEach(diagnostic.channels) { channel in
                        VStack(alignment: .leading, spacing: 2) {
                            HStack {
                                Text(channel.shortUUID)
                                    .font(.system(.caption2, design: .monospaced))
                                    .fontWeight(.semibold)
                                Spacer()
                                Text(channel.subscriptionLabel)
                                    .font(.caption2)
                                    .foregroundStyle(channel.subscribed ? .green : .secondary)
                            }

                            Text("Pakete: \\(channel.packetCount)")
                                .font(.caption2)

                            if let lastReceived = channel.lastReceived {
                                Text("RX \\(lastReceived.formatted(date: .omitted, time: .standard)) · \\(channel.lastLength) B")
                                    .font(.system(size: 9, design: .monospaced))
                                    .foregroundStyle(.secondary)
                            }

                            if !channel.lastHex.isEmpty {
                                Text(channel.lastHex)
                                    .font(.system(size: 8, design: .monospaced))
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .padding(.vertical, 3)
                    }
                }

                if !diagnostic.events.isEmpty {
                    Divider()
                    Text("Letzte RX-Pakete")
                        .font(.caption)
                        .fontWeight(.semibold)

                    ForEach(diagnostic.events) { event in
                        VStack(alignment: .leading, spacing: 1) {
                            Text("\\(event.receivedAt.formatted(date: .omitted, time: .standard))  \\(event.shortUUID)  \\(event.length) B")
                                .font(.system(size: 9, design: .monospaced))
                            Text(event.hex)
                                .font(.system(size: 8, design: .monospaced))
                                .foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 2)
                    }
                }

                if diagnostic.finished {
                    Text("10-Minuten-Listener beendet")
                        .font(.caption)
                        .fontWeight(.semibold)
                        .foregroundStyle(.green)
                }

                Button(diagnostic.isRunning ? "Test läuft…" : "Test starten") {
                    diagnostic.startTest()
                }
                .disabled(diagnostic.isRunning)

                if diagnostic.isRunning {
                    Button("Abbrechen") {
                        diagnostic.stopTest(reason: "abgebrochen", finished: false)
                    }
                }

                Text("Der Test verbindet die Watch direkt mit dem G7 und aktiviert nur BLE-Notify/Indicate für die vorhandenen G7-Characteristics. Dabei wird lediglich die BLE-Notification-Konfiguration gesetzt; es werden keine Dexcom-Authentifizierungs-, Glukose-, Start-, Stop- oder Kalibrierungsbefehle gesendet.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
        }
    }

    @ViewBuilder
    private func diagnosticRow(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption)
        }
    }
}

private struct G7NotifyChannel: Identifiable {
    let id: String
    let fullUUID: String
    let shortUUID: String
    let properties: String
    var subscribed: Bool = false
    var subscriptionError: String = ""
    var packetCount: Int = 0
    var lastReceived: Date?
    var lastLength: Int = 0
    var lastHex: String = ""

    var subscriptionLabel: String {
        if subscribed { return "✓ aktiv" }
        if !subscriptionError.isEmpty { return "Fehler" }
        return "…"
    }
}

private struct G7NotifyEvent: Identifiable {
    let id = UUID()
    let receivedAt: Date
    let shortUUID: String
    let length: Int
    let hex: String
}

private final class G7BLEDiagnosticModel: NSObject, ObservableObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    private let advertisementUUID = CBUUID(string: "FEBC")
    private let g7ServiceUUID = CBUUID(string: "F8083532-849E-531C-C594-30F1F86A4EA5")
    private let listenerDuration: TimeInterval = 10 * 60

    @Published var bluetoothState = "initialisiert"
    @Published var status = "bereit"
    @Published var deviceName = ""
    @Published var rssi: Int?
    @Published var g7ServiceFound = false
    @Published var channels: [G7NotifyChannel] = []
    @Published var events: [G7NotifyEvent] = []
    @Published var remainingSeconds = 10 * 60
    @Published var listenerStarted = false
    @Published var finished = false
    @Published var isRunning = false

    private var central: CBCentralManager!
    private var targetPeripheral: CBPeripheral?
    private var characteristicsByUUID: [String: CBCharacteristic] = [:]
    private var listenerEndDate: Date?
    private var timer: Timer?

    var remainingTimeString: String {
        let minutes = remainingSeconds / 60
        let seconds = remainingSeconds % 60
        return String(format: "%02d:%02d", minutes, seconds)
    }

    override init() {
        super.init()
        central = CBCentralManager(delegate: self, queue: .main)
    }

    func startTest() {
        resetForNewTest()
        isRunning = true
        status = "warte auf Bluetooth…"

        if central.state == .poweredOn {
            beginDiscovery()
        }
    }

    func stopTest(reason: String, finished: Bool) {
        timer?.invalidate()
        timer = nil
        central.stopScan()
        isRunning = false
        self.finished = finished
        status = reason

        if let targetPeripheral {
            central.cancelPeripheralConnection(targetPeripheral)
        }
    }

    private func resetForNewTest() {
        timer?.invalidate()
        timer = nil
        central.stopScan()
        if let targetPeripheral {
            central.cancelPeripheralConnection(targetPeripheral)
        }

        targetPeripheral = nil
        characteristicsByUUID = [:]
        listenerEndDate = nil
        deviceName = ""
        rssi = nil
        g7ServiceFound = false
        channels = []
        events = []
        remainingSeconds = Int(listenerDuration)
        listenerStarted = false
        finished = false
    }

    private func beginDiscovery() {
        guard isRunning else { return }
        bluetoothState = "ein"
        status = listenerStarted ? "suche G7 erneut…" : "suche G7…"

        let connected = central.retrieveConnectedPeripherals(withServices: [g7ServiceUUID])
        if let peripheral = connected.first(where: { ($0.name ?? "").hasPrefix("DX") }) ?? connected.first {
            inspect(peripheral: peripheral, rssi: nil, source: "systemweit verbunden")
            return
        }

        central.scanForPeripherals(withServices: [advertisementUUID], options: [CBCentralManagerScanOptionAllowDuplicatesKey: false])
    }

    private func inspect(peripheral: CBPeripheral, rssi: NSNumber?, source: String) {
        guard isRunning, targetPeripheral == nil else { return }
        central.stopScan()
        targetPeripheral = peripheral
        peripheral.delegate = self
        deviceName = peripheral.name ?? "unbekannt"
        self.rssi = rssi?.intValue
        status = "G7 gefunden (\\(source)); verbinde…"
        central.connect(peripheral, options: nil)
    }

    private func startListenerClockIfNeeded() {
        guard listenerEndDate == nil else { return }
        listenerStarted = true
        listenerEndDate = Date().addingTimeInterval(listenerDuration)
        remainingSeconds = Int(listenerDuration)

        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            guard let self, let endDate = self.listenerEndDate, self.isRunning else { return }
            let remaining = max(0, Int(ceil(endDate.timeIntervalSinceNow)))
            self.remainingSeconds = remaining
            if remaining == 0 {
                let total = self.channels.reduce(0) { $0 + $1.packetCount }
                self.stopTest(reason: "Fertig: \\(total) RX-Pakete in 10 Min.", finished: true)
            }
        }
    }

    private func updateChannel(uuid: String, _ change: (inout G7NotifyChannel) -> Void) {
        guard let index = channels.firstIndex(where: { $0.id == uuid }) else { return }
        var updated = channels[index]
        change(&updated)
        channels[index] = updated
    }

    private func hexString(_ data: Data, maxBytes: Int = 64) -> String {
        let prefix = data.prefix(maxBytes)
        let body = prefix.map { String(format: "%02X", $0) }.joined(separator: " ")
        return data.count > maxBytes ? body + " …" : body
    }

    private func shortUUID(_ uuid: String) -> String {
        let upper = uuid.uppercased()
        if upper.hasPrefix("F80835"), let first = upper.split(separator: "-").first {
            return String(first)
        }
        return upper
    }

    private func describe(_ properties: CBCharacteristicProperties) -> String {
        var values: [String] = []
        if properties.contains(.read) { values.append("R") }
        if properties.contains(.write) { values.append("W") }
        if properties.contains(.writeWithoutResponse) { values.append("WNR") }
        if properties.contains(.notify) { values.append("N") }
        if properties.contains(.indicate) { values.append("I") }
        if properties.contains(.broadcast) { values.append("B") }
        if properties.contains(.authenticatedSignedWrites) { values.append("ASW") }
        if properties.contains(.extendedProperties) { values.append("EXT") }
        if properties.contains(.notifyEncryptionRequired) { values.append("N-ENC") }
        if properties.contains(.indicateEncryptionRequired) { values.append("I-ENC") }
        return values.isEmpty ? "keine Properties" : values.joined(separator: " | ")
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        switch central.state {
        case .poweredOn:
            bluetoothState = "ein"
            if isRunning, targetPeripheral == nil {
                beginDiscovery()
            }
        case .poweredOff:
            bluetoothState = "aus"
            if isRunning { stopTest(reason: "Bluetooth ist aus", finished: false) }
        case .unauthorized:
            bluetoothState = "keine Berechtigung"
            if isRunning { stopTest(reason: "Bluetooth-Berechtigung fehlt", finished: false) }
        case .unsupported:
            bluetoothState = "nicht unterstützt"
            if isRunning { stopTest(reason: "CoreBluetooth nicht unterstützt", finished: false) }
        case .resetting:
            bluetoothState = "wird zurückgesetzt"
        case .unknown:
            bluetoothState = "unbekannt"
        @unknown default:
            bluetoothState = "unbekannt"
        }
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral, advertisementData: [String : Any], rssi RSSI: NSNumber) {
        let name = peripheral.name ?? (advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? "")
        guard name.hasPrefix("DX") else { return }
        inspect(peripheral: peripheral, rssi: RSSI, source: "Advertisement FEBC")
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        status = "BLE verbunden; prüfe GATT…"
        peripheral.discoverServices([g7ServiceUUID])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        targetPeripheral = nil
        status = "Verbindung fehlgeschlagen; suche weiter…"
        if isRunning { beginDiscovery() }
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        guard targetPeripheral?.identifier == peripheral.identifier else { return }
        targetPeripheral = nil
        characteristicsByUUID = [:]

        if isRunning {
            for index in channels.indices {
                channels[index].subscribed = false
            }
            status = "G7 getrennt; verbinde erneut…"
            beginDiscovery()
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        if let error {
            status = "Service-Suche fehlgeschlagen: \\(error.localizedDescription)"
            central.cancelPeripheralConnection(peripheral)
            return
        }

        guard let service = peripheral.services?.first(where: { $0.uuid == g7ServiceUUID }) else {
            status = "G7-Service fehlt; suche weiter…"
            central.cancelPeripheralConnection(peripheral)
            return
        }

        g7ServiceFound = true
        status = "G7-Service gefunden; suche Notify-Kanäle…"
        peripheral.discoverCharacteristics(nil, for: service)
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        if let error {
            status = "Characteristic-Suche fehlgeschlagen: \\(error.localizedDescription)"
            central.cancelPeripheralConnection(peripheral)
            return
        }

        let discovered = (service.characteristics ?? []).filter {
            $0.properties.contains(.notify) || $0.properties.contains(.indicate)
        }

        characteristicsByUUID = Dictionary(uniqueKeysWithValues: discovered.map { ($0.uuid.uuidString, $0) })

        if channels.isEmpty {
            channels = discovered.map { characteristic in
                G7NotifyChannel(
                    id: characteristic.uuid.uuidString,
                    fullUUID: characteristic.uuid.uuidString,
                    shortUUID: shortUUID(characteristic.uuid.uuidString),
                    properties: describe(characteristic.properties)
                )
            }
            .sorted { $0.fullUUID < $1.fullUUID }
        } else {
            for characteristic in discovered {
                let uuid = characteristic.uuid.uuidString
                updateChannel(uuid: uuid) {
                    $0.subscribed = false
                    $0.subscriptionError = ""
                }
            }
        }

        guard !discovered.isEmpty else {
            status = "Keine Notify-/Indicate-Kanäle gefunden"
            central.cancelPeripheralConnection(peripheral)
            return
        }

        startListenerClockIfNeeded()
        status = "aktiviere \\(discovered.count) Notify-Kanäle…"
        for characteristic in discovered {
            peripheral.setNotifyValue(true, for: characteristic)
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?) {
        let uuid = characteristic.uuid.uuidString
        updateChannel(uuid: uuid) { channel in
            channel.subscribed = characteristic.isNotifying && error == nil
            channel.subscriptionError = error?.localizedDescription ?? ""
        }

        let active = channels.filter { $0.subscribed }.count
        let errors = channels.filter { !$0.subscriptionError.isEmpty }.count
        if errors > 0 {
            status = "Listener aktiv: \\(active)/\\(channels.count), \\(errors) Fehler"
        } else {
            status = "Listener aktiv: \\(active)/\\(channels.count)"
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard isRunning else { return }
        let uuid = characteristic.uuid.uuidString

        if let error {
            updateChannel(uuid: uuid) { $0.subscriptionError = "RX: " + error.localizedDescription }
            return
        }

        guard let data = characteristic.value else { return }
        let receivedAt = Date()
        let hex = hexString(data)

        updateChannel(uuid: uuid) { channel in
            channel.packetCount += 1
            channel.lastReceived = receivedAt
            channel.lastLength = data.count
            channel.lastHex = hex
        }

        let event = G7NotifyEvent(
            receivedAt: receivedAt,
            shortUUID: shortUUID(uuid),
            length: data.count,
            hex: hex
        )
        events.insert(event, at: 0)
        if events.count > 12 {
            events.removeLast(events.count - 12)
        }

        let total = channels.reduce(0) { $0 + $1.packetCount }
        status = "Listener aktiv · \\(total) RX-Pakete"
    }
}
''',
1)

root.write_text(text)

plist = Path("xDrip-Watch-App-Info.plist")
plist_text = plist.read_text()
if "NSBluetoothAlwaysUsageDescription" not in plist_text:
    plist_text = plist_text.replace(
        "</dict>",
        "\t<key>NSBluetoothAlwaysUsageDescription</key>\n\t<string>xDrip uses Bluetooth in this diagnostic build to detect and passively listen to the currently active Dexcom G7 sensor connection.</string>\n</dict>",
        1,
    )
plist.write_text(plist_text)

print("10-minute G7 Watch notify listener patch applied successfully.")
