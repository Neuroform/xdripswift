from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def insert_once_in_direct_manager(path: Path, anchor: str, insertion: str, label: str) -> None:
    """Insert only inside the proven G7DirectBLEManager block.

    Build 42 contains other diagnostic BLE helpers with identically named utility methods.
    Global text replacement is therefore intentionally forbidden here.
    """
    text = path.read_text(encoding="utf-8")
    start_marker = "// MARK: - Direct G7 BLE manager"
    end_marker = "// MARK: - WCSession delegate"
    start = text.find(start_marker)
    end = text.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0:
        raise RuntimeError(f"{label}: Direct G7 manager boundaries not found in {path}")

    manager = text[start:end]
    count = manager.count(anchor)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor inside Direct G7 manager, found {count}")

    manager = manager.replace(anchor, insertion + anchor, 1)
    path.write_text(text[:start] + manager + text[end:], encoding="utf-8")


# Build 43 starts DIRECTLY from the permanent Build 42 functional baseline.
# It does not touch any widget layout, widget registration, WatchConnectivity transport,
# G7 parser, Direct-G7 discovery/reconnect/restoration code, or RootView.
#
# The only functional change is this:
# every valid direct 0x4E G7 reading is written straight from G7DirectBLEManager into the
# existing App Group complication payload and the three existing widgets are reloaded.
# WatchStateModel remains a consumer of the same reading when its existing auth state allows it,
# but it is no longer required for the widget payload to be updated.

state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")

bridge_methods = r'''
    // Build 43: direct sensor -> App Group -> existing widgets bridge.
    // This path deliberately bypasses WatchStateModel. It runs synchronously from the
    // CoreBluetooth 0x4E receive callback so a fresh G7 value does not wait for the Watch UI.
    private func publishReadingDirectlyToWidgets(_ reading: DirectG7Reading) {
        guard let sharedUserDefaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else {
            trace41("WIDGET_STORE unavailable")
            return
        }

        let stateKey = "complicationSharedUserDefaults.\(Bundle.main.mainAppBundleIdentifier)"
        let sourceKey = "complicationDataSource.\(Bundle.main.mainAppBundleIdentifier)"

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

        // Replace a duplicate copy of the same five-minute sample and keep only recent history.
        merged.removeAll { abs($0.0.timeIntervalSince(reading.date)) < 90 }
        merged.append((reading.date, reading.glucoseMgDl))
        merged = merged
            .filter { $0.0 > Date().addingTimeInterval(-12 * 60 * 60) }
            .sorted { $0.0 > $1.0 }

        let isMgDl = (payload["isMgDl"] as? Bool) ?? true
        let slopeOrdinal = directWidgetSlopeOrdinal(for: reading.trendMgDlPerMinute)

        var deltaValueInUserUnit = 0.0
        if merged.count > 1 {
            let previous = merged[1]
            let interval = reading.date.timeIntervalSince(previous.0)
            if interval > 0, interval <= 7.5 * 60 {
                if isMgDl {
                    deltaValueInUserUnit = reading.glucoseMgDl - previous.1
                } else {
                    let currentMmol = ((reading.glucoseMgDl / 18.0182) * 10).rounded() / 10
                    let previousMmol = ((previous.1 / 18.0182) * 10).rounded() / 10
                    deltaValueInUserUnit = currentMmol - previousMmol
                }
            }
        }

        payload["bgReadingValues"] = merged.map { $0.1 }
        payload["bgReadingDatesAsDouble"] = merged.map { $0.0.timeIntervalSince1970 }
        payload["isMgDl"] = isMgDl
        payload["slopeOrdinal"] = slopeOrdinal
        payload["deltaValueInUserUnit"] = deltaValueInUserUnit

        // These fields are required by ComplicationSharedUserDefaultsModel. Preserve any
        // user/app values already present; use the WatchStateModel defaults only for a truly
        // empty store, e.g. directly after an app update before the UI has ever been opened.
        if payload["urgentLowLimitInMgDl"] == nil { payload["urgentLowLimitInMgDl"] = 60.0 }
        if payload["lowLimitInMgDl"] == nil { payload["lowLimitInMgDl"] = 80.0 }
        if payload["highLimitInMgDl"] == nil { payload["highLimitInMgDl"] = 170.0 }
        if payload["urgentHighLimitInMgDl"] == nil { payload["urgentHighLimitInMgDl"] = 250.0 }
        if payload["keepAliveIsDisabled"] == nil { payload["keepAliveIsDisabled"] = false }

        guard JSONSerialization.isValidJSONObject(payload),
              let encoded = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]) else {
            trace41("WIDGET_STORE encode_failed")
            return
        }

        // Persist before requesting a reload. The Widget Provider already reads this exact key.
        sharedUserDefaults.set(encoded, forKey: stateKey)
        sharedUserDefaults.set("G7 BLE Direct", forKey: sourceKey)
        sharedUserDefaults.set(reading.date.timeIntervalSince1970, forKey: "xdrip.g7Direct.widgetBridge43.lastReadingDate")
        sharedUserDefaults.set(reading.glucoseMgDl, forKey: "xdrip.g7Direct.widgetBridge43.lastBG")
        sharedUserDefaults.set(Int(reading.sequence), forKey: "xdrip.g7Direct.widgetBridge43.lastSequence")
        sharedUserDefaults.set(Date().timeIntervalSince1970, forKey: "xdrip.g7Direct.widgetBridge43.lastWriteAt")

        for complicationKind in ["xDripGraphV33", "xDripBGV36", "xDripDeltaV36"] {
            WidgetCenter.shared.reloadTimelines(ofKind: complicationKind)
        }

        trace41("WIDGET_WRITE seq=\(reading.sequence) bg=\(Int(reading.glucoseMgDl))")
    }

    private func directWidgetSlopeOrdinal(for trend: Double?) -> Int {
        guard let trend else { return 0 }
        if trend >= 3 { return 1 }
        if trend >= 2 { return 2 }
        if trend >= 1 { return 3 }
        if trend > -1 { return 4 }
        if trend > -2 { return 5 }
        if trend > -3 { return 6 }
        return 7
    }

'''

