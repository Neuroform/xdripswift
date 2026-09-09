from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1))


# Build 14 runs AFTER Build 13.
# It keeps the successful Build 13 transport unchanged: manual foreground test,
# name-independent FEBC + 3532 + exact 3534/3535/3536/3538 fingerprint, CCCD Notify only.
# Build 14 adds READ-ONLY decoding/classification of spontaneous packets already delivered
# by CoreBluetooth. It does NOT call writeValue(), does NOT send a Dexcom application command,
# does NOT update the xDrip graph/complication from the decoded value, and does NOT enable
# background BLE. The existing stale-BG safety remains authoritative for the xDrip complication.

watch_state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")

replace_once(
    watch_state,
    '''    private var firstRXAt: Date?

    private var overallTimeoutTask: DispatchWorkItem?''',
    '''    private var firstRXAt: Date?
    private var latestPassiveBGSummary = ""

    private var overallTimeoutTask: DispatchWorkItem?''',
    "Build14 passive BG summary state",
)

replace_once(
    watch_state,
    '''        rxCounts.removeAll()
        firstRXAt = nil
        latestRXHex = ""
    }''',
    '''        rxCounts.removeAll()
        firstRXAt = nil
        latestRXHex = ""
        latestPassiveBGSummary = ""
    }''',
    "Build14 reset passive BG summary",
)

replace_once(
    watch_state,
    '''        addEvent("Build13 gestartet · FEBC/GATT-Match · Name ignoriert")
        addEvent("Nur CCCD Notify · Dexcom-App-TX = 0")''',
    '''        addEvent("Build14 gestartet · passiver 0x4E-BG-Decoder")
        addEvent("FEBC/GATT-Match · Name ignoriert · nur CCCD Notify")
        addEvent("Dexcom-App-TX = 0 · Decoder schreibt NICHT in xDrip-BG")''',
    "Build14 startup telemetry",
)

replace_once(
    watch_state,
    '''    private func hex(_ data: Data) -> String {
        data.map { String(format: "%02X", $0) }.joined()
    }

    private func remainingSeconds() -> TimeInterval {''',
    '''    private func hex(_ data: Data) -> String {
        data.map { String(format: "%02X", $0) }.joined()
    }

    private func littleEndianUInt16(_ data: Data, offset: Int) -> UInt16 {
        UInt16(data[offset]) | (UInt16(data[offset + 1]) << 8)
    }

    private func littleEndianUInt32(_ data: Data, offset: Int) -> UInt32 {
        UInt32(data[offset])
            | (UInt32(data[offset + 1]) << 8)
            | (UInt32(data[offset + 2]) << 16)
            | (UInt32(data[offset + 3]) << 24)
    }

    /// Decode only packets that the sensor has already notified to us. This mirrors the
    /// established G7 real-time packet field layout used by xDrip/Loop-style G7 parsers:
    /// opcode 0x4E, message timestamp @2, sequence @6, age @10, glucose @12,
    /// algorithm state @14, trend @15. No application-level BLE write is performed here.
    private func passivePacketSummary(_ data: Data, characteristic: CBCharacteristic) -> String? {
        let channel = shortUUID(characteristic.uuid)

        if channel == "F8083534", data.count >= 19, data[0] == 0x4E, data[1] == 0x00 {
            let messageTimestamp = littleEndianUInt32(data, offset: 2)
            let sequence = littleEndianUInt16(data, offset: 6)
            let ageSeconds = Int(data[10])
            let glucoseWord = littleEndianUInt16(data, offset: 12)
            let glucose = Int(glucoseWord & 0x0FFF)
            let algorithmState = Int(data[14])
            let trendRaw = Int(Int8(bitPattern: data[15]))
            let trend = Double(trendRaw) / 10.0

            addEvent(
                String(
                    format: "DECODE 0x4E ts=%u seq=%u age=%ds BG=%d state=%d trend=%+.1f",
                    messageTimestamp,
                    sequence,
                    ageSeconds,
                    glucose,
                    algorithmState,
                    trend
                )
            )

            guard (20...600).contains(glucose) else {
                return "0x4E erkannt · BG-Feld unplausibel: \\(glucose) · nur Diagnose"
            }

            // The diagnostic page may display a decoded value, but an unexpectedly old packet
            // is explicitly labelled as not current and is never written to xDrip state.
            guard ageSeconds <= 7 * 60 else {
                return "0x4E erkannt · \\(glucose) mg/dL · Alter \\(ageSeconds)s · NICHT AKTUELL"
            }

            return String(
                format: "PASSIV-BG %d mg/dL · Alter %ds · Trend %+.1f/min · Seq %u · State %d",
                glucose,
                ageSeconds,
                trend,
                sequence,
                algorithmState
            )
        }

        if channel == "F8083535", data.count >= 1, data[0] == 0x03 {
            return "PASSIV Auth-Challenge 0x03 · \\(data.count) Byte · keine Antwort"
        }

        if channel == "F8083535", data.count >= 3, data[0] == 0x05 {
            return String(format: "PASSIV Auth-Status 05 %02X %02X · keine TX", data[1], data[2])
        }

        if channel == "F8083534", let opcode = data.first {
            return String(format: "PASSIV 3534 Opcode 0x%02X · %d Byte", opcode, data.count)
        }

        if channel == "F8083536" {
            return "PASSIV 3536 Notify · \\(data.count) Byte"
        }

        if channel == "F8083538" {
            return "PASSIV 3538 Notify · \\(data.count) Byte"
        }

        return nil
    }

    private func remainingSeconds() -> TimeInterval {''',
    "Build14 passive packet decoder helpers",
)

