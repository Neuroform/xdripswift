from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1))


# This patch runs AFTER apply_personal_watch_phase1.py and
# apply_g7_watch_ble_diagnostic.py. It deliberately returns the automatic
# Direct-G7 collector to a conservative foreground-only diagnostic state:
# no automatic BLE startup, no state restoration, no background reconnect.
# A separate, user-triggered Auth Probe performs only the first xDrip+/KEKS
# G7 authentication request and records the response. It does NOT answer a
# received challenge, bond, pair, start/stop/calibrate, request glucose, or
# reconnect automatically.

watch_state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")

replace_once(
    watch_state,
    '''    @Published var directG7ReadingCount: Int = 0''',
    '''    @Published var directG7ReadingCount: Int = 0

    // Manual G7 authentication probe. This is intentionally opt-in and foreground-only.
    private var g7AuthProbeManager: G7AuthProbeManager?
    @Published var g7AuthProbeStatus: String = "bereit"
    @Published var g7AuthProbeDeviceName: String = ""
    @Published var g7AuthProbeResponseHex: String = ""
    @Published var g7AuthProbeRunning: Bool = false
    @Published var g7AuthProbeChallengeReceived: Bool = false''',
    "WatchStateModel auth probe properties",
)

# Build 7 is the safe reference. Do not auto-start the direct BLE manager in this
# diagnostic build, because Build 8 showed that an aggressive Watch BLE lifecycle
# can interfere with the official Dexcom Direct-to-Watch path.
old_startup = '''        directG7Manager = G7DirectBLEManager(
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
        directG7Manager?.start()'''

new_startup = '''        // Auth-probe build: never start Direct-G7 automatically.
        // The official Dexcom Watch connection must remain untouched unless the user
        // explicitly starts the short foreground Auth Probe from the G7 page.
        directG7Manager = nil
        directG7Status = "Auto-Direct aus · Auth-Test bereit"'''

replace_once(
    watch_state,
    old_startup,
    new_startup,
    "disable automatic Direct-G7 startup",
)

probe_methods = r'''
    // MARK: - Manual G7 authentication probe

    func startG7AuthProbe() {
        guard !g7AuthProbeRunning else { return }

        g7AuthProbeStatus = "initialisiere Auth-Probe…"
        g7AuthProbeDeviceName = ""
        g7AuthProbeResponseHex = ""
        g7AuthProbeChallengeReceived = false
        g7AuthProbeRunning = true

        let manager = G7AuthProbeManager { [weak self] status, deviceName, responseHex, challengeReceived, finished in
            DispatchQueue.main.async {
                guard let self else { return }
                self.g7AuthProbeStatus = status
                self.g7AuthProbeDeviceName = deviceName
                self.g7AuthProbeResponseHex = responseHex
                self.g7AuthProbeChallengeReceived = challengeReceived
                if finished {
                    self.g7AuthProbeRunning = false
                    self.g7AuthProbeManager = nil
                }
            }
        }

        g7AuthProbeManager = manager
        manager.start()
    }

    func stopG7AuthProbe() {
        g7AuthProbeManager?.stop(userInitiated: true)
    }

'''

replace_once(
    watch_state,
    '''    // MARK: - Direct Dexcom G7 Watch BLE path
''',
    probe_methods + '''    // MARK: - Direct Dexcom G7 Watch BLE path
''',
    "WatchStateModel auth probe controls",
)

