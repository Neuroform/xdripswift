from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1))


watch_state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")

# Keep the BLE owner alive as a process-wide singleton. SwiftUI state subscribes to it, but the
# CBCentralManager itself is no longer owned by a visible view/model lifetime.
replace_once(
    watch_state,
    '''    private var directG7Manager: G7DirectBLEManager?''',
    '''    private let directG7Manager = G7DirectBLEManager.shared''',
    "WatchStateModel singleton manager",
)

replace_once(
    watch_state,
    '''        directG7Manager = G7DirectBLEManager(
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
        directG7Manager?.start()''',
    '''        directG7Manager.setHandlers(
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
        directG7Manager.start()''',
    "WatchStateModel singleton handler binding",
)

# Persist the final Watch-state write time so a later foreground inspection can distinguish
# BLE receipt from Widget/App Group propagation.
replace_once(
    watch_state,
    '''        // Persist immediately for the WidgetKit complication and ask only the xDrip complication
        // timeline to reload. WidgetKit still controls the exact render timing.
        updateComplicationData()''',
    '''        // Persist immediately for the WidgetKit complication and ask only the xDrip complication
        // timeline to reload. WidgetKit still controls the exact render timing.
        updateComplicationData()
        UserDefaults.standard.set(Date().timeIntervalSince1970, forKey: G7DirectBLEManager.DiagnosticKey.lastWidgetWrite)''',
    "WatchStateModel persistent widget timestamp",
)

# Expose persisted diagnostic timestamps through the Watch state. They intentionally read from
# UserDefaults so the values survive process suspension/termination and can be inspected later.
replace_once(
    watch_state,
    '''    @Published var directG7ReadingCount: Int = 0''',
    '''    @Published var directG7ReadingCount: Int = 0

    var directG7LastBLEWake: Date? { G7DirectBLEManager.diagnosticDate(G7DirectBLEManager.DiagnosticKey.lastBLEWake) }
    var directG7LastRestore: Date? { G7DirectBLEManager.diagnosticDate(G7DirectBLEManager.DiagnosticKey.lastRestore) }
    var directG7LastDisconnect: Date? { G7DirectBLEManager.diagnosticDate(G7DirectBLEManager.DiagnosticKey.lastDisconnect) }
    var directG7LastScanStart: Date? { G7DirectBLEManager.diagnosticDate(G7DirectBLEManager.DiagnosticKey.lastScanStart) }
    var directG7LastAdvertisement: Date? { G7DirectBLEManager.diagnosticDate(G7DirectBLEManager.DiagnosticKey.lastAdvertisement) }
    var directG7LastConnect: Date? { G7DirectBLEManager.diagnosticDate(G7DirectBLEManager.DiagnosticKey.lastConnect) }
    var directG7LastAuth: Date? { G7DirectBLEManager.diagnosticDate(G7DirectBLEManager.DiagnosticKey.lastAuth) }
    var directG7LastPacket: Date? { G7DirectBLEManager.diagnosticDate(G7DirectBLEManager.DiagnosticKey.lastPacket) }
    var directG7LastWidgetWrite: Date? { G7DirectBLEManager.diagnosticDate(G7DirectBLEManager.DiagnosticKey.lastWidgetWrite) }''',
    "WatchStateModel diagnostic properties",
)

# Replace the prototype manager with a low-power/background-oriented version. Important changes:
# - process-wide singleton created before the visible Watch view is needed
# - no DispatchQueue delayed reconnect and no app-owned authentication timeout
# - persistent successful peripheral ID is tried first
# - state-restored peripherals are adopted immediately
# - scans are registered directly with CoreBluetooth after a disconnect/failure
# - durable lifecycle timestamps allow post-suspension diagnosis
manager_start = '''private final class G7DirectBLEManager: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
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
    }'''

