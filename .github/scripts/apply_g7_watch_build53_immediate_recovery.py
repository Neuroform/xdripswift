from pathlib import Path

WATCH_STATE = Path("xDrip Watch App/DataModels/WatchStateModel.swift")
text = WATCH_STATE.read_text(encoding="utf-8")


def rep(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# Build 53 is a strict reliability follow-up to Build 52. Field evidence showed six
# consecutive Direct-G7 cycles were missed while the app was backgrounded, then delivered
# later by iPhone WatchConnectivity (new=6). The two-second delayed recovery registration is
# therefore removed: the verified FEBC scan is armed synchronously inside the CoreBluetooth
# callback before watchOS can suspend the process. No pairing/bond/keepalive/whitelist writes.

rep(
    """    private func connectVerifiedWithSystemAutoReconnect(_ peripheral: CBPeripheral, reason: String) {
        targetPeripheral = peripheral
        peripheral.delegate = self
        registerVerifiedConnectionEvents(peripheral.identifier)
        trace41("AUTO_CONNECT request reason=\(reason) state=\(peripheral.state.rawValue)")
        central.connect(
            peripheral,
            options: [CBConnectPeripheralOptionEnableAutoReconnect: true]
        )
    }
""",
    """    private func connectVerifiedWithSystemAutoReconnect(_ peripheral: CBPeripheral, reason: String) {
        targetPeripheral = peripheral
        peripheral.delegate = self
        registerVerifiedConnectionEvents(peripheral.identifier)
        trace41("AUTO_CONNECT request reason=\(reason) state=\(peripheral.state.rawValue)")

        switch peripheral.state {
        case .connected:
            if central.isScanning { central.stopScan() }
            peripheral.discoverServices([serviceUUID])
        case .connecting:
            // Do not issue a second connect request. Keep the FEBC scan registered so the
            // next sensor advertisement remains a system wake source while CoreBluetooth owns
            // the pending connection.
            startGapRecoveryScan52(reason: "already-connecting-\(reason)")
        case .disconnected:
            central.connect(
                peripheral,
                options: [CBConnectPeripheralOptionEnableAutoReconnect: true]
            )
        case .disconnecting:
            startGapRecoveryScan52(reason: "disconnecting-\(reason)")
        @unknown default:
            startGapRecoveryScan52(reason: "unknown-state-\(reason)")
        }
    }
""",
    "deduplicate verified connect requests",
)

rep(
    """    private func inspect(_ peripheral: CBPeripheral) {
        guard enabled, targetPeripheral == nil else { return }

        central.stopScan()
        targetPeripheral = peripheral
        peripheral.delegate = self
        lastDeviceName = peripheral.name ?? "unbekannt"
        authenticated = false
        pendingGlucosePacket = nil
        trace41("DISCOVER \(lastDeviceName) state=\(peripheral.state.rawValue)")
        if peripheral.state == .connected {
            publish("G7 verbunden; registriere Notify erneut…")
            if isVerifiedPeripheral(peripheral) {
                registerVerifiedConnectionEvents(peripheral.identifier)
            }
            peripheral.discoverServices([serviceUUID])
        } else if isVerifiedPeripheral(peripheral) {
            publish("Verifiziertes G7 gefunden; System-AutoReconnect…")
            connectVerifiedWithSystemAutoReconnect(peripheral, reason: "inspect-known")
        } else {
            publish("G7 gefunden; verbinde zur Verifizierung…")
            central.connect(peripheral, options: nil)
        }
    }
""",
    """    private func inspect(_ peripheral: CBPeripheral) {
        guard enabled, targetPeripheral == nil else { return }

        let verified = isVerifiedPeripheral(peripheral)
        // For an already verified xDrip peer, do not tear down the filtered FEBC scan while
        // waiting for the short G7 radio window. The scan itself is the background wake source.
        if !verified { central.stopScan() }

        targetPeripheral = peripheral
        peripheral.delegate = self
        lastDeviceName = peripheral.name ?? "unbekannt"
        authenticated = false
        pendingGlucosePacket = nil
        trace41("DISCOVER \(lastDeviceName) state=\(peripheral.state.rawValue)")
        if peripheral.state == .connected {
            if central.isScanning { central.stopScan() }
            publish("G7 verbunden; registriere Notify erneut…")
            if verified {
                registerVerifiedConnectionEvents(peripheral.identifier)
            }
            peripheral.discoverServices([serviceUUID])
        } else if verified {
            publish("Verifiziertes G7 gefunden; FEBC-Wake + System-AutoReconnect…")
            startGapRecoveryScan52(reason: "inspect-known-immediate")
            connectVerifiedWithSystemAutoReconnect(peripheral, reason: "inspect-known")
        } else {
            publish("G7 gefunden; verbinde zur Verifizierung…")
            central.connect(peripheral, options: nil)
        }
    }
""",
    "keep verified recovery scan armed while waiting",
)

rep(
    """    private func scheduleGapRecoveryScan52(reason: String) {
        // Match the proven G7SensorKit reconnect pattern: hold the BLE callback context for
        // two seconds so the sensor can finish shutting down, then scan for the next FEBC
        // advertisement. The actual CBCentralManager still runs on the main queue.
        DispatchQueue.global(qos: .utility).async { [weak self] in
            Thread.sleep(forTimeInterval: 2.0)
            DispatchQueue.main.async {
                self?.startGapRecoveryScan52(reason: reason)
            }
        }
    }
""",
    """    private func scheduleGapRecoveryScan52(reason: String) {
        // Build 53: register the next FEBC advertisement synchronously while this BLE callback
        // still owns background execution time. A delayed DispatchQueue/Thread.sleep can be
        // suspended before scan registration and was observed to miss six consecutive cycles.
        startGapRecoveryScan52(reason: "immediate-\(reason)")
        trace41("GAP_RECOVERY_ARMED_IMMEDIATE reason=\(reason)")
    }
""",
    "remove suspended two-second recovery delay",
)

rep(
    """        case .poweredOn:
            publish("Bluetooth ein")
            beginDiscovery()
""",
    """        case .poweredOn:
            publish("Bluetooth ein")
            if verifiedPeripheralID() != nil {
                startGapRecoveryScan52(reason: "central-powered-on")
            }
            beginDiscovery()
""",
    "arm verified scan at central powered-on",
)

rep(
    """            if peripheral.state == .connected {
                peripheral.discoverServices([serviceUUID])
            } else if isVerifiedPeripheral(peripheral) {
                connectVerifiedWithSystemAutoReconnect(peripheral, reason: "state-restoration")
            } else {
""",
    """            if peripheral.state == .connected {
                peripheral.discoverServices([serviceUUID])
            } else if isVerifiedPeripheral(peripheral) {
                startGapRecoveryScan52(reason: "state-restoration-immediate")
                connectVerifiedWithSystemAutoReconnect(peripheral, reason: "state-restoration")
            } else {
""",
    "state restoration immediate recovery scan",
)

rep(
    """        if isVerifiedPeripheral(peripheral) {
            targetPeripheral = peripheral
            publish("Verifiziertes G7 noch nicht erreichbar; System-Verbindung bleibt registriert")
            if central.state == .poweredOn, peripheral.state == .disconnected {
                connectVerifiedWithSystemAutoReconnect(peripheral, reason: "connect-failed")
            }
            return
        }
""",
    """        if isVerifiedPeripheral(peripheral) {
            targetPeripheral = peripheral
            publish("Verifiziertes G7 noch nicht erreichbar; FEBC-Wake bleibt registriert")
            if central.state == .poweredOn {
                startGapRecoveryScan52(reason: "connect-failed-immediate")
                if peripheral.state == .disconnected {
                    connectVerifiedWithSystemAutoReconnect(peripheral, reason: "connect-failed")
                }
            }
            return
        }
""",
    "connect failure keeps scan wake armed",
)

rep(
    """        trace41("CONNECTION_EVENT \(label) state=\(peripheral.state.rawValue)")
        if event == .peerConnected, peripheral.state == .connected {
            if central.isScanning { central.stopScan() }
            peripheral.discoverServices([serviceUUID])
        }
""",
    """        trace41("CONNECTION_EVENT \(label) state=\(peripheral.state.rawValue)")
        if event == .peerDisconnected {
            // Earliest possible background callback: arm the next FEBC wake before any later
            // disconnect delegate or suspension can occur.
            startGapRecoveryScan52(reason: "connection-event-peerDisconnected")
        } else if event == .peerConnected, peripheral.state == .connected {
            if central.isScanning { central.stopScan() }
            peripheral.discoverServices([serviceUUID])
        }
""",
    "connection event immediate scan",
)

# Make early 3536 delivery lossless. If backfill arrives before the first live packet has
# established the sensor activation epoch, retain the raw 9-byte records and decode them as
# soon as the next 0x4E establishes that epoch.
rep(
    """    private var backfillBuffer52: [DirectG7BackfillReading] = []
    private let verifiedPeripheralIDKey = "xdrip.g7Direct.verifiedPeripheralID.build47"
""",
    """    private var backfillBuffer52: [DirectG7BackfillReading] = []
    private var deferredBackfillFrames53: [Data] = []
    private var deferredBackfillFinished53 = false
    private let verifiedPeripheralIDKey = "xdrip.g7Direct.verifiedPeripheralID.build47"
""",
    "deferred backfill state",
)

rep(
    """        if characteristic.uuid == backfillUUID {
            if let reading = parseBackfill52(value) {
                if !backfillBuffer52.contains(where: { abs($0.date.timeIntervalSince(reading.date)) < 30 }) {
                    backfillBuffer52.append(reading)
                    trace41("BACKFILL_RX bg=\(Int(reading.glucoseMgDl)) sample=\(Int(reading.date.timeIntervalSince1970))")
                }
            } else {
                trace41("BACKFILL_RX rejected len=\(value.count)")
            }
            return
        }

        if characteristic.uuid == controlUUID, value[0] == 0x59 {
            trace41("BACKFILL_FINISHED count=\(backfillBuffer52.count)")
            flushBackfill52(reason: "0x59-finished")
            return
        }
""",
    """        if characteristic.uuid == backfillUUID {
            if sensorActivationDate52 == nil, value.count == 9 {
                deferredBackfillFrames53.append(value)
                if deferredBackfillFrames53.count > 64 {
                    deferredBackfillFrames53.removeFirst(deferredBackfillFrames53.count - 64)
                }
                trace41("BACKFILL_DEFERRED len=9 count=\(deferredBackfillFrames53.count)")
                return
            }
            if let reading = parseBackfill52(value) {
                if !backfillBuffer52.contains(where: { abs($0.date.timeIntervalSince(reading.date)) < 30 }) {
                    backfillBuffer52.append(reading)
                    trace41("BACKFILL_RX bg=\(Int(reading.glucoseMgDl)) sample=\(Int(reading.date.timeIntervalSince1970))")
                }
            } else {
                trace41("BACKFILL_RX rejected len=\(value.count)")
            }
            return
        }

        if characteristic.uuid == controlUUID, value[0] == 0x59 {
            if sensorActivationDate52 == nil, !deferredBackfillFrames53.isEmpty {
                deferredBackfillFinished53 = true
                trace41("BACKFILL_FINISHED deferred count=\(deferredBackfillFrames53.count)")
            } else {
                trace41("BACKFILL_FINISHED count=\(backfillBuffer52.count)")
                flushBackfill52(reason: "0x59-finished")
            }
            return
        }
""",
    "defer backfill until activation epoch exists",
)

rep(
    """        if value.count >= 11 {
            let messageTimestamp52 = littleEndianUInt32(value, offset: 2)
            let messageAge52 = TimeInterval(value[10])
            sensorActivationDate52 = Date().addingTimeInterval(-TimeInterval(messageTimestamp52) - messageAge52)
        }
        trace41("RX4E seq=\(seq41) bg=\(bg41) auth=\(authenticated)")
""",
    """        if value.count >= 11 {
            let messageTimestamp52 = littleEndianUInt32(value, offset: 2)
            let messageAge52 = TimeInterval(value[10])
            sensorActivationDate52 = Date().addingTimeInterval(-TimeInterval(messageTimestamp52) - messageAge52)

            if !deferredBackfillFrames53.isEmpty {
                let deferred = deferredBackfillFrames53
                deferredBackfillFrames53.removeAll(keepingCapacity: true)
                for frame in deferred {
                    if let backfill = parseBackfill52(frame),
                       !backfillBuffer52.contains(where: { abs($0.date.timeIntervalSince(backfill.date)) < 30 }) {
                        backfillBuffer52.append(backfill)
                    }
                }
                trace41("BACKFILL_DEFERRED_DECODED count=\(backfillBuffer52.count)")
                if deferredBackfillFinished53 {
                    deferredBackfillFinished53 = false
                    flushBackfill52(reason: "deferred-0x59-after-live")
                }
            }
        }
        trace41("RX4E seq=\(seq41) bg=\(bg41) auth=\(authenticated)")
""",
    "decode deferred backfill after live epoch",
)

WATCH_STATE.write_text(text, encoding="utf-8")
print("Build 53 immediate background recovery patch applied.")