probe_manager = r'''
// MARK: - Manual G7 authentication probe

private final class G7AuthProbeManager: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    typealias UpdateHandler = (_ status: String, _ deviceName: String, _ responseHex: String, _ challengeReceived: Bool, _ finished: Bool) -> Void

    private let advertisementUUID = CBUUID(string: "FEBC")
    private let serviceUUID = CBUUID(string: "F8083532-849E-531C-C594-30F1F86A4EA5")
    private let authUUID = CBUUID(string: "F8083535-849E-531C-C594-30F1F86A4EA5")

    private let onUpdate: UpdateHandler
    private var central: CBCentralManager!
    private var targetPeripheral: CBPeripheral?
    private var authCharacteristic: CBCharacteristic?
    private var protectedPeripheralIDs = Set<UUID>()
    private var timeoutTask: DispatchWorkItem?
    private var running = false
    private var authRequestSent = false
    private var lastDeviceName = ""
    private var lastResponseHex = ""
    private var challengeReceived = false

    init(onUpdate: @escaping UpdateHandler) {
        self.onUpdate = onUpdate
        super.init()

        // Deliberately no CBCentralManager restore identifier: this test must never
        // be resurrected by watchOS in the background.
        central = CBCentralManager(delegate: self, queue: .main, options: nil)
    }

    func start() {
        running = true
        publish("warte auf Bluetooth…")
        if central.state == .poweredOn {
            beginSafeDiscovery()
        }
    }

    func stop(userInitiated: Bool) {
        finish(userInitiated ? "Auth-Probe abgebrochen" : "Auth-Probe beendet")
    }

    private func publish(_ status: String, finished: Bool = false) {
        onUpdate(status, lastDeviceName, lastResponseHex, challengeReceived, finished)
    }

    private func armTimeout(seconds: TimeInterval, status: String) {
        timeoutTask?.cancel()
        let task = DispatchWorkItem { [weak self] in
            guard let self, self.running else { return }
            self.finish(status)
        }
        timeoutTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: task)
    }

    private func beginSafeDiscovery() {
        guard running, central.state == .poweredOn else { return }

        // Protect every G7 peripheral that watchOS reports as already connected.
        // The probe will never select one of these IDs. This is specifically intended
        // to avoid touching the active official Dexcom Direct-to-Watch connection.
        let connected = central.retrieveConnectedPeripherals(withServices: [serviceUUID])
        protectedPeripheralIDs = Set(connected.map { $0.identifier })

        publish("suche freien G7-Kandidaten…")
        central.scanForPeripherals(
            withServices: [advertisementUUID],
            options: [CBCentralManagerScanOptionAllowDuplicatesKey: false]
        )
        armTimeout(seconds: 20, status: "kein freier G7-Kandidat in 20 s")
    }

    private func inspect(_ peripheral: CBPeripheral, name: String) {
        guard running, targetPeripheral == nil else { return }
        guard !protectedPeripheralIDs.contains(peripheral.identifier) else { return }

        central.stopScan()
        timeoutTask?.cancel()
        targetPeripheral = peripheral
        peripheral.delegate = self
        lastDeviceName = name.isEmpty ? (peripheral.name ?? "unbekannt") : name
        publish("freier Kandidat gefunden; verbinde einmalig…")
        central.connect(peripheral, options: nil)
        armTimeout(seconds: 12, status: "Verbindung/Auth-Probe Timeout")
    }

    private func sendInitialAuthRequest(_ peripheral: CBPeripheral, characteristic: CBCharacteristic) {
        guard running, !authRequestSent else { return }
        guard characteristic.properties.contains(.write) else {
            finish("Auth-Characteristic ist nicht beschreibbar")
            return
        }

        // xDrip+ KEKS AuthRequestTxMessage2:
        // opcode 0x02 + 8-byte single-use token + standard slot byte 0x02.
        // We stop after the sensor's first response and intentionally DO NOT answer
        // a 0x03 challenge, so this probe cannot complete pairing/authentication.
        var packet = Data([0x02])
        for _ in 0..<8 {
            packet.append(UInt8.random(in: UInt8.min...UInt8.max))
        }
        packet.append(0x02)

        authRequestSent = true
        publish("Auth-Request 0x02 gesendet; warte auf erste Antwort…")
        peripheral.writeValue(packet, for: characteristic, type: .withResponse)
        armTimeout(seconds: 10, status: "keine Auth-Antwort in 10 s")
    }

    private func finish(_ status: String) {
        guard running else { return }
        running = false
        timeoutTask?.cancel()
        timeoutTask = nil
        central.stopScan()

        if let peripheral = targetPeripheral {
            if let authCharacteristic, authCharacteristic.isNotifying {
                peripheral.setNotifyValue(false, for: authCharacteristic)
            }
            if peripheral.state != .disconnected {
                central.cancelPeripheralConnection(peripheral)
            }
        }

        publish(status, finished: true)
    }

    private func hex(_ data: Data) -> String {
        data.map { String(format: "%02X", $0) }.joined(separator: " ")
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard running else { return }
        switch central.state {
        case .poweredOn:
            beginSafeDiscovery()
        case .poweredOff:
            finish("Bluetooth aus")
        case .unauthorized:
            finish("Bluetooth-Berechtigung fehlt")
        case .unsupported:
            finish("CoreBluetooth nicht unterstützt")
        case .resetting:
            publish("Bluetooth wird zurückgesetzt")
        case .unknown:
            publish("Bluetooth-Status unbekannt")
        @unknown default:
            publish("Bluetooth-Status unbekannt")
        }
    }

    func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String : Any],
        rssi RSSI: NSNumber
    ) {
        guard running else { return }
        let name = peripheral.name ?? (advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? "")
        guard name.hasPrefix("DX") else { return }
        inspect(peripheral, name: name)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        guard running, targetPeripheral?.identifier == peripheral.identifier else { return }
        lastDeviceName = peripheral.name ?? lastDeviceName
        publish("verbunden; suche nur Auth-Characteristic…")
        peripheral.discoverServices([serviceUUID])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        guard running else { return }
        finish("einmalige Verbindung fehlgeschlagen")
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        guard running else { return }
        finish("G7 hat Verbindung beendet")
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard running else { return }
        guard error == nil,
              let service = peripheral.services?.first(where: { $0.uuid == serviceUUID }) else {
            finish("G7-Service nicht verfügbar")
            return
        }

        peripheral.discoverCharacteristics([authUUID], for: service)
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard running else { return }
        guard error == nil,
              let characteristic = service.characteristics?.first(where: { $0.uuid == authUUID }) else {
            finish("Auth-Characteristic 3535 nicht gefunden")
            return
        }

        authCharacteristic = characteristic

        guard characteristic.properties.contains(.notify) || characteristic.properties.contains(.indicate) else {
            finish("Auth-Characteristic kann nicht benachrichtigen")
            return
        }

        publish("3535 gefunden; aktiviere Notify/Indicate…")
        peripheral.setNotifyValue(true, for: characteristic)
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?) {
        guard running, characteristic.uuid == authUUID else { return }
        if let error {
            finish("Notify-Fehler: \(error.localizedDescription)")
            return
        }

        guard characteristic.isNotifying else {
            finish("Auth-Notify wurde nicht aktiviert")
            return
        }

        sendInitialAuthRequest(peripheral, characteristic: characteristic)
    }

    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        guard running, characteristic.uuid == authUUID else { return }
        if let error {
            finish("Auth-Request Schreibfehler: \(error.localizedDescription)")
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard running, characteristic.uuid == authUUID else { return }
        guard error == nil, let value = characteristic.value, !value.isEmpty else {
            finish("leere/fehlerhafte Auth-Antwort")
            return
        }

        lastResponseHex = hex(value)

        switch value[0] {
        case 0x03:
            // xDrip+ AuthChallengeRxMessage is 17 bytes: opcode + 8-byte tokenHash + 8-byte challenge.
            if value.count >= 17 {
                challengeReceived = true
                finish("0x03 Challenge erhalten · Probe erfolgreich · keine Antwort gesendet")
            } else {
                finish("0x03 empfangen, aber Paket zu kurz")
            }

        case 0x05:
            if value.count >= 3 {
                let authenticated = value[1] == 0x01
                let bonded = value[2] == 0x01
                finish("0x05 Status: auth=\(authenticated ? "ja" : "nein"), bonded=\(bonded ? "ja" : "nein")")
            } else {
                finish("0x05 Status empfangen, aber Paket zu kurz")
            }

        default:
            finish(String(format: "Auth-Antwort 0x%02X erhalten · Probe beendet", value[0]))
        }
    }
}

'''

