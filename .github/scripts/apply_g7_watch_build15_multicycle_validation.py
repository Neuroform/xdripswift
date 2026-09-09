from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1))


def replace_between(path: Path, start: str, end: str, replacement: str, label: str) -> None:
    text = path.read_text()
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"{label}: start marker not found in {path}")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"{label}: end marker not found in {path}")
    path.write_text(text[:start_index] + replacement + text[end_index:])


# Build 15 runs AFTER Build 14.
# Build 14 proved that a spontaneous F8083534 0x4E packet decoded on Apple Watch
# matched the official Dexcom value (97 mg/dL at 20:19). Build 15 is deliberately
# still diagnostic/read-only: it validates repeated G7 measurement cycles before any
# decoded value is allowed to feed xDrip state or the complication.
#
# Goals:
# - manual foreground validation window up to 45 minutes
# - collect unique passive 0x4E BG packets across repeated G7 connection windows
# - verify a run of 6 consecutive sequence numbers (roughly 25 minutes of G7 cycles)
# - preserve BG/age/trend/sequence/state telemetry for comparison with Dexcom
# - disconnect after each short capture window and scan again
# - CCCD Notify only; NO Dexcom application-protocol TX, auth response, session command,
#   calibration command, background BLE, or writes into xDrip/complication state

watch_state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")

replace_once(
    watch_state,
    '    private let testWindowSeconds: TimeInterval = 600\n',
    '    private let testWindowSeconds: TimeInterval = 2700\n',
    "Build15 45-minute validation window",
)

replace_once(
    watch_state,
    '''    private let captureAfterFirstRXSeconds: TimeInterval = 3
''',
    '''    private let captureAfterFirstRXSeconds: TimeInterval = 4
    private let targetConsecutiveBGReadings = 6
''',
    "Build15 capture window and target",
)

replace_once(
    watch_state,
    '''    private var firstRXAt: Date?
    private var latestPassiveBGSummary = ""

    private var overallTimeoutTask: DispatchWorkItem?''',
    '''    private var firstRXAt: Date?
    private var latestPassiveBGSummary = ""

    // Build 15 validation state is intentionally kept across retry/disconnect attempts.
    // Per-attempt BLE state is still reset normally.
    private var capturedBGReadings: [String] = []
    private var capturedBGSequences = Set<UInt16>()
    private var lastCapturedBGSequence: UInt16?
    private var consecutiveBGRun = 0
    private var longestConsecutiveBGRun = 0
    private var duplicateBGPackets = 0

    private var overallTimeoutTask: DispatchWorkItem?''',
    "Build15 cumulative validation state",
)

replace_once(
    watch_state,
    '''        attemptCount = 0
        resetPerAttemptData()''',
    '''        attemptCount = 0
        capturedBGReadings.removeAll()
        capturedBGSequences.removeAll()
        lastCapturedBGSequence = nil
        consecutiveBGRun = 0
        longestConsecutiveBGRun = 0
        duplicateBGPackets = 0
        resetPerAttemptData()''',
    "Build15 reset cumulative validation state on manual start",
)

replace_once(
    watch_state,
    '''        addEvent("Build14 gestartet · passiver 0x4E-BG-Decoder")
        addEvent("FEBC/GATT-Match · Name ignoriert · nur CCCD Notify")
        addEvent("Dexcom-App-TX = 0 · Decoder schreibt NICHT in xDrip-BG")''',
    '''        addEvent("Build15 gestartet · Multi-Cycle 0x4E-Validierung")
        addEvent("45 min max · Ziel 6 fortlaufende BG-Sequenzen")
        addEvent("FEBC/GATT-Match · Name ignoriert · nur CCCD Notify")
        addEvent("Dexcom-App-TX = 0 · KEIN Schreiben in xDrip/Komplikation")''',
    "Build15 startup telemetry",
)

replace_once(
    watch_state,
    '''        if eventLog.count > 100 {
            eventLog.removeFirst(eventLog.count - 100)
        }''',
    '''        if eventLog.count > 240 {
            eventLog.removeFirst(eventLog.count - 240)
        }''',
    "Build15 larger telemetry buffer",
)

