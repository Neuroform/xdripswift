from pathlib import Path

state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")
text = state.read_text(encoding="utf-8")

manager_start = text.index("// MARK: - Direct G7 BLE manager")
manager_end = text.index("// MARK: - WCSession delegate", manager_start)
manager = text[manager_start:manager_end]


def replace_in_manager(old: str, new: str, label: str) -> None:
    global text, manager, manager_start, manager_end
    count = manager.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in Direct G7 manager, found {count}")
    manager = manager.replace(old, new, 1)
    text = text[:manager_start] + manager + text[manager_end:]
    manager_end = manager_start + len(manager)


# Build 44 deliberately keeps G7DirectBLEManager inside the existing xDrip Watch app/model.
# It only hardens the already-working CoreBluetooth subscription so that, after one user
# initialization following install/update, CoreBluetooth has a durable peripheral connection /
# notify subscription to restore and wake for future sensor events.

replace_in_manager(
    '''    private var reconnectTask: DispatchWorkItem?\n    private var lastDeviceName = ""''',
    '''    private var reconnectTask: DispatchWorkItem?\n    private var lastDeviceName = ""\n\n    // Persist the sensor CoreBluetooth identifier after a valid G7 packet. This lets a later\n    // CoreBluetooth wake/restoration reconnect directly to the same peripheral without waiting\n    // for an app-owned discovery timer.\n    private let knownPeripheralIDKey = "xdrip.g7Direct.knownPeripheralID.build44"''',
    "add persistent peripheral identifier",
)

replace_in_manager(
    '''        reconnectTask?.cancel()\n        reconnectTask = nil\n        publish("suche G7…")\n\n        let connected = central.retrieveConnectedPeripherals(withServices: [serviceUUID])''',
    '''        reconnectTask?.cancel()\n        reconnectTask = nil\n        publish("suche G7…")\n\n        // Prefer the exact sensor that already delivered a valid direct G7 packet. Register the\n        // CoreBluetooth connect immediately; do not depend on the Watch UI being foreground.\n        if let storedID = UserDefaults.standard.string(forKey: knownPeripheralIDKey),\n           let uuid = UUID(uuidString: storedID),\n           let known = central.retrievePeripherals(withIdentifiers: [uuid]).first {\n            inspect(known)\n            return\n        }\n\n        let connected = central.retrieveConnectedPeripherals(withServices: [serviceUUID])''',
    "prefer known peripheral",
)

replace_in_manager(
    '''        publish("G7 gefunden; verbinde…")\n        central.connect(peripheral, options: nil)''',
    '''        if peripheral.state == .connected {\n            publish("G7 bereits verbunden; aktiviere Subscription…")\n            peripheral.discoverServices([serviceUUID])\n        } else {\n            publish("G7 gefunden; verbinde…")\n            // The connection itself is the durable CoreBluetooth operation. Once registered,\n            // watchOS can restore/wake this app for subsequent BLE events after initialization.\n            central.connect(peripheral, options: nil)\n        }''',
    "durable connect registration",
)

replace_in_manager(
    '''    private func scheduleReconnect() {\n        reconnectTask?.cancel()\n        let task = DispatchWorkItem { [weak self] in\n            guard let self, self.enabled, self.targetPeripheral == nil else { return }\n            self.beginDiscovery()\n        }\n        reconnectTask = task\n        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0, execute: task)\n    }''',
    '''    private func scheduleReconnect() {\n        reconnectTask?.cancel()\n        reconnectTask = nil\n        guard enabled, central.state == .poweredOn, targetPeripheral == nil else { return }\n\n        // Do not rely on a delayed DispatchQueue timer: watchOS may suspend the app before it\n        // fires. Register the next CoreBluetooth operation immediately so the system owns it.\n        beginDiscovery()\n    }''',
    "replace timer reconnect with immediate CoreBluetooth registration",
)

old_restore = '''    func centralManager(_ central: CBCentralManager, willRestoreState dict: [String : Any]) {\n        let restored = dict[CBCentralManagerRestoredStatePeripheralsKey] as? [CBPeripheral] ?? []\n        let restoredState = restored.first?.state.rawValue ?? -1\n        trace41("RESTORE count=\\(restored.count) state=\\(restoredState)")\n        if let peripherals = dict[CBCentralManagerRestoredStatePeripheralsKey] as? [CBPeripheral],\n           let peripheral = peripherals.first {\n            enabled = true\n            targetPeripheral = peripheral\n            peripheral.delegate = self\n            lastDeviceName = peripheral.name ?? "unbekannt"\n            authenticated = false\n            publish("G7-Verbindung wiederhergestellt")\n\n            if peripheral.state == .connected {\n                peripheral.discoverServices([serviceUUID])\n            } else {\n                central.connect(peripheral, options: nil)\n            }\n        }\n    }'''

new_restore = '''    func centralManager(_ central: CBCentralManager, willRestoreState dict: [String : Any]) {\n        let restored = dict[CBCentralManagerRestoredStatePeripheralsKey] as? [CBPeripheral] ?? []\n        let restoredState = restored.first?.state.rawValue ?? -1\n        trace41("RESTORE count=\\(restored.count) state=\\(restoredState)")\n\n        // A CoreBluetooth restoration is itself the background wake. Adopt the restored sensor\n        // immediately and re-establish the existing GATT notify subscription without involving\n        // RootView or any foreground UI action.\n        enabled = true\n        if let peripheral = restored.first(where: { $0.state == .connected }) ?? restored.first {\n            targetPeripheral = peripheral\n            peripheral.delegate = self\n            lastDeviceName = peripheral.name ?? "unbekannt"\n            authenticated = false\n            publish("G7-Verbindung wiederhergestellt")\n\n            if peripheral.state == .connected {\n                peripheral.discoverServices([serviceUUID])\n            } else {\n                central.connect(peripheral, options: nil)\n            }\n            return\n        }\n\n        // Restoration can contain a pending scan without a peripheral. Register discovery now.\n        if central.state == .poweredOn {\n            beginDiscovery()\n        }\n    }'''
replace_in_manager(old_restore, new_restore, "harden state restoration")

replace_in_manager(
    '''        let seq41 = value.count >= 8 ? littleEndianUInt16(value, offset: 6) : 0\n        let bg41 = value.count >= 14 ? Int(littleEndianUInt16(value, offset: 12) & 0x0FFF) : -1\n        trace41("RX4E seq=\\(seq41) bg=\\(bg41) auth=\\(authenticated)")''',
    '''        let seq41 = value.count >= 8 ? littleEndianUInt16(value, offset: 6) : 0\n        let bg41 = value.count >= 14 ? Int(littleEndianUInt16(value, offset: 12) & 0x0FFF) : -1\n        trace41("RX4E seq=\\(seq41) bg=\\(bg41) auth=\\(authenticated)")\n\n        // Once this peripheral proves itself by sending the expected G7 glucose packet, remember\n        // its CoreBluetooth identifier for all subsequent background reconnect/restoration cycles.\n        UserDefaults.standard.set(peripheral.identifier.uuidString, forKey: knownPeripheralIDKey)''',
    "persist valid G7 peripheral",
)

state.write_text(text, encoding="utf-8")
print("Build 44 applied: existing Direct-G7 receiver retained; durable CoreBluetooth connect/notify subscription and immediate restoration/reconnect registered; Build 43 direct widget bypass preserved.")
