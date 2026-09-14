from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Build 41 is applied AFTER accepted Build 37.
# Scope is intentionally narrow: instrument only the existing G7DirectBLEManager lifecycle.
# No RootView, WatchConnectivity, complication provider, widget registration or widget view changes.

state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")

# Persistent rolling trace stored in the existing Watch app group.
replace_once(
    state,
    '''    private var reconnectTask: DispatchWorkItem?
    private var lastDeviceName = ""''',
    '''    private var reconnectTask: DispatchWorkItem?
    private var lastDeviceName = ""

    // Build 41: persistent BLE lifecycle trace. This deliberately lives inside the existing
    // direct-G7 manager so no Watch UI or complication code needs to change.
    private let lifecycleTraceKey41 = "xdrip.g7Direct.lifecycleTrace41"

    private func trace41(_ event: String) {
        guard let defaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else { return }
        var events = defaults.stringArray(forKey: lifecycleTraceKey41) ?? []
        events.append("\\(Date().timeIntervalSince1970)|\\(event)")
        if events.count > 80 {
            events.removeFirst(events.count - 80)
        }
        defaults.set(events, forKey: lifecycleTraceKey41)
    }

    private func traceTail41() -> String {
        guard let defaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else { return "no-app-group" }
        let events = defaults.stringArray(forKey: lifecycleTraceKey41) ?? []
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "HH:mm:ss"

        return events.suffix(8).map { item in
            let parts = item.split(separator: "|", maxSplits: 1).map(String.init)
            guard parts.count == 2, let ts = Double(parts[0]) else { return item }
            return "\\(formatter.string(from: Date(timeIntervalSince1970: ts))) \\(parts[1])"
        }.joined(separator: " · ")
    }''',
    "Build41 lifecycle trace helpers",
)

# Existing status page already displays directG7Status. Include the persistent tail there,
# avoiding any RootView modification.
replace_once(
    state,
    '''    private func publish(_ status: String) {
        onState(status, lastDeviceName, authenticated)
    }''',
    '''    private func publish(_ status: String) {
        onState("L41 \\(status) | \\(traceTail41())", lastDeviceName, authenticated)
    }''',
    "Build41 publish trace tail",
)

replace_once(
    state,
    '''    func start() {
        enabled = true
        if central.state == .poweredOn {''',
    '''    func start() {
        enabled = true
        trace41("START central=\\(central.state.rawValue)")
        if central.state == .poweredOn {''',
    "Build41 start marker",
)

replace_once(
    state,
    '''        publish("suche G7…")

        let connected = central.retrieveConnectedPeripherals(withServices: [serviceUUID])''',
    '''        trace41("SCAN begin")
        publish("suche G7…")

        let connected = central.retrieveConnectedPeripherals(withServices: [serviceUUID])''',
    "Build41 scan marker",
)

replace_once(
    state,
    '''        lastDeviceName = peripheral.name ?? "unbekannt"
        authenticated = false
        pendingGlucosePacket = nil
        publish("G7 gefunden; verbinde…")''',
    '''        lastDeviceName = peripheral.name ?? "unbekannt"
        authenticated = false
        pendingGlucosePacket = nil
        trace41("DISCOVER \\(lastDeviceName) state=\\(peripheral.state.rawValue)")
        publish("G7 gefunden; verbinde…")''',
    "Build41 discovery marker",
)

replace_once(
    state,
    '''    private func scheduleReconnect() {
        reconnectTask?.cancel()''',
    '''    private func scheduleReconnect() {
        trace41("RECONNECT scheduled")
        reconnectTask?.cancel()''',
    "Build41 reconnect marker",
)

replace_once(
    state,
    '''    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        switch central.state {''',
    '''    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        trace41("CENTRAL state=\\(central.state.rawValue)")
        switch central.state {''',
    "Build41 central state marker",
)

replace_once(
    state,
    '''    func centralManager(_ central: CBCentralManager, willRestoreState dict: [String : Any]) {
        if let peripherals = dict[CBCentralManagerRestoredStatePeripheralsKey] as? [CBPeripheral],''',
    '''    func centralManager(_ central: CBCentralManager, willRestoreState dict: [String : Any]) {
        let restored = dict[CBCentralManagerRestoredStatePeripheralsKey] as? [CBPeripheral] ?? []
        let restoredState = restored.first?.state.rawValue ?? -1
        trace41("RESTORE count=\\(restored.count) state=\\(restoredState)")
        if let peripherals = dict[CBCentralManagerRestoredStatePeripheralsKey] as? [CBPeripheral],''',
    "Build41 restore marker",
)

replace_once(
    state,
    '''    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        lastDeviceName = peripheral.name ?? lastDeviceName''',
    '''    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        trace41("CONNECTED \\(peripheral.name ?? "unknown")")
        lastDeviceName = peripheral.name ?? lastDeviceName''',
    "Build41 didConnect marker",
)

replace_once(
    state,
    '''    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        if targetPeripheral?.identifier == peripheral.identifier {''',
    '''    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        trace41("CONNECT_FAIL err=\\(error?.localizedDescription ?? "nil")")
        if targetPeripheral?.identifier == peripheral.identifier {''',
    "Build41 connect failure marker",
)

replace_once(
    state,
    '''    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        guard targetPeripheral?.identifier == peripheral.identifier else { return }''',
    '''    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        trace41("DISCONNECT err=\\(error?.localizedDescription ?? "nil") state=\\(peripheral.state.rawValue)")
        guard targetPeripheral?.identifier == peripheral.identifier else { return }''',
    "Build41 disconnect marker",
)

replace_once(
    state,
    '''    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?) {
        if let error {''',
    '''    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?) {
        trace41("NOTIFY \\(characteristic.uuid.uuidString.suffix(4)) on=\\(characteristic.isNotifying) err=\\(error?.localizedDescription ?? "nil")")
        if let error {''',
    "Build41 notify marker",
)

replace_once(
    state,
    '''        guard characteristic.uuid == controlUUID, value[0] == 0x4E else { return }

        guard authenticated else {''',
    '''        guard characteristic.uuid == controlUUID, value[0] == 0x4E else { return }

        let seq41 = value.count >= 8 ? littleEndianUInt16(value, offset: 6) : 0
        let bg41 = value.count >= 14 ? Int(littleEndianUInt16(value, offset: 12) & 0x0FFF) : -1
        trace41("RX4E seq=\\(seq41) bg=\\(bg41) auth=\\(authenticated)")

        guard authenticated else {''',
    "Build41 0x4E marker",
)

print("Build 41 applied: persistent Direct-G7 BLE lifecycle trace only; UI/widgets/WatchConnectivity untouched.")