replace_once(
    watch_state,
    '''        addEvent("SPONTAN-RX erkannt · sammle noch \\(Int(captureAfterFirstRXSeconds)) s")
        publish("Spontane G7-Notify-Daten empfangen · RX \\(rxTotal)")

        let task = DispatchWorkItem { [weak self, weak peripheral] in
            guard let self, self.running,
                  let peripheral,
                  self.targetPeripheral?.identifier == peripheral.identifier else { return }
            self.requestLocalDisconnect(
                finalStatus: "Spontane Notify-Daten empfangen · \\(self.rxTotal) Pakete · Dexcom-TX 0",
                finish: true
            )
        }''',
    '''        addEvent("SPONTAN-RX erkannt · sammle noch \\(Int(captureAfterFirstRXSeconds)) s")
        if latestPassiveBGSummary.isEmpty {
            publish("Spontane G7-Notify-Daten empfangen · RX \\(rxTotal)")
        } else {
            publish("\\(latestPassiveBGSummary) · RX \\(rxTotal) · TX 0")
        }

        let task = DispatchWorkItem { [weak self, weak peripheral] in
            guard let self, self.running,
                  let peripheral,
                  self.targetPeripheral?.identifier == peripheral.identifier else { return }
            let finalStatus = self.latestPassiveBGSummary.isEmpty
                ? "Spontane Notify-Daten empfangen · \\(self.rxTotal) Pakete · Dexcom-TX 0"
                : "\\(self.latestPassiveBGSummary) · \\(self.rxTotal) Pakete · Dexcom-TX 0"
            self.requestLocalDisconnect(
                finalStatus: finalStatus,
                finish: true
            )
        }''',
    "Build14 preserve decoded BG in final status",
)