manager_replacement = '''final class G7DirectBLEManager: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    static let shared = G7DirectBLEManager()

    enum DiagnosticKey {
        static let knownPeripheralID = "xDrip.G7.Direct.knownPeripheralID"
        static let lastBLEWake = "xDrip.G7.Direct.lastBLEWake"
        static let lastRestore = "xDrip.G7.Direct.lastRestore"
        static let lastDisconnect = "xDrip.G7.Direct.lastDisconnect"
        static let lastScanStart = "xDrip.G7.Direct.lastScanStart"
        static let lastAdvertisement = "xDrip.G7.Direct.lastAdvertisement"
        static let lastConnect = "xDrip.G7.Direct.lastConnect"
        static let lastAuth = "xDrip.G7.Direct.lastAuth"
        static let lastPacket = "xDrip.G7.Direct.lastPacket"
        static let lastWidgetWrite = "xDrip.G7.Direct.lastWidgetWrite"
    }

    static func diagnosticDate(_ key: String) -> Date? {
        let value = UserDefaults.standard.double(forKey: key)
        return value > 0 ? Date(timeIntervalSince1970: value) : nil
    }

    private let advertisementUUID = CBUUID(string: "FEBC")
    private let serviceUUID = CBUUID(string: "F8083532-849E-531C-C594-30F1F86A4EA5")
    private let controlUUID = CBUUID(string: "F8083534-849E-531C-C594-30F1F86A4EA5")
    private let authUUID = CBUUID(string: "F8083535-849E-531C-C594-30F1F86A4EA5")

    private var onState: ((String, String, Bool) -> Void)?
    private var onReading: ((DirectG7Reading) -> Void)?
    private var bufferedReading: DirectG7Reading?

    private var central: CBCentralManager!
    private var targetPeripheral: CBPeripheral?
    private var enabled = false
    private var authenticated = false
    private var pendingGlucosePacket: Data?
    private var lastDeviceName = ""

    private override init() {
        super.init()

        // Creating this manager early is important for CoreBluetooth state restoration. CoreBluetooth,
        // rather than an app-owned timer, is responsible for waking/reconnecting the process.
        central = CBCentralManager(
            delegate: self,
            queue: .main,
            options: [CBCentralManagerOptionRestoreIdentifierKey: "xDrip.G7.Direct.Central"]
        )
    }

    func setHandlers(
        onState: @escaping (String, String, Bool) -> Void,
        onReading: @escaping (DirectG7Reading) -> Void
    ) {
        self.onState = onState
        self.onReading = onReading
        onState(currentStatusText(), lastDeviceName, authenticated)

        if let bufferedReading {
            self.bufferedReading = nil
            onReading(bufferedReading)
        }
    }

    func start() {
        enabled = true
        if central.state == .poweredOn {
            beginDiscovery()
        }
    }

    private func stamp(_ key: String) {
        UserDefaults.standard.set(Date().timeIntervalSince1970, forKey: key)
    }

    private var lastPublishedStatus = "initialisiert"

    private func currentStatusText() -> String {
        lastPublishedStatus
    }

    private func publish(_ status: String) {
        lastPublishedStatus = status
        onState?(status, lastDeviceName, authenticated)
    }

    private func emit(_ reading: DirectG7Reading) {
        stamp(DiagnosticKey.lastPacket)
        if let targetPeripheral {
            UserDefaults.standard.set(targetPeripheral.identifier.uuidString, forKey: DiagnosticKey.knownPeripheralID)
        }

        if let onReading {
            onReading(reading)
        } else {
            bufferedReading = reading
        }
    }

    private func beginDiscovery() {
        guard enabled, central.state == .poweredOn, targetPeripheral == nil else { return }

        publish("suche G7…")

        // First ask CoreBluetooth for the peripheral that last delivered a valid G7 glucose packet.
        // This avoids depending on a fresh scan after process restoration whenever the system still
        // knows that peripheral.
        if let identifierString = UserDefaults.standard.string(forKey: DiagnosticKey.knownPeripheralID),
           let identifier = UUID(uuidString: identifierString),
           let known = central.retrievePeripherals(withIdentifiers: [identifier]).first {
            inspect(known)
            return
        }

        let connected = central.retrieveConnectedPeripherals(withServices: [serviceUUID])
        if let peripheral = connected.first(where: { ($0.name ?? "").hasPrefix("DX") }) ?? connected.first {
            inspect(peripheral)
            return
        }

        stamp(DiagnosticKey.lastScanStart)
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

        if peripheral.state == .connected {
            publish("G7 bereits verbunden; prüfe Service…")
            peripheral.discoverServices([serviceUUID])
        } else {
            publish("G7 gefunden; verbinde…")
            central.connect(peripheral, options: nil)
        }
    }

    private func reconnectImmediately() {
        guard enabled, central.state == .poweredOn, targetPeripheral == nil else { return }
        // Do not use DispatchQueue.asyncAfter here. A delayed app timer is unreliable when watchOS
        // suspends xDrip, especially with Low Power Mode enabled. Register the next CoreBluetooth
        // operation immediately and let the system wake us for the BLE event.
        beginDiscovery()
    }'''