replace_once(
    watch_state,
    '        addEvent("Notify-Multi-Window gestartet: 600 s")',
    '        addEvent("Build15 Multi-Cycle-Fenster gestartet: 2700 s / 45 min")',
    "Build15 observation window telemetry",
)

# Insert cumulative validation helpers immediately before remainingSeconds().
replace_once(
    watch_state,
    '''    private func remainingSeconds() -> TimeInterval {''',
    r'''    private func recordPassiveBGPacket(_ data: Data) {
        guard data.count >= 19, data[0] == 0x4E, data[1] == 0x00 else { return }

        let messageTimestamp = littleEndianUInt32(data, offset: 2)
        let sequence = littleEndianUInt16(data, offset: 6)
        let ageSeconds = Int(data[10])
        let glucoseWord = littleEndianUInt16(data, offset: 12)
        let glucose = Int(glucoseWord & 0x0FFF)
        let algorithmState = Int(data[14])
        let trendRaw = Int(Int8(bitPattern: data[15]))
        let trend = Double(trendRaw) / 10.0

        guard (20...600).contains(glucose), ageSeconds <= 7 * 60 else { return }

        guard capturedBGSequences.insert(sequence).inserted else {
            duplicateBGPackets += 1
            addEvent("VALIDIERUNG DUP · Seq \(sequence) · BG \(glucose) · duplicates \(duplicateBGPackets)")
            return
        }

        if let previous = lastCapturedBGSequence, sequence == previous &+ 1 {
            consecutiveBGRun += 1
        } else {
            consecutiveBGRun = 1
        }
        lastCapturedBGSequence = sequence
        longestConsecutiveBGRun = max(longestConsecutiveBGRun, consecutiveBGRun)

        let item = String(
            format: "%@ · BG %d · Seq %u · age %ds · trend %+.1f · state %d · ts %u",
            timestamp(),
            glucose,
            sequence,
            ageSeconds,
            trend,
            algorithmState,
            messageTimestamp
        )
        capturedBGReadings.append(item)
        addEvent(
            "VALIDIERUNG BG#\(capturedBGReadings.count) · Serie \(consecutiveBGRun)/\(targetConsecutiveBGReadings) · \(item)"
        )
    }

    private func validationStatusLine() -> String {
        let base = "BG \(capturedBGReadings.count) unique · Serie \(consecutiveBGRun)/\(targetConsecutiveBGReadings) · Max \(longestConsecutiveBGRun)"
        if latestPassiveBGSummary.isEmpty {
            return base
        }
        return "\(base) · \(latestPassiveBGSummary)"
    }

    private func appendValidationSummaryEvents() {
        addEvent(
            "BUILD15 ERGEBNIS · \(capturedBGReadings.count) unique BG · längste Serie \(longestConsecutiveBGRun)/\(targetConsecutiveBGReadings) · Duplikate \(duplicateBGPackets)"
        )
        for (index, item) in capturedBGReadings.enumerated() {
            addEvent("ERGEBNIS #\(index + 1) · \(item)")
        }
    }

    private func remainingSeconds() -> TimeInterval {''',
    "Build15 cumulative BG validation helpers",
)

# Replace the 10-minute Build 13/14 timeout with a 45-minute validation result.
replace_between(
    watch_state,
    "    private func armOverallTimeout() {",
    "    private func scheduleStatusTick() {",
    r'''    private func armOverallTimeout() {
        overallTimeoutTask?.cancel()
        let task = DispatchWorkItem { [weak self] in
            guard let self, self.running else { return }
            self.addEvent(
                "45-Min-Fenster beendet · Attempts=\(self.attemptCount) · BG=\(self.capturedBGReadings.count) · MaxSerie=\(self.longestConsecutiveBGRun)"
            )
            self.appendValidationSummaryEvents()
            let finalStatus = "Build15 Zeitfenster beendet · \(self.validationStatusLine())"
            if let peripheral = self.targetPeripheral,
               peripheral.state == .connected || peripheral.state == .connecting {
                self.requestLocalDisconnect(finalStatus: finalStatus, finish: true)
            } else {
                self.finishWithoutConnection(finalStatus)
            }
        }
        overallTimeoutTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + testWindowSeconds, execute: task)
    }

''',
    "Build15 overall timeout",
)

