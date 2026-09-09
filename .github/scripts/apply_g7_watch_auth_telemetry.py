from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1))


def replace_between(path: Path, start: str, end: str, replacement: str, label: str) -> None:
    text = path.read_text()
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"{label}: start marker not found in {path}")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"{label}: end marker not found in {path}")
    path.write_text(text[:start_index] + replacement + text[end_index:])


# This patch runs AFTER apply_g7_watch_auth_probe_and_stale_safety.py.
# It keeps Build 9's safety model intact and changes only the manual foreground
# Auth Probe into a higher-resolution telemetry probe:
# - no automatic G7 BLE startup / no restoration / no background reconnect
# - already-connected G7 peripherals remain excluded from selection
# - subscribe to 3534/3535/3536/3538 for passive RX logging
# - send exactly one application-level Dexcom command: AuthRequest opcode 0x02 on 3535
# - NEVER answer a 0x03 challenge
# - observe for 3 seconds after TX unless the peripheral disconnects first
# - record whether the disconnect was remote or locally requested

watch_state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")

replace_once(
    watch_state,
    '''    @Published var g7AuthProbeChallengeReceived: Bool = false''',
    '''    @Published var g7AuthProbeChallengeReceived: Bool = false
    @Published var g7AuthProbeTelemetry: String = ""''',
    "add auth telemetry published property",
)

replace_once(
    watch_state,
    '''        g7AuthProbeChallengeReceived = false
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
        }''',
    '''        g7AuthProbeChallengeReceived = false
        g7AuthProbeTelemetry = ""
        g7AuthProbeRunning = true

        let manager = G7AuthProbeManager { [weak self] status, deviceName, responseHex, challengeReceived, telemetry, finished in
            DispatchQueue.main.async {
                guard let self else { return }
                self.g7AuthProbeStatus = status
                self.g7AuthProbeDeviceName = deviceName
                self.g7AuthProbeResponseHex = responseHex
                self.g7AuthProbeChallengeReceived = challengeReceived
                self.g7AuthProbeTelemetry = telemetry
                if finished {
                    self.g7AuthProbeRunning = false
                    self.g7AuthProbeManager = nil
                }
            }
        }''',
    "wire auth telemetry callback",
)

manager_start = '''// MARK: - Manual G7 authentication probe

private final class G7AuthProbeManager'''
manager_end = '''// MARK: - Direct G7 BLE manager
'''

