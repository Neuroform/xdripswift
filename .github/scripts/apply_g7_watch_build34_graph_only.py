from pathlib import Path

p = Path('xDrip Watch Complication/XDripWatchComplication.swift')
s = p.read_text(encoding='utf-8')
old_kind = 'let kind: String = "xDripWatchComplication"'
if s.count(old_kind) != 1:
    raise RuntimeError(f'Expected exactly one original widget kind, found {s.count(old_kind)}')
s = s.replace(old_kind, 'let kind: String = "xDripGraphV33"', 1)
old = '''        .configurationDisplayName(ConstantsHomeView.applicationName)\n        .description("Show the current blood glucose level")\n        // Build 18: use every pixel WidgetKit exposes for the middle Ultra complication.\n        .contentMarginsDisabled()'''
new = '''        .configurationDisplayName("xDrip Graph")\n        .description("xDrip 2-hour glucose graph")\n        .supportedFamilies([.accessoryRectangular])\n        .contentMarginsDisabled()'''
if s.count(old) != 1:
    raise RuntimeError(f'Expected exactly one Build18 widget configuration, found {s.count(old)}')
p.write_text(s.replace(old, new, 1), encoding='utf-8')

p = Path('xDrip Watch Complication/Views/AccessoryRectangularView.swift')
s = p.read_text(encoding='utf-8')
geometry_start = s.index('            GeometryReader { geometry in')
overlay_start = s.index('\n\n            if entry.widgetState.keepAliveIsDisabled', geometry_start)
graph_only = '''            RollingTwoHourGlucoseGraph(entry: entry)\n                .frame(maxWidth: .infinity, maxHeight: .infinity)'''
s = s[:geometry_start] + graph_only + s[overlay_start:]

panel_start = s.index('\n\nprivate struct CurrentGlucosePanel: View')
graph_start = s.index('\n\nprivate struct RollingTwoHourGlucoseGraph: View', panel_start)
s = s[:panel_start] + s[graph_start:]

old_margins = '''            // Build 18: use virtually the complete Canvas. Only reserve enough room for\n            // readable 3-digit Y labels and the moving HH:mm labels. No decorative padding.\n            let leftMargin: CGFloat = size.width < 115 ? 13 : 15\n            let rightMargin: CGFloat = 0\n            let topMargin: CGFloat = 0.5\n            let bottomMargin: CGFloat = size.height < 55 ? 8 : 9'''
new_margins = '''            // Build 34: the whole rectangular complication belongs to the graph.\n            // Reserve only the space required for larger Y labels and HH:mm labels.\n            let leftMargin: CGFloat = size.width < 115 ? 22 : 25\n            let rightMargin: CGFloat = 1\n            let topMargin: CGFloat = 7\n            let bottomMargin: CGFloat = size.height < 55 ? 14 : 16'''
if old_margins not in s:
    raise RuntimeError('Build34: expected Build18 graph margins not found')
s = s.replace(old_margins, new_margins, 1)

old_y = '''                drawLabel(String(Int(level)), at: CGPoint(x: plotLeft - 1.5, y: y), anchor: UnitPoint(x: 1, y: 0.5), size: 6.0)'''
new_y = '''                let labelAnchor: UnitPoint = level == 220.0 ? UnitPoint(x: 1, y: 0) : UnitPoint(x: 1, y: 0.5)\n                drawLabel(String(Int(level)), at: CGPoint(x: plotLeft - 3.0, y: y), anchor: labelAnchor, size: 9.0)'''
if old_y not in s:
    raise RuntimeError('Build34: expected Build18 Y-axis label statement not found')
s = s.replace(old_y, new_y, 1)

old_times = '''            drawLabel(Self.timeFormatter.string(from: leftDate), at: CGPoint(x: plotLeft, y: labelY), anchor: UnitPoint(x: 0, y: 1), size: 6.0)\n            drawLabel(Self.timeFormatter.string(from: middleDate), at: CGPoint(x: plotLeft + plotWidth / 2, y: labelY), anchor: UnitPoint(x: 0.5, y: 1), size: 6.0)\n            drawLabel(Self.timeFormatter.string(from: entry.date), at: CGPoint(x: plotRight, y: labelY), anchor: UnitPoint(x: 1, y: 1), size: 6.0)'''
new_times = '''            drawLabel(Self.timeFormatter.string(from: leftDate), at: CGPoint(x: plotLeft, y: labelY), anchor: UnitPoint(x: 0, y: 1), size: 9.0)\n            drawLabel(Self.timeFormatter.string(from: middleDate), at: CGPoint(x: plotLeft + plotWidth / 2, y: labelY), anchor: UnitPoint(x: 0.5, y: 1), size: 9.0)\n            drawLabel(Self.timeFormatter.string(from: entry.date), at: CGPoint(x: plotRight, y: labelY), anchor: UnitPoint(x: 1, y: 1), size: 9.0)'''
if old_times not in s:
    raise RuntimeError('Build34: expected Build18 time-axis labels not found')
s = s.replace(old_times, new_times, 1)

old_label = '''                    Text(text)\n                        .font(.system(size: fontSize, weight: .medium))\n                        .foregroundStyle(Color.secondary)'''
new_label = '''                    Text(text)\n                        .font(.system(size: fontSize, weight: .semibold))\n                        .foregroundStyle(Color.white)\n                        .monospacedDigit()'''
if old_label not in s:
    raise RuntimeError('Build34: expected graph label renderer not found')
s = s.replace(old_label, new_label, 1)

p.write_text(s, encoding='utf-8')
print('Build 34 graph-only patch applied successfully.')
