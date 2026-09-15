from pathlib import Path

state_path = Path("xDrip Watch App/DataModels/WatchStateModel.swift")
app_path = Path("xDrip Watch App/xDripWatchApp.swift")

state = state_path.read_text(encoding="utf-8")
app = app_path.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# Expose one explicit entry point from the existing WatchStateModel to the existing Direct-G7
# manager. This does not create a second BLE owner and does not move the receiver out of xDrip.
state = replace_once(
    state,
    '''        directG7Manager?.start()\n    }\n\n    // MARK: - Functions to provide context data to populate the views''',
    '''        directG7Manager?.start()\n    }\n\n    // Build 45: watchOS Bluetooth-alert wake entry point. The existing Direct-G7 manager stays\n    // inside xDrip; this only gives SwiftUI's background-task handler a direct way to re-register\n    // the already-known CoreBluetooth operation without waiting for foreground UI activity.\n    @MainActor\n    func handleDirectG7BluetoothAlert() {\n        directG7Manager?.handleBluetoothAlertWake()\n    }\n\n    // MARK: - Functions to provide context data to populate the views''',
    "add WatchState bluetooth-alert entry point",
)

# Work only inside the production Direct-G7 manager. Build 43 contains other BLE diagnostic
# helpers, and all global replacements are intentionally avoided after the Build 43/44 anchor
# failures.
manager_start = state.index("// MARK: - Direct G7 BLE manager")
manager_end = state.index("// MARK: - WCSession delegate", manager_start)
manager = state[manager_start:manager_end]


def replace_manager(old: str, new: str, label: str) -> None:
    global manager
    count = manager.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in Direct G7 manager, found {count}")
    manager = manager.replace(old, new, 1)


# Persist the concrete sensor after a valid G7 packet so the background wake can immediately
# retrieve and reconnect to that same peripheral after the one-time foreground initialization.
replace_manager(
    '''    private var reconnectTask: DispatchWorkItem?\n    private var lastDeviceName = ""''',
    '''    private var reconnectTask: DispatchWorkItem?\n    private var lastDeviceName = ""\n    private let knownPeripheralIDKey = "xdrip.g7Direct.knownPeripheralID.build45"''',
    "add persistent peripheral id",
)

# Prefer the known G7 before scanning. This registers a concrete CoreBluetooth operation during
# a Bluetooth-alert wake and avoids an app-owned wait loop.
replace_manager(
    '''        trace41("SCAN begin")\n        publish("suche G7…")\n\n        let connected = central.retrieveConnectedPeripherals(withServices: [serviceUUID])''',
    '''        trace41("SCAN begin")\n        publish("suche G7…")\n\n        if let storedID = UserDefaults.standard.string(forKey: knownPeripheralIDKey),\n           let uuid = UUID(uuidString: storedID),\n           let known = central.retrievePeripherals(withIdentifiers: [uuid]).first {\n            inspect(known)\n            return\n        }\n\n        let connected = central.retrieveConnectedPeripherals(withServices: [serviceUUID])''',
    "prefer known G7 peripheral",
)

# If CoreBluetooth already retained the connection, do not reconnect unnecessarily: immediately
# rediscover GATT service/characteristics so setNotifyValue(true) is re-established.
replace_manager(
    '''        trace41("DISCOVER \\(lastDeviceName) state=\\(peripheral.state.rawValue)")\n        publish("G7 gefunden; verbinde…")\n        central.connect(peripheral, options: nil)''',
    '''        trace41("DISCOVER \\(lastDeviceName) state=\\(peripheral.state.rawValue)")\n        if peripheral.state == .connected {\n            publish("G7 verbunden; registriere Notify erneut…")\n            peripheral.discoverServices([serviceUUID])\n        } else {\n            publish("G7 gefunden; verbinde…")\n            central.connect(peripheral, options: nil)\n        }''',
    "reuse retained G7 connection",
)

# Replace the delayed reconnect timer with immediate registration of the next CoreBluetooth
# operation. Delayed DispatchQueue work is precisely what can be lost when watchOS suspends xDrip.
replace_manager(
    '''    private func scheduleReconnect() {\n        trace41("RECONNECT scheduled")\n        reconnectTask?.cancel()\n        let task = DispatchWorkItem { [weak self] in\n            guard let self, self.enabled, self.targetPeripheral == nil else { return }\n            self.beginDiscovery()\n        }\n        reconnectTask = task\n        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0, execute: task)\n    }\n\n    private func armAuthenticationTimeout''',
    '''    private func scheduleReconnect() {\n        trace41("RECONNECT immediate")\n        reconnectTask?.cancel()\n        reconnectTask = nil\n        guard enabled, central.state == .poweredOn, targetPeripheral == nil else { return }\n        beginDiscovery()\n    }\n\n    // Invoked by SwiftUI .backgroundTask(.bluetoothAlert). The handler does not decode or\n    // fabricate glucose. It only makes sure the existing xDrip CoreBluetooth connection / GATT\n    // subscription is registered so the normal didUpdateValueFor(0x4E) callback can execute.\n    func handleBluetoothAlertWake() {\n        enabled = true\n        trace41("BLUETOOTH_ALERT wake central=\\(central.state.rawValue)")\n\n        guard central.state == .poweredOn else { return }\n\n        if let peripheral = targetPeripheral {\n            peripheral.delegate = self\n            if peripheral.state == .connected {\n                peripheral.discoverServices([serviceUUID])\n            } else if peripheral.state == .disconnected {\n                central.connect(peripheral, options: nil)\n            }\n            return\n        }\n\n        beginDiscovery()\n    }\n\n    private func armAuthenticationTimeout''',
    "add bluetooth-alert wake handler and immediate reconnect",
)