manager = r'''// MARK: - Manual G7 authentication probe

private final class G7AuthProbeManager: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    typealias UpdateHandler = (_ status: String, _ deviceName: String, _ responseHex: String, _ challengeReceived: Bool, _ telemetry: String, _ finished: Bool) -> Void

    private let advertisementUUID = CBUUID(string: "FEBC")
    private let serviceUUID = CBUUID(string: "F8083532-849E-531C-C594-30F1F86A4EA5")
    private let authUUID = CBUUID(string: "F8083535-849E-531C-C594-30F1F86A4EA5")
    private let channelUUIDs = [
        CBUUID(string: "F8083534-849E-531C-C594-30F1F86A4EA5"),
        CBUUID(string: "F8083535-849E-531C-C594-30F1F86A4EA5"),
        CBUUID(string: "F8083536-849E-531C-C594-30F1F86A4EA5"),
        CBUUID(string: "F8083538-849E-531C-C594-30F1F86A4EA5")
    ]

    private let onUpdate: UpdateHandler
    private var central: CBCentralManager!
    private var targetPeripheral: CBPeripheral?
    private var characteristics: [String: CBCharacteristic] = [:]
    private var protectedPeripheralIDs = Set<UUID>()
    private var notifyPending = Set<String>()
    private var timeoutTask: DispatchWorkItem?
    private var captureTask: DispatchWorkItem?
    private var running = false
    private var authRequestSent = false
    private var localDisconnectRequested = false
    private var lastDeviceName = ""
    private var lastResponseHex = ""
    private var challengeReceived = false
    private var eventLog: [String] = []
    private var connectedAt: Date?
    private var txAt: Date?

    init(onUpdate: @escaping UpdateHandler) {
        self.onUpdate = onUpdate
        super.init()

        // Intentionally no restore identifier. This probe is foreground-only and
        // must never be resurrected by watchOS in the background.
        central = CBCentralManager(delegate: self, queue: .main, options: nil)
    }

    func start() {
        running = true
        addEvent("Probe gestartet")
        publish("warte auf Bluetooth…")
        if central.state == .poweredOn {
            beginSafeDiscovery()
        }
    }

    func stop(userInitiated: Bool) {
        guard running else { return }
        addEvent(userInitiated ? "Benutzerabbruch" : "Probe stop")
        requestLocalDisconnect(finalStatus: userInitiated ? "Auth-Probe abgebrochen" : "Auth-Probe beendet")
    }

    private func shortUUID(_ uuid: CBUUID) -> String {
        let s = uuid.uuidString.uppercased()
        if s.hasPrefix("F808") && s.count >= 8 {
            return String(s.prefix(8))
        }
        return s
    }

    private func timestamp(_ date: Date = Date()) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "HH:mm:ss.SSS"
        return formatter.string(from: date)
    }

    private func elapsedMS(from start: Date?, to end: Date = Date()) -> String {
        guard let start else { return "n/a" }
        return String(format: "%.0f ms", end.timeIntervalSince(start) * 1000.0)
    }

    private func hex(_ data: Data) -> String {
        data.map { String(format: "%02X", $0) }.joined(separator: " ")
    }

    private func addEvent(_ text: String) {
        eventLog.append("\(timestamp())  \(text)")
        if eventLog.count > 50 {
            eventLog.removeFirst(eventLog.count - 50)
        }
    }

    private func publish(_ status: String, finished: Bool = false) {
        onUpdate(status, lastDeviceName, lastResponseHex, challengeReceived, eventLog.joined(separator: "\n"), finished)
    }

    private func armTimeout(seconds: TimeInterval, status: String) {
        timeoutTask?.cancel()
        let task = DispatchWorkItem { [weak self] in
            guard let self, self.running else { return }
            self.addEvent("Timeout: \(status)")
            self.requestLocalDisconnect(finalStatus: status)
        }
        timeoutTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: task)
    }

    private func beginSafeDiscovery() {
        guard running, central.state == .poweredOn else { return }

        let connected = central.retrieveConnectedPeripherals(withServices: [serviceUUID])
        protectedPeripheralIDs = Set(connected.map { $0.identifier })
        addEvent("Bereits verbundene G7 geschützt: \(protectedPeripheralIDs.count)")

        publish("suche freien G7-Kandidaten…")
        central.scanForPeripherals(
            withServices: [advertisementUUID],
            options: [CBCentralManagerScanOptionAllowDuplicatesKey: false]
        )
        armTimeout(seconds: 20, status: "kein freier G7-Kandidat in 20 s")
    }

    private func inspect(_ peripheral: CBPeripheral, name: String) {
        guard running, targetPeripheral == nil else { return }
        guard !protectedPeripheralIDs.contains(peripheral.identifier) else {
            addEvent("Ignoriere geschützten Peripheral \(name)")
            publish("offiziell verbundenen G7 übersprungen")
            return
        }

        central.stopScan()
        timeoutTask?.cancel()
        targetPeripheral = peripheral
        peripheral.delegate = self
        lastDeviceName = name.isEmpty ? (peripheral.name ?? "unbekannt") : name
        addEvent("Kandidat: \(lastDeviceName) id=\(peripheral.identifier.uuidString)")
        publish("freier Kandidat gefunden; verbinde einmalig…")
        central.connect(peripheral, options: nil)
        armTimeout(seconds: 12, status: "Verbindung/Auth-Probe Timeout")
    }

    private func sendInitialAuthRequest(_ peripheral: CBPeripheral, characteristic: CBCharacteristic) {
        guard running, !authRequestSent else { return }
        guard characteristic.properties.contains(.write) else {
            addEvent("3535 nicht write-fähig")
            requestLocalDisconnect(finalStatus: "Auth-Characteristic ist nicht beschreibbar")
            return
        }

        // Exact same conservative one-shot AuthRequest as Build 9:
        // opcode 0x02 + 8-byte single-use token + slot byte 0x02.
        // No 0x03 challenge is ever answered.
        var packet = Data([0x02])
        for _ in 0..<8 {
            packet.append(UInt8.random(in: UInt8.min...UInt8.max))
        }
        packet.append(0x02)

        authRequestSent = true
        txAt = Date()
        addEvent("TX F8083535 \(packet.count) B [withResponse]")
        addEvent("TX HEX: \(hex(packet))")
        publish("Auth-Request 0x02 gesendet; 3 s RX-Beobachtung…")
        peripheral.writeValue(packet, for: characteristic, type: .withResponse)

        // Observe all subscribed channels for three seconds. If the G7 disconnects
        // sooner, didDisconnect will prove that no local disconnect was requested.
        captureTask?.cancel()
        let task = DispatchWorkItem { [weak self] in
            guard let self, self.running else { return }
            self.addEvent("3-s-RX-Fenster beendet")
            self.requestLocalDisconnect(finalStatus: "3-s-Telemetrie vollständig")
        }
        captureTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + 3.0, execute: task)
    }

    private func requestLocalDisconnect(finalStatus: String) {
        guard running else { return }
        timeoutTask?.cancel()
        timeoutTask = nil
        captureTask?.cancel()
        captureTask = nil
        central.stopScan()

        guard let peripheral = targetPeripheral, peripheral.state != .disconnected else {
            running = false
            addEvent("Kein lokaler Disconnect nötig")
            publish(finalStatus, finished: true)
            return
        }

        localDisconnectRequested = true
        addEvent("LOCAL CANCEL angefordert: JA")
        addEvent("TX→LocalCancel: \(elapsedMS(from: txAt))")
        publish("beende Probe lokal nach Beobachtungsfenster…")
        central.cancelPeripheralConnection(peripheral)

        // Normal completion is published from didDisconnect so the callback itself
        // is captured. Failsafe only if CoreBluetooth never returns didDisconnect.
        let task = DispatchWorkItem { [weak self] in
            guard let self, self.running else { return }
            self.running = false
            self.addEvent("didDisconnect-Failsafe nach LocalCancel")
            self.publish(finalStatus, finished: true)
        }
        timeoutTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0, execute: task)
    }

    private func finishWithoutConnection(_ status: String) {
        guard running else { return }
        running = false
        timeoutTask?.cancel()
        timeoutTask = nil
        captureTask?.cancel()
        captureTask = nil
        central.stopScan()
        addEvent(status)
        publish(status, finished: true)
    }

    private func maybeSendAuthRequest(_ peripheral: CBPeripheral) {
        guard running, !authRequestSent, notifyPending.isEmpty else { return }
        guard let authCharacteristic = characteristics[authUUID.uuidString], authCharacteristic.isNotifying else {
            addEvent("3535 Notify nicht aktiv – kein TX")
            requestLocalDisconnect(finalStatus: "Auth-Notify wurde nicht aktiviert")
            return
        }
        sendInitialAuthRequest(peripheral, characteristic: authCharacteristic)
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard running else { return }
        switch central.state {
        case .poweredOn:
            addEvent("Bluetooth poweredOn")
            beginSafeDiscovery()
        case .poweredOff:
            finishWithoutConnection("Bluetooth aus")
        case .unauthorized:
            finishWithoutConnection("Bluetooth-Berechtigung fehlt")
        case .unsupported:
            finishWithoutConnection("CoreBluetooth nicht unterstützt")
        case .resetting:
            addEvent("Bluetooth resetting")
            publish("Bluetooth wird zurückgesetzt")
        case .unknown:
            addEvent("Bluetooth unknown")
            publish("Bluetooth-Status unbekannt")
        @unknown default:
            addEvent("Bluetooth unknown default")
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
        addEvent("Scan: \(name) RSSI=\(RSSI) dBm")
        inspect(peripheral, name: name)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        guard running, targetPeripheral?.identifier == peripheral.identifier else { return }
        timeoutTask?.cancel()
        connectedAt = Date()
        lastDeviceName = peripheral.name ?? lastDeviceName
        addEvent("CONNECTED \(lastDeviceName)")
        addEvent("Connected time: \(timestamp(connectedAt!))")
        publish("verbunden; ermittle 4 GATT-Kanäle…")
        peripheral.discoverServices([serviceUUID])
        armTimeout(seconds: 10, status: "GATT Discovery Timeout")
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        guard running else { return }
        addEvent("didFailToConnect error=\(error?.localizedDescription ?? "nil")")
        finishWithoutConnection("einmalige Verbindung fehlgeschlagen")
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        guard targetPeripheral?.identifier == peripheral.identifier else { return }
        guard running else { return }

        timeoutTask?.cancel()
        timeoutTask = nil
        captureTask?.cancel()
        captureTask = nil

        let source = localDisconnectRequested ? "LOCAL" : "REMOTE/COREBT"
        addEvent("DISCONNECT source=\(source)")
        addEvent("didDisconnect error=\(error?.localizedDescription ?? "nil")")
        addEvent("TX→Disconnect: \(elapsedMS(from: txAt))")
        addEvent("Connected→Disconnect: \(elapsedMS(from: connectedAt))")

        running = false
        if localDisconnectRequested {
            publish("lokaler Probe-Disconnect bestätigt", finished: true)
        } else {
            publish("G7/CoreBluetooth hat Verbindung beendet", finished: true)
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard running else { return }
        guard error == nil,
              let service = peripheral.services?.first(where: { $0.uuid == serviceUUID }) else {
            addEvent("Service discovery error=\(error?.localizedDescription ?? "nil")")
            requestLocalDisconnect(finalStatus: "G7-Service nicht verfügbar")
            return
        }

        addEvent("G7 service 3532 gefunden")
        peripheral.discoverCharacteristics(channelUUIDs, for: service)
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard running else { return }
        timeoutTask?.cancel()
        guard error == nil else {
            addEvent("Characteristic discovery error=\(error?.localizedDescription ?? "nil")")
            requestLocalDisconnect(finalStatus: "GATT-Characteristics nicht verfügbar")
            return
        }

        let discovered = service.characteristics ?? []
        characteristics = Dictionary(uniqueKeysWithValues: discovered.map { ($0.uuid.uuidString, $0) })
        addEvent("Characteristics gefunden: \(discovered.count)")

        guard characteristics[authUUID.uuidString] != nil else {
            addEvent("3535 fehlt")
            requestLocalDisconnect(finalStatus: "Auth-Characteristic 3535 nicht gefunden")
            return
        }

        notifyPending.removeAll()
        for uuid in channelUUIDs {
            guard let characteristic = characteristics[uuid.uuidString] else {
                addEvent("\(shortUUID(uuid)) fehlt")
                continue
            }

            if characteristic.properties.contains(.notify) || characteristic.properties.contains(.indicate) {
                let key = characteristic.uuid.uuidString
                notifyPending.insert(key)
                addEvent("SUBSCRIBE \(shortUUID(characteristic.uuid))")
                peripheral.setNotifyValue(true, for: characteristic)
            } else {
                addEvent("\(shortUUID(characteristic.uuid)) ohne Notify/Indicate")
            }
        }

        if notifyPending.isEmpty {
            requestLocalDisconnect(finalStatus: "keine Notify-Kanäle verfügbar")
        } else {
            publish("abonniere 3534/3535/3536/3538…")
            armTimeout(seconds: 8, status: "Notify Setup Timeout")
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?) {
        guard running else { return }
        let key = characteristic.uuid.uuidString
        guard channelUUIDs.contains(where: { $0.uuidString == key }) else { return }

        notifyPending.remove(key)
        if let error {
            addEvent("SUB \(shortUUID(characteristic.uuid)) FEHLER: \(error.localizedDescription)")
        } else {
            addEvent("SUB \(shortUUID(characteristic.uuid)) \(characteristic.isNotifying ? "OK" : "NICHT AKTIV")")
        }
        publish("Notify-Status \(shortUUID(characteristic.uuid)) erfasst")
        maybeSendAuthRequest(peripheral)
    }

    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        guard running, characteristic.uuid == authUUID else { return }
        if let error {
            addEvent("didWrite 3535 FEHLER: \(error.localizedDescription)")
        } else {
            addEvent("didWrite 3535 OK · TX→ACK \(elapsedMS(from: txAt))")
        }
        publish("AuthRequest write callback erfasst")
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard running else { return }
        let key = characteristic.uuid.uuidString
        guard channelUUIDs.contains(where: { $0.uuidString == key }) else { return }

        if let error {
            addEvent("RX \(shortUUID(characteristic.uuid)) FEHLER: \(error.localizedDescription)")
            publish("RX-Fehler protokolliert")
            return
        }

        guard let value = characteristic.value, !value.isEmpty else {
            addEvent("RX \(shortUUID(characteristic.uuid)) LEER")
            publish("leeres RX protokolliert")
            return
        }

        let packetHex = hex(value)
        addEvent("RX \(shortUUID(characteristic.uuid)) \(value.count) B · TX→RX \(elapsedMS(from: txAt))")
        addEvent("RX HEX: \(packetHex)")

        if characteristic.uuid == authUUID {
            lastResponseHex = packetHex
            if value[0] == 0x03 {
                challengeReceived = true
                addEvent("0x03 Challenge erkannt · NUR protokolliert · KEINE Antwort")
            } else if value[0] == 0x05 {
                addEvent("0x05 Auth-Status erkannt · NUR protokolliert")
            } else {
                addEvent(String(format: "3535 Opcode 0x%02X · nur protokolliert", value[0]))
            }
        }

        publish("RX auf \(shortUUID(characteristic.uuid)) protokolliert")
    }
}

'''

