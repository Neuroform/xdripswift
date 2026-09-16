from pathlib import Path

WATCH_STATE = Path("xDrip Watch App/DataModels/WatchStateModel.swift")
text = WATCH_STATE.read_text(encoding="utf-8")


def rep(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# Build 52 is based on the proven Build 51 direct-G7 listener. It does not pair, bond,
# whitelist, keep-alive, or write protocol commands to the sensor. It only makes the
# passive receive path resilient: service-filtered scanning after the G7 shuts its short
# radio window, plus passive parsing of the sensor's normal backfill characteristic.

rep(
    """private func bgIngressTraceSnapshot51() -> (source: String, text: String) {
""",
    """private struct DirectG7BackfillReading {
    let glucoseMgDl: Double
    let date: Date
    let trendMgDlPerMinute: Double?
    let algorithmStateRaw: UInt8
}

private func bgIngressTraceSnapshot51() -> (source: String, text: String) {
""",
    "backfill reading struct",
)

rep(
    """    private let controlUUID = CBUUID(string: \"F8083534-849E-531C-C594-30F1F86A4EA5\")
    private let authUUID = CBUUID(string: \"F8083535-849E-531C-C594-30F1F86A4EA5\")
""",
    """    private let controlUUID = CBUUID(string: \"F8083534-849E-531C-C594-30F1F86A4EA5\")
    private let authUUID = CBUUID(string: \"F8083535-849E-531C-C594-30F1F86A4EA5\")
    private let backfillUUID = CBUUID(string: \"F8083536-849E-531C-C594-30F1F86A4EA5\")
""",
    "backfill characteristic UUID",
)

rep(
    """    private var reconnectTask: DispatchWorkItem?
    private var lastDeviceName = \"\"
""",
    """    private var reconnectTask: DispatchWorkItem?
    private var lastDeviceName = \"\"

    // Build 52: sequence continuity + passive Dexcom backfill.
    private var lastLiveSequence52: UInt16?
    private var sensorActivationDate52: Date?
    private var backfillBuffer52: [DirectG7BackfillReading] = []
""",
    "Build 52 state",
)

# Insert proven G7SensorKit-style scan fallback before the existing authentication watchdog.
anchor = """    private func armAuthenticationTimeout(for peripheral: CBPeripheral) {
"""
if text.count(anchor) != 1:
    raise RuntimeError("gap recovery helper anchor mismatch")
helpers = """    // Build 52: Dexcom G7 powers its BLE radio down between five-minute windows.
    // LoopKit/G7SensorKit uses a service-filtered scan after remote disconnect because a
    // persistent CoreBluetooth connection alone does not reliably wake the app when the
    // transmitter advertises again. Keep AutoReconnect as a secondary path, but always arm
    // the FEBC scan so watchOS has an advertisement-based wake source too.
    private func startGapRecoveryScan52(reason: String) {
        guard enabled, central.state == .poweredOn else { return }

        if let id = verifiedPeripheralID() {
            registerVerifiedConnectionEvents(id)
        }

        if !central.isScanning {
            central.scanForPeripherals(
                withServices: [advertisementUUID],
                options: [CBCentralManagerScanOptionAllowDuplicatesKey: false]
            )
        }
        trace41("GAP_RECOVERY_SCAN begin reason=\\(reason)")
    }

    private func scheduleGapRecoveryScan52(reason: String) {
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

    private func parseBackfill52(_ data: Data) -> DirectG7BackfillReading? {
        // Dexcom G7 backfill record format used by G7SensorKit:
        // bytes 0...2 sensor timestamp (UInt24 LE), 4...5 BG, 6 algorithm state,
        // byte 8 trend. Byte 3/7 are metadata/flags.
        guard data.count == 9, let activationDate = sensorActivationDate52 else { return nil }

        let timestamp = UInt32(data[0])
            | (UInt32(data[1]) << 8)
            | (UInt32(data[2]) << 16)
        let glucoseRaw = UInt16(data[4]) | (UInt16(data[5]) << 8)
        guard glucoseRaw != 0xFFFF else { return nil }
        let glucose = Double(glucoseRaw & 0x0FFF)
        guard glucose > 0 else { return nil }

        let trend: Double?
        if data[8] == 0x7F {
            trend = nil
        } else {
            trend = Double(Int8(bitPattern: data[8])) / 10.0
        }

        return DirectG7BackfillReading(
            glucoseMgDl: glucose,
            date: activationDate.addingTimeInterval(TimeInterval(timestamp)),
            trendMgDlPerMinute: trend,
            algorithmStateRaw: data[6]
        )
    }

    private func publishBackfill52(_ readings: [DirectG7BackfillReading], reason: String) {
        guard !readings.isEmpty,
              let sharedUserDefaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else { return }

        let stateKey = "complicationSharedUserDefaults.\\(Bundle.main.mainAppBundleIdentifier)"
        let sourceKey = "complicationDataSource.\\(Bundle.main.mainAppBundleIdentifier)"

        var payload: [String: Any] = [:]
        if let existingData = sharedUserDefaults.data(forKey: stateKey),
           let existingObject = try? JSONSerialization.jsonObject(with: existingData),
           let existingPayload = existingObject as? [String: Any] {
            payload = existingPayload
        }

        let existingDates = (payload["bgReadingDatesAsDouble"] as? [NSNumber])?.map { $0.doubleValue }
            ?? (payload["bgReadingDatesAsDouble"] as? [Double])
            ?? []
        let existingValues = (payload["bgReadingValues"] as? [NSNumber])?.map { $0.doubleValue }
            ?? (payload["bgReadingValues"] as? [Double])
            ?? []

        let count = min(existingDates.count, existingValues.count)
        var merged: [(Date, Double)] = (0..<count).map {
            (Date(timeIntervalSince1970: existingDates[$0]), existingValues[$0])
        }

        var inserted = 0
        for reading in readings {
            // Ignore impossible future records and records older than the 12h widget history.
            guard reading.date <= Date().addingTimeInterval(60),
                  reading.date > Date().addingTimeInterval(-12 * 60 * 60) else { continue }

            if merged.contains(where: { abs($0.0.timeIntervalSince(reading.date)) < 90 }) {
                continue
            }
            merged.append((reading.date, reading.glucoseMgDl))
            inserted += 1
            appendBgIngressTrace51(
                source: "DIRECT_G7",
                route: "CORE_BLUETOOTH_BACKFILL_3536",
                sampleDate: reading.date,
                bg: reading.glucoseMgDl,
                sequence: nil,
                batchCount: readings.count,
                newCount: 1
            )
        }

        guard inserted > 0 else {
            trace41("BACKFILL_WRITE none reason=\\(reason)")
            return
        }

        merged = merged
            .filter { $0.0 > Date().addingTimeInterval(-12 * 60 * 60) }
            .sorted { $0.0 > $1.0 }

        payload["bgReadingValues"] = merged.map { $0.1 }
        payload["bgReadingDatesAsDouble"] = merged.map { $0.0.timeIntervalSince1970 }

        // Historical backfill must never replace the live reading's trend/delta. Preserve all
        // current-state fields and only repair the time-series history.
        if payload["isMgDl"] == nil { payload["isMgDl"] = true }
        if payload["slopeOrdinal"] == nil { payload["slopeOrdinal"] = 4 }
        if payload["deltaValueInUserUnit"] == nil { payload["deltaValueInUserUnit"] = 0.0 }
        if payload["urgentLowLimitInMgDl"] == nil { payload["urgentLowLimitInMgDl"] = 60.0 }
        if payload["lowLimitInMgDl"] == nil { payload["lowLimitInMgDl"] = 80.0 }
        if payload["highLimitInMgDl"] == nil { payload["highLimitInMgDl"] = 170.0 }
        if payload["urgentHighLimitInMgDl"] == nil { payload["urgentHighLimitInMgDl"] = 250.0 }
        if payload["keepAliveIsDisabled"] == nil { payload["keepAliveIsDisabled"] = false }

        guard JSONSerialization.isValidJSONObject(payload),
              let encoded = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]) else {
            trace41("BACKFILL_STORE encode_failed")
            return
        }

        sharedUserDefaults.set(encoded, forKey: stateKey)
        sharedUserDefaults.set("G7 BLE Direct", forKey: sourceKey)
        sharedUserDefaults.set(inserted, forKey: "xdrip.g7Direct.build52.lastBackfillInserted")
        sharedUserDefaults.set(Date().timeIntervalSince1970, forKey: "xdrip.g7Direct.build52.lastBackfillWriteAt")

        // One bundle-wide invalidation makes graph/BG/delta consume the same freshly committed
        // App Group snapshot instead of racing three independent reload requests.
        WidgetCenter.shared.reloadAllTimelines()
        trace41("BACKFILL_WRITE inserted=\\(inserted) received=\\(readings.count) reason=\\(reason)")
    }

    private func flushBackfill52(reason: String) {
        guard !backfillBuffer52.isEmpty else { return }
        let readings = backfillBuffer52
        backfillBuffer52.removeAll(keepingCapacity: true)
        publishBackfill52(readings, reason: reason)
    }

"""
text = text.replace(anchor, helpers + anchor, 1)

# A single bundle reload prevents the graph from winning a three-request race against the two circles.
rep(
    """        for complicationKind in [\"xDripGraphV33\", \"xDripBGV36\", \"xDripDeltaV36\"] {
            WidgetCenter.shared.reloadTimelines(ofKind: complicationKind)
        }

        trace41(\"WIDGET_WRITE seq=\\(reading.sequence) bg=\\(Int(reading.glucoseMgDl))\")
""",
    """        WidgetCenter.shared.reloadAllTimelines()

        trace41(\"WIDGET_WRITE seq=\\(reading.sequence) bg=\\(Int(reading.glucoseMgDl)) reload=ALL\")
""",
    "unified widget reload",
)

# Keep the scan alive for verified advertisements even while AutoReconnect owns a peripheral object.
rep(
    """    func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String : Any],
        rssi RSSI: NSNumber
    ) {
        let name = peripheral.name ?? (advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? \"\")
        guard name.hasPrefix(\"DX\") else { return }
        inspect(peripheral)
    }
""",
    """    func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String : Any],
        rssi RSSI: NSNumber
    ) {
        let name = peripheral.name ?? (advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? \"\")

        // Once a real 0x4E has verified a peripheral, the recovery scan is deliberately pinned
        // to that exact xDrip peer. Never opportunistically jump to another G7 advertisement.
        if let verifiedID = verifiedPeripheralID() {
            guard peripheral.identifier == verifiedID else { return }
            targetPeripheral = peripheral
            peripheral.delegate = self
            lastDeviceName = name
            trace41(\"GAP_RECOVERY_ADV verified state=\\(peripheral.state.rawValue)\")
            switch peripheral.state {
            case .connected:
                central.stopScan()
                peripheral.discoverServices([serviceUUID])
            case .disconnected:
                connectVerifiedWithSystemAutoReconnect(peripheral, reason: \"gap-recovery-advertisement\")
            case .connecting:
                break
            case .disconnecting:
                break
            @unknown default:
                break
            }
            return
        }

        guard name.hasPrefix(\"DX\") else { return }
        inspect(peripheral)
    }
""",
    "verified advertisement recovery",
)

rep(
    """    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        trace41(\"CONNECTED \\(peripheral.name ?? \"unknown\") verified=\\(isVerifiedPeripheral(peripheral))\")
""",
    """    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        if central.isScanning { central.stopScan() }
        trace41(\"CONNECTED \\(peripheral.name ?? \"unknown\") verified=\\(isVerifiedPeripheral(peripheral))\")
""",
    "stop recovery scan on connect",
)

# Flush any passive backfill already received, then arm both AutoReconnect and advertisement scan.
rep(
    """        if isVerifiedPeripheral(peripheral) {
            targetPeripheral = peripheral
            publish(\"G7-Fenster beendet; System-AutoReconnect registriert\")
            if central.state == .poweredOn, peripheral.state == .disconnected {
                connectVerifiedWithSystemAutoReconnect(peripheral, reason: \"legacy-disconnect\")
            }
            return
        }
""",
    """        if isVerifiedPeripheral(peripheral) {
            flushBackfill52(reason: \"legacy-disconnect\")
            targetPeripheral = peripheral
            publish(\"G7-Fenster beendet; AutoReconnect + FEBC-Recovery-Scan\")
            if central.state == .poweredOn, peripheral.state == .disconnected {
                connectVerifiedWithSystemAutoReconnect(peripheral, reason: \"legacy-disconnect\")
            }
            scheduleGapRecoveryScan52(reason: \"legacy-disconnect\")
            return
        }
""",
    "legacy disconnect gap recovery",
)

rep(
    """        if isVerifiedPeripheral(peripheral) {
            targetPeripheral = peripheral
            registerVerifiedConnectionEvents(peripheral.identifier)
            if isReconnecting {
                publish(\"G7-Fenster beendet; CoreBluetooth wartet automatisch auf nächsten Sensorzyklus\")
            } else if central.state == .poweredOn, peripheral.state == .disconnected {
                publish(\"G7-Fenster beendet; AutoReconnect wird erneut registriert\")
                connectVerifiedWithSystemAutoReconnect(peripheral, reason: \"auto-disconnect-not-reconnecting\")
            }
            return
        }
""",
    """        if isVerifiedPeripheral(peripheral) {
            flushBackfill52(reason: \"auto-disconnect\")
            targetPeripheral = peripheral
            registerVerifiedConnectionEvents(peripheral.identifier)
            if isReconnecting {
                publish(\"G7-Fenster beendet; AutoReconnect + FEBC-Recovery-Scan\")
            } else if central.state == .poweredOn, peripheral.state == .disconnected {
                publish(\"G7-Fenster beendet; AutoReconnect wird erneut registriert\")
                connectVerifiedWithSystemAutoReconnect(peripheral, reason: \"auto-disconnect-not-reconnecting\")
            }
            scheduleGapRecoveryScan52(reason: \"auto-disconnect\")
            return
        }
""",
    "auto disconnect gap recovery",
)

# On connection events re-arm GATT immediately; this is idempotent with didConnect.
rep(
    """        trace41(\"CONNECTION_EVENT \\(label) state=\\(peripheral.state.rawValue)\")
    }
""",
    """        trace41(\"CONNECTION_EVENT \\(label) state=\\(peripheral.state.rawValue)\")
        if event == .peerConnected, peripheral.state == .connected {
            if central.isScanning { central.stopScan() }
            peripheral.discoverServices([serviceUUID])
        }
    }
""",
    "connection event GATT rearm",
)

# Route passive 3536 backfill and the 0x59 end marker before the existing live 0x4E path.
needle = """    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard error == nil, let value = characteristic.value, !value.isEmpty else { return }

        if characteristic.uuid == authUUID, value.count >= 3, value[0] == 0x05 {
"""
replacement = """    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard error == nil, let value = characteristic.value, !value.isEmpty else { return }

        if characteristic.uuid == backfillUUID {
            if let reading = parseBackfill52(value) {
                if !backfillBuffer52.contains(where: { abs($0.date.timeIntervalSince(reading.date)) < 30 }) {
                    backfillBuffer52.append(reading)
                    trace41(\"BACKFILL_RX bg=\\(Int(reading.glucoseMgDl)) sample=\\(Int(reading.date.timeIntervalSince1970))\")
                }
            } else {
                trace41(\"BACKFILL_RX rejected len=\\(value.count)\")
            }
            return
        }

        if characteristic.uuid == controlUUID, value[0] == 0x59 {
            trace41(\"BACKFILL_FINISHED count=\\(backfillBuffer52.count)\")
            flushBackfill52(reason: \"0x59-finished\")
            return
        }

        if characteristic.uuid == authUUID, value.count >= 3, value[0] == 0x05 {
"""
if text.count(needle) != 1:
    raise RuntimeError(f"backfill callback anchor expected once, found {text.count(needle)}")
text = text.replace(needle, replacement, 1)

# Establish the sensor activation epoch from every valid live packet and report sequence gaps.
rep(
    """        let seq41 = value.count >= 8 ? littleEndianUInt16(value, offset: 6) : 0
        let bg41 = value.count >= 14 ? Int(littleEndianUInt16(value, offset: 12) & 0x0FFF) : -1
        trace41(\"RX4E seq=\\(seq41) bg=\\(bg41) auth=\\(authenticated)\")
""",
    """        let seq41 = value.count >= 8 ? littleEndianUInt16(value, offset: 6) : 0
        let bg41 = value.count >= 14 ? Int(littleEndianUInt16(value, offset: 12) & 0x0FFF) : -1
        if value.count >= 11 {
            let messageTimestamp52 = littleEndianUInt32(value, offset: 2)
            let messageAge52 = TimeInterval(value[10])
            sensorActivationDate52 = Date().addingTimeInterval(-TimeInterval(messageTimestamp52) - messageAge52)
        }
        trace41(\"RX4E seq=\\(seq41) bg=\\(bg41) auth=\\(authenticated)\")
""",
    "activation epoch",
)

rep(
    """        appendBgIngressTrace51(
            source: \"DIRECT_G7\",
            route: \"CORE_BLUETOOTH_0x4E\",
            sampleDate: reading.date,
            bg: reading.glucoseMgDl,
            sequence: reading.sequence,
            batchCount: 1,
            newCount: 1
        )

        // Build 43/46: every valid sensor packet goes directly to the existing widgets.
""",
    """        if let previous = lastLiveSequence52 {
            let expected = previous &+ 1
            if reading.sequence != expected {
                let gap = (Int(reading.sequence) - Int(expected) + 65536) % 65536
                if gap > 0 && gap < 100 {
                    trace41(\"MISSED_SEQ expected=\\(expected) received=\\(reading.sequence) count=\\(gap)\")
                }
            }
        }
        lastLiveSequence52 = reading.sequence

        appendBgIngressTrace51(
            source: \"DIRECT_G7\",
            route: \"CORE_BLUETOOTH_0x4E\",
            sampleDate: reading.date,
            bg: reading.glucoseMgDl,
            sequence: reading.sequence,
            batchCount: 1,
            newCount: 1
        )

        // Build 43/46/52: every valid sensor packet goes directly to the existing widgets.
""",
    "sequence gap trace",
)

WATCH_STATE.write_text(text, encoding="utf-8")
print("Build 52 gapless Direct-G7 scan/backfill patch applied.")
