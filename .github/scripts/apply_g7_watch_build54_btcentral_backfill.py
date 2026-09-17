from pathlib import Path

PATH = Path("xDrip Watch App/DataModels/WatchStateModel.swift")
text = PATH.read_text(encoding="utf-8")

manager_start = text.index("private final class G7DirectBLEManager")
manager_end = text.index("// MARK: - WCSession delegate", manager_start)
prefix = text[:manager_start]
manager = text[manager_start:manager_end]
suffix = text[manager_end:]


def require(token: str, where: str = "manager") -> None:
    haystack = manager if where == "manager" else text
    if token not in haystack:
        raise RuntimeError(f"Build54 precondition missing: {token}")


def replace_once(old: str, new: str, label: str) -> None:
    global manager
    count = manager.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in Direct G7 manager, found {count}")
    manager = manager.replace(old, new, 1)


def replace_function(signature: str, replacement: str, label: str) -> None:
    global manager
    start = manager.find(signature)
    if start < 0:
        raise RuntimeError(f"{label}: signature not found: {signature}")
    brace = manager.find("{", start)
    if brace < 0:
        raise RuntimeError(f"{label}: opening brace not found")
    depth = 0
    end = None
    for i in range(brace, len(manager)):
        ch = manager[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise RuntimeError(f"{label}: closing brace not found")
    manager = manager[:start] + replacement.rstrip() + manager[end:]


# Build 53 continuity guard. These paths are already proven and must remain intact.
for token in [
    'private final class G7DirectBLEManager',
    'CBCentralManagerOptionRestoreIdentifierKey: "xDrip.G7.Direct.Central"',
    'publishReadingDirectlyToWidgets(reading)',
    'CORE_BLUETOOTH_0x4E',
    'backfillUUID',
    'CORE_BLUETOOTH_BACKFILL_3536',
    'MISSED_SEQ',
    'BACKFILL_WRITE',
    'deferredBackfillFrames53',
    'retrievePeripherals(withIdentifiers:',
]:
    require(token)

# 1) Put every productive CoreBluetooth callback/operation on one dedicated serial queue.
replace_once(
    "    private var central: CBCentralManager!\n",
    "    private let centralQueue54 = DispatchQueue(label: \"xDrip.G7.Direct.bt.central\", qos: .userInitiated)\n"
    "    private var central: CBCentralManager!\n",
    "dedicated bt.central queue property",
)

replace_once(
    "            queue: .main,\n            options: [CBCentralManagerOptionRestoreIdentifierKey: \"xDrip.G7.Direct.Central\"]",
    "            queue: centralQueue54,\n            options: [CBCentralManagerOptionRestoreIdentifierKey: \"xDrip.G7.Direct.Central\"]",
    "central queue",
)

replace_once(
    "    private var lastLiveSequence52: UInt16?\n",
    "    private var connectPending54 = false\n"
    "    private var controlCharacteristic54: CBCharacteristic?\n"
    "    private var backfillRequestInFlight54 = false\n"
    "    private var lastLiveSequence52: UInt16?\n",
    "Build54 state",
)

# 2) Keep the verified G7 as one known CoreBluetooth peer. Do not combine connection-event
# registration, AutoReconnect, and FEBC scanning for the same normal five-minute cycle.
replace_function(
    "    private func registerVerifiedConnectionEvents(_ identifier: UUID)",
    '''    private func registerVerifiedConnectionEvents(_ identifier: UUID) {
        // Build 54: deliberately no registerForConnectionEvents here. The verified G7 uses one
        // OS-level pending connect. A service-filtered scan is only a first-discovery/fallback path.
        trace41("CONNECTION_EVENTS54 disabled id=\\(identifier.uuidString)")
    }''',
    "disable competing connection-event registration",
)

replace_function(
    "    private func connectVerifiedWithSystemAutoReconnect(_ peripheral: CBPeripheral, reason: String)",
    '''    private func connectVerifiedWithSystemAutoReconnect(_ peripheral: CBPeripheral, reason: String) {
        guard enabled, central.state == .poweredOn else { return }

        let known: CBPeripheral
        if let id = verifiedPeripheralID(),
           let refreshed = central.retrievePeripherals(withIdentifiers: [id]).first {
            known = refreshed
        } else {
            known = peripheral
        }

        targetPeripheral = known
        known.delegate = self
        if central.isScanning { central.stopScan() }

        trace41("KNOWN_PEER_ARMED54 reason=\\(reason) state=\\(known.state.rawValue) id=\\(known.identifier.uuidString)")

        switch known.state {
        case .connected:
            connectPending54 = false
            known.discoverServices([serviceUUID])
        case .connecting:
            connectPending54 = true
        case .disconnected:
            guard !connectPending54 else {
                trace41("KNOWN_PEER_CONNECT54 already-pending reason=\\(reason)")
                return
            }
            connectPending54 = true
            central.connect(known, options: nil)
        case .disconnecting:
            break
        @unknown default:
            break
        }
    }''',
    "single known-peer connect",
)

replace_function(
    "    private func startGapRecoveryScan52(reason: String)",
    '''    private func startGapRecoveryScan52(reason: String) {
        guard enabled, central.state == .poweredOn else { return }

        if let id = verifiedPeripheralID(),
           let known = central.retrievePeripherals(withIdentifiers: [id]).first {
            // Build 54: normal G7 duty-cycle recovery is a pending connection to the known peer,
            // not an advertisement scan racing a second connection mechanism.
            connectVerifiedWithSystemAutoReconnect(known, reason: "known-peer-\\(reason)")
            return
        }

        // Only if there is no retrievable verified peer do we fall back to FEBC discovery.
        targetPeripheral = nil
        connectPending54 = false
        if !central.isScanning {
            central.scanForPeripherals(
                withServices: [advertisementUUID],
                options: [CBCentralManagerScanOptionAllowDuplicatesKey: false]
            )
        }
        trace41("FALLBACK_SCAN54 begin reason=\\(reason)")
    }''',
    "known peer instead of parallel recovery scan",
)

replace_function(
    "    private func scheduleGapRecoveryScan52(reason: String)",
    '''    private func scheduleGapRecoveryScan52(reason: String) {
        startGapRecoveryScan52(reason: "immediate-\\(reason)")
        trace41("KNOWN_PEER_RECOVERY54 reason=\\(reason)")
    }''',
    "deterministic recovery scheduling",
)

# Ensure pending-connect bookkeeping is reset by all productive lifecycle callbacks.
replace_once(
    "    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {\n        if central.isScanning { central.stopScan() }",
    "    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {\n        connectPending54 = false\n        if central.isScanning { central.stopScan() }",
    "didConnect pending reset",
)

replace_once(
    "    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {\n        trace41(",
    "    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {\n        connectPending54 = false\n        backfillRequestInFlight54 = false\n        trace41(",
    "didFail pending reset",
)

replace_once(
    "    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {\n        trace41(",
    "    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {\n        connectPending54 = false\n        backfillRequestInFlight54 = false\n        controlCharacteristic54 = nil\n        trace41(",
    "legacy disconnect reset",
)

replace_once(
    "        trace41(\"DISCONNECT_AUTO reconnecting=\\(isReconnecting) err=\\(error?.localizedDescription ?? \\\"nil\\\")\")",
    "        connectPending54 = false\n        backfillRequestInFlight54 = false\n        controlCharacteristic54 = nil\n        trace41(\"DISCONNECT_AUTO reconnecting=\\(isReconnecting) err=\\(error?.localizedDescription ?? \\\"nil\\\")\")",
    "modern disconnect reset",
)

# The old callback comments referenced AutoReconnect even though Build54 intentionally removes it.
manager = manager.replace(
    "// watchOS 10+ CoreBluetooth callback used by CBConnectPeripheralOptionEnableAutoReconnect.\n"
    "    // If isReconnecting is true the operating system already owns the pending reconnect; do not\n"
    "    // scan, sleep, schedule a timer or issue a competing connection request.",
    "// watchOS 10+ disconnect callback. Build54 uses the same single-known-peer recovery path\n"
    "    // regardless of which disconnect overload watchOS delivers.",
)
manager = manager.replace(
    "// Legacy disconnect callback remains as a fallback. Verified G7 links are immediately\n"
    "    // re-registered with CoreBluetooth AutoReconnect rather than returning to scanning.",
    "// Legacy disconnect callback remains as a fallback and feeds the same Build54 known-peer path.",
)

# 3) Capture the 3534 control characteristic while keeping the existing notify registration unchanged.
replace_once(
    "        let notifyCharacteristics = (service.characteristics ?? []).filter {",
    "        let allCharacteristics54 = service.characteristics ?? []\n"
    "        controlCharacteristic54 = allCharacteristics54.first(where: { $0.uuid == controlUUID })\n"
    "        let notifyCharacteristics = allCharacteristics54.filter {",
    "capture G7 control characteristic",
)

# 4) Active gap repair: request only the missing sensor-relative window through the already
# authenticated 3534 connection. Failure to qualify simply leaves the proven live path untouched.
notify_signature = "    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?)"
notify_pos = manager.find(notify_signature)
if notify_pos < 0:
    raise RuntimeError("Build54: productive didUpdateNotificationStateFor not found")

backfill_helpers = r'''
    private func appendUInt32LE54(_ value: UInt32, to data: inout Data) {
        data.append(UInt8(truncatingIfNeeded: value))
        data.append(UInt8(truncatingIfNeeded: value >> 8))
        data.append(UInt8(truncatingIfNeeded: value >> 16))
        data.append(UInt8(truncatingIfNeeded: value >> 24))
    }

    private func requestBackfill54(current: DirectG7Reading, missingCount: Int, peripheral: CBPeripheral) {
        guard missingCount > 0, missingCount <= 36 else {
            trace41("BACKFILL_REQUEST54 skipped gap=\(missingCount) reason=range")
            return
        }
        guard authenticated else {
            trace41("BACKFILL_REQUEST54 skipped gap=\(missingCount) reason=not-authenticated")
            return
        }
        guard !backfillRequestInFlight54 else {
            trace41("BACKFILL_REQUEST54 skipped gap=\(missingCount) reason=in-flight")
            return
        }
        guard let activation = sensorActivationDate52,
              let control = controlCharacteristic54 else {
            trace41("BACKFILL_REQUEST54 skipped gap=\(missingCount) reason=no-control-or-activation")
            return
        }
        guard peripheral.identifier == targetPeripheral?.identifier else {
            trace41("BACKFILL_REQUEST54 skipped gap=\(missingCount) reason=wrong-peer")
            return
        }

        let relative = current.date.timeIntervalSince(activation)
        guard relative > 300, relative < Double(UInt32.max) else {
            trace41("BACKFILL_REQUEST54 skipped gap=\(missingCount) reason=timestamp")
            return
        }

        let currentTimestamp = UInt32(relative.rounded())
        let missingSeconds = UInt32(missingCount * 300)
        guard currentTimestamp > missingSeconds else { return }

        let firstMissing = currentTimestamp - missingSeconds
        let lastMissing = currentTimestamp - 300
        let startTime = firstMissing > 90 ? firstMissing - 90 : 0
        let endTime = min(currentTimestamp - 30, lastMissing + 90)
        guard endTime >= startTime else { return }

        var command = Data([0x59])
        appendUInt32LE54(startTime, to: &command)
        appendUInt32LE54(endTime, to: &command)

        let writeType: CBCharacteristicWriteType
        if control.properties.contains(.write) {
            writeType = .withResponse
        } else if control.properties.contains(.writeWithoutResponse) {
            writeType = .withoutResponse
        } else {
            trace41("BACKFILL_REQUEST54 skipped gap=\(missingCount) reason=control-not-writable")
            return
        }

        backfillRequestInFlight54 = true
        backfillBuffer52.removeAll(keepingCapacity: true)
        peripheral.writeValue(command, for: control, type: writeType)
        trace41("BACKFILL_REQUEST54 gap=\(missingCount) start=\(startTime) end=\(endTime) bytes=\(command.count)")
    }

'''
manager = manager[:notify_pos] + backfill_helpers + manager[notify_pos:]

# Replace the notification callback so the normal watchOS BLE budget errors are explicitly visible.
replace_function(
    notify_signature,
    '''    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?) {
        trace41("NOTIFY \\(characteristic.uuid.uuidString.suffix(4)) on=\\(characteristic.isNotifying) err=\\(error?.localizedDescription ?? \"nil\")")
        if let cbError = error as? CBError {
            if #available(watchOS 9.0, *) {
                switch cbError.code {
                case .leGattNearBackgroundNotificationLimit:
                    trace41("BLE_BUDGET54 leGattNearBackgroundNotificationLimit")
                case .leGattExceededBackgroundNotificationLimit:
                    trace41("BLE_BUDGET54 leGattExceededBackgroundNotificationLimit")
                default:
                    break
                }
            }
        }
        if let error {
            publish("Notify-Fehler: \\(error.localizedDescription)")
        }
    }''',
    "BLE budget diagnostics",
)

# Request backfill at the exact point where the existing continuity code proves samples are missing.
old_gap = '''                if gap > 0 && gap < 100 {
                    trace41("MISSED_SEQ expected=\\(expected) received=\\(reading.sequence) count=\\(gap)")
                }'''
new_gap = '''                if gap > 0 && gap < 100 {
                    trace41("MISSED_SEQ expected=\\(expected) received=\\(reading.sequence) count=\\(gap)")
                    requestBackfill54(current: reading, missingCount: gap, peripheral: peripheral)
                }'''
replace_once(old_gap, new_gap, "active gap backfill request")

# A 0x59 completion ends the current active request; existing Build52/53 buffering and widget merge stay unchanged.
replace_once(
    "        if characteristic.uuid == controlUUID, value[0] == 0x59 {\n",
    "        if characteristic.uuid == controlUUID, value[0] == 0x59 {\n            backfillRequestInFlight54 = false\n",
    "backfill completion reset",
)

# Final architecture assertions, scoped only to the productive Direct-G7 manager.
for forbidden in [
    "CBConnectPeripheralOptionEnableAutoReconnect",
    "central.registerForConnectionEvents(",
    "writeValue(Data([0x06",
    "writeValue(Data([0x07",
    "B50_BOND",
]:
    if forbidden in manager:
        raise RuntimeError(f"Build54 forbidden legacy mechanism still present: {forbidden}")

for required in [
    'xDrip.G7.Direct.bt.central',
    'queue: centralQueue54',
    'KNOWN_PEER_ARMED54',
    'retrievePeripherals(withIdentifiers:',
    'FALLBACK_SCAN54',
    'BACKFILL_REQUEST54',
    'leGattNearBackgroundNotificationLimit',
    'leGattExceededBackgroundNotificationLimit',
    'publishReadingDirectlyToWidgets(reading)',
    'WidgetCenter.shared.reloadAllTimelines()',
]:
    if required not in manager:
        raise RuntimeError(f"Build54 required token missing after patch: {required}")

updated = prefix + manager + suffix
PATH.write_text(updated, encoding="utf-8")
print("Build 54 bt.central + single-known-peer + targeted backfill patch applied.")