replace_once(
    watch_state,
    '''        if firstRXAt == nil {
            firstRXAt = Date()
            addEvent("ERSTER SPONTAN-RX · nach \\(elapsedMS(from: connectedAt))")
        }

        publish("Spontan-RX \\(rxTotal) · letzter \\(shortUUID(characteristic.uuid)) · Dexcom-TX 0")
        scheduleFinishAfterRX(for: peripheral)''',
    '''        if firstRXAt == nil {
            firstRXAt = Date()
            addEvent("ERSTER SPONTAN-RX · nach \\(elapsedMS(from: connectedAt))")
        }

        if let decoded = passivePacketSummary(data, characteristic: characteristic) {
            addEvent("KLASSE: \\(decoded)")
            if decoded.hasPrefix("PASSIV-BG ") {
                latestPassiveBGSummary = decoded
            }
        }

        if latestPassiveBGSummary.isEmpty {
            publish("Spontan-RX \\(rxTotal) · letzter \\(shortUUID(characteristic.uuid)) · Dexcom-TX 0")
        } else {
            publish("\\(latestPassiveBGSummary) · RX \\(rxTotal) · TX 0")
        }
        scheduleFinishAfterRX(for: peripheral)''',
    "Build14 decode spontaneous notifications",
)

root = Path("xDrip Watch App/Views/RootView.swift")

replace_once(
    root,
    'Text("Build 13 Notify Listener · name-unabhängig")',
    'Text("Build 14 Passive BG Decoder · kein Dexcom-TX")',
    "Build14 page title",
)

replace_once(
    root,
    'Text("Separater G7-Notify-Test")',
    'Text("Separater passiver G7-BG-Decoder")',
    "Build14 section title",
)

replace_once(
    root,
    'Text("Der Test läuft nur nach Tippen und beobachtet bis zu 10 Minuten mehrere Verbindungsfenster. Ein Sensorname wie DXCMD2/DXCMam wird NICHT zur Identifikation verwendet. Kandidaten werden über FEBC und danach über den G7-GATT-Fingerprint 3532 + 3534/3535/3536/3538 bestätigt. Erst dann werden diese vier Channels per BLE-Notify abonniert. Es gibt KEIN Dexcom-Protokoll-TX, kein AuthRequest, kein Pairing/Bonding und keine Session-/Kalibrierungsaktion.")',
    'Text("Der Test läuft nur nach Tippen. Der Sensorname wird weiterhin NICHT zur Identifikation verwendet: FEBC + Service 3532 + 3534/3535/3536/3538 bilden den G7-Fingerprint. Build 14 decodiert ausschließlich spontan empfangene Notify-Pakete. Ein 0x4E-Paket auf 3534 wird diagnostisch als BG/Alter/Trend/Sequenz/State angezeigt. Der Wert wird NICHT in den xDrip-Graph oder die Komplikation geschrieben. Es gibt KEIN Dexcom-Protokoll-TX, kein AuthRequest, kein Pairing/Bonding und keine Session-/Kalibrierungsaktion.")',
    "Build14 explanation",
)

replace_once(
    root,
    'row("Notify-Test", watchState.g7AuthProbeStatus)',
    'row("Passive Decode", watchState.g7AuthProbeStatus)',
    "Build14 status row",
)

replace_once(
    root,
    'Button(watchState.g7AuthProbeRunning ? "Notify-Test abbrechen" : "Notify-Test starten")',
    'Button(watchState.g7AuthProbeRunning ? "Decoder-Test abbrechen" : "Decoder-Test starten")',
    "Build14 button",
)

replace_once(
    root,
    'Text("Während des Tests bitte die Dexcom-Komplikation beobachten. Build 13 verändert nur die BLE-CCCD-Subscription für die kurzzeitige Testverbindung. Es wird kein Dexcom-Anwendungsprotokoll geschrieben und kein automatischer Background-Reconnect gestartet. Der Sensorname ist reine Telemetrie und kein Match-Kriterium.")',
    'Text("Während des Tests bitte die Dexcom-Komplikation beobachten. Build 14 verändert gegenüber Build 13 nur die lokale Auswertung der bereits empfangenen Bytes. Auf BLE-Ebene bleibt es bei CCCD Notify; Dexcom-Anwendungs-TX = 0. Kein automatischer Background-Reconnect. Die bestehende xDrip-Sicherheitslogik zeigt bei fehlendem aktuellen BG weiterhin --- statt eines alten Werts.")',
    "Build14 safety footer",
)

print("Build 14 passive G7 BG decoder applied successfully.")
