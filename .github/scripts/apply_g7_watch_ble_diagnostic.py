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

            // Personal diagnostic page: passive G7 discovery + read-only GATT inspection.
            // It never starts/stops a sensor, writes characteristics or subscribes to glucose data.
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

// MARK: - Personal G7 BLE diagnostic

private struct G7BLEDiagnosticView: View {
    @StateObject private var diagnostic = G7BLEDiagnosticModel()

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                Text("G7 GATT Test")
                    .font(.headline)

                Text("Nur Diagnose – keine Sensorbefehle")
                    .font(.caption2)
                    .foregroundStyle(.secondary)

                diagnosticRow("Bluetooth", diagnostic.bluetoothState)
                diagnosticRow("Status", diagnostic.status)

                if !diagnostic.deviceName.isEmpty {
                    diagnosticRow("Gerät", diagnostic.deviceName)
                }

                if let rssi = diagnostic.rssi {
                    diagnosticRow("RSSI", "\\(rssi) dBm")
                }

                diagnosticRow("G7 Service", diagnostic.g7ServiceFound ? "gefunden" : "—")

                if !diagnostic.characteristics.isEmpty {
                    Divider()
                    Text("Characteristics")
                        .font(.caption)
                        .fontWeight(.semibold)

                    ForEach(diagnostic.characteristics) { characteristic in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(characteristic.shortUUID)
                                .font(.system(.caption2, design: .monospaced))
                                .fontWeight(.semibold)
                            Text(characteristic.properties)
                                .font(.system(.caption2, design: .monospaced))
                                .foregroundStyle(.secondary)
                            Text(characteristic.fullUUID)
                                .font(.system(size: 8, design: .monospaced))
                                .foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 2)
                    }
                }

                if diagnostic.discoveryComplete {
                    Text("GATT-Struktur vollständig gelesen")
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
                        diagnostic.stopTest(reason: "abgebrochen")
                    }
                }

                Text("Der Test scannt nach G7, verbindet sich und liest ausschließlich Service-/Characteristic-Metadaten einschließlich Read/Write/Notify/Indicate-Eigenschaften. Keine Characteristic wird gelesen, beschrieben oder abonniert.")
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

private struct G7CharacteristicDiagnostic: Identifiable {
    let id: String
    let fullUUID: String
    let shortUUID: String
    let properties: String
}