# Build 42 contains two littleEndianUInt16 helpers (Direct-G7 + manual auth diagnostics).
# Anchor the insertion strictly inside the Direct-G7 manager to avoid the exact ambiguity
# that caused Build 43 run #1 to stop before Xcode.
insert_once_in_direct_manager(
    state,
    '''    private func littleEndianUInt16(_ data: Data, offset: Int) -> UInt16 {''',
    bridge_methods,
    "insert direct widget bridge",
)

old_receive = r'''        guard characteristic.uuid == controlUUID, value[0] == 0x4E else { return }

        let seq41 = value.count >= 8 ? littleEndianUInt16(value, offset: 6) : 0
        let bg41 = value.count >= 14 ? Int(littleEndianUInt16(value, offset: 12) & 0x0FFF) : -1
        trace41("RX4E seq=\(seq41) bg=\(bg41) auth=\(authenticated)")

        guard authenticated else {
            pendingGlucosePacket = value
            publish("0x4E empfangen; warte auf Auth-Freigabe")
            return
        }

        guard let reading = parseG7Glucose(value) else {
            publish("0x4E empfangen; Parser abgelehnt")
            return
        }

        publish("Direct BG \(Int(reading.glucoseMgDl)) mg/dL")
        onReading(reading)'''

new_receive = r'''        guard characteristic.uuid == controlUUID, value[0] == 0x4E else { return }

        let seq41 = value.count >= 8 ? littleEndianUInt16(value, offset: 6) : 0
        let bg41 = value.count >= 14 ? Int(littleEndianUInt16(value, offset: 12) & 0x0FFF) : -1
        trace41("RX4E seq=\(seq41) bg=\(bg41) auth=\(authenticated)")

        guard let reading = parseG7Glucose(value) else {
            publish("0x4E empfangen; Parser abgelehnt")
            return
        }

        // Build 43: the widget payload is updated immediately from the sensor packet.
        // This deliberately happens BEFORE the existing WatchStateModel/auth gate.
        publishReadingDirectlyToWidgets(reading)

        guard authenticated else {
            pendingGlucosePacket = value
            publish("0x4E empfangen · Widgets direkt aktualisiert")
            return
        }

        publish("Direct BG \(Int(reading.glucoseMgDl)) mg/dL")
        onReading(reading)'''

# This receive sequence is unique to the production Direct-G7 manager in Build 42.
replace_once(state, old_receive, new_receive, "route 0x4E directly to widget bridge")

print("Build 43 applied: every valid direct G7 0x4E packet now writes straight to App Group and reloads the existing widgets; UI/widgets unchanged.")
