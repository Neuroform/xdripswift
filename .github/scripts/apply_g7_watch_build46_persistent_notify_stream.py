from pathlib import Path

state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")
text = state.read_text(encoding="utf-8")

start_marker = "// MARK: - Direct G7 BLE manager"
end_marker = "// MARK: - WCSession delegate"
start = text.find(start_marker)
end = text.find(end_marker, start + len(start_marker))
if start < 0 or end < 0:
    raise RuntimeError("Build46: Direct G7 manager boundaries not found")

manager = text[start:end]


def replace_once(old: str, new: str, label: str) -> None:
    global manager
    count = manager.count(old)
    if count != 1:
        raise RuntimeError(f"Build46 {label}: expected exactly one match in Direct G7 manager, found {count}")
    manager = manager.replace(old, new, 1)


# Build 45 proved that a valid direct 0x4E packet can write the current BG straight into the
# existing WidgetKit payload. The subsequent stream stopped because the production Direct-G7
# manager still carried an old 20-second authentication watchdog whose only action was to cancel
# the CoreBluetooth peripheral whenever the app-level 'authenticated' flag had not been set.
# That is incompatible with the proven passive 0x4E widget bypass: the packet is already valid and
# useful before that UI/auth gate. Build 46 therefore keeps the established GATT Notify subscription
# alive and lets only real CoreBluetooth disconnect/fail events drive reconnection.

old_timeout = '''    private func armAuthenticationTimeout(for peripheral: CBPeripheral) {
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

new_timeout = '''    private func armAuthenticationTimeout(for peripheral: CBPeripheral) {
        // Build 46: DO NOT tear down a proven Direct-G7 Notify subscription after 20 seconds.
        // Build 45 demonstrated that valid 0x4E glucose packets reach the direct widget bridge
        // before the legacy app-level authentication flag changes. Cancelling this connection
        // destroyed the very background subscription that must survive while the Watch UI sleeps.
        // Real BLE failures/disconnects are still handled by didFailToConnect/didDisconnectPeripheral.
        authTimeoutTask?.cancel()
        authTimeoutTask = nil
        trace41("AUTH watchdog bypassed; keep notify subscription alive id=\\(peripheral.identifier.uuidString)")
    }'''
replace_once(old_timeout, new_timeout, "replace destructive auth watchdog")

old_rx = '''        // Build 43: the widget payload is updated immediately from the sensor packet.
        // This deliberately happens BEFORE the existing WatchStateModel/auth gate.
        publishReadingDirectlyToWidgets(reading)

        guard authenticated else {
            pendingGlucosePacket = value
            publish("0x4E empfangen · Widgets direkt aktualisiert")
            return
        }'''

new_rx = '''        // Build 43/46: every valid sensor packet goes directly to the existing widgets.
        // A received 0x4E also proves that this is the correct live G7 connection, so any legacy
        // auth watchdog must remain cancelled and the GATT Notify subscription must stay intact.
        authTimeoutTask?.cancel()
        authTimeoutTask = nil
        publishReadingDirectlyToWidgets(reading)

        guard authenticated else {
            pendingGlucosePacket = value
            publish("0x4E empfangen · Widgets direkt aktualisiert · Notify bleibt aktiv")
            return
        }'''
replace_once(old_rx, new_rx, "keep subscription alive after valid 0x4E")

text = text[:start] + manager + text[end:]
state.write_text(text, encoding="utf-8")

print("Build 46 applied: destructive 20-second auth disconnect removed; valid Direct-G7 Notify stream remains subscribed and continues feeding the existing widget bypass.")
