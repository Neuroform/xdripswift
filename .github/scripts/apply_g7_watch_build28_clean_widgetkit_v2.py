from pathlib import Path
import runpy

# The direct-G7 baseline intentionally changed the original upstream
# reloadAllTimelines() call to the old single-widget kind. Normalize only that
# one publication statement back to the upstream form before applying the clean
# Build-28 patch. This does not change any BLE logic or data handling.
watch_state_path = Path("xDrip Watch App/DataModels/WatchStateModel.swift")
text = watch_state_path.read_text(encoding="utf-8")
old = '''        // Ask only the xDrip complication to reload. WidgetKit may still defer the actual render.\n        WidgetCenter.shared.reloadTimelines(ofKind: "xDripWatchComplication")'''
new = '''        // now that the new data is stored in the app group, try to force the complications to reload\n        WidgetCenter.shared.reloadAllTimelines()'''
count = text.count(old)
if count != 1:
    raise RuntimeError(f"Build28 v2: expected one direct-G7 legacy reload block, found {count}")
watch_state_path.write_text(text.replace(old, new, 1), encoding="utf-8")

runpy.run_path(
    ".github/scripts/apply_g7_watch_build28_clean_widgetkit_complications.py",
    run_name="__main__",
)