replace_once(
    watch_state,
    '''// MARK: - Direct G7 BLE manager
''',
    probe_manager + '''// MARK: - Direct G7 BLE manager
''',
    "insert manual G7 auth probe manager",
)

# The old Direct manager is retained only so the proven parser remains available in this branch,
# but remove state restoration from it as an additional safety guard. It is not started in this build.
replace_once(
    watch_state,
    '''        central = CBCentralManager(
            delegate: self,
            queue: .main,
            options: [CBCentralManagerOptionRestoreIdentifierKey: "xDrip.G7.Direct.Central"]
        )''',
    '''        central = CBCentralManager(
            delegate: self,
            queue: .main,
            options: nil
        )''',
    "remove Direct-G7 state restoration",
)

# Add the Auth Probe UI to the existing G7 Direct diagnostic page.
root = Path("xDrip Watch App/Views/RootView.swift")

old_intro = '''                Text("Automatischer BLE-Pfad · iPhone bleibt Fallback")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
'''
new_intro = '''                Text("Build 9 Auth-Probe · kein automatischer G7-BLE-Pfad")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
'''
replace_once(root, old_intro, new_intro, "G7 page auth probe title")

old_footer = '''                Text("D = Direct-G7. Wenn Direct ausfällt, darf ein neuerer iPhone-Wert automatisch übernehmen.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
'''
new_footer = '''                Divider()

                Text("Separater G7-Authentifizierungs-Test")
                    .font(.headline)

                Text("Der Test läuft nur nach Tippen, schließt bereits verbundene G7-Peripherals aus und sendet genau einen xDrip+ AuthRequest 0x02. Eine 0x03-Challenge wird nur protokolliert und NICHT beantwortet.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)

                row("Auth-Probe", watchState.g7AuthProbeStatus)

                if !watchState.g7AuthProbeDeviceName.isEmpty {
                    row("Probe-Gerät", watchState.g7AuthProbeDeviceName)
                }

                if !watchState.g7AuthProbeResponseHex.isEmpty {
                    row("Letzte Auth-Antwort", watchState.g7AuthProbeResponseHex)
                }

                if watchState.g7AuthProbeChallengeReceived {
                    Text("✓ Separate 0x03-Challenge erhalten")
                        .font(.caption)
                        .foregroundStyle(.green)
                }

                Button(watchState.g7AuthProbeRunning ? "Auth-Probe abbrechen" : "Auth-Probe starten") {
                    if watchState.g7AuthProbeRunning {
                        watchState.stopG7AuthProbe()
                    } else {
                        watchState.startG7AuthProbe()
                    }
                }
                .buttonStyle(.borderedProminent)

                Text("Während der Probe bitte die Dexcom-Komplikation beobachten. Der Test führt kein Bonding/Pairing durch und startet keinen Reconnect.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
'''
replace_once(root, old_footer, new_footer, "G7 page auth probe controls")

