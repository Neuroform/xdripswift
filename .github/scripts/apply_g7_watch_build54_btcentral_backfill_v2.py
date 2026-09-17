from pathlib import Path

# Build54 patch revision 2. The architecture patch is intentionally kept unchanged;
# this wrapper only replaces two brittle source-code anchors with structural lookups
# before executing the patch against the materialized Build53 baseline.
legacy_path = Path("/tmp/apply_g7_watch_build54_btcentral_backfill.py")
source = legacy_path.read_text(encoding="utf-8")

# Replace the brittle exact-string insertion in the modern CoreBluetooth disconnect callback.
label = '"modern disconnect reset"'
label_pos = source.index(label)
block_start = source.rfind("replace_once(", 0, label_pos)
block_end = source.index("\n)\n", label_pos) + len("\n)\n")
modern_replacement = r'''modern_signature54 = (
    "    func centralManager(_ central: CBCentralManager,\n"
    "                    didDisconnectPeripheral peripheral: CBPeripheral,\n"
    "                    timestamp:"
)
modern_start54 = manager.find(modern_signature54)
if modern_start54 < 0:
    raise RuntimeError("modern disconnect reset: callback signature not found")
modern_brace54 = manager.find("{", modern_start54)
if modern_brace54 < 0:
    raise RuntimeError("modern disconnect reset: opening brace not found")
manager = (
    manager[:modern_brace54 + 1]
    + "\n        connectPending54 = false\n"
      "        backfillRequestInFlight54 = false\n"
      "        controlCharacteristic54 = nil"
    + manager[modern_brace54 + 1:]
)
'''
source = source[:block_start] + modern_replacement + source[block_end:]

# Replace the multiline MISSED_SEQ text match with a unique line-anchor insertion.
section_start = source.index("# Request backfill at the exact point where the existing continuity code proves samples are missing.")
section_end = source.index("# A 0x59 completion ends the current active request", section_start)
gap_replacement = r'''# Request backfill at the exact point where the existing continuity code proves samples are missing.
gap_anchor54 = 'trace41("MISSED_SEQ'
if manager.count(gap_anchor54) != 1:
    raise RuntimeError(f"active gap backfill request: expected one MISSED_SEQ anchor, found {manager.count(gap_anchor54)}")
gap_pos54 = manager.index(gap_anchor54)
gap_line_end54 = manager.index("\n", gap_pos54)
manager = (
    manager[:gap_line_end54 + 1]
    + "                    requestBackfill54(current: reading, missingCount: gap, peripheral: peripheral)\n"
    + manager[gap_line_end54 + 1:]
)

'''
source = source[:section_start] + gap_replacement + source[section_end:]

compiled_path = "/tmp/apply_g7_watch_build54_btcentral_backfill_compiled_v2.py"
Path(compiled_path).write_text(source, encoding="utf-8")
compile(source, compiled_path, "exec")
exec(compile(source, compiled_path, "exec"), {"__name__": "__main__", "__file__": compiled_path})