replace_once(watch_state, manager_start, manager_replacement, "G7 manager low-power core")

# State restoration: adopt all useful restored state immediately. If no restored peripheral is
# supplied, centralManagerDidUpdateState will re-register discovery once Bluetooth is powered on.
old_restore = '''    func centralManager(_ central: CBCentralManager, willRestoreState dict: [String : Any]) {
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
    }'''

new_restore = '''    func centralManager(_ central: CBCentralManager, willRestoreState dict: [String : Any]) {
        enabled = true
        stamp(DiagnosticKey.lastRestore)

        if let peripherals = dict[CBCentralManagerRestoredStatePeripheralsKey] as? [CBPeripheral],
           let peripheral = peripherals.first(where: { $0.state == .connected }) ?? peripherals.first {
            targetPeripheral = peripheral
            peripheral.delegate = self
            lastDeviceName = peripheral.name ?? "unbekannt"
            authenticated = false
            publish("G7 BLE-State wiederhergestellt")

            if peripheral.state == .connected {
                peripheral.discoverServices([serviceUUID])
            } else {
                central.connect(peripheral, options: nil)
            }
            return
        }

        // A restored scan has no peripheral yet. Do not schedule an app timer; once the manager is
        // powered on, beginDiscovery() registers the BLE scan directly with CoreBluetooth.
        publish("BLE-State wiederhergestellt; warte auf G7…")
        if central.state == .poweredOn {
            beginDiscovery()
        }
    }'''

replace_once(watch_state, old_restore, new_restore, "G7 state restoration")

# Persist lifecycle events and remove timer-based reconnect/auth logic.
replace_once(
    watch_state,
    '''        case .poweredOn:
            publish("Bluetooth ein")
            beginDiscovery()''',
    '''        case .poweredOn:
            stamp(DiagnosticKey.lastBLEWake)
            publish("Bluetooth ein")
            beginDiscovery()''',
    "G7 Bluetooth wake timestamp",
)

replace_once(
    watch_state,
    '''        let name = peripheral.name ?? (advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? "")
        guard name.hasPrefix("DX") else { return }
        inspect(peripheral)''',
    '''        let name = peripheral.name ?? (advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? "")
        guard name.hasPrefix("DX") else { return }
        stamp(DiagnosticKey.lastAdvertisement)
        inspect(peripheral)''',
    "G7 advertisement timestamp",
)

replace_once(
    watch_state,
    '''    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        lastDeviceName = peripheral.name ?? lastDeviceName
        publish("BLE verbunden; prüfe G7-Service…")
        armAuthenticationTimeout(for: peripheral)
        peripheral.discoverServices([serviceUUID])
    }''',
    '''    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        lastDeviceName = peripheral.name ?? lastDeviceName
        stamp(DiagnosticKey.lastConnect)
        publish("BLE verbunden; prüfe G7-Service…")
        peripheral.discoverServices([serviceUUID])
    }''',
    "G7 connect without auth timer",
)

replace_once(
    watch_state,
    '''    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        if targetPeripheral?.identifier == peripheral.identifier {
            targetPeripheral = nil
        }
        authenticated = false
        publish("Verbindung fehlgeschlagen; neuer Versuch…")
        scheduleReconnect()
    }''',
    '''    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        if targetPeripheral?.identifier == peripheral.identifier {
            targetPeripheral = nil
        }
        authenticated = false

        // A remembered peripheral may have rotated away. Clear it after a failed connection so the
        // next attempt can fall back to service-based discovery rather than looping on stale state.
        if UserDefaults.standard.string(forKey: DiagnosticKey.knownPeripheralID) == peripheral.identifier.uuidString {
            UserDefaults.standard.removeObject(forKey: DiagnosticKey.knownPeripheralID)
        }

        publish("Verbindung fehlgeschlagen; suche sofort weiter…")
        reconnectImmediately()
    }''',
    "G7 immediate reconnect after failure",
)

