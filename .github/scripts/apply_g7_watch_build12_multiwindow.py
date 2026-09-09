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


# Build 12 runs after the Build 11 patch chain.
# Foreground/manual only. No Notify, no write, no Dexcom application command.
watch_state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")

manager_start = "// MARK: - Manual G7 authentication probe\n\nprivate final class G7AuthProbeManager"
manager_end = "// MARK: - Direct G7 BLE manager\n"

manager = r'''// MARK: - Manual G7 authentication probe

private final class G7AuthProbeManager: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    typealias UpdateHandler = (_ status: String, _ deviceName: String, _ responseHex: String, _ challengeReceived: Bool, _ telemetry: String, _ finished: Bool) -> Void

    private let advertisementUUID = CBUUID(string: "FEBC")
    private let serviceUUID = CBUUID(string: "F8083532-849E-531C-C594-30F1F86A4EA5")
    private let expectedChannelUUIDs = [
        CBUUID(string: "F8083534-849E-531C-C594-30F1F86A4EA5"),
        CBUUID(string: "F8083535-849E-531C-C594-30F1F86A4EA5"),
        CBUUID(string: "F8083536-849E-531C-C594-30F1F86A4EA5"),
        CBUUID(string: "F8083538-849E-531C-C594-30F1F86A4EA5")
    ]

    private let testWindowSeconds: TimeInterval = 600
    private let retryDelaySeconds: TimeInterval = 3
    private let minStableConnectionSeconds: TimeInterval = 0.25
    private let connectTimeoutSeconds: TimeInterval = 15
    private let gattTimeoutSeconds: TimeInterval = 8

    private let onUpdate: UpdateHandler
    private var central: CBCentralManager!
    private var targetPeripheral: CBPeripheral?
    private var protectedPeripheralIDs = Set<UUID>()

    private var running = false
    private var localDisconnectRequested = false
    private var finishAfterLocalDisconnect = false
    private var retryAfterLocalDisconnect = false
    private var pendingFinalStatus = ""

    private var lastDeviceName = ""
    private var eventLog: [String] = []
    private var connectedAt: Date?
    private var overallDeadline: Date?
    private var attemptCount = 0

    private var overallTimeoutTask: DispatchWorkItem?
    private var statusTickTask: DispatchWorkItem?
    private var retryTask: DispatchWorkItem?
    private var connectTimeoutTask: DispatchWorkItem?
    private var qualificationTask: DispatchWorkItem?
    private var gattTimeoutTask: DispatchWorkItem?

    init(onUpdate: @escaping UpdateHandler) {
        self.onUpdate = onUpdate
        super.init()
        central = CBCentralManager(delegate: self, queue: .main, options: nil)
    }

    func start() {
        guard !running else { return }
        running = true
        targetPeripheral = nil
        protectedPeripheralIDs.removeAll()
        localDisconnectRequested = false
        finishAfterLocalDisconnect = false
        retryAfterLocalDisconnect = false
        pendingFinalStatus = ""
        lastDeviceName = ""
        eventLog.removeAll()
        connectedAt = nil
        overallDeadline = nil
        attemptCount = 0

        addEvent("Build12 gestartet · GATT-only · kein Notify/kein TX")
        publish("warte auf Bluetooth…")

        if central.state == .poweredOn {
            beginObservationWindow()
        }
    }

    func stop(userInitiated: Bool) {
        guard running else { return }
        addEvent(userInitiated ? "Benutzerabbruch" : "Probe stop")
        if let peripheral = targetPeripheral,
           peripheral.state == .connected || peripheral.state == .connecting {
            requestLocalDisconnect(
                finalStatus: userInitiated ? "Multi-Window-Test abgebrochen" : "Multi-Window-Test beendet",
                finish: true
            )
        } else {
            finishWithoutConnection(userInitiated ? "Multi-Window-Test abgebrochen" : "Multi-Window-Test beendet")
        }
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

    private func shortUUID(_ uuid: CBUUID) -> String {
        let value = uuid.uuidString.uppercased()
        if value.hasPrefix("F808") && value.count >= 8 {
            return String(value.prefix(8))
        }
        return value
    }

    private func propertyText(_ characteristic: CBCharacteristic) -> String {
        var values: [String] = []
        let properties = characteristic.properties
        if properties.contains(.read) { values.append("R") }
        if properties.contains(.write) { values.append("W") }
        if properties.contains(.writeWithoutResponse) { values.append("WNR") }
        if properties.contains(.notify) { values.append("N") }
        if properties.contains(.indicate) { values.append("I") }
        if properties.contains(.broadcast) { values.append("B") }
        return values.isEmpty ? "-" : values.joined(separator: "|")
    }

    private func remainingSeconds() -> TimeInterval {
        guard let deadline = overallDeadline else { return testWindowSeconds }
        return max(0, deadline.timeIntervalSinceNow)
    }

    private func formatRemaining(_ seconds: TimeInterval) -> String {
        let total = max(0, Int(ceil(seconds)))
        return String(format: "%02d:%02d", total / 60, total % 60)
    }

    private func addEvent(_ text: String) {
        eventLog.append("\(timestamp())  \(text)")
        if eventLog.count > 80 {
            eventLog.removeFirst(eventLog.count - 80)
        }
    }

    private func publish(_ status: String, finished: Bool = false) {
        onUpdate(status, lastDeviceName, "", false, eventLog.joined(separator: "\n"), finished)
    }

    private func cancelPerAttemptTasks() {
        retryTask?.cancel()
        retryTask = nil
        connectTimeoutTask?.cancel()
        connectTimeoutTask = nil
        qualificationTask?.cancel()
        qualificationTask = nil
        gattTimeoutTask?.cancel()
        gattTimeoutTask = nil
    }

    private func cancelAllTasks() {
        cancelPerAttemptTasks()
        overallTimeoutTask?.cancel()
        overallTimeoutTask = nil
        statusTickTask?.cancel()
        statusTickTask = nil
    }

    private func beginObservationWindow() {
        guard running, central.state == .poweredOn, overallDeadline == nil else { return }

        let connected = central.retrieveConnectedPeripherals(withServices: [serviceUUID])
        protectedPeripheralIDs = Set(connected.map { $0.identifier })
        addEvent("Bereits verbundene G7 geschützt: \(protectedPeripheralIDs.count)")
        for id in protectedPeripheralIDs {
            addEvent("GESCHÜTZT id=\(id.uuidString)")
        }

        overallDeadline = Date().addingTimeInterval(testWindowSeconds)
        addEvent("Multi-Window-Fenster gestartet: 600 s")
        armOverallTimeout()
        scheduleStatusTick()
        startScan()
    }

    private func armOverallTimeout() {
        overallTimeoutTask?.cancel()
        let task = DispatchWorkItem { [weak self] in
            guard let self, self.running else { return }
            self.addEvent("10-Min-Fenster beendet · Attempts=\(self.attemptCount)")
            if let peripheral = self.targetPeripheral,
               peripheral.state == .connected || peripheral.state == .connecting {
                self.requestLocalDisconnect(
                    finalStatus: "10-Min-Test beendet · kein stabiles GATT-Fenster",
                    finish: true
                )
            } else {
                self.finishWithoutConnection("10-Min-Test beendet · kein stabiles GATT-Fenster")
            }
        }
        overallTimeoutTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + testWindowSeconds, execute: task)
    }

    private func scheduleStatusTick() {
        statusTickTask?.cancel()
        guard running else { return }

        let remaining = remainingSeconds()
        publish("Multi-Window-Test · \(formatRemaining(remaining)) · Attempts \(attemptCount)")

        guard remaining > 0 else { return }
        let task = DispatchWorkItem { [weak self] in
            self?.scheduleStatusTick()
        }
        statusTickTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + 10, execute: task)
    }

    private func startScan() {
        guard running, central.state == .poweredOn, targetPeripheral == nil else { return }
        guard remainingSeconds() > 0 else { return }

        central.stopScan()
        central.scanForPeripherals(
            withServices: [advertisementUUID],
            options: [CBCentralManagerScanOptionAllowDuplicatesKey: true]
        )
        addEvent("SCAN aktiv · Rest \(formatRemaining(remainingSeconds()))")
        publish("suche G7-Fenster… \(formatRemaining(remainingSeconds())) verbleibend")
    }

    private func scheduleRetry(_ reason: String) {
        guard running else { return }

        cancelPerAttemptTasks()
        central.stopScan()
        targetPeripheral = nil
        connectedAt = nil
        localDisconnectRequested = false
        finishAfterLocalDisconnect = false
        retryAfterLocalDisconnect = false
        pendingFinalStatus = ""

        let remaining = remainingSeconds()
        guard remaining > 0 else {
            finishWithoutConnection("10-Min-Test beendet · kein stabiles GATT-Fenster")
            return
        }

        addEvent("RETRY in 3 s · \(reason)")
        publish("Fenster geschlossen · neuer Versuch in 3 s")

        let task = DispatchWorkItem { [weak self] in
            guard let self, self.running else { return }
            self.retryTask = nil
            self.startScan()
        }
        retryTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + min(retryDelaySeconds, remaining), execute: task)
    }

    private func armConnectTimeout(for peripheral: CBPeripheral) {
        connectTimeoutTask?.cancel()
        let task = DispatchWorkItem { [weak self, weak peripheral] in
            guard let self, self.running,
                  let peripheral,
                  self.targetPeripheral?.identifier == peripheral.identifier else { return }

            self.addEvent("CONNECT timeout Attempt #\(self.attemptCount)")
            if peripheral.state == .connected || peripheral.state == .connecting {
                self.requestLocalDisconnect(finalStatus: "Connect-Timeout", retry: true)
            } else {
                self.scheduleRetry("Connect-Timeout")
            }
        }
        connectTimeoutTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + connectTimeoutSeconds, execute: task)
    }

    private func armGattTimeout(for peripheral: CBPeripheral, stage: String) {
        gattTimeoutTask?.cancel()
        let task = DispatchWorkItem { [weak self, weak peripheral] in
            guard let self, self.running,
                  let peripheral,
                  self.targetPeripheral?.identifier == peripheral.identifier else { return }
            self.addEvent("GATT timeout · \(stage)")
            self.requestLocalDisconnect(finalStatus: "GATT-Timeout \(stage)", retry: true)
        }
        gattTimeoutTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + gattTimeoutSeconds, execute: task)
    }

    private func requestLocalDisconnect(
        finalStatus: String,
        finish: Bool = false,
        retry: Bool = false
    ) {
        guard running else { return }

        central.stopScan()
        qualificationTask?.cancel()
        qualificationTask = nil
        connectTimeoutTask?.cancel()
        connectTimeoutTask = nil
        gattTimeoutTask?.cancel()
        gattTimeoutTask = nil

        pendingFinalStatus = finalStatus
        finishAfterLocalDisconnect = finish
        retryAfterLocalDisconnect = retry

        guard let peripheral = targetPeripheral,
              peripheral.state == .connected || peripheral.state == .connecting else {
            if finish {
                finishWithoutConnection(finalStatus)
            } else if retry {
                scheduleRetry(finalStatus)
            } else {
                finishWithoutConnection(finalStatus)
            }
            return
        }

        localDisconnectRequested = true
        addEvent("LOCAL CANCEL angefordert · \(finalStatus)")
        central.cancelPeripheralConnection(peripheral)
    }

    private func finishWithoutConnection(_ status: String) {
        guard running else { return }

        running = false
        central.stopScan()
        cancelAllTasks()
        targetPeripheral = nil
        connectedAt = nil
        addEvent(status)
        publish(status, finished: true)
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard running else { return }

        switch central.state {
        case .poweredOn:
            addEvent("Bluetooth poweredOn")
            beginObservationWindow()
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
        guard running, targetPeripheral == nil else { return }

        let name = peripheral.name ?? (advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? "")
        guard name.hasPrefix("DX") else { return }

        let advertisedServices = advertisementData[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID] ?? []
        let servicesText = advertisedServices.isEmpty
            ? "keine"
            : advertisedServices.map { $0.uuidString.uppercased() }.joined(separator: ",")
        let connectable = (advertisementData[CBAdvertisementDataIsConnectable] as? NSNumber)?.boolValue
        let connectableText = connectable.map { $0 ? "ja" : "nein" } ?? "unbekannt"

        addEvent("ADV \(name) RSSI=\(RSSI) dBm conn=\(connectableText)")
        addEvent("ADV services=\(servicesText)")
        addEvent("ADV id=\(peripheral.identifier.uuidString)")

        guard !protectedPeripheralIDs.contains(peripheral.identifier) else {
            addEvent("ADV ignoriert · geschützter Peripheral")
            publish("bereits verbundenen G7 geschützt")
            return
        }

        guard connectable != false else {
            addEvent("ADV ignoriert · nicht connectable")
            return
        }

        central.stopScan()
        targetPeripheral = peripheral
        peripheral.delegate = self
        lastDeviceName = name.isEmpty ? (peripheral.name ?? "unbekannt") : name
        connectedAt = nil
        localDisconnectRequested = false
        finishAfterLocalDisconnect = false
        retryAfterLocalDisconnect = false
        pendingFinalStatus = ""
        attemptCount += 1

        addEvent("Attempt #\(attemptCount) · CONNECT \(lastDeviceName)")
        publish("Attempt \(attemptCount): verbinde ohne GATT/TX…")
        central.connect(peripheral, options: nil)
        armConnectTimeout(for: peripheral)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        guard running, targetPeripheral?.identifier == peripheral.identifier else { return }

        connectTimeoutTask?.cancel()
        connectTimeoutTask = nil
        connectedAt = Date()
        lastDeviceName = peripheral.name ?? lastDeviceName

        addEvent("CONNECTED #\(attemptCount) \(lastDeviceName)")
        addEvent("Connected time: \(timestamp(connectedAt!))")
        publish("verbunden · 250 ms Stabilitätstest · noch kein GATT")

        qualificationTask?.cancel()
        let task = DispatchWorkItem { [weak self, weak peripheral] in
            guard let self, self.running,
                  let peripheral,
                  self.targetPeripheral?.identifier == peripheral.identifier,
                  peripheral.state == .connected else { return }

            self.addEvent("Connection ≥250 ms · discoverServices 3532")
            self.publish("≥250 ms stabil · lese nur GATT-Service 3532")
            peripheral.discoverServices([self.serviceUUID])
            self.armGattTimeout(for: peripheral, stage: "Service 3532")
        }
        qualificationTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + minStableConnectionSeconds, execute: task)
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        guard running, targetPeripheral?.identifier == peripheral.identifier else { return }

        connectTimeoutTask?.cancel()
        connectTimeoutTask = nil
        addEvent("didFailToConnect #\(attemptCount) error=\(error?.localizedDescription ?? "nil")")
        scheduleRetry("Connect fehlgeschlagen")
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        guard running, targetPeripheral?.identifier == peripheral.identifier else { return }

        connectTimeoutTask?.cancel()
        connectTimeoutTask = nil
        qualificationTask?.cancel()
        qualificationTask = nil
        gattTimeoutTask?.cancel()
        gattTimeoutTask = nil

        let source = localDisconnectRequested ? "LOCAL" : "REMOTE/COREBT"
        addEvent("DISCONNECT #\(attemptCount) source=\(source)")
        addEvent("didDisconnect error=\(error?.localizedDescription ?? "nil")")
        addEvent("Connected→Disconnect: \(elapsedMS(from: connectedAt))")

        if localDisconnectRequested {
            let finalStatus = pendingFinalStatus
            let shouldFinish = finishAfterLocalDisconnect
            let shouldRetry = retryAfterLocalDisconnect

            localDisconnectRequested = false
            finishAfterLocalDisconnect = false
            retryAfterLocalDisconnect = false
            pendingFinalStatus = ""

            if shouldFinish {
                running = false
                central.stopScan()
                cancelAllTasks()
                targetPeripheral = nil
                connectedAt = nil
                publish(finalStatus.isEmpty ? "lokaler Disconnect bestätigt" : finalStatus, finished: true)
            } else if shouldRetry {
                scheduleRetry(finalStatus.isEmpty ? "lokaler Retry-Disconnect" : finalStatus)
            } else {
                finishWithoutConnection(finalStatus.isEmpty ? "lokaler Disconnect bestätigt" : finalStatus)
            }
        } else {
            scheduleRetry("Remote-Disconnect nach \(elapsedMS(from: connectedAt))")
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard running, targetPeripheral?.identifier == peripheral.identifier else { return }

        gattTimeoutTask?.cancel()
        gattTimeoutTask = nil

        guard error == nil,
              let service = peripheral.services?.first(where: { $0.uuid == serviceUUID }) else {
            addEvent("Service discovery error=\(error?.localizedDescription ?? "nil")")
            requestLocalDisconnect(finalStatus: "Service 3532 nicht lesbar", retry: true)
            return
        }

        addEvent("GATT 3532 gefunden")
        publish("3532 gefunden · enumeriere Characteristics · kein Notify")
        peripheral.discoverCharacteristics(nil, for: service)
        armGattTimeout(for: peripheral, stage: "Characteristics")
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard running, targetPeripheral?.identifier == peripheral.identifier else { return }

        gattTimeoutTask?.cancel()
        gattTimeoutTask = nil

        guard error == nil else {
            addEvent("Characteristic discovery error=\(error?.localizedDescription ?? "nil")")
            requestLocalDisconnect(finalStatus: "Characteristics nicht lesbar", retry: true)
            return
        }

        let discovered = service.characteristics ?? []
        addEvent("GATT Characteristics: \(discovered.count)")
        for characteristic in discovered {
            addEvent("\(shortUUID(characteristic.uuid)) props=\(propertyText(characteristic))")
        }

        let discoveredUUIDs = Set(discovered.map { $0.uuid })
        let expectedFound = expectedChannelUUIDs.filter { discoveredUUIDs.contains($0) }
        addEvent("Erwartete 3534/35/36/38 gefunden: \(expectedFound.count)/4")

        guard !discovered.isEmpty else {
            requestLocalDisconnect(finalStatus: "0 Characteristics · neuer Versuch", retry: true)
            return
        }

        addEvent("PASSIV-GATT erfolgreich · KEIN Notify · KEIN TX")
        requestLocalDisconnect(
            finalStatus: "GATT-Struktur passiv gelesen · kein Notify/kein TX",
            finish: true
        )
    }
}

'''

