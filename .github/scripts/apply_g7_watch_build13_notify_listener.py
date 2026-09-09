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


# Build 13 runs AFTER Build 12.
# It is manual/foreground only. Candidate selection is deliberately NAME-INDEPENDENT:
# FEBC advertisement -> G7 service 3532 -> exact 3534/3535/3536/3538 GATT fingerprint.
# Device/local name and CBPeripheral UUID are telemetry only and are never persisted as
# a hard selector, so a replacement G7 with a different name/UUID can be identified.
# Build 13 performs BLE notification subscriptions (CCCD) only. It never calls
# writeValue(), never sends a Dexcom application-protocol command, and never performs
# pairing/bonding/session/calibration operations.

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
    private let notifySetupTimeoutSeconds: TimeInterval = 5
    private let passiveListenSeconds: TimeInterval = 20
    private let captureAfterFirstRXSeconds: TimeInterval = 3

    private let onUpdate: UpdateHandler
    private var central: CBCentralManager!
    private var targetPeripheral: CBPeripheral?
    private var protectedPeripheralIDs = Set<UUID>()
    private var expectedCharacteristics: [CBUUID: CBCharacteristic] = [:]

    private var running = false
    private var localDisconnectRequested = false
    private var finishAfterLocalDisconnect = false
    private var retryAfterLocalDisconnect = false
    private var pendingFinalStatus = ""

    private var lastDeviceName = ""
    private var latestRXHex = ""
    private var eventLog: [String] = []
    private var connectedAt: Date?
    private var overallDeadline: Date?
    private var attemptCount = 0

    private var pendingNotifyUUIDs = Set<CBUUID>()
    private var enabledNotifyUUIDs = Set<CBUUID>()
    private var failedNotifyUUIDs = Set<CBUUID>()
    private var rxCounts: [CBUUID: Int] = [:]
    private var firstRXAt: Date?

    private var overallTimeoutTask: DispatchWorkItem?
    private var statusTickTask: DispatchWorkItem?
    private var retryTask: DispatchWorkItem?
    private var connectTimeoutTask: DispatchWorkItem?
    private var qualificationTask: DispatchWorkItem?
    private var gattTimeoutTask: DispatchWorkItem?
    private var notifySetupTimeoutTask: DispatchWorkItem?
    private var passiveListenTask: DispatchWorkItem?
    private var rxFinishTask: DispatchWorkItem?

    init(onUpdate: @escaping UpdateHandler) {
        self.onUpdate = onUpdate
        super.init()
        // No restore identifier: this manual diagnostic must not be resurrected by watchOS.
        central = CBCentralManager(delegate: self, queue: .main, options: nil)
    }

    private var rxTotal: Int {
        rxCounts.values.reduce(0, +)
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
        latestRXHex = ""
        eventLog.removeAll()
        connectedAt = nil
        overallDeadline = nil
        attemptCount = 0
        resetPerAttemptData()

        addEvent("Build13 gestartet · FEBC/GATT-Match · Name ignoriert")
        addEvent("Nur CCCD Notify · Dexcom-App-TX = 0")
        publish("warte auf Bluetooth…")

        if central.state == .poweredOn {
            beginObservationWindow()
        }
    }

    func stop(userInitiated: Bool) {
        guard running else { return }
        addEvent(userInitiated ? "Benutzerabbruch" : "Notify-Test stop")
        if let peripheral = targetPeripheral,
           peripheral.state == .connected || peripheral.state == .connecting {
            requestLocalDisconnect(
                finalStatus: userInitiated ? "Notify-Test abgebrochen" : "Notify-Test beendet",
                finish: true
            )
        } else {
            finishWithoutConnection(userInitiated ? "Notify-Test abgebrochen" : "Notify-Test beendet")
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

    private func hex(_ data: Data) -> String {
        data.map { String(format: "%02X", $0) }.joined()
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
        if eventLog.count > 100 {
            eventLog.removeFirst(eventLog.count - 100)
        }
    }

    private func publish(_ status: String, finished: Bool = false) {
        onUpdate(status, lastDeviceName, latestRXHex, false, eventLog.joined(separator: "\n"), finished)
    }

    private func resetPerAttemptData() {
        expectedCharacteristics.removeAll()
        pendingNotifyUUIDs.removeAll()
        enabledNotifyUUIDs.removeAll()
        failedNotifyUUIDs.removeAll()
        rxCounts.removeAll()
        firstRXAt = nil
        latestRXHex = ""
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
        notifySetupTimeoutTask?.cancel()
        notifySetupTimeoutTask = nil
        passiveListenTask?.cancel()
        passiveListenTask = nil
        rxFinishTask?.cancel()
        rxFinishTask = nil
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
        addEvent("Notify-Multi-Window gestartet: 600 s")
        armOverallTimeout()
        scheduleStatusTick()
        startScan()
    }

    private func armOverallTimeout() {
        overallTimeoutTask?.cancel()
        let task = DispatchWorkItem { [weak self] in
            guard let self, self.running else { return }
            self.addEvent("10-Min-Fenster beendet · Attempts=\(self.attemptCount) · RX=\(self.rxTotal)")
            if let peripheral = self.targetPeripheral,
               peripheral.state == .connected || peripheral.state == .connecting {
                self.requestLocalDisconnect(
                    finalStatus: "10-Min-Notify-Test beendet · kein spontanes RX",
                    finish: true
                )
            } else {
                self.finishWithoutConnection("10-Min-Notify-Test beendet · kein spontanes RX")
            }
        }
        overallTimeoutTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + testWindowSeconds, execute: task)
    }

    private func scheduleStatusTick() {
        statusTickTask?.cancel()
        guard running else { return }

        let remaining = remainingSeconds()
        publish("Notify-Test · \(formatRemaining(remaining)) · Attempts \(attemptCount) · RX \(rxTotal)")

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
        addEvent("SCAN FEBC aktiv · Name kein Filter · Rest \(formatRemaining(remainingSeconds()))")
        publish("suche FEBC-G7-Fenster… \(formatRemaining(remainingSeconds()))")
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
        resetPerAttemptData()

        let remaining = remainingSeconds()
        guard remaining > 0 else {
            finishWithoutConnection("10-Min-Notify-Test beendet · kein spontanes RX")
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

    private func armNotifySetupTimeout(for peripheral: CBPeripheral) {
        notifySetupTimeoutTask?.cancel()
        let task = DispatchWorkItem { [weak self, weak peripheral] in
            guard let self, self.running,
                  let peripheral,
                  self.targetPeripheral?.identifier == peripheral.identifier else { return }
            let waiting = self.pendingNotifyUUIDs.map { self.shortUUID($0) }.sorted().joined(separator: ",")
            self.addEvent("NOTIFY setup timeout · offen=\(waiting)")
            self.requestLocalDisconnect(finalStatus: "Notify-Setup-Timeout", retry: true)
        }
        notifySetupTimeoutTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + notifySetupTimeoutSeconds, execute: task)
    }

    private func armPassiveListen(for peripheral: CBPeripheral) {
        passiveListenTask?.cancel()

        if rxTotal > 0 {
            scheduleFinishAfterRX(for: peripheral)
            return
        }

        addEvent("NOTIFY 4/4 aktiv · passiv \(Int(passiveListenSeconds)) s · Dexcom-TX=0")
        publish("Notify 4/4 aktiv · warte passiv auf RX…")

        let task = DispatchWorkItem { [weak self, weak peripheral] in
            guard let self, self.running,
                  let peripheral,
                  self.targetPeripheral?.identifier == peripheral.identifier else { return }
            self.addEvent("20 s Notify ohne RX")
            self.requestLocalDisconnect(finalStatus: "Notify aktiv · 20 s ohne RX", retry: true)
        }
        passiveListenTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + passiveListenSeconds, execute: task)
    }

    private func scheduleFinishAfterRX(for peripheral: CBPeripheral) {
        guard rxFinishTask == nil else { return }
        passiveListenTask?.cancel()
        passiveListenTask = nil

        addEvent("SPONTAN-RX erkannt · sammle noch \(Int(captureAfterFirstRXSeconds)) s")
        publish("Spontane G7-Notify-Daten empfangen · RX \(rxTotal)")

        let task = DispatchWorkItem { [weak self, weak peripheral] in
            guard let self, self.running,
                  let peripheral,
                  self.targetPeripheral?.identifier == peripheral.identifier else { return }
            self.requestLocalDisconnect(
                finalStatus: "Spontane Notify-Daten empfangen · \(self.rxTotal) Pakete · Dexcom-TX 0",
                finish: true
            )
        }
        rxFinishTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + captureAfterFirstRXSeconds, execute: task)
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
        notifySetupTimeoutTask?.cancel()
        notifySetupTimeoutTask = nil
        passiveListenTask?.cancel()
        passiveListenTask = nil
        rxFinishTask?.cancel()
        rxFinishTask = nil

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

    private func finishRemoteAfterRX(_ status: String) {
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

        let advertisedServices = advertisementData[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID] ?? []
        let connectable = (advertisementData[CBAdvertisementDataIsConnectable] as? NSNumber)?.boolValue
        let name = peripheral.name ?? (advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? "")
        let displayName = name.isEmpty ? "FEBC/ohne Namen" : name
        let servicesText = advertisedServices.isEmpty
            ? "nicht geliefert (Scanfilter FEBC)"
            : advertisedServices.map { $0.uuidString.uppercased() }.joined(separator: ",")
        let connectableText = connectable.map { $0 ? "ja" : "nein" } ?? "unbekannt"

        // Name-independent identity: scanForPeripherals is already filtered to FEBC.
        // If service UUIDs are present in the callback, require FEBC as an extra check.
        if !advertisedServices.isEmpty && !advertisedServices.contains(advertisementUUID) {
            addEvent("ADV ignoriert · FEBC fehlt trotz Scanfilter")
            return
        }

        addEvent("ADV \(displayName) RSSI=\(RSSI) dBm conn=\(connectableText)")
        addEvent("MATCH=FEBC · Name nur Anzeige")
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
        lastDeviceName = displayName
        connectedAt = nil
        localDisconnectRequested = false
        finishAfterLocalDisconnect = false
        retryAfterLocalDisconnect = false
        pendingFinalStatus = ""
        resetPerAttemptData()
        attemptCount += 1

        addEvent("Attempt #\(attemptCount) · CONNECT \(displayName)")
        publish("FEBC-Kandidat · verbinde · Name nicht als ID verwendet")
        central.connect(peripheral, options: nil)
        armConnectTimeout(for: peripheral)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        guard running, targetPeripheral?.identifier == peripheral.identifier else { return }

        connectTimeoutTask?.cancel()
        connectTimeoutTask = nil
        connectedAt = Date()
        let liveName = peripheral.name ?? ""
        if !liveName.isEmpty { lastDeviceName = liveName }

        addEvent("CONNECTED #\(attemptCount) \(lastDeviceName)")
        addEvent("Connected time: \(timestamp(connectedAt!))")
        publish("verbunden · 250 ms Stabilitätstest · noch kein Notify")

        qualificationTask?.cancel()
        let task = DispatchWorkItem { [weak self, weak peripheral] in
            guard let self, self.running,
                  let peripheral,
                  self.targetPeripheral?.identifier == peripheral.identifier,
                  peripheral.state == .connected else { return }

            self.addEvent("Connection ≥250 ms · discoverServices 3532")
            self.publish("≥250 ms stabil · prüfe G7-Service 3532")
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

        cancelPerAttemptTasks()

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
        } else if rxTotal > 0 {
            finishRemoteAfterRX("Remote-Disconnect nach spontanen RX · \(rxTotal) Pakete · Dexcom-TX 0")
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
            requestLocalDisconnect(finalStatus: "Kein G7-Service 3532 · verwerfe Kandidat", retry: true)
            return
        }

        addEvent("G7-FINGERPRINT Stufe 2: Service 3532")
        publish("3532 bestätigt · prüfe 3534/3535/3536/3538")
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

        let byUUID = Dictionary(uniqueKeysWithValues: discovered.map { ($0.uuid, $0) })
        let expectedFound = expectedChannelUUIDs.filter { byUUID[$0] != nil }
        addEvent("G7-FINGERPRINT: \(expectedFound.count)/4 erwartete Channels")

        guard expectedFound.count == expectedChannelUUIDs.count else {
            requestLocalDisconnect(finalStatus: "GATT-Fingerprint unvollständig · kein G7-Match", retry: true)
            return
        }

        expectedCharacteristics = byUUID.filter { expectedChannelUUIDs.contains($0.key) }
        pendingNotifyUUIDs = Set(expectedChannelUUIDs)
        enabledNotifyUUIDs.removeAll()
        failedNotifyUUIDs.removeAll()

        addEvent("G7-MATCH bestätigt · FEBC + 3532 + 4/4 · Name irrelevant")
        publish("G7-Match bestätigt · aktiviere Notify 3534/35/36/38")

        for uuid in expectedChannelUUIDs {
            guard let characteristic = expectedCharacteristics[uuid] else { continue }
            guard characteristic.properties.contains(.notify) || characteristic.properties.contains(.indicate) else {
                pendingNotifyUUIDs.remove(uuid)
                failedNotifyUUIDs.insert(uuid)
                addEvent("SUBSCRIBE \(shortUUID(uuid)) nicht unterstützt")
                continue
            }
            addEvent("SUBSCRIBE \(shortUUID(uuid)) · CCCD only")
            peripheral.setNotifyValue(true, for: characteristic)
        }

        if !failedNotifyUUIDs.isEmpty {
            requestLocalDisconnect(finalStatus: "Nicht alle G7-Channels unterstützen Notify", retry: true)
            return
        }

        armNotifySetupTimeout(for: peripheral)
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?) {
        guard running, targetPeripheral?.identifier == peripheral.identifier else { return }
        guard expectedChannelUUIDs.contains(characteristic.uuid) else { return }

        pendingNotifyUUIDs.remove(characteristic.uuid)

        if let error {
            failedNotifyUUIDs.insert(characteristic.uuid)
            addEvent("NOTIFY \(shortUUID(characteristic.uuid)) ERROR=\(error.localizedDescription)")
        } else if characteristic.isNotifying {
            enabledNotifyUUIDs.insert(characteristic.uuid)
            addEvent("NOTIFY \(shortUUID(characteristic.uuid)) ON")
        } else {
            failedNotifyUUIDs.insert(characteristic.uuid)
            addEvent("NOTIFY \(shortUUID(characteristic.uuid)) OFF/unerwartet")
        }

        publish("Notify \(enabledNotifyUUIDs.count)/4 · offen \(pendingNotifyUUIDs.count) · RX \(rxTotal)")

        guard pendingNotifyUUIDs.isEmpty else { return }

        notifySetupTimeoutTask?.cancel()
        notifySetupTimeoutTask = nil

        guard failedNotifyUUIDs.isEmpty, enabledNotifyUUIDs.count == expectedChannelUUIDs.count else {
            requestLocalDisconnect(finalStatus: "Notify-Setup nicht 4/4", retry: true)
            return
        }

        armPassiveListen(for: peripheral)
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard running, targetPeripheral?.identifier == peripheral.identifier else { return }
        guard expectedChannelUUIDs.contains(characteristic.uuid) else { return }

        if let error {
            addEvent("RX \(shortUUID(characteristic.uuid)) ERROR=\(error.localizedDescription)")
            publish("Notify RX-Fehler auf \(shortUUID(characteristic.uuid))")
            return
        }

        guard let data = characteristic.value else {
            addEvent("RX \(shortUUID(characteristic.uuid)) value=nil")
            return
        }

        let count = (rxCounts[characteristic.uuid] ?? 0) + 1
        rxCounts[characteristic.uuid] = count
        let packetHex = hex(data)
        latestRXHex = "\(shortUUID(characteristic.uuid)) #\(count) \(packetHex)"
        addEvent("RX \(shortUUID(characteristic.uuid)) #\(count) len=\(data.count) HEX=\(packetHex)")

        if firstRXAt == nil {
            firstRXAt = Date()
            addEvent("ERSTER SPONTAN-RX · nach \(elapsedMS(from: connectedAt))")
        }

        publish("Spontan-RX \(rxTotal) · letzter \(shortUUID(characteristic.uuid)) · Dexcom-TX 0")
        scheduleFinishAfterRX(for: peripheral)
    }
}