replace_once(
    watch_state,
    '''    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        guard targetPeripheral?.identifier == peripheral.identifier else { return }

        authTimeoutTask?.cancel()
        authTimeoutTask = nil
        targetPeripheral = nil
        authenticated = false
        pendingGlucosePacket = nil
        publish("G7 getrennt; verbinde erneut…")
        scheduleReconnect()
    }''',
    '''    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        guard targetPeripheral?.identifier == peripheral.identifier else { return }

        stamp(DiagnosticKey.lastDisconnect)
        targetPeripheral = nil
        authenticated = false
        pendingGlucosePacket = nil
        publish("G7 getrennt; warte auf nächsten BLE-Zyklus…")
        reconnectImmediately()
    }''',
    "G7 immediate reconnect after disconnect",
)

replace_once(
    watch_state,
    '''            if authenticated {
                authTimeoutTask?.cancel()
                authTimeoutTask = nil
                publish("Dexcom-authentifiziert · Direct aktiv")''',
    '''            if authenticated {
                stamp(DiagnosticKey.lastAuth)
                publish("Dexcom-authentifiziert · Direct aktiv")''',
    "G7 auth timestamp",
)

replace_once(
    watch_state,
    '''                    self.pendingGlucosePacket = nil
                    onReading(reading)''',
    '''                    self.pendingGlucosePacket = nil
                    emit(reading)''',
    "G7 buffered read emission",
)

replace_once(
    watch_state,
    '''        publish("Direct BG \\(Int(reading.glucoseMgDl)) mg/dL")
        onReading(reading)''',
    '''        publish("Direct BG \\(Int(reading.glucoseMgDl)) mg/dL")
        emit(reading)''',
    "G7 direct read emission",
)

# Instantiate the CoreBluetooth singleton at Watch app construction time, before the visible
# navigation hierarchy matters. This gives watchOS a stable restoration owner.
watch_app = Path("xDrip Watch App/xDripWatchApp.swift")
replace_once(
    watch_app,
    '''struct xDrip_Watch_AppApp: App {
    @StateObject var watchState = WatchStateModel()
    
    var body: some Scene {''',
    '''struct xDrip_Watch_AppApp: App {
    @StateObject var watchState = WatchStateModel()

    init() {
        G7DirectBLEManager.shared.start()
    }
    
    var body: some Scene {''',
    "Watch app early G7 singleton startup",
)

# Extend the direct status page with persistent timestamps. These are intentionally compact and
# are primarily for the next several-hour Low Power Mode test.
root = Path("xDrip Watch App/Views/RootView.swift")
replace_once(
    root,
    '''                row("Direct-Werte", "\\(watchState.directG7ReadingCount)")

                Text("D = Direct-G7. Wenn Direct ausfällt, darf ein neuerer iPhone-Wert automatisch übernehmen.")''',
    '''                row("Direct-Werte", "\\(watchState.directG7ReadingCount)")

                Divider()
                Text("Background-Diagnose")
                    .font(.caption)
                    .fontWeight(.semibold)

                diagnosticRow("BLE-Wake", watchState.directG7LastBLEWake)
                diagnosticRow("State-Restore", watchState.directG7LastRestore)
                diagnosticRow("Disconnect", watchState.directG7LastDisconnect)
                diagnosticRow("Scan-Start", watchState.directG7LastScanStart)
                diagnosticRow("Advertisement", watchState.directG7LastAdvertisement)
                diagnosticRow("Connect", watchState.directG7LastConnect)
                diagnosticRow("Auth", watchState.directG7LastAuth)
                diagnosticRow("0x4E", watchState.directG7LastPacket)
                diagnosticRow("Widget-Write", watchState.directG7LastWidgetWrite)

                Text("D = Direct-G7. Wenn Direct ausfällt, darf ein neuerer iPhone-Wert automatisch übernehmen.")''',
    "G7 status background diagnostics rows",
)

replace_once(
    root,
    '''    @ViewBuilder
    private func row(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption)
        }
    }
}''',
    '''    @ViewBuilder
    private func row(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption)
        }
    }

    @ViewBuilder
    private func diagnosticRow(_ label: String, _ date: Date?) -> some View {
        row(label, date?.formatted(date: .omitted, time: .standard) ?? "—")
    }
}''',
    "G7 status diagnostic row helper",
)

print("Personal G7 Watch low-power/background hardening patch applied successfully.")