replace_between(
    watch_state,
    "    private func scheduleStatusTick() {",
    "    private func startScan() {",
    r'''    private func scheduleStatusTick() {
        statusTickTask?.cancel()
        guard running else { return }

        let remaining = remainingSeconds()
        publish(
            "Build15 · \(validationStatusLine()) · Rest \(formatRemaining(remaining)) · Attempts \(attemptCount)"
        )

        guard remaining > 0 else { return }
        let task = DispatchWorkItem { [weak self] in
            self?.scheduleStatusTick()
        }
        statusTickTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + 10, execute: task)
    }

''',
    "Build15 status tick",
)

# If the retry path reaches the 45-minute deadline first, finish with the accumulated result.
replace_once(
    watch_state,
    '''        guard remaining > 0 else {
            finishWithoutConnection("10-Min-Notify-Test beendet · kein spontanes RX")
            return
        }''',
    '''        guard remaining > 0 else {
            appendValidationSummaryEvents()
            finishWithoutConnection("Build15 Zeitfenster beendet · \\(validationStatusLine())")
            return
        }''',
    "Build15 retry deadline result",
)

# Build 14 already validates the packet before this block. Record each fresh/valid 0x4E
# packet once, keyed by sequence number, while keeping latestPassiveBGSummary for display.
replace_once(
    watch_state,
    '''        if let decoded = passivePacketSummary(data, characteristic: characteristic) {
            addEvent("KLASSE: \\(decoded)")
            if decoded.hasPrefix("PASSIV-BG ") {
                latestPassiveBGSummary = decoded
            }
        }''',
    '''        if let decoded = passivePacketSummary(data, characteristic: characteristic) {
            addEvent("KLASSE: \\(decoded)")
            if decoded.hasPrefix("PASSIV-BG ") {
                latestPassiveBGSummary = decoded
                recordPassiveBGPacket(data)
            }
        }''',
    "Build15 record decoded BG across attempts",
)

# Do not end the whole diagnostic after the first RX window. Disconnect briefly and retry
# until 6 consecutive G7 sequence numbers are captured, or the 45-minute limit is reached.
replace_between(
    watch_state,
    "    private func scheduleFinishAfterRX(for peripheral: CBPeripheral) {",
    "    private func requestLocalDisconnect(",
    r'''    private func scheduleFinishAfterRX(for peripheral: CBPeripheral) {
        guard rxFinishTask == nil else { return }
        passiveListenTask?.cancel()
        passiveListenTask = nil

        addEvent("SPONTAN-RX erkannt · sammle noch \(Int(captureAfterFirstRXSeconds)) s")
        publish("Build15 · \(validationStatusLine()) · sammle RX-Fenster")

        let task = DispatchWorkItem { [weak self, weak peripheral] in
            guard let self, self.running,
                  let peripheral,
                  self.targetPeripheral?.identifier == peripheral.identifier else { return }

            let reachedTarget = self.consecutiveBGRun >= self.targetConsecutiveBGReadings
            if reachedTarget {
                self.addEvent("ZIEL ERREICHT · 6 fortlaufende G7-BG-Sequenzen")
                self.appendValidationSummaryEvents()
                self.requestLocalDisconnect(
                    finalStatus: "Build15 BESTÄTIGT · \(self.validationStatusLine()) · Dexcom-TX 0",
                    finish: true
                )
            } else {
                self.requestLocalDisconnect(
                    finalStatus: "Build15 Fenster erfasst · \(self.validationStatusLine()) · Dexcom-TX 0",
                    retry: true
                )
            }
        }
        rxFinishTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + captureAfterFirstRXSeconds, execute: task)
    }

''',
    "Build15 repeated RX windows",
)