# Persist only after the packet has proven that this is the expected G7 control channel.
replace_manager(
    '''        trace41("RX4E seq=\\(seq41) bg=\\(bg41) auth=\\(authenticated)")\n\n        guard let reading = parseG7Glucose(value) else {''',
    '''        trace41("RX4E seq=\\(seq41) bg=\\(bg41) auth=\\(authenticated)")\n        UserDefaults.standard.set(peripheral.identifier.uuidString, forKey: knownPeripheralIDKey)\n\n        guard let reading = parseG7Glucose(value) else {''',
    "persist proven G7 peripheral",
)

# Strengthen state restoration without changing the receiver architecture. A restored peripheral
# is adopted immediately and the normal service -> characteristic -> setNotifyValue(true) chain
# is reused.
old_restore = '''    func centralManager(_ central: CBCentralManager, willRestoreState dict: [String : Any]) {\n        let restored = dict[CBCentralManagerRestoredStatePeripheralsKey] as? [CBPeripheral] ?? []\n        let restoredState = restored.first?.state.rawValue ?? -1\n        trace41("RESTORE count=\\(restored.count) state=\\(restoredState)")\n        if let peripherals = dict[CBCentralManagerRestoredStatePeripheralsKey] as? [CBPeripheral],\n           let peripheral = peripherals.first {\n            enabled = true\n            targetPeripheral = peripheral\n            peripheral.delegate = self\n            lastDeviceName = peripheral.name ?? "unbekannt"\n            authenticated = false\n            publish("G7-Verbindung wiederhergestellt")\n\n            if peripheral.state == .connected {\n                peripheral.discoverServices([serviceUUID])\n            } else {\n                central.connect(peripheral, options: nil)\n            }\n        }\n    }'''
new_restore = '''    func centralManager(_ central: CBCentralManager, willRestoreState dict: [String : Any]) {\n        let restored = dict[CBCentralManagerRestoredStatePeripheralsKey] as? [CBPeripheral] ?? []\n        let restoredState = restored.first?.state.rawValue ?? -1\n        trace41("RESTORE count=\\(restored.count) state=\\(restoredState)")\n        enabled = true\n\n        if let peripheral = restored.first(where: { $0.state == .connected }) ?? restored.first {\n            targetPeripheral = peripheral\n            peripheral.delegate = self\n            lastDeviceName = peripheral.name ?? "unbekannt"\n            authenticated = false\n            UserDefaults.standard.set(peripheral.identifier.uuidString, forKey: knownPeripheralIDKey)\n            publish("G7-Verbindung wiederhergestellt")\n\n            if peripheral.state == .connected {\n                peripheral.discoverServices([serviceUUID])\n            } else {\n                central.connect(peripheral, options: nil)\n            }\n            return\n        }\n\n        if central.state == .poweredOn {\n            beginDiscovery()\n        }\n    }'''
replace_manager(old_restore, new_restore, "harden CoreBluetooth restoration")

state = state[:manager_start] + manager + state[manager_end:]
state_path.write_text(state, encoding="utf-8")

# Register the documented SwiftUI watchOS Bluetooth background-task handler. The handler calls
# back into the SAME WatchStateModel / G7DirectBLEManager; no second receiver or widget BLE client
# is introduced.
app = replace_once(
    app,
    '''        WindowGroup {\n            NavigationView {\n                RootView()\n            }.environmentObject(watchState)\n        }''',
    '''        WindowGroup {\n            NavigationView {\n                RootView()\n            }.environmentObject(watchState)\n        }\n        .backgroundTask(.bluetoothAlert) {\n            await watchState.handleDirectG7BluetoothAlert()\n        }''',
    "register SwiftUI bluetoothAlert background task",
)
app_path.write_text(app, encoding="utf-8")

print("Build 45 applied: existing Direct-G7 receiver retained; bluetoothAlert wake registered; known peripheral/restoration/immediate reconnect feed the existing Build-43 direct widget bypass.")
