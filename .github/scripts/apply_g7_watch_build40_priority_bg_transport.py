from pathlib import Path

# Build 40 transport test.
# Base: accepted Build 37. Change ONLY iPhone WatchManager transport selection.
# Watch app, WatchStateModel, Widget provider, widget registration and all complication views stay untouched.

path = Path("xDrip/Managers/Watch/WatchManager.swift")
text = path.read_text(encoding="utf-8")
old = '''                if (lastForcedComplicationUpdateTimeStamp < .now.addingTimeInterval(-Double(UserDefaults.standard.forceComplicationUpdateInMinutes * 60)) && session.isComplicationEnabled) || forceComplicationUpdate {'''
new = '''                if (userInfo["bgReadings"] != nil && session.isComplicationEnabled) || (lastForcedComplicationUpdateTimeStamp < .now.addingTimeInterval(-Double(UserDefaults.standard.forceComplicationUpdateInMinutes * 60)) && session.isComplicationEnabled) || forceComplicationUpdate {'''
count = text.count(old)
if count != 1:
    raise RuntimeError(f"Build40: expected exactly one background complication condition, found {count}")
text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")

print("Build 40 applied: every background BG payload uses complication-priority WatchConnectivity transfer; no Watch-side code changed.")