replace_between(
    watch_state,
    manager_start,
    manager_end,
    manager,
    "replace manual auth probe manager with telemetry version",
)

root = Path("xDrip Watch App/Views/RootView.swift")

replace_once(
    root,
    '''Text("Build 9 Auth-Probe · kein automatischer G7-BLE-Pfad")''',
    '''Text("Build 10 Auth-Telemetrie · kein automatischer G7-BLE-Pfad")''',
    "update diagnostic page title",
)

replace_once(
    root,
    '''Text("Der Test läuft nur nach Tippen, schließt bereits verbundene G7-Peripherals aus und sendet genau einen xDrip+ AuthRequest 0x02. Eine 0x03-Challenge wird nur protokolliert und NICHT beantwortet.")''',
    '''Text("Der Test läuft nur nach Tippen, schützt bereits verbundene G7-Peripherals, abonniert 3534/3535/3536/3538 und sendet genau einen AuthRequest 0x02 auf 3535. Drei Sekunden lang werden RX/ACK/Disconnect-Zeiten protokolliert. Eine 0x03-Challenge wird NICHT beantwortet.")''',
    "update auth telemetry explanation",
)

replace_once(
    root,
    '''                if watchState.g7AuthProbeChallengeReceived {
                    Text("✓ Separate 0x03-Challenge erhalten")
                        .font(.caption)
                        .foregroundStyle(.green)
                }

                Button(watchState.g7AuthProbeRunning ? "Auth-Probe abbrechen" : "Auth-Probe starten") {''',
    '''                if watchState.g7AuthProbeChallengeReceived {
                    Text("✓ Separate 0x03-Challenge erhalten · keine Antwort gesendet")
                        .font(.caption)
                        .foregroundStyle(.green)
                }

                if !watchState.g7AuthProbeTelemetry.isEmpty {
                    Text("Telemetrie")
                        .font(.headline)
                    Text(watchState.g7AuthProbeTelemetry)
                        .font(.system(size: 9, design: .monospaced))
                        .textSelection(.disabled)
                }

                Button(watchState.g7AuthProbeRunning ? "Auth-Probe abbrechen" : "Auth-Probe starten") {''',
    "add telemetry display",
)

# watchOS does not need/select text interaction here. Remove the modifier if the
# SDK rejects it; it is informational only and avoids the earlier Build 1 issue.
root_text = root.read_text()
root_text = root_text.replace('''                        .textSelection(.disabled)\n''', '')
root.write_text(root_text)

print("G7 auth telemetry patch applied successfully.")
