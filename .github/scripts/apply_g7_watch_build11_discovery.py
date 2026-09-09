from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1))


# Build 11 runs AFTER apply_g7_watch_auth_telemetry.py.
# It does not change the conservative authentication payload or stale-BG safety.
# It only makes manual foreground G7 discovery robust enough to span a full
# Dexcom G7 measurement/advertising cycle and adds explicit discovery telemetry.

watch_state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")

replace_once(
    watch_state,
    '''    private var eventLog: [String] = []
    private var connectedAt: Date?
    private var txAt: Date?''',
    '''    private var eventLog: [String] = []
    private var connectedAt: Date?
    private var txAt: Date?
    private let scanWindowSeconds: TimeInterval = 360
    private var scanDeadline: Date?
    private var scanTickTask: DispatchWorkItem?''',
    "add six-minute scan state",
)

old_discovery = '''    private func beginSafeDiscovery() {
        guard running, central.state == .poweredOn else { return }

        let connected = central.retrieveConnectedPeripherals(withServices: [serviceUUID])
        protectedPeripheralIDs = Set(connected.map { $0.identifier })
        addEvent("Bereits verbundene G7 geschützt: \\(protectedPeripheralIDs.count)")

        publish("suche freien G7-Kandidaten…")
        central.scanForPeripherals(
            withServices: [advertisementUUID],
            options: [CBCentralManagerScanOptionAllowDuplicatesKey: false]
        )
        armTimeout(seconds: 20, status: "kein freier G7-Kandidat in 20 s")
    }
'''

new_discovery = '''    private func formatScanRemaining(_ seconds: TimeInterval) -> String {
        let total = max(0, Int(ceil(seconds)))
        return String(format: "%02d:%02d", total / 60, total % 60)
    }

    private func scheduleScanTick() {
        scanTickTask?.cancel()
        guard running, targetPeripheral == nil, let deadline = scanDeadline else { return }

        let remaining = max(0, deadline.timeIntervalSinceNow)
        publish("suche freien G7… \\(formatScanRemaining(remaining)) verbleibend")
        guard remaining > 0 else { return }

        let task = DispatchWorkItem { [weak self] in
            self?.scheduleScanTick()
        }
        scanTickTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + 10.0, execute: task)
    }

    private func beginSafeDiscovery() {
        guard running, central.state == .poweredOn else { return }

        let connected = central.retrieveConnectedPeripherals(withServices: [serviceUUID])
        protectedPeripheralIDs = Set(connected.map { $0.identifier })
        addEvent("Bereits verbundene G7 geschützt: \\(protectedPeripheralIDs.count)")
        if !protectedPeripheralIDs.isEmpty {
            for id in protectedPeripheralIDs {
                addEvent("GESCHÜTZT id=\\(id.uuidString)")
            }
        }

        scanDeadline = Date().addingTimeInterval(scanWindowSeconds)
        addEvent("Scan-Fenster gestartet: 360 s")
        central.scanForPeripherals(
            withServices: [advertisementUUID],
            options: [CBCentralManagerScanOptionAllowDuplicatesKey: false]
        )
        scheduleScanTick()
        armTimeout(seconds: scanWindowSeconds, status: "kein freier G7-Kandidat in 6 Min.")
    }
'''

replace_once(
    watch_state,
    old_discovery,
    new_discovery,
    "replace 20-second discovery with six-minute discovery",
)

replace_once(
    watch_state,
    '''        central.stopScan()
        timeoutTask?.cancel()
        targetPeripheral = peripheral''',
    '''        central.stopScan()
        timeoutTask?.cancel()
        scanTickTask?.cancel()
        scanTickTask = nil
        scanDeadline = nil
        targetPeripheral = peripheral''',
    "stop discovery countdown when candidate selected",
)

replace_once(
    watch_state,
    '''        timeoutTask?.cancel()
        timeoutTask = nil
        captureTask?.cancel()
        captureTask = nil
        central.stopScan()

        guard let peripheral = targetPeripheral''',
    '''        timeoutTask?.cancel()
        timeoutTask = nil
        captureTask?.cancel()
        captureTask = nil
        scanTickTask?.cancel()
        scanTickTask = nil
        scanDeadline = nil
        central.stopScan()

        guard let peripheral = targetPeripheral''',
    "cancel discovery countdown on local completion",
)

replace_once(
    watch_state,
    '''        timeoutTask?.cancel()
        timeoutTask = nil
        captureTask?.cancel()
        captureTask = nil
        central.stopScan()
        addEvent(status)''',
    '''        timeoutTask?.cancel()
        timeoutTask = nil
        captureTask?.cancel()
        captureTask = nil
        scanTickTask?.cancel()
        scanTickTask = nil
        scanDeadline = nil
        central.stopScan()
        addEvent(status)''',
    "cancel discovery countdown on no-connection finish",
)

replace_once(
    watch_state,
    '''        let name = peripheral.name ?? (advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? "")
        guard name.hasPrefix("DX") else { return }
        addEvent("Scan: \\(name) RSSI=\\(RSSI) dBm")
        inspect(peripheral, name: name)''',
    '''        let name = peripheral.name ?? (advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? "")
        guard name.hasPrefix("DX") else { return }

        let advertisedServices = advertisementData[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID] ?? []
        let servicesText = advertisedServices.isEmpty
            ? "keine"
            : advertisedServices.map { $0.uuidString.uppercased() }.joined(separator: ",")
        let connectable = (advertisementData[CBAdvertisementDataIsConnectable] as? NSNumber)?.boolValue
        let connectableText = connectable.map { $0 ? "ja" : "nein" } ?? "unbekannt"

        addEvent("ADV \\(name) RSSI=\\(RSSI) dBm conn=\\(connectableText)")
        addEvent("ADV services=\\(servicesText)")
        addEvent("ADV id=\\(peripheral.identifier.uuidString)")
        inspect(peripheral, name: name)''',
    "add candidate advertisement telemetry",
)

root = Path("xDrip Watch App/Views/RootView.swift")

replace_once(
    root,
    '''Text("Build 10 Auth-Telemetrie · kein automatischer G7-BLE-Pfad")''',
    '''Text("Build 11 Auth-Telemetrie · 6-Min-G7-Suche")''',
    "update Build 11 page title",
)

replace_once(
    root,
    '''Text("Der Test läuft nur nach Tippen, schützt bereits verbundene G7-Peripherals, abonniert 3534/3535/3536/3538 und sendet genau einen AuthRequest 0x02 auf 3535. Drei Sekunden lang werden RX/ACK/Disconnect-Zeiten protokolliert. Eine 0x03-Challenge wird NICHT beantwortet.")''',
    '''Text("Der Test läuft nur nach Tippen und sucht bis zu 6 Minuten nach einem freien G7. Bereits verbundene G7-Peripherals bleiben geschützt. Beim ersten freien Kandidaten werden 3534/3535/3536/3538 abonniert und genau ein AuthRequest 0x02 auf 3535 gesendet. Eine 0x03-Challenge wird nur protokolliert und NICHT beantwortet.")''',
    "update Build 11 explanation",
)

print("Build 11 six-minute G7 discovery patch applied successfully.")
