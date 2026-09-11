from pathlib import Path

path = Path("xDrip Watch Complication/Views/AccessoryRectangularView.swift")
text = path.read_text()
old = '''                    CurrentGlucosePanel(entry: entry)
                        .frame(width: sideWidth, maxHeight: .infinity, alignment: .leading)'''
new = '''                    CurrentGlucosePanel(entry: entry)
                        .frame(width: sideWidth)
                        .frame(maxHeight: .infinity, alignment: .leading)'''
count = text.count(old)
if count != 1:
    raise RuntimeError(f"Build16 frame fix: expected exactly one match, found {count}")
path.write_text(text.replace(old, new, 1))
print("Build 16 complication compile fix applied successfully.")