private final class G7BLEDiagnosticModel: NSObject, ObservableObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    private let advertisementUUID = CBUUID(string: "FEBC")
    private let g7ServiceUUID = CBUUID(string: "F8083532-849E-531C-C594-30F1F86A4EA5")

    @Published var bluetoothState = "initialisiert"
    @Published var status = "bereit"
    @Published var deviceName = ""
    @Published var rssi: Int?
    @Published var g7ServiceFound = false
    @Published var characteristics: [G7CharacteristicDiagnostic] = []
    @Published var discoveryComplete = false
    @Published var connectionSucceeded = false
    @Published var isRunning = false

    private var central: CBCentralManager!
    private var targetPeripheral: CBPeripheral?
    private var timeoutTask: DispatchWorkItem?

    override init() {
        super.init()
        central = CBCentralManager(delegate: self, queue: .main)
    }

    func startTest() {
        resetResults()
        isRunning = true
        status = "warte auf Bluetooth…"

        if central.state == .poweredOn {
            beginDiscovery()
        }

        let task = DispatchWorkItem { [weak self] in
            guard let self, self.isRunning else { return }
            self.stopTest(reason: self.discoveryComplete ? "Test beendet" : "Timeout – Diagnose unvollständig")
        }
        timeoutTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + 45, execute: task)
    }

    func stopTest(reason: String) {
        timeoutTask?.cancel()
        timeoutTask = nil
        central.stopScan()
        if let targetPeripheral {
            central.cancelPeripheralConnection(targetPeripheral)
        }
        isRunning = false
        status = reason
    }

    private func resetResults() {
        timeoutTask?.cancel()
        central.stopScan()
        if let targetPeripheral {
            central.cancelPeripheralConnection(targetPeripheral)
        }
        targetPeripheral = nil
        deviceName = ""
        rssi = nil
        g7ServiceFound = false
        characteristics = []
        discoveryComplete = false
        connectionSucceeded = false
    }

    private func beginDiscovery() {
        bluetoothState = "ein"
        status = "suche G7…"

        let connected = central.retrieveConnectedPeripherals(withServices: [g7ServiceUUID])
        if let peripheral = connected.first(where: { ($0.name ?? "").hasPrefix("DX") }) ?? connected.first {
            inspect(peripheral: peripheral, rssi: nil, source: "bereits systemweit verbunden")
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

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        switch central.state {
        case .poweredOn:
            bluetoothState = "ein"
            if isRunning, targetPeripheral == nil {
                beginDiscovery()
            }
        case .poweredOff:
            bluetoothState = "aus"
            if isRunning { stopTest(reason: "Bluetooth ist aus") }
        case .unauthorized:
            bluetoothState = "keine Berechtigung"
            if isRunning { stopTest(reason: "Bluetooth-Berechtigung fehlt") }
        case .unsupported:
            bluetoothState = "nicht unterstützt"
            if isRunning { stopTest(reason: "CoreBluetooth nicht unterstützt") }
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
        connectionSucceeded = true
        status = "BLE verbunden; prüfe GATT…"
        peripheral.discoverServices([g7ServiceUUID])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        connectionSucceeded = false
        targetPeripheral = nil
        status = "Verbindung fehlgeschlagen: \\(error?.localizedDescription ?? "unbekannt")"
        if isRunning {
            central.scanForPeripherals(withServices: [advertisementUUID], options: [CBCentralManagerScanOptionAllowDuplicatesKey: false])
        }
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        if isRunning, !discoveryComplete {
            targetPeripheral = nil
            status = "getrennt; suche weiter…"
            central.scanForPeripherals(withServices: [advertisementUUID], options: [CBCentralManagerScanOptionAllowDuplicatesKey: false])
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        if let error {
            stopTest(reason: "Service-Suche fehlgeschlagen: \\(error.localizedDescription)")
            return
        }

        guard let service = peripheral.services?.first(where: { $0.uuid == g7ServiceUUID }) else {
            stopTest(reason: "BLE verbunden, aber G7-Service fehlt")
            return
        }

        g7ServiceFound = true
        status = "G7-Service gefunden; lese alle Characteristics…"
        peripheral.discoverCharacteristics(nil, for: service)
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        if let error {
            stopTest(reason: "Characteristic-Suche fehlgeschlagen: \\(error.localizedDescription)")
            return
        }

        let rows = (service.characteristics ?? []).map { characteristic in
            G7CharacteristicDiagnostic(
                id: characteristic.uuid.uuidString,
                fullUUID: characteristic.uuid.uuidString,
                shortUUID: self.shortUUID(characteristic.uuid.uuidString),
                properties: self.describe(characteristic.properties)
            )
        }
        .sorted { $0.fullUUID < $1.fullUUID }

        characteristics = rows
        discoveryComplete = true
        stopTest(reason: "Erfolg: \\(rows.count) Characteristics gefunden")
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
}
''',
1)

root.write_text(text)

plist = Path("xDrip-Watch-App-Info.plist")
plist_text = plist.read_text()
if "NSBluetoothAlwaysUsageDescription" not in plist_text:
    plist_text = plist_text.replace(
        "</dict>",
        "\t<key>NSBluetoothAlwaysUsageDescription</key>\n\t<string>xDrip uses Bluetooth in this diagnostic build to detect and inspect the currently active Dexcom G7 sensor connection.</string>\n</dict>",
        1,
    )
plist.write_text(plist_text)

print("Extended G7 Watch GATT diagnostic patch applied successfully.")
