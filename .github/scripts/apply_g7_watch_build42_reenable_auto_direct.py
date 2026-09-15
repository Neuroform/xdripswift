from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Build 42 runs AFTER accepted Build 37 and Build 41 lifecycle instrumentation.
# It restores only the already-proven automatic Direct-G7 collector that was deliberately
# disabled by the later auth-probe safety patch. No widget/UI/WatchConnectivity code changes.

state = Path("xDrip Watch App/DataModels/WatchStateModel.swift")

# Re-enable the exact automatic Direct-G7 manager construction from the original proven path.
replace_once(
    state,
    '''        // Auth-probe build: never start Direct-G7 automatically.
        // The official Dexcom Watch connection must remain untouched unless the user
        // explicitly starts the short foreground Auth Probe from the G7 page.
        directG7Manager = nil
        directG7Status = "Auto-Direct aus · Auth-Test bereit"''',
    '''        // Build 42: restore the already-proven automatic Direct-G7 path.
        // WatchConnectivity remains a fallback; Direct-G7 wins when the same sample arrives.
        directG7Manager = G7DirectBLEManager(
            onState: { [weak self] status, deviceName, authenticated in
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.directG7Status = status
                    self.directG7DeviceName = deviceName
                    self.directG7Authenticated = authenticated
                }
            },
            onReading: { [weak self] reading in
                DispatchQueue.main.async {
                    self?.processDirectG7Reading(reading)
                }
            }
        )
        directG7Manager?.start()''',
    "Build42 restore automatic Direct-G7 startup",
)

# Restore CoreBluetooth state restoration for the existing Direct-G7 CBCentralManager.
replace_once(
    state,
    '''        central = CBCentralManager(
            delegate: self,
            queue: .main,
            options: nil
        )''',
    '''        central = CBCentralManager(
            delegate: self,
            queue: .main,
            options: [CBCentralManagerOptionRestoreIdentifierKey: "xDrip.G7.Direct.Central"]
        )''',
    "Build42 restore Direct-G7 CoreBluetooth state restoration",
)

# Make the Watch target explicitly eligible for CoreBluetooth central background execution.
# This is part of the permanent functional baseline, not temporary diagnostic state.
plist = Path("xDrip-Watch-App-Info.plist")
plist_text = plist.read_text(encoding="utf-8")
if "<string>bluetooth-central</string>" not in plist_text:
    marker = "\t<key>MainAppBundleIdentifier</key>\n\t<string>$(MAIN_APP_BUNDLE_IDENTIFIER)</string>\n"
    replacement = marker + "\t<key>UIBackgroundModes</key>\n\t<array>\n\t\t<string>bluetooth-central</string>\n\t</array>\n"
    if marker not in plist_text:
        raise RuntimeError("Build42 Watch plist: insertion marker not found")
    plist.write_text(plist_text.replace(marker, replacement, 1), encoding="utf-8")

print("Build 42 applied: automatic Direct-G7 startup + CoreBluetooth restoration + bluetooth-central background mode enabled; Build 37 UI/widgets untouched.")
