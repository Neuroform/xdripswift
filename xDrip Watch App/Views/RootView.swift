//
//  RootView.swift
//  xDrip Watch App
//
//  Created by Paul Plant on 21/7/24.
//  Copyright © 2024 Johan Degraeve. All rights reserved.
//

import Foundation
import SwiftUI

struct RootView: View {
    @EnvironmentObject var watchState: WatchStateModel

    // save the last selected tab on the Watch so re-opening the app returns to the same page
    @AppStorage("watchAppSelectedPage") private var selectedPage = WatchAppPage.main.rawValue

    // keep both main pages on the same chart range so swiping between them only changes whether
    // the AGP background is visible. The chart content should not jump between pages.
    @State private var hoursToShowIndex = ConstantsAppleWatch.hoursToShowDefaultIndex
    
    var body: some View {
        TabView(selection: $selectedPage) {
            // normal main page
            MainView(hoursToShowIndex: $hoursToShowIndex)
                .tag(WatchAppPage.main.rawValue)

            // same main page layout, but with the AGP background enabled in the chart
            MainView(showsAGPBackground: true, hoursToShowIndex: $hoursToShowIndex)
                .tag(WatchAppPage.agp.rawValue)

            // large number page
            BigNumberView()
                .tag(WatchAppPage.bigNumber.rawValue)

            // Personal direct-G7 status page. Collection runs automatically in WatchStateModel.
            G7DirectStatusView()
                .tag(WatchAppPage.g7Direct.rawValue)
        }
        .modifier(RootViewTabViewStyleModifier())
        .environmentObject(watchState)
        .onAppear {
            // if a saved tab value from an older build is invalid, fall back to the normal main page
            if WatchAppPage(rawValue: selectedPage) == nil {
                selectedPage = WatchAppPage.main.rawValue
            }
        }
    }
}

private enum WatchAppPage: Int {
    case main = 0
    case agp = 1
    case bigNumber = 2
    case g7Direct = 3
}

private struct G7DirectStatusView: View {
    @EnvironmentObject var watchState: WatchStateModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                Text("G7 Direct")
                    .font(.headline)

                Text("Build 15 Multi-Cycle Validation · 6 direkte BG")
                    .font(.caption2)
                    .foregroundStyle(.secondary)

                row("Status", watchState.directG7Status)

                if !watchState.directG7DeviceName.isEmpty {
                    row("Gerät", watchState.directG7DeviceName)
                }

                row("Authentifiziert", watchState.directG7Authenticated ? "ja" : "nein")
                row("Aktive BG-Quelle", watchState.bgDataSource)

                if let value = watchState.directG7LastValue {
                    row("Letzter Direct-BG", "\(Int(value.rounded())) mg/dL")
                }

                if let date = watchState.directG7LastDate {
                    row("Direct-Zeit", date.formatted(date: .omitted, time: .standard))
                }

                if let trend = watchState.directG7LastTrend {
                    row("Trend", String(format: "%+.1f mg/dL/min", trend))
                }

                if let sequence = watchState.directG7LastSequence {
                    row("Sequenz", "\(sequence)")
                }

                row("Direct-Werte", "\(watchState.directG7ReadingCount)")

                Divider()

                Text("Build 51 BG-Quellenprotokoll")
                    .font(.headline)
                Text("Produktiver Datenpfad · keine Validierung starten. DIRECT_G7 = Sensor direkt; IPHONE_WC = WatchConnectivity vom iPhone. batch/new zeigt insbesondere nachgelieferte Messpunkte.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                row("Letzte Quelle", watchState.lastBgIngressSource51)
                Text(watchState.bgIngressTrace51)
                    .font(.system(size: 9, design: .monospaced))

                Divider()

                Text("Build 15 G7 Multi-Cycle-Validierung")
                    .font(.headline)

                Text("Build 15 validiert die in Build 14 bestätigte direkte G7-BG-Decodierung über mehrere Messzyklen. Nach Tippen läuft der Test bis zu 45 Minuten und sucht über FEBC + Service 3532 + 3534/3535/3536/3538 wiederholt nach G7-Verbindungsfenstern. Ziel sind 6 fortlaufende 0x4E-BG-Sequenzen. BG, Alter, Trend, Sequenz und State werden nur diagnostisch protokolliert. Der Wert wird weiterhin NICHT in den xDrip-Graph oder die Komplikation geschrieben. Dexcom-Anwendungs-TX bleibt 0.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)

                row("Multi-Cycle", watchState.g7AuthProbeStatus)

                if !watchState.g7AuthProbeDeviceName.isEmpty {
                    row("Probe-Gerät", watchState.g7AuthProbeDeviceName)
                }

                if !watchState.g7AuthProbeResponseHex.isEmpty {
                    row("Letzte Auth-Antwort", watchState.g7AuthProbeResponseHex)
                }

                if watchState.g7AuthProbeChallengeReceived {
                    Text("✓ Separate 0x03-Challenge erhalten · keine Antwort gesendet")
                        .font(.caption)
                        .foregroundStyle(.green)
                }

                if !watchState.g7AuthProbeTelemetry.isEmpty {
                    Text("Telemetrie")
                        .font(.headline)
                    Text(watchState.g7AuthProbeTelemetry)
                        .font(.system(size: 9, design: .monospaced))
                }

                Button(watchState.g7AuthProbeRunning ? "Validierung abbrechen" : "Validierung starten") {
                    if watchState.g7AuthProbeRunning {
                        watchState.stopG7AuthProbe()
                    } else {
                        watchState.startG7AuthProbe()
                    }
                }
                .buttonStyle(.borderedProminent)

                Text("Während der Build-15-Validierung bitte die Dexcom-App bzw. Dexcom-Komplikation zum Zeitvergleich beobachten. Jeder neue direkte BG wird mit Uhrzeit, Sequenz, Alter, Trend und State protokolliert. Nach einem kurzen RX-Fenster trennt die Diagnoseverbindung und sucht das nächste G7-Fenster. Es gibt weiterhin keinen Dexcom-Anwendungs-TX, keinen Background-Reconnect und keine Übernahme des Diagnosewerts in xDrip oder die Komplikation. --- bleibt die Sicherheitsanzeige ohne aktuellen freigegebenen Wert.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
        }
    }

    @ViewBuilder
    private func row(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption)
        }
    }
}

#if os(watchOS)
struct RootViewTabViewStyleModifier: ViewModifier {
    
    func body(content: Content) -> some View {
        content.tabViewStyle(.carousel)
    }
}
#else
struct RootViewTabViewStyleModifier: ViewModifier {
    
    func body(content: Content) -> some View {
        content.tabViewStyle(.page)
    }
}
#endif

#Preview {
    RootView()
}