'''

replace_between(
    watch_state,
    manager_start,
    manager_end,
    manager + manager_end,
    "replace Build 12 GATT manager with Build 13 name-independent Notify listener",
)

root = Path("xDrip Watch App/Views/RootView.swift")

replace_once(
    root,
    'Text("Build 12 Multi-Window GATT · 10-Min-Fenster")',
    'Text("Build 13 Notify Listener · name-unabhängig")',
    "update Build 13 page title",
)

replace_once(
    root,
    'Text("Separater G7-Multi-Window-Test")',
    'Text("Separater G7-Notify-Test")',
    "update Build 13 section title",
)

replace_once(
    root,
    'Text("Der Test läuft nur nach Tippen und beobachtet bis zu 10 Minuten mehrere G7-Verbindungsfenster. Bereits von CoreBluetooth als verbunden gemeldete G7 bleiben geschützt. Nach einem Remote-Disconnect wird erneut gesucht. Erst wenn eine Verbindung mindestens 250 ms hält, werden ausschließlich Service 3532 und dessen Characteristics gelesen. Es gibt KEIN Notify, KEIN Write und KEIN Dexcom-Protokollkommando.")',
    'Text("Der Test läuft nur nach Tippen und beobachtet bis zu 10 Minuten mehrere Verbindungsfenster. Ein Sensorname wie DXCMD2/DXCMam wird NICHT zur Identifikation verwendet. Kandidaten werden über FEBC und danach über den G7-GATT-Fingerprint 3532 + 3534/3535/3536/3538 bestätigt. Erst dann werden diese vier Channels per BLE-Notify abonniert. Es gibt KEIN Dexcom-Protokoll-TX, kein AuthRequest, kein Pairing/Bonding und keine Session-/Kalibrierungsaktion.")',
    "update Build 13 explanation",
)

replace_once(
    root,
    'row("G7-Fenster-Test", watchState.g7AuthProbeStatus)',
    'row("Notify-Test", watchState.g7AuthProbeStatus)',
    "update Build 13 status row",
)

replace_once(
    root,
    'Button(watchState.g7AuthProbeRunning ? "Multi-Window-Test abbrechen" : "Multi-Window-Test starten")',
    'Button(watchState.g7AuthProbeRunning ? "Notify-Test abbrechen" : "Notify-Test starten")',
    "update Build 13 button",
)

replace_once(
    root,
    'Text("Während des Tests bitte die Dexcom-Komplikation beobachten. Build 12 schreibt nichts zum Sensor, aktiviert keine Notifications, führt kein Bonding/Pairing durch und startet keinen automatischen Background-Reconnect.")',
    'Text("Während des Tests bitte die Dexcom-Komplikation beobachten. Build 13 verändert nur die BLE-CCCD-Subscription für die kurzzeitige Testverbindung. Es wird kein Dexcom-Anwendungsprotokoll geschrieben und kein automatischer Background-Reconnect gestartet. Der Sensorname ist reine Telemetrie und kein Match-Kriterium.")',
    "update Build 13 safety footer",
)

print("Build 13 name-independent passive Notify listener applied successfully.")