replace_between(
    watch_state,
    manager_start,
    manager_end,
    manager + manager_end,
    "replace Build 11 auth manager with Build 12 multi-window GATT manager",
)

root = Path("xDrip Watch App/Views/RootView.swift")

replace_once(
    root,
    'Text("Build 11 Auth-Telemetrie · 6-Min-G7-Suche")',
    'Text("Build 12 Multi-Window GATT · 10-Min-Fenster")',
    "update Build 12 page title",
)

replace_once(
    root,
    'Text("Separater G7-Authentifizierungs-Test")',
    'Text("Separater G7-Multi-Window-Test")',
    "update Build 12 section title",
)

replace_once(
    root,
    'Text("Der Test läuft nur nach Tippen und sucht bis zu 6 Minuten nach einem freien G7. Bereits verbundene G7-Peripherals bleiben geschützt. Beim ersten freien Kandidaten werden 3534/3535/3536/3538 abonniert und genau ein AuthRequest 0x02 auf 3535 gesendet. Eine 0x03-Challenge wird nur protokolliert und NICHT beantwortet.")',
    'Text("Der Test läuft nur nach Tippen und beobachtet bis zu 10 Minuten mehrere G7-Verbindungsfenster. Bereits von CoreBluetooth als verbunden gemeldete G7 bleiben geschützt. Nach einem Remote-Disconnect wird erneut gesucht. Erst wenn eine Verbindung mindestens 250 ms hält, werden ausschließlich Service 3532 und dessen Characteristics gelesen. Es gibt KEIN Notify, KEIN Write und KEIN Dexcom-Protokollkommando.")',
    "update Build 12 explanation",
)

replace_once(
    root,
    'row("Auth-Probe", watchState.g7AuthProbeStatus)',
    'row("G7-Fenster-Test", watchState.g7AuthProbeStatus)',
    "update Build 12 status row",
)

replace_once(
    root,
    'Button(watchState.g7AuthProbeRunning ? "Auth-Probe abbrechen" : "Auth-Probe starten")',
    'Button(watchState.g7AuthProbeRunning ? "Multi-Window-Test abbrechen" : "Multi-Window-Test starten")',
    "update Build 12 button",
)

replace_once(
    root,
    'Text("Während der Probe bitte die Dexcom-Komplikation beobachten. Der Test führt kein Bonding/Pairing durch und startet keinen Reconnect.")',
    'Text("Während des Tests bitte die Dexcom-Komplikation beobachten. Build 12 schreibt nichts zum Sensor, aktiviert keine Notifications, führt kein Bonding/Pairing durch und startet keinen automatischen Background-Reconnect.")',
    "update Build 12 safety footer",
)

print("Build 12 multi-window connection/GATT probe applied successfully.")
