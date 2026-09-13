from pathlib import Path
import plistlib


# Build 26 runs AFTER Build 25.
#
# Build 25 rendered correctly in the binary but disappeared completely from the
# iPhone Watch-app complication picker. The regression was introduced by mixing
# a pure WidgetKit WidgetBundle with a legacy ClockKit descriptor bridge and by
# forcibly calling reloadComplicationDescriptors() on every Watch-app launch.
#
# Build 26 returns discovery to the architecture Apple documents for a STATIC set
# of WidgetKit complications:
#   * one WidgetKit extension
#   * one @main WidgetBundle
#   * three static Widget configurations in that bundle
#   * NO ClockKit complication data-source registration for picker discovery
#   * NO forced descriptor reload
#
# The three WidgetKit kinds are also versioned for Build 26 so watchOS/iOS cannot
# reuse the bad Build-25 widget-registration cache.
#
# UI/logic from Build 25 is intentionally unchanged:
#   - Martin's xDrip Graph (accessoryRectangular)
#   - xDrip BG mg/dL (accessoryCircular; turquoise minute ring; stale >12 min)
#   - BG Trend + Δ mg/dL (accessoryCircular; stale >12 min)


def replace_exactly_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# 1) Remove the Build-24/25 ClockKit discovery bridge from the Watch app.
#    WidgetKit itself must own complication discovery on watchOS 9+.
# -----------------------------------------------------------------------------
watch_app_path = Path("xDrip Watch App/xDripWatchApp.swift")
watch_app = watch_app_path.read_text(encoding="utf-8")

bridge_marker = "\n// MARK: - Complication discovery bridge"
if bridge_marker not in watch_app:
    raise RuntimeError("Build26: ClockKit bridge marker not found")
watch_app = watch_app.split(bridge_marker, 1)[0].rstrip() + "\n"

reload_block = '''    @StateObject var watchState = WatchStateModel()\n\n    init() {\n        CLKComplicationServer.sharedInstance().reloadComplicationDescriptors()\n    }\n    \n    var body: some Scene {'''
normal_block = '''    @StateObject var watchState = WatchStateModel()\n    \n    var body: some Scene {'''
watch_app = replace_exactly_once(
    watch_app,
    reload_block,
    normal_block,
    "Build26 remove forced ClockKit descriptor reload",
)

watch_app = watch_app.replace("import ClockKit\n", "", 1)
if "CLKComplication" in watch_app or "reloadComplicationDescriptors" in watch_app:
    raise RuntimeError("Build26: legacy ClockKit complication code remains in Watch app")

watch_app_path.write_text(watch_app, encoding="utf-8")


# -----------------------------------------------------------------------------
# 2) Remove legacy ClockKit provider metadata from the Watch app Info.plist.
#    The embedded WidgetKit extension is now the sole provider.
# -----------------------------------------------------------------------------
watch_info_path = Path("xDrip-Watch-App-Info.plist")
with watch_info_path.open("rb") as handle:
    watch_info = plistlib.load(handle)

watch_info.pop("CLKComplicationPrincipalClass", None)
watch_info.pop("CLKComplicationSupportedFamilies", None)

with watch_info_path.open("wb") as handle:
    plistlib.dump(watch_info, handle, sort_keys=False)


# -----------------------------------------------------------------------------
# 3) Keep the Build-25 WidgetBundle, but use NEW WidgetKit kind identifiers.
#    This deliberately invalidates the bad Build-25 discovery cache while keeping
#    the visible names and every graph/circular rendering detail unchanged.
# -----------------------------------------------------------------------------
widget_path = Path("xDrip Watch Complication/XDripWatchComplication.swift")
widget = widget_path.read_text(encoding="utf-8")

widget = replace_exactly_once(
    widget,
    'let kind: String = "xDripWatchComplication"',
    'let kind: String = "xDripGraphV26"',
    "Build26 graph kind",
)
widget = replace_exactly_once(
    widget,
    'let kind: String = "xDripBGComplication"',
    'let kind: String = "xDripBGV26"',
    "Build26 BG kind",
)
widget = replace_exactly_once(
    widget,
    'let kind: String = "xDripTrendComplication"',
    'let kind: String = "xDripTrendV26"',
    "Build26 trend kind",
)

required_widget_tokens = [
    "@main",
    "struct XDripWatchComplicationBundle: WidgetBundle",
    '.configurationDisplayName("Martin’s xDrip Graph")',
    '.configurationDisplayName("xDrip BG mg/dL")',
    '.configurationDisplayName("BG Trend + Δ mg/dL")',
    '.supportedFamilies([.accessoryRectangular])',
    '.supportedFamilies([.accessoryCircular])',
]
for token in required_widget_tokens:
    if token not in widget:
        raise RuntimeError(f"Build26: required WidgetKit token missing: {token}")

widget_path.write_text(widget, encoding="utf-8")


# -----------------------------------------------------------------------------
# 4) Point immediate BG-state reloads at the three new Build-26 WidgetKit kinds.
# -----------------------------------------------------------------------------
watch_state_path = Path("xDrip Watch App/DataModels/WatchStateModel.swift")
watch_state = watch_state_path.read_text(encoding="utf-8")

old_kinds = '''            for complicationKind in [\n                "xDripWatchComplication",\n                "xDripBGComplication",\n                "xDripTrendComplication"\n            ] {'''
new_kinds = '''            for complicationKind in [\n                "xDripGraphV26",\n                "xDripBGV26",\n                "xDripTrendV26"\n            ] {'''
watch_state = replace_exactly_once(
    watch_state,
    old_kinds,
    new_kinds,
    "Build26 reload new WidgetKit kinds",
)
watch_state_path.write_text(watch_state, encoding="utf-8")


# -----------------------------------------------------------------------------
# 5) Verify the WidgetKit extension remains a modern extension target.
# -----------------------------------------------------------------------------
ext_info_path = Path("xDrip Watch Complication/Info.plist")
with ext_info_path.open("rb") as handle:
    ext_info = plistlib.load(handle)

if ext_info.get("NSExtension", {}).get("NSExtensionPointIdentifier") != "com.apple.widgetkit-extension":
    raise RuntimeError("Build26: WidgetKit NSExtensionPointIdentifier is missing/incorrect")
if ext_info.get("CFBundleDisplayName") != "xDrip":
    raise RuntimeError("Build26: Widget extension display name must remain xDrip")

print("Build 26 applied: pure WidgetKit WidgetBundle registration, fresh widget kinds, no ClockKit picker bridge.")