# Safety: when the newest glucose sample is older than the Phase-1 7-minute limit,
# the rectangular xDrip complication must behave like Dexcom: show '---' rather than
# presenting a historic glucose value as current. Graph history may remain visible.
view = Path("xDrip Watch Complication/Views/AccessoryRectangularView.swift")

old_stale = '''                        HStack(alignment: .center, spacing: 5) {
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
                        }'''

new_stale = '''                        HStack(alignment: .center, spacing: 5) {
                            Text("---")
                                .font(.system(size: entry.widgetState.isSmallScreen() ? 20 : 24)).bold()
                                .foregroundStyle(.gray)

                            Text("KEIN AKTUELLER WERT")
                                .font(.system(size: entry.widgetState.isSmallScreen() ? 8 : 9, weight: .semibold))
                                .foregroundStyle(.orange)
                                .lineLimit(1)
                                .minimumScaleFactor(0.7)
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
                        }'''

replace_once(view, old_stale, new_stale, "xDrip stale BG placeholder")

# A green Direct marker must never remain visible when the displayed state is stale.
replace_once(
    view,
    '''            if entry.widgetState.dataSource == "G7 BLE" {''',
    '''            if entry.widgetState.hasRecentReading && entry.widgetState.dataSource == "G7 BLE" {''',
    "hide Direct marker when stale",
)

# This is a foreground-only probe; do not request bluetooth-central background execution.
plist = Path("xDrip-Watch-App-Info.plist")
plist_text = plist.read_text()
background_block = '''\t<key>UIBackgroundModes</key>\n\t<array>\n\t\t<string>bluetooth-central</string>\n\t</array>\n'''
if background_block in plist_text:
    plist_text = plist_text.replace(background_block, "", 1)
plist.write_text(plist_text)

print("Manual G7 auth probe + stale BG safety patch applied successfully.")