# A sensor/CoreBluetooth remote disconnect after RX must also continue the validation unless
# the six-reading consecutive target has already been met.
replace_once(
    watch_state,
    '''        } else if rxTotal > 0 {
            finishRemoteAfterRX("Remote-Disconnect nach spontanen RX · \\(rxTotal) Pakete · Dexcom-TX 0")
        } else {
            scheduleRetry("Remote-Disconnect nach \\(elapsedMS(from: connectedAt))")
        }''',
    '''        } else if consecutiveBGRun >= targetConsecutiveBGReadings {
            appendValidationSummaryEvents()
            finishRemoteAfterRX("Build15 BESTÄTIGT · \\(validationStatusLine()) · Dexcom-TX 0")
        } else if rxTotal > 0 {
            scheduleRetry("Remote-Disconnect nach RX · \\(validationStatusLine())")
        } else {
            scheduleRetry("Remote-Disconnect nach \\(elapsedMS(from: connectedAt))")
        }''',
    "Build15 remote disconnect continues validation",
)

root = Path("xDrip Watch App/Views/RootView.swift")

replace_once(
    root,
    'Text("Build 14 Passive BG Decoder · kein Dexcom-TX")',
    'Text("Build 15 Multi-Cycle Validation · 6 direkte BG")',
    "Build15 page title",
)

replace_once(
    root,
    'Text("Separater passiver G7-BG-Decoder")',
    'Text("Build 15 G7 Multi-Cycle-Validierung")',
    "Build15 section title",
)

replace_once(
    root,
    'Text("Der Test läuft nur nach Tippen. Der Sensorname wird weiterhin NICHT zur Identifikation verwendet: FEBC + Service 3532 + 3534/3535/3536/3538 bilden den G7-Fingerprint. Build 14 decodiert ausschließlich spontan empfangene Notify-Pakete. Ein 0x4E-Paket auf 3534 wird diagnostisch als BG/Alter/Trend/Sequenz/State angezeigt. Der Wert wird NICHT in den xDrip-Graph oder die Komplikation geschrieben. Es gibt KEIN Dexcom-Protokoll-TX, kein AuthRequest, kein Pairing/Bonding und keine Session-/Kalibrierungsaktion.")',
    'Text("Build 15 validiert die in Build 14 bestätigte direkte G7-BG-Decodierung über mehrere Messzyklen. Nach Tippen läuft der Test bis zu 45 Minuten und sucht über FEBC + Service 3532 + 3534/3535/3536/3538 wiederholt nach G7-Verbindungsfenstern. Ziel sind 6 fortlaufende 0x4E-BG-Sequenzen. BG, Alter, Trend, Sequenz und State werden nur diagnostisch protokolliert. Der Wert wird weiterhin NICHT in den xDrip-Graph oder die Komplikation geschrieben. Dexcom-Anwendungs-TX bleibt 0.")',
    "Build15 explanation",
)

replace_once(
    root,
    'row("Passive Decode", watchState.g7AuthProbeStatus)',
    'row("Multi-Cycle", watchState.g7AuthProbeStatus)',
    "Build15 status row",
)

replace_once(
    root,
    'Button(watchState.g7AuthProbeRunning ? "Decoder-Test abbrechen" : "Decoder-Test starten")',
    'Button(watchState.g7AuthProbeRunning ? "Validierung abbrechen" : "Validierung starten")',
    "Build15 button",
)

replace_once(
    root,
    'Text("Während des Tests bitte die Dexcom-Komplikation beobachten. Build 14 verändert gegenüber Build 13 nur die lokale Auswertung der bereits empfangenen Bytes. Auf BLE-Ebene bleibt es bei CCCD Notify; Dexcom-Anwendungs-TX = 0. Kein automatischer Background-Reconnect. Die bestehende xDrip-Sicherheitslogik zeigt bei fehlendem aktuellen BG weiterhin --- statt eines alten Werts.")',
    'Text("Während der Build-15-Validierung bitte die Dexcom-App bzw. Dexcom-Komplikation zum Zeitvergleich beobachten. Jeder neue direkte BG wird mit Uhrzeit, Sequenz, Alter, Trend und State protokolliert. Nach einem kurzen RX-Fenster trennt die Diagnoseverbindung und sucht das nächste G7-Fenster. Es gibt weiterhin keinen Dexcom-Anwendungs-TX, keinen Background-Reconnect und keine Übernahme des Diagnosewerts in xDrip oder die Komplikation. --- bleibt die Sicherheitsanzeige ohne aktuellen freigegebenen Wert.")',
    "Build15 safety footer",
)

print("Build 15 multi-cycle G7 validation patch applied successfully.")
