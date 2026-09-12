from pathlib import Path
import plistlib


# Build 20 runs AFTER the complete Build 19 patch chain.
# Fix the Watch complication registration metadata so the WidgetKit extension
# is associated explicitly with the embedded xDrip Watch app. This is required
# for reliable discovery in the iPhone Watch app complication picker.

info_path = Path("xDrip Watch Complication/Info.plist")
with info_path.open("rb") as handle:
    info = plistlib.load(handle)

extension = info.setdefault("NSExtension", {})
extension["NSExtensionPointIdentifier"] = "com.apple.widgetkit-extension"
attributes = extension.setdefault("NSExtensionAttributes", {})
attributes["WKAppBundleIdentifier"] = "$(MAIN_APP_BUNDLE_IDENTIFIER).watchkitapp"

# Give the complication extension an unambiguous user-facing name in the
# complication gallery instead of inheriting the personalized app display name.
info["CFBundleDisplayName"] = "xDrip"

with info_path.open("wb") as handle:
    plistlib.dump(info, handle, sort_keys=False)

print("Build 20 Watch complication registration metadata applied successfully.")
