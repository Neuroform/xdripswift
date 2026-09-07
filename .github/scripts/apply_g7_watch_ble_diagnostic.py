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
                Text("G7 BLE Test")
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
                diagnosticRow("Auth Char", diagnostic.authCharacteristicFound ? "gefunden" : "—")
                diagnosticRow("Control Char", diagnostic.controlCharacteristicFound ? "gefunden" : "—")
                diagnosticRow("Backfill Char", diagnostic.backfillCharacteristicFound ? "gefunden" : "—")

                if diagnostic.connectionSucceeded {
                    Text(diagnostic.g7ServiceFound ? "BLE/GATT erreichbar" : "BLE verbunden, G7-Service nicht gefunden")
                        .font(.caption)
                        .fontWeight(.semibold)
                        .foregroundStyle(diagnostic.g7ServiceFound ? .green : .orange)
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

                Text("Der Test scannt nach G7, versucht eine BLE-Verbindung und liest nur Service-/Characteristic-Metadaten. Es werden keine Pairing-, Start-, Stop-, Kalibrierungs- oder Glukosebefehle gesendet.")
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
                .textSelection(.enabled)
        }
    }
}

private final class G7BLEDiagnosticModel: NSObject, ObservableObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    private let advertisementUUID = CBUUID(string: "FEBC")
    private let g7ServiceUUID = CBUUID(string: "F8083532-849E-531C-C594-30F1F86A4EA5")
    private let communicationUUID = CBUUID(string: "F8083533-849E-531C-C594-30F1F86A4EA5")
    private let controlUUID = CBUUID(string: "F8083534-849E-531C-C594-30F1F86A4EA5")
    private let authenticationUUID = CBUUID(string: "F8083535-849E-531C-C594-30F1F86A4EA5")
    private let backfillUUID = CBUUID(string: "F8083536-849E-531C-C594-30F1F86A4EA5")

    @Published var bluetoothState = "initialisiert"
    @Published var status = "bereit"
    @Published var deviceName = ""
    @Published var rssi: Int?
    @Published var g7ServiceFound = false
    @Published var authCharacteristicFound = false
    @Published var controlCharacteristicFound = false
    @Published var backfillCharacteristicFound = false
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
            self.stopTest(reason: self.connectionSucceeded ? "Test beendet" : "Timeout – kein nutzbarer G7 gefunden")
        }
        timeoutTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + 35, execute: task)
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
        authCharacteristicFound = false
        controlCharacteristicFound = false
        backfillCharacteristicFound = false
        connectionSucceeded = false
    }

    private func beginDiscovery() {
        bluetoothState = "ein"
        status = "suche G7…"

        // First ask iOS/watchOS whether a peripheral exposing the native G7 service is already
        // connected at system level (for example by another app). If not, scan advertisements.
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
        if isRunning, !g7ServiceFound {
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
        status = "G7-Service gefunden; prüfe Characteristics…"
        peripheral.discoverCharacteristics([communicationUUID, controlUUID, authenticationUUID, backfillUUID], for: service)
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        if let error {
            stopTest(reason: "Characteristic-Suche fehlgeschlagen: \\(error.localizedDescription)")
            return
        }

        let characteristics = service.characteristics ?? []
        authCharacteristicFound = characteristics.contains(where: { $0.uuid == authenticationUUID })
        controlCharacteristicFound = characteristics.contains(where: { $0.uuid == controlUUID })
        backfillCharacteristicFound = characteristics.contains(where: { $0.uuid == backfillUUID })
        let communicationFound = characteristics.contains(where: { $0.uuid == communicationUUID })

        let essential = authCharacteristicFound && controlCharacteristicFound && communicationFound
        stopTest(reason: essential ? "Erfolg: G7 BLE/GATT direkt erreichbar" : "G7-Service erreichbar, Characteristics unvollständig")
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

print("G7 Watch BLE diagnostic patch applied successfully.")
