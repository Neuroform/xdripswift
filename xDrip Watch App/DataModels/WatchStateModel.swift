//
//  WatchStateModel.swift
//  xDrip Watch App
//
//  Created by Paul Plant on 11/2/24.
//  Copyright © 2024 Johan Degraeve. All rights reserved.
//

import Combine
import CoreBluetooth
import Foundation
import os
import SwiftUI
import WatchConnectivity
import WidgetKit

/// sensor noise states received from the paired iPhone
private enum WatchSensorNoiseState: Int {
    case collecting = 0
    case low = 1
    case elevated = 2
    case veryHigh = 3
    case extreme = 4
    case flatlineSuspected = 5

    var color: Color {
        switch self {
        case .collecting:
            return .gray
        case .low:
            return .green
        case .elevated:
            return .yellow
        case .veryHigh:
            return .orange
        case .extreme, .flatlineSuspected:
            return .red
        }
    }

    var localizedTitle: String {
        switch self {
        case .collecting:
            return Texts_HomeView.sensorManagementNoiseCollecting
        case .low:
            return Texts_HomeView.sensorManagementNoiseLow
        case .elevated:
            return Texts_HomeView.sensorManagementNoiseElevated
        case .veryHigh:
            return Texts_HomeView.sensorManagementNoiseVeryHigh
        case .extreme:
            return Texts_HomeView.sensorManagementNoiseExtreme
        case .flatlineSuspected:
            return Texts_HomeView.sensorNoiseWarningFlatlineTitle
        }
    }
}

// compact AGP point as received from the iOS app
// this stays as minute-of-day until the Watch maps it onto the visible chart range
private struct WatchAGPProfilePoint {
    let minuteOfDay: Int
    let p5MgDl: Double
    let p25MgDl: Double
    let medianMgDl: Double
    let p75MgDl: Double
    let p95MgDl: Double
}

/// holds, the watch state and allows updates and computed properties/variables to be generated for the different views that use it
/// also used to update the ComplicationSharedUserDefaultsModel in the app group so that the complication can access the data
final class WatchStateModel: NSObject, ObservableObject {
    private let log = Logger(subsystem: "xDrip", category: "WatchStateModel")

    /// the Watch Connectivity session
    var session: WCSession

    // set timer to automatically refresh the view
    // https://www.hackingwithswift.com/quick-start/swiftui/how-to-use-a-timer-with-swiftui
    let timer = Timer.publish(every: 2, tolerance: 0.5, on: .main, in: .common).autoconnect()
    @Published var timerControlDate = Date()

    var bgReadingValues: [Double] = []
    var bgReadingDates: [Date] = []
    var bgReadingDatesAsDouble: [Double] = []
    // AGP points are kept separate from BG readings so the normal main page can stay glucose-only
    // while the second main page renders the same chart with the AGP background enabled
    @Published var agpBackgroundPoints: [GlucoseChartAGPPoint] = []

    // store the compact minute-of-day AGP profile from the iOS app
    // this lets the Watch remap AGP instantly when the chart hours change
    private var agpProfilePoints: [WatchAGPProfilePoint] = []

    // make sure late AGP replies from older requests don't replace newer chart data
    private var latestAGPRequestID: Double = 0

    // Prevent queued/background WatchConnectivity payloads from replacing a newer glucose state.
    private var latestBgPayloadGeneratedAt: Double = 0

    // Personal direct-G7 Watch path. The BLE manager subscribes only to existing notifications;
    // it does not start/stop/calibrate the sensor or send Dexcom protocol commands.
    private var directG7Manager: G7DirectBLEManager?
    private var lastDirectG7ReadingDate: Date?

    @Published var bgDataSource: String = "iPhone"
    @Published var directG7Status: String = "initialisiert"
    @Published var directG7DeviceName: String = ""
    @Published var directG7Authenticated: Bool = false
    @Published var directG7LastValue: Double?
    @Published var directG7LastDate: Date?
    @Published var directG7LastTrend: Double?
    @Published var directG7LastSequence: UInt16?
    @Published var directG7ReadingCount: Int = 0

    // Manual G7 authentication probe. This is intentionally opt-in and foreground-only.
    private var g7AuthProbeManager: G7AuthProbeManager?
    @Published var g7AuthProbeStatus: String = "bereit"
    @Published var g7AuthProbeDeviceName: String = ""
    @Published var g7AuthProbeResponseHex: String = ""
    @Published var g7AuthProbeRunning: Bool = false
    @Published var g7AuthProbeChallengeReceived: Bool = false
    @Published var g7AuthProbeTelemetry: String = ""

    // keep the latest AGP request if WatchConnectivity is not ready yet
    // this fixes first-load cases where the AGP page appears before the session is reachable
    private var pendingAGPRequestRange: (startDate: Date, endDate: Date)?

    @Published var isMgDl: Bool = true
    @Published var slopeOrdinal: Int = 2
    @Published var deltaValueInUserUnit: Double = 0
    @Published var urgentLowLimitInMgDl: Double = 60
    @Published var lowLimitInMgDl: Double = 80
    @Published var highLimitInMgDl: Double = 170
    @Published var urgentHighLimitInMgDl: Double = 250
    @Published var updatedDate: Date = .now
    @Published var activeSensorDescription: String = ""
    @Published var sensorAgeInMinutes: Double = 0
    @Published var sensorMaxAgeInMinutes: Double = 14400
    @Published var preferSensorCountdown: Bool = false
    @Published var sensorNoiseStateRawValue: Int?
    @Published var timeStampOfLastFollowerConnection: Date = .now
    @Published var secondsUntilFollowerDisconnectWarning: Int = 60 * 6
    @Published var timeStampOfLastHeartBeat: Date = .now
    @Published var secondsUntilHeartBeatDisconnectWarning: Int = 90
    @Published var isMaster: Bool = true
    @Published var followerDataSourceType: FollowerDataSourceType = .nightscout
    @Published var followerBackgroundKeepAliveType: FollowerBackgroundKeepAliveType = .normal
    @Published var followerConnectionStatusRawValue: String?
    @Published var keepAliveIsDisabled: Bool = false

    @Published var lastUpdatedTextString: String = Texts_WatchApp.requestingData
    @Published var lastUpdatedTimeString: String = ""
    @Published var lastUpdatedTimeAgoString: String = ""
    @Published var requestingDataIconColor: Color = ConstantsAppleWatch.requestingDataIconColorInactive
    @Published var lastComplicationUpdateTimeStamp: Date = .distantPast

    @Published var aidStatus: AIDStatus?

    // we use the following to record when the user has manually requested a state update on each view so that we can trigger the animation on just this view
    // this is to prevent the UI animating "pending animations" when we switch view tabs
    @Published var updateBigNumberViewDate: Date = .now
    @Published var updateMainViewDate: Date = .now

    init(session: WCSession = .default) {
        self.session = session
        super.init()

        session.delegate = self
        session.activate()

        // Build 42: restore the already-proven automatic Direct-G7 path.
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
        directG7Manager?.start()
    }

    // Build 45: watchOS Bluetooth-alert wake entry point. The existing Direct-G7 manager stays
    // inside xDrip; this only gives SwiftUI's background-task handler a direct way to re-register
    // the already-known CoreBluetooth operation without waiting for foreground UI activity.
    @MainActor
    func handleDirectG7BluetoothAlert() {
        directG7Manager?.handleBluetoothAlertWake()
    }

    // MARK: - Functions to provide context data to populate the views

    /// the latest BG reading value in the array as a double
    /// - Returns: an optional double with the bg value in mg/dL if it exists
    func bgValueInMgDl() -> Double? {
        return bgReadingValues.isEmpty ? nil : bgReadingValues[0]
    }

    /// returns blood glucose value as a string in the user-defined measurement unit. Will check and display also high, low and error texts as required.
    /// - Returns: a String with the formatted value/unit or error text
    func bgValueStringInUserChosenUnit() -> String {
        if let bgReadingDate = bgReadingDate(), let bgValueInMgDl = bgValueInMgDl(), bgReadingDate > Date().addingTimeInterval(-60 * 7) {
            var returnValue: String

            if bgValueInMgDl >= 400 {
                returnValue = Texts_Common.HIGH
            } else if bgValueInMgDl >= 40 {
                returnValue = bgValueInMgDl.mgDlToMmolAndToString(mgDl: isMgDl)
            } else if bgValueInMgDl > 12 {
                returnValue = Texts_Common.LOW
            } else {
                switch bgValueInMgDl {
                case 0:
                    returnValue = "??0"
                case 1:
                    returnValue = "?SN"
                case 2:
                    returnValue = "??2"
                case 3:
                    returnValue = "?NA"
                case 5:
                    returnValue = "?NC"
                case 6:
                    returnValue = "?CD"
                case 9:
                    returnValue = "?AD"
                case 12:
                    returnValue = "?RF"
                default:
                    returnValue = "???"
                }
            }
            return returnValue
        } else {
            return isMgDl ? "---" : "-.-"
        }
    }

    /// the timestamp of the latest BG reading value in the array
    /// - Returns: an optional date
    func bgReadingDate() -> Date? {
        return bgReadingDates.isEmpty ? nil : bgReadingDates.first
    }

    /// returns the localized string of mg/dL or mmol/L
    /// - Returns: string representation of mg/dL or mmol/L
    func bgUnitString() -> String {
        return isMgDl ? Texts_Common.mgdl : Texts_Common.mmol
    }

    /// Blood glucose color dependant on the user defined limit values and also on if it is a recent value
    /// - Returns: a Color object either red, yellow or green
    func bgTextColor() -> Color {
        if let bgReadingDate = bgReadingDate(), bgReadingDate > Date().addingTimeInterval(-60 * 7), let bgValueInMgDl = bgValueInMgDl() {
            if bgValueInMgDl >= urgentHighLimitInMgDl || bgValueInMgDl <= urgentLowLimitInMgDl {
                return .red
            } else if bgValueInMgDl >= highLimitInMgDl || bgValueInMgDl <= lowLimitInMgDl {
                return .yellow
            } else {
                return .green
            }
        } else {
            return .gray
        }
    }

    /// returns the minutes ago string of the last updated time
    /// check if more than 1 hour has passed. If so, then the amount of text to show would be too much so return the shorter version
    /// - Returns: string representation of last reading time as "x mins ago"
    func lastUpdatedMinsAgoString() -> String {
        if let bgReadingDate = bgReadingDate() {
            let diffComponents = Calendar.current.dateComponents([.hour], from: bgReadingDate, to: Date())

            if let hours = diffComponents.hour, hours >= 1 {
                return bgReadingDate.daysAndHoursAgo(appendAgo: true)
            } else {
                return bgReadingDate.daysAndHoursAgoFull(appendAgo: true)
            }
        } else {
            return "Waiting..."
        }
    }

    /// Color dependant on how long ago the last BG reading was
    /// - Returns: a Color either normal (gray) or yellow/red if the reading was several minutes ago and hasn't been updated
    func lastUpdatedTimeColor() -> Color {
        if let bgReadingDate = bgReadingDate(), bgReadingDate > Date().addingTimeInterval(-60 * 7) {
            return .colorSecondary
        } else if let bgReadingDate = bgReadingDate(), bgReadingDate > Date().addingTimeInterval(-60 * 12) {
            return .yellow
        } else if let bgReadingDate = bgReadingDate(), bgReadingDate > Date().addingTimeInterval(-60 * 22) {
            return .red
        } else {
            return .colorTertiary
        }
    }

    ///  returns a string holding the trend arrow
    /// - Returns: trend arrow string (i.e.  "↑")
    func trendArrow() -> String {
        if let bgReadingDate = bgReadingDate(), bgReadingDate > Date().addingTimeInterval(-60 * 7) {
            switch slopeOrdinal {
            case 7:
                return "\u{2193}\u{2193}" // ↓↓
            case 6:
                return "\u{2193}" // ↓
            case 5:
                return "\u{2198}" // ↘
            case 4:
                return "\u{2192}" // →
            case 3:
                return "\u{2197}" // ↗
            case 2:
                return "\u{2191}" // ↑
            case 1:
                return "\u{2191}\u{2191}" // ↑↑
            default:
                return ""
            }
        } else {
            return ""
        }
    }

    /// convert the optional delta change int (in mg/dL) to a formatted change value in the user chosen unit making sure all zero values are shown as a positive change to follow Nightscout convention
    /// - Returns: a string holding the formatted delta change value (i.e. +0.4 or -6)
    func deltaChangeStringInUserChosenUnit() -> String {
        if let bgReadingDate = bgReadingDate(), bgReadingDate > Date().addingTimeInterval(-60 * 7) {
            let deltaValueAsString = isMgDl ? deltaValueInUserUnit.mgDlToMmolAndToString(mgDl: isMgDl) : deltaValueInUserUnit.mmolToString()

            var deltaSign = ""

            if deltaValueInUserUnit > 0 {
                deltaSign = "+"
            }

            // quickly check "value" and prevent "-0mg/dl" or "-0.0mmol/l" being displayed
            // show unitized zero deltas as +0 or +0.0 as per Nightscout format
            return deltaValueInUserUnit == 0.0 ? (isMgDl ? "+0" : "+0.0") : (deltaSign + deltaValueAsString)
        } else {
            return "-"
        }
    }

    /// function to calculate the sensor progress value and return a text color to be used by the view
    /// - Returns: progress: the % progress between 0 and 1, textColor:
    func activeSensorProgress() -> (progress: Float, textColor: Color) {
        if sensorAgeInMinutes > 0, sensorMaxAgeInMinutes > 0 {
            let sensorTimeLeftInMinutes = sensorMaxAgeInMinutes - sensorAgeInMinutes
            let progress = Float(min(max(preferSensorCountdown ? sensorTimeLeftInMinutes / sensorMaxAgeInMinutes : sensorAgeInMinutes / sensorMaxAgeInMinutes, 0), 1))

            // irrespective of all the above, if the current sensor age is over the max age, then just set everything to the expired colour to make it clear
            if sensorTimeLeftInMinutes < 0 {
                return (preferSensorCountdown ? 0 : 1, ConstantsHomeView.sensorProgressExpiredSwiftUI)
            } else if sensorTimeLeftInMinutes <= ConstantsHomeView.sensorProgressViewUrgentInMinutes {
                return (progress, ConstantsHomeView.sensorProgressViewProgressColorUrgentSwiftUI)
            } else if sensorTimeLeftInMinutes <= ConstantsHomeView.sensorProgressViewWarningInMinutes {
                return (progress, ConstantsHomeView.sensorProgressViewProgressColorWarningSwiftUI)
            } else {
                return (progress, ConstantsHomeView.sensorProgressNormalTextColorSwiftUI)
            }
        } else {
            return (0, ConstantsHomeView.sensorProgressNormalTextColorSwiftUI)
        }
    }

    /// returns either the elapsed or remaining sensor lifetime based upon the user's preference
    /// - Returns: string representation of the sensor lifetime as days and hours
    func activeSensorLifetimeText() -> String {
        let lifetimeInMinutes = preferSensorCountdown ? max(sensorMaxAgeInMinutes - sensorAgeInMinutes, 0) : sensorAgeInMinutes
        return lifetimeInMinutes.minutesToDaysAndHours()
    }

    /// returns the sensor noise indicator color supplied by the paired iPhone
    func sensorNoiseIndicatorColor() -> Color? {
        sensorNoiseState()?.color
    }

    /// returns an accessible description of the current sensor noise state
    func sensorNoiseIndicatorAccessibilityLabel() -> String {
        guard let sensorNoiseState = sensorNoiseState() else { return "" }

        return Texts_HomeView.sensorManagementNoiseTitle + ": " + sensorNoiseState.localizedTitle
    }

    private func sensorNoiseState() -> WatchSensorNoiseState? {
        guard isMaster, let sensorNoiseStateRawValue else { return nil }

        return WatchSensorNoiseState(rawValue: sensorNoiseStateRawValue)
    }

    /// check when the last follower connection was and compare that to the actual time
    /// - Returns: color of the follower connection status indicator
    func followerConnectionIndicatorColor() -> Color {
        if followerDataSourceType == .careLink, let followerConnectionStatusRawValue {
            switch followerConnectionStatusRawValue {
            case "loginRequired", "selectPatient": return .gray
            case "connecting", "noData": return .yellow
            case "active": return .green
            case "stale", "rateLimited": return .orange
            case "error": return .red
            default: break
            }
        }

        if timeStampOfLastFollowerConnection > Date().addingTimeInterval(-Double(secondsUntilFollowerDisconnectWarning)) {
            return .green
        } else {
            if followerBackgroundKeepAliveType != .disabled {
                return .red
            } else {
                // if keep-alive is disabled, then this will never show a constant server connection so just "disable"
                // the indicator when not recent. It would be incorrect to show a red error.
                return .gray
            }
        }
    }

    /// check when the last heartbeat connection was and compare that to the actual time
    /// if no heartbeat, just return the standard gray colour for the keep alive type icon
    func getFollowerBackgroundKeepAliveColor() -> Color {
        if followerBackgroundKeepAliveType == .heartbeat {
            if let timeDifferenceInSeconds = Calendar.current.dateComponents([.second], from: timeStampOfLastHeartBeat, to: Date()).second, timeDifferenceInSeconds > secondsUntilHeartBeatDisconnectWarning {
                return .red
            } else {
                return .green
            }
        } else {
            return .gray
        }
    }

    /// used to return values and colors used by a SwiftUI gauge view
    /// - Returns: minValue/maxValue - used to define the limits of the gauge. nilValue - used if there is currently no data present (basically puts the gauge at the 50% mark). gaugeGradient - the color ranges used
    func gaugeModel() -> (minValue: Double, maxValue: Double, nilValue: Double, gaugeGradient: Gradient) {
        // if no readings are available yet, return a gray gradient
        if bgValueInMgDl() == nil {
            return (0, 1, 0.5, Gradient(colors: [.gray]))
        }

        // now we've got the values, if there is no recent reading, return a gray gradient
        if let bgReadingDate = bgReadingDate(), bgReadingDate < Date().addingTimeInterval(-60 * 7) {
            return (0, 1, 0.5, Gradient(colors: [.gray]))
        }

        var minValue: Double = lowLimitInMgDl
        var maxValue: Double = highLimitInMgDl
        var colorArray = [Color]()

        // let's put the min and max values into values/context that makes sense for the UI we show to the user
        if let bgValueInMgDl = bgValueInMgDl() {
            if bgValueInMgDl >= urgentHighLimitInMgDl {
                maxValue = ConstantsCalibrationAlgorithms.maximumBgReadingCalculatedValue
            } else if bgValueInMgDl >= highLimitInMgDl {
                maxValue = urgentHighLimitInMgDl
            }

            if bgValueInMgDl <= urgentLowLimitInMgDl {
                minValue = ConstantsCalibrationAlgorithms.minimumBgReadingCalculatedValue
            } else if bgValueInMgDl <= lowLimitInMgDl {
                minValue = urgentLowLimitInMgDl
            }
        }

        // calculate a nil value to show on the gauge (as it can't display nil). This should basically just peg the gauge indicator in the middle of the current range
        let nilValue = minValue + ((maxValue - minValue) / 2)

        // this means that there is a recent reading so we can show a colored gauge
        // let's round the min value down to nearest 10 and the max up to nearest 10
        // this is to start creating the gradient ranges
        let minValueRoundedDown = Double(10 * Int(minValue / 10))
        let maxValueRoundedUp = Double(10 * Int(maxValue / 10)) + 10

        // the prevent the gradient changes from being too sharp, we'll reduce the granularity if trying to show a bigger range (such as >200mg/dL)
        let reducedGranularity = (maxValueRoundedUp - minValueRoundedDown) > 200

        // step through the range and append the colors as necessary
        for currentValue in stride(from: minValueRoundedDown, through: maxValueRoundedUp, by: reducedGranularity ? 20 : 10) {
            if currentValue > urgentHighLimitInMgDl || currentValue <= urgentLowLimitInMgDl {
                colorArray.append(.red)
            } else if currentValue > highLimitInMgDl || currentValue <= lowLimitInMgDl {
                colorArray.append(.yellow)
            } else {
                colorArray.append(.green)
            }
        }

        return (minValue, maxValue, nilValue, Gradient(colors: colorArray))
    }

    func aidStatusColor() -> Color? {
        aidStatus?.presentation().color
    }

    func aidStatusIconImage() -> Image? {
        guard let systemImage = aidStatus?.presentation().systemImage else { return nil }
        return Image(systemName: systemImage)
    }

    func aidStatusIOBString() -> String {
        guard let aidStatus, aidStatus.presentation().hasFreshData, let iob = aidStatus.iob else { return "-U" }
        return "\(iob.round(toDecimalPlaces: 2).stringWithoutTrailingZeroes)U"
    }

    func aidStatusCOBString() -> String {
        guard let aidStatus, aidStatus.presentation().hasFreshData, let cob = aidStatus.cob else { return "-g" }
        return "\(cob.round(toDecimalPlaces: 0).stringWithoutTrailingZeroes)g"
    }

    func aidStatusActivityAgeString() -> String {
        guard let aidStatus, aidStatus.presentation().showsActivityAge else { return "" }
        guard let lastActivityAt = aidStatus.lastActivityAt else { return "-m" }

        let diffComponents = Calendar.current.dateComponents([.hour], from: lastActivityAt, to: Date())

        if let hours = diffComponents.hour, hours < 1 {
            return "\(lastActivityAt.daysAndHoursAgo(appendAgo: false))"
        } else {
            return "-m"
        }
    }

    // MARK: - helper functions not related with the class structure

    /// request a state update from the iOS companion app
    func requestWatchStateUpdate() {
        guard session.activationState == .activated else {
            session.activate()
            return
        }
        // change the text, this must be done in the main thread but only do it if the watch app is reachable
        if session.isReachable {
            DispatchQueue.main.async {
                self.requestingDataIconColor = ConstantsAppleWatch.requestingDataIconColorPending
            }

            requestWatchUpdate(updateType: "status")
            requestWatchUpdate(updateType: "bgReadings")
        }
    }

    /// request the compact AGP profile used by the Watch main chart background
    func requestAGPBackground(startDate: Date, endDate: Date) {
        // always save the latest requested range first
        // if the session isn't ready, we'll retry when activation/reachability changes
        pendingAGPRequestRange = (startDate: startDate, endDate: endDate)

        sendPendingAGPRequestIfPossible()
    }

    private func sendPendingAGPRequestIfPossible() {
        guard let pendingAGPRequestRange else { return }

        // the Watch app can appear before WCSession has finished activating
        // keep the pending range and try again when activation completes
        guard session.activationState == .activated else {
            session.activate()
            return
        }

        // if the phone isn't reachable yet, keep the pending range and retry on reachability change
        guard session.isReachable else { return }

        // tag each request so old phone replies can be ignored
        latestAGPRequestID += 1

        session.sendMessage([
            "requestWatchUpdate": "agp",
            "requestID": latestAGPRequestID,
            "visibleStartDate": pendingAGPRequestRange.startDate.timeIntervalSince1970,
            "visibleEndDate": pendingAGPRequestRange.endDate.timeIntervalSince1970
        ], replyHandler: nil) { [log] error in
            log.error("Error requesting agp: \(error.localizedDescription, privacy: .public)")
        }
    }

    /// Maps the stored daily AGP profile onto the dates currently visible on the Watch chart.
    func agpBackgroundPointsMatching(startDate: Date, endDate: Date) -> [GlucoseChartAGPPoint] {
        // convert the stored minute-of-day profile into real chart dates for this render pass
        mapAGPProfileToVisibleRange(startDate: startDate, endDate: endDate)
    }

    private func mapAGPProfileToVisibleRange(startDate: Date, endDate: Date) -> [GlucoseChartAGPPoint] {
        guard startDate < endDate, !agpProfilePoints.isEmpty else { return [] }

        let calendar = Calendar.current
        let sortedProfile = agpProfilePoints.sorted { $0.minuteOfDay < $1.minuteOfDay }
        var day = calendar.startOfDay(for: startDate)
        let finalDay = calendar.startOfDay(for: endDate)
        var mappedPoints: [GlucoseChartAGPPoint] = []

        // add interpolated edge points so the AGP bands reach the exact chart start
        if let startBoundaryPoint = agpBoundaryPoint(for: startDate, from: sortedProfile, calendar: calendar) {
            mappedPoints.append(startBoundaryPoint)
        }

        // add every AGP bucket that lands inside the visible chart range
        while day <= finalDay {
            for point in sortedProfile {
                guard let date = calendar.date(byAdding: .minute, value: point.minuteOfDay, to: day),
                      date > startDate,
                      date < endDate else {
                    continue
                }

                mappedPoints.append(GlucoseChartAGPPoint(
                    date: date,
                    p5MgDl: point.p5MgDl,
                    p25MgDl: point.p25MgDl,
                    medianMgDl: point.medianMgDl,
                    p75MgDl: point.p75MgDl,
                    p95MgDl: point.p95MgDl
                ))
            }

            guard let nextDay = calendar.date(byAdding: .day, value: 1, to: day), nextDay > day else {
                break
            }

            day = nextDay
        }

        // add an interpolated edge point so the AGP bands reach the exact chart end
        if let endBoundaryPoint = agpBoundaryPoint(for: endDate, from: sortedProfile, calendar: calendar) {
            mappedPoints.append(endBoundaryPoint)
        }

        return mappedPoints.sorted { $0.date < $1.date }
    }

    private func agpBoundaryPoint(for date: Date, from sortedProfile: [WatchAGPProfilePoint], calendar: Calendar) -> GlucoseChartAGPPoint? {
        guard let firstPoint = sortedProfile.first else { return nil }

        // find where this exact date sits between the surrounding AGP minute-of-day buckets
        // this prevents small gaps at the left and right edges of the chart
        let components = calendar.dateComponents([.hour, .minute, .second], from: date)
        let minuteOfDay = Double((components.hour ?? 0) * 60 + (components.minute ?? 0)) + Double(components.second ?? 0) / 60
        let lowerPoint = sortedProfile.last { Double($0.minuteOfDay) <= minuteOfDay } ?? sortedProfile.last ?? firstPoint
        let upperPoint = sortedProfile.first { Double($0.minuteOfDay) >= minuteOfDay && $0.minuteOfDay != lowerPoint.minuteOfDay } ?? firstPoint
        let lowerMinute = Double(lowerPoint.minuteOfDay)
        let upperMinute = upperPoint.minuteOfDay <= lowerPoint.minuteOfDay ? Double(upperPoint.minuteOfDay + 1440) : Double(upperPoint.minuteOfDay)
        let normalizedMinute = minuteOfDay < lowerMinute ? minuteOfDay + 1440 : minuteOfDay
        let interpolationRange = max(upperMinute - lowerMinute, 1)
        let progress = min(max((normalizedMinute - lowerMinute) / interpolationRange, 0), 1)

        return GlucoseChartAGPPoint(
            date: date,
            p5MgDl: interpolatedAGPValue(from: lowerPoint.p5MgDl, to: upperPoint.p5MgDl, progress: progress),
            p25MgDl: interpolatedAGPValue(from: lowerPoint.p25MgDl, to: upperPoint.p25MgDl, progress: progress),
            medianMgDl: interpolatedAGPValue(from: lowerPoint.medianMgDl, to: upperPoint.medianMgDl, progress: progress),
            p75MgDl: interpolatedAGPValue(from: lowerPoint.p75MgDl, to: upperPoint.p75MgDl, progress: progress),
            p95MgDl: interpolatedAGPValue(from: lowerPoint.p95MgDl, to: upperPoint.p95MgDl, progress: progress)
        )
    }

    private func interpolatedAGPValue(from lowerValue: Double, to upperValue: Double, progress: Double) -> Double {
        lowerValue + (upperValue - lowerValue) * progress
    }

    private func requestWatchUpdate(updateType: String) {
        session.sendMessage(["requestWatchUpdate": updateType], replyHandler: nil) { [log] error in
            log.error("Error requesting \(updateType, privacy: .public): \(error.localizedDescription, privacy: .public)")
        }
    }

    // MARK: - Private functions used to interact with the WCSession and prepare internal data

    private func processWatchPayloadFromDictionary(dictionary: [String: Any]) {
        var processedUpdate = false

        if let statusDictionary = dictionary["status"] as? [String: Any] {
            processedUpdate = processStatusFromDictionary(dictionary: statusDictionary)
        }

        if let bgReadingsDictionary = dictionary["bgReadings"] as? [String: Any] {
            processedUpdate = processBgReadingsFromDictionary(dictionary: bgReadingsDictionary) || processedUpdate
        }

        if let agpDictionary = dictionary["agp"] as? [String: Any] {
            processAGPFromDictionary(dictionary: agpDictionary)
            processedUpdate = true
        }

        if processedUpdate {
            // now process the shared user defaults to get data for the WidgetKit complications
            updateComplicationData()
        }
    }

    private func processBgReadingsFromDictionary(dictionary: [String: Any]) -> Bool {
        let bgReadingDatesFromDictionary: [Double] = dictionary["bgReadingDatesAsDouble"] as? [Double] ?? []

        guard let incomingLatestTimestamp = bgReadingDatesFromDictionary.first else {
            return false
        }

        let incomingLatestDate = Date(timeIntervalSince1970: incomingLatestTimestamp)
        let incomingGeneratedAt = dictionary["generatedAt"] as? Double ?? incomingLatestTimestamp

        // If the Watch has already received this same G7 sample directly, keep the direct state.
        // A genuinely newer iPhone sample still wins automatically, which preserves fallback.
        if let lastDirectG7ReadingDate,
           abs(lastDirectG7ReadingDate.timeIntervalSince(incomingLatestDate)) < 90 {
            return false
        }

        // Ignore very old queued states and, critically, never allow an older BG state to replace
        // a newer value that has already reached the Watch through another delivery channel.
        guard incomingLatestDate > Date(timeIntervalSinceNow: -60 * 60) else {
            return false
        }

        if let currentLatestDate = bgReadingDates.first {
            if incomingLatestDate < currentLatestDate {
                return false
            }

            if incomingLatestDate == currentLatestDate,
               incomingGeneratedAt <= latestBgPayloadGeneratedAt {
                return false
            }
        }

        latestBgPayloadGeneratedAt = incomingGeneratedAt
        bgReadingDates = bgReadingDatesFromDictionary.map { Date(timeIntervalSince1970: $0) }
        bgReadingValues = dictionary["bgReadingValues"] as? [Double] ?? []
        slopeOrdinal = dictionary["slopeOrdinal"] as? Int ?? 0
        deltaValueInUserUnit = dictionary["deltaValueInUserUnit"] as? Double ?? 0
        updatedDate = Date(timeIntervalSince1970: incomingGeneratedAt)
        bgDataSource = "iPhone"

        if let bgReadingDate = bgReadingDate() {
            lastUpdatedTextString = Texts_WatchApp.lastReading + " "
            lastUpdatedTimeString = bgReadingDate.formatted(date: .omitted, time: .shortened)
            lastUpdatedTimeAgoString = bgReadingDate.daysAndHoursAgo(appendAgo: true)
        } else {
            lastUpdatedTextString = Texts_WatchApp.noSensorData
            lastUpdatedTimeString = ""
            lastUpdatedTimeAgoString = ""
        }

        return true
    }

    private func processStatusFromDictionary(dictionary: [String: Any]) -> Bool {
        // transferUserInfo queues every payload while the Watch app is inactive. Ignore old status
        // updates so reopening the app does not replay days of state changes one by one.
        guard let generatedAt = dictionary["generatedAt"] as? Double,
              Date(timeIntervalSince1970: generatedAt) > Date(timeIntervalSinceNow: -60 * 60) else {
            return false
        }

        isMgDl = dictionary["isMgDl"] as? Bool ?? true
        urgentLowLimitInMgDl = dictionary["urgentLowLimitInMgDl"] as? Double ?? 60
        lowLimitInMgDl = dictionary["lowLimitInMgDl"] as? Double ?? 70
        highLimitInMgDl = dictionary["highLimitInMgDl"] as? Double ?? 180
        urgentHighLimitInMgDl = dictionary["urgentHighLimitInMgDl"] as? Double ?? 250
        updatedDate = Date(timeIntervalSince1970: generatedAt)
        activeSensorDescription = dictionary["activeSensorDescription"] as? String ?? ""
        sensorAgeInMinutes = dictionary["sensorAgeInMinutes"] as? Double ?? 0
        sensorMaxAgeInMinutes = dictionary["sensorMaxAgeInMinutes"] as? Double ?? 0
        preferSensorCountdown = dictionary["preferSensorCountdown"] as? Bool ?? false
        sensorNoiseStateRawValue = dictionary["sensorNoiseStateRawValue"] as? Int
        isMaster = dictionary["isMaster"] as? Bool ?? true
        followerDataSourceType = FollowerDataSourceType(rawValue: dictionary["followerDataSourceTypeRawValue"] as? Int ?? 0) ?? .nightscout
        followerBackgroundKeepAliveType = FollowerBackgroundKeepAliveType(rawValue: dictionary["followerBackgroundKeepAliveTypeRawValue"] as? Int ?? 0) ?? .normal
        followerConnectionStatusRawValue = dictionary["followerConnectionStatusRawValue"] as? String
        timeStampOfLastFollowerConnection = Date(timeIntervalSince1970: dictionary["timeStampOfLastFollowerConnection"] as? Double ?? 0)
        secondsUntilFollowerDisconnectWarning = dictionary["secondsUntilFollowerDisconnectWarning"] as? Int ?? 0
        timeStampOfLastHeartBeat = Date(timeIntervalSince1970: dictionary["timeStampOfLastHeartBeat"] as? Double ?? 0)
        secondsUntilHeartBeatDisconnectWarning = dictionary["secondsUntilHeartBeatDisconnectWarning"] as? Int ?? 0
        keepAliveIsDisabled = dictionary["keepAliveIsDisabled"] as? Bool ?? false

        if let aidStatusDictionary = dictionary["aidStatus"] as? [String: Any],
           let data = try? JSONSerialization.data(withJSONObject: aidStatusDictionary),
           let decodedStatus = try? JSONDecoder().decode(AIDStatus.self, from: data) {
            aidStatus = decodedStatus
        } else {
            aidStatus = nil
        }

        return true
    }

    private func processAGPFromDictionary(dictionary: [String: Any]) {
        // the payload is column-based because it's smaller and cheaper to decode on watchOS
        // than sending raw glucose history or nested report objects
        let requestID = dictionary["requestID"] as? Double ?? 0
        let minuteOfDayValues = dictionary["minuteOfDayValues"] as? [Int] ?? []
        let p5Values = dictionary["p5Values"] as? [Double] ?? []
        let p25Values = dictionary["p25Values"] as? [Double] ?? []
        let medianValues = dictionary["medianValues"] as? [Double] ?? []
        let p75Values = dictionary["p75Values"] as? [Double] ?? []
        let p95Values = dictionary["p95Values"] as? [Double] ?? []
        let pointCount = [
            minuteOfDayValues.count,
            p5Values.count,
            p25Values.count,
            medianValues.count,
            p75Values.count,
            p95Values.count
        ].min() ?? 0

        // ignore stale replies if the user has already requested a newer AGP profile
        guard requestID == latestAGPRequestID else {
            return
        }

        // this request has now been answered, even if the profile itself is empty
        pendingAGPRequestRange = nil

        guard pointCount > 0 else {
            agpProfilePoints = []
            agpBackgroundPoints = []
            return
        }

        // validate the percentile ordering before storing the profile
        // bad ordering can make Swift Charts draw crossing AGP bands
        agpProfilePoints = (0..<pointCount).compactMap { index in
            let p5 = p5Values[index]
            let p25 = p25Values[index]
            let median = medianValues[index]
            let p75 = p75Values[index]
            let p95 = p95Values[index]
            let minuteOfDay = minuteOfDayValues[index]

            guard (0..<1440).contains(minuteOfDay), p5 <= p25, p25 <= median, median <= p75, p75 <= p95 else {
                return nil
            }

            return WatchAGPProfilePoint(
                minuteOfDay: minuteOfDay,
                p5MgDl: p5,
                p25MgDl: p25,
                medianMgDl: median,
                p75MgDl: p75,
                p95MgDl: p95
            )
        }

        let fallbackEndDate = Date()
        let fallbackStartDate = fallbackEndDate.addingTimeInterval(-12 * 60 * 60)

        // create an initial mapped set immediately so the AGP page can render as soon as the data arrives
        // later chart renders will remap from agpProfilePoints for their own visible range
        agpBackgroundPoints = mapAGPProfileToVisibleRange(
            startDate: bgReadingDates.last ?? fallbackStartDate,
            endDate: bgReadingDates.first ?? fallbackEndDate
        )
    }



    // MARK: - Manual G7 authentication probe

    func startG7AuthProbe() {
        guard !g7AuthProbeRunning else { return }

        g7AuthProbeStatus = "initialisiere Auth-Probe…"
        g7AuthProbeDeviceName = ""
        g7AuthProbeResponseHex = ""
        g7AuthProbeChallengeReceived = false
        g7AuthProbeTelemetry = ""
        g7AuthProbeRunning = true

        let manager = G7AuthProbeManager { [weak self] status, deviceName, responseHex, challengeReceived, telemetry, finished in
            DispatchQueue.main.async {
                guard let self else { return }
                self.g7AuthProbeStatus = status
                self.g7AuthProbeDeviceName = deviceName
                self.g7AuthProbeResponseHex = responseHex
                self.g7AuthProbeChallengeReceived = challengeReceived
                self.g7AuthProbeTelemetry = telemetry
                if finished {
                    self.g7AuthProbeRunning = false
                    self.g7AuthProbeManager = nil
                }
            }
        }

        g7AuthProbeManager = manager
        manager.start()
    }

    func stopG7AuthProbe() {
        g7AuthProbeManager?.stop(userInitiated: true)
    }

    // MARK: - Direct Dexcom G7 Watch BLE path

    private func processDirectG7Reading(_ reading: DirectG7Reading) {
        // Never let an old/expired peripheral replace a clearly newer state already on the Watch.
        if let currentLatestDate = bgReadingDates.first,
           currentLatestDate > reading.date.addingTimeInterval(90) {
            return
        }

        // Merge into the existing 12-hour history. Remove the same sample if it already arrived
        // from the iPhone (timestamps can differ by a few seconds between the two paths).
        var merged = Array(zip(bgReadingDates, bgReadingValues))
        merged.removeAll { abs($0.0.timeIntervalSince(reading.date)) < 90 }
        merged.append((reading.date, reading.glucoseMgDl))
        merged = merged
            .filter { $0.0 > Date().addingTimeInterval(-12 * 60 * 60) }
            .sorted { $0.0 > $1.0 }

        bgReadingDates = merged.map { $0.0 }
        bgReadingValues = merged.map { $0.1 }
        bgReadingDatesAsDouble = bgReadingDates.map { $0.timeIntervalSince1970 }

        slopeOrdinal = directSlopeOrdinal(for: reading.trendMgDlPerMinute)

        // Delta is meaningful only when the previous sample is from roughly one G7 interval ago.
        if merged.count > 1 {
            let previousDate = merged[1].0
            let previousMgDl = merged[1].1
            let interval = reading.date.timeIntervalSince(previousDate)

            if interval > 0, interval <= 7.5 * 60 {
                if isMgDl {
                    deltaValueInUserUnit = reading.glucoseMgDl - previousMgDl
                } else {
                    let currentMmol = ((reading.glucoseMgDl / 18.0182) * 10).rounded() / 10
                    let previousMmol = ((previousMgDl / 18.0182) * 10).rounded() / 10
                    deltaValueInUserUnit = currentMmol - previousMmol
                }
            } else {
                deltaValueInUserUnit = 0
            }
        } else {
            deltaValueInUserUnit = 0
        }

        let now = Date()
        latestBgPayloadGeneratedAt = max(latestBgPayloadGeneratedAt, now.timeIntervalSince1970)
        lastDirectG7ReadingDate = reading.date
        updatedDate = now
        bgDataSource = "G7 BLE"

        directG7LastValue = reading.glucoseMgDl
        directG7LastDate = reading.date
        directG7LastTrend = reading.trendMgDlPerMinute
        directG7LastSequence = reading.sequence
        directG7ReadingCount += 1

        lastUpdatedTextString = Texts_WatchApp.lastReading + " "
        lastUpdatedTimeString = reading.date.formatted(date: .omitted, time: .shortened)
        lastUpdatedTimeAgoString = reading.date.daysAndHoursAgo(appendAgo: true)

        // Persist immediately for the WidgetKit complication and ask only the xDrip complication
        // timeline to reload. WidgetKit still controls the exact render timing.
        updateComplicationData()
    }

    private func directSlopeOrdinal(for trend: Double?) -> Int {
        guard let trend else { return 0 }

        if trend >= 3 {
            return 1       // ↑↑
        } else if trend >= 2 {
            return 2       // ↑
        } else if trend >= 1 {
            return 3       // ↗
        } else if trend > -1 {
            return 4       // →
        } else if trend > -2 {
            return 5       // ↘
        } else if trend > -3 {
            return 6       // ↓
        } else {
            return 7       // ↓↓
        }
    }

    /// once we've process the state update, then save this data to the shared app group so that the complication can read it
    private func updateComplicationData() {
        guard let sharedUserDefaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else { return }

        // Do not leave stale glucose behind the warning when disabled; complications may remain
        // visible long after watchOS stops receiving updates from the phone.
        let complicationBgReadingValues = keepAliveIsDisabled ? [] : bgReadingValues
        let complicationBgReadingDates = keepAliveIsDisabled ? [] : bgReadingDates
        let complicationSlopeOrdinal = keepAliveIsDisabled ? 0 : slopeOrdinal
        let complicationDeltaValueInUserUnit = keepAliveIsDisabled ? 0 : deltaValueInUserUnit

        let bgReadingDatesAsDouble = complicationBgReadingDates.map { date in
            date.timeIntervalSince1970
        }

        let complicationSharedUserDefaultsModel = ComplicationSharedUserDefaultsModel(bgReadingValues: complicationBgReadingValues, bgReadingDatesAsDouble: bgReadingDatesAsDouble, isMgDl: isMgDl, slopeOrdinal: complicationSlopeOrdinal, deltaValueInUserUnit: complicationDeltaValueInUserUnit, urgentLowLimitInMgDl: urgentLowLimitInMgDl, lowLimitInMgDl: lowLimitInMgDl, highLimitInMgDl: highLimitInMgDl, urgentHighLimitInMgDl: urgentHighLimitInMgDl, keepAliveIsDisabled: keepAliveIsDisabled)

        // store the model in the shared user defaults using a name that is uniquely specific to this copy of the app as installed on
        // the user's device - this allows several copies of the app to be installed without cross-contamination of widget/complication data
        let stateKey = "complicationSharedUserDefaults.\(Bundle.main.mainAppBundleIdentifier)"
        let sourceKey = "complicationDataSource.\(Bundle.main.mainAppBundleIdentifier)"
        var stateChanged = false

        if let stateData = try? JSONEncoder().encode(complicationSharedUserDefaultsModel),
           sharedUserDefaults.data(forKey: stateKey) != stateData {
            sharedUserDefaults.set(stateData, forKey: stateKey)
            stateChanged = true
        }

        // Keep the source key backward-compatible, but don't spend a WidgetKit reload budget
        // when neither the BG payload nor its source actually changed.
        let sourceChanged = sharedUserDefaults.string(forKey: sourceKey) != bgDataSource
        if sourceChanged {
            sharedUserDefaults.set(bgDataSource, forKey: sourceKey)
        }

        if stateChanged || sourceChanged {
            // Every genuinely new BG state is already persisted at this point. Reload ONLY the
            // xDrip complication; the Provider then replaces its rolling/stale future timeline.
            for complicationKind in [
                "xDripGraphV33",
                "xDripBGV36",
                "xDripDeltaV36"
            ] {
                WidgetCenter.shared.reloadTimelines(ofKind: complicationKind)
            }
            lastComplicationUpdateTimeStamp = .now
        }
    }
}



// MARK: - Manual G7 authentication probe

private final class G7AuthProbeManager: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    typealias UpdateHandler = (_ status: String, _ deviceName: String, _ responseHex: String, _ challengeReceived: Bool, _ telemetry: String, _ finished: Bool) -> Void

    private let advertisementUUID = CBUUID(string: "FEBC")
    private let serviceUUID = CBUUID(string: "F8083532-849E-531C-C594-30F1F86A4EA5")
    private let expectedChannelUUIDs = [
        CBUUID(string: "F8083534-849E-531C-C594-30F1F86A4EA5"),
        CBUUID(string: "F8083535-849E-531C-C594-30F1F86A4EA5"),
        CBUUID(string: "F8083536-849E-531C-C594-30F1F86A4EA5"),
        CBUUID(string: "F8083538-849E-531C-C594-30F1F86A4EA5")
    ]

    private let testWindowSeconds: TimeInterval = 2700
    private let retryDelaySeconds: TimeInterval = 3
    private let minStableConnectionSeconds: TimeInterval = 0.25
    private let connectTimeoutSeconds: TimeInterval = 15
    private let gattTimeoutSeconds: TimeInterval = 8
    private let notifySetupTimeoutSeconds: TimeInterval = 5
    private let passiveListenSeconds: TimeInterval = 20
    private let captureAfterFirstRXSeconds: TimeInterval = 4
    private let targetConsecutiveBGReadings = 6

    private let onUpdate: UpdateHandler
    private var central: CBCentralManager!
    private var targetPeripheral: CBPeripheral?
    private var protectedPeripheralIDs = Set<UUID>()
    private var expectedCharacteristics: [CBUUID: CBCharacteristic] = [:]

    private var running = false
    private var localDisconnectRequested = false
    private var finishAfterLocalDisconnect = false
    private var retryAfterLocalDisconnect = false
    private var pendingFinalStatus = ""

    private var lastDeviceName = ""
    private var latestRXHex = ""
    private var eventLog: [String] = []
    private var connectedAt: Date?
    private var overallDeadline: Date?
    private var attemptCount = 0

    private var pendingNotifyUUIDs = Set<CBUUID>()
    private var enabledNotifyUUIDs = Set<CBUUID>()
    private var failedNotifyUUIDs = Set<CBUUID>()
    private var rxCounts: [CBUUID: Int] = [:]
    private var firstRXAt: Date?
    private var latestPassiveBGSummary = ""

    // Build 15 validation state is intentionally kept across retry/disconnect attempts.
    // Per-attempt BLE state is still reset normally.
    private var capturedBGReadings: [String] = []
    private var capturedBGSequences = Set<UInt16>()
    private var lastCapturedBGSequence: UInt16?
    private var consecutiveBGRun = 0
    private var longestConsecutiveBGRun = 0
    private var duplicateBGPackets = 0

    private var overallTimeoutTask: DispatchWorkItem?
    private var statusTickTask: DispatchWorkItem?
    private var retryTask: DispatchWorkItem?
    private var connectTimeoutTask: DispatchWorkItem?
    private var qualificationTask: DispatchWorkItem?
    private var gattTimeoutTask: DispatchWorkItem?
    private var notifySetupTimeoutTask: DispatchWorkItem?
    private var passiveListenTask: DispatchWorkItem?
    private var rxFinishTask: DispatchWorkItem?

    init(onUpdate: @escaping UpdateHandler) {
        self.onUpdate = onUpdate
        super.init()
        // No restore identifier: this manual diagnostic must not be resurrected by watchOS.
        central = CBCentralManager(delegate: self, queue: .main, options: nil)
    }

    private var rxTotal: Int {
        rxCounts.values.reduce(0, +)
    }

    func start() {
        guard !running else { return }
        running = true
        targetPeripheral = nil
        protectedPeripheralIDs.removeAll()
        localDisconnectRequested = false
        finishAfterLocalDisconnect = false
        retryAfterLocalDisconnect = false
        pendingFinalStatus = ""
        lastDeviceName = ""
        latestRXHex = ""
        eventLog.removeAll()
        connectedAt = nil
        overallDeadline = nil
        attemptCount = 0
        capturedBGReadings.removeAll()
        capturedBGSequences.removeAll()
        lastCapturedBGSequence = nil
        consecutiveBGRun = 0
        longestConsecutiveBGRun = 0
        duplicateBGPackets = 0
        resetPerAttemptData()

        addEvent("Build15 gestartet · Multi-Cycle 0x4E-Validierung")
        addEvent("45 min max · Ziel 6 fortlaufende BG-Sequenzen")
        addEvent("FEBC/GATT-Match · Name ignoriert · nur CCCD Notify")
        addEvent("Dexcom-App-TX = 0 · KEIN Schreiben in xDrip/Komplikation")
        publish("warte auf Bluetooth…")

        if central.state == .poweredOn {
            beginObservationWindow()
        }
    }

    func stop(userInitiated: Bool) {
        guard running else { return }
        addEvent(userInitiated ? "Benutzerabbruch" : "Notify-Test stop")
        if let peripheral = targetPeripheral,
           peripheral.state == .connected || peripheral.state == .connecting {
            requestLocalDisconnect(
                finalStatus: userInitiated ? "Notify-Test abgebrochen" : "Notify-Test beendet",
                finish: true
            )
        } else {
            finishWithoutConnection(userInitiated ? "Notify-Test abgebrochen" : "Notify-Test beendet")
        }
    }

    private func timestamp(_ date: Date = Date()) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "HH:mm:ss.SSS"
        return formatter.string(from: date)
    }

    private func elapsedMS(from start: Date?, to end: Date = Date()) -> String {
        guard let start else { return "n/a" }
        return String(format: "%.0f ms", end.timeIntervalSince(start) * 1000.0)
    }

    private func shortUUID(_ uuid: CBUUID) -> String {
        let value = uuid.uuidString.uppercased()
        if value.hasPrefix("F808") && value.count >= 8 {
            return String(value.prefix(8))
        }
        return value
    }

    private func propertyText(_ characteristic: CBCharacteristic) -> String {
        var values: [String] = []
        let properties = characteristic.properties
        if properties.contains(.read) { values.append("R") }
        if properties.contains(.write) { values.append("W") }
        if properties.contains(.writeWithoutResponse) { values.append("WNR") }
        if properties.contains(.notify) { values.append("N") }
        if properties.contains(.indicate) { values.append("I") }
        if properties.contains(.broadcast) { values.append("B") }
        return values.isEmpty ? "-" : values.joined(separator: "|")
    }

    private func hex(_ data: Data) -> String {
        data.map { String(format: "%02X", $0) }.joined()
    }

    private func littleEndianUInt16(_ data: Data, offset: Int) -> UInt16 {
        UInt16(data[offset]) | (UInt16(data[offset + 1]) << 8)
    }

    private func littleEndianUInt32(_ data: Data, offset: Int) -> UInt32 {
        UInt32(data[offset])
            | (UInt32(data[offset + 1]) << 8)
            | (UInt32(data[offset + 2]) << 16)
            | (UInt32(data[offset + 3]) << 24)
    }

    /// Decode only packets that the sensor has already notified to us. This mirrors the
    /// established G7 real-time packet field layout used by xDrip/Loop-style G7 parsers:
    /// opcode 0x4E, message timestamp @2, sequence @6, age @10, glucose @12,
    /// algorithm state @14, trend @15. No application-level BLE write is performed here.
    private func passivePacketSummary(_ data: Data, characteristic: CBCharacteristic) -> String? {
        let channel = shortUUID(characteristic.uuid)

        if channel == "F8083534", data.count >= 19, data[0] == 0x4E, data[1] == 0x00 {
            let messageTimestamp = littleEndianUInt32(data, offset: 2)
            let sequence = littleEndianUInt16(data, offset: 6)
            let ageSeconds = Int(data[10])
            let glucoseWord = littleEndianUInt16(data, offset: 12)
            let glucose = Int(glucoseWord & 0x0FFF)
            let algorithmState = Int(data[14])
            let trendRaw = Int(Int8(bitPattern: data[15]))
            let trend = Double(trendRaw) / 10.0

            addEvent(
                String(
                    format: "DECODE 0x4E ts=%u seq=%u age=%ds BG=%d state=%d trend=%+.1f",
                    messageTimestamp,
                    sequence,
                    ageSeconds,
                    glucose,
                    algorithmState,
                    trend
                )
            )

            guard (20...600).contains(glucose) else {
                return "0x4E erkannt · BG-Feld unplausibel: \(glucose) · nur Diagnose"
            }

            // The diagnostic page may display a decoded value, but an unexpectedly old packet
            // is explicitly labelled as not current and is never written to xDrip state.
            guard ageSeconds <= 7 * 60 else {
                return "0x4E erkannt · \(glucose) mg/dL · Alter \(ageSeconds)s · NICHT AKTUELL"
            }

            return String(
                format: "PASSIV-BG %d mg/dL · Alter %ds · Trend %+.1f/min · Seq %u · State %d",
                glucose,
                ageSeconds,
                trend,
                sequence,
                algorithmState
            )
        }

        if channel == "F8083535", data.count >= 1, data[0] == 0x03 {
            return "PASSIV Auth-Challenge 0x03 · \(data.count) Byte · keine Antwort"
        }

        if channel == "F8083535", data.count >= 3, data[0] == 0x05 {
            return String(format: "PASSIV Auth-Status 05 %02X %02X · keine TX", data[1], data[2])
        }

        if channel == "F8083534", let opcode = data.first {
            return String(format: "PASSIV 3534 Opcode 0x%02X · %d Byte", opcode, data.count)
        }

        if channel == "F8083536" {
            return "PASSIV 3536 Notify · \(data.count) Byte"
        }

        if channel == "F8083538" {
            return "PASSIV 3538 Notify · \(data.count) Byte"
        }

        return nil
    }

    private func recordPassiveBGPacket(_ data: Data) {
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

    private func remainingSeconds() -> TimeInterval {
        guard let deadline = overallDeadline else { return testWindowSeconds }
        return max(0, deadline.timeIntervalSinceNow)
    }

    private func formatRemaining(_ seconds: TimeInterval) -> String {
        let total = max(0, Int(ceil(seconds)))
        return String(format: "%02d:%02d", total / 60, total % 60)
    }

    private func addEvent(_ text: String) {
        eventLog.append("\(timestamp())  \(text)")
        if eventLog.count > 240 {
            eventLog.removeFirst(eventLog.count - 240)
        }
    }

    private func publish(_ status: String, finished: Bool = false) {
        onUpdate(status, lastDeviceName, latestRXHex, false, eventLog.joined(separator: "\n"), finished)
    }

    private func resetPerAttemptData() {
        expectedCharacteristics.removeAll()
        pendingNotifyUUIDs.removeAll()
        enabledNotifyUUIDs.removeAll()
        failedNotifyUUIDs.removeAll()
        rxCounts.removeAll()
        firstRXAt = nil
        latestRXHex = ""
        latestPassiveBGSummary = ""
    }

    private func cancelPerAttemptTasks() {
        retryTask?.cancel()
        retryTask = nil
        connectTimeoutTask?.cancel()
        connectTimeoutTask = nil
        qualificationTask?.cancel()
        qualificationTask = nil
        gattTimeoutTask?.cancel()
        gattTimeoutTask = nil
        notifySetupTimeoutTask?.cancel()
        notifySetupTimeoutTask = nil
        passiveListenTask?.cancel()
        passiveListenTask = nil
        rxFinishTask?.cancel()
        rxFinishTask = nil
    }

    private func cancelAllTasks() {
        cancelPerAttemptTasks()
        overallTimeoutTask?.cancel()
        overallTimeoutTask = nil
        statusTickTask?.cancel()
        statusTickTask = nil
    }

    private func beginObservationWindow() {
        guard running, central.state == .poweredOn, overallDeadline == nil else { return }

        let connected = central.retrieveConnectedPeripherals(withServices: [serviceUUID])
        protectedPeripheralIDs = Set(connected.map { $0.identifier })
        addEvent("Bereits verbundene G7 geschützt: \(protectedPeripheralIDs.count)")
        for id in protectedPeripheralIDs {
            addEvent("GESCHÜTZT id=\(id.uuidString)")
        }

        overallDeadline = Date().addingTimeInterval(testWindowSeconds)
        addEvent("Build15 Multi-Cycle-Fenster gestartet: 2700 s / 45 min")
        armOverallTimeout()
        scheduleStatusTick()
        startScan()
    }

    private func armOverallTimeout() {
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

    private func scheduleStatusTick() {
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

    private func startScan() {
        guard running, central.state == .poweredOn, targetPeripheral == nil else { return }
        guard remainingSeconds() > 0 else { return }

        central.stopScan()
        central.scanForPeripherals(
            withServices: [advertisementUUID],
            options: [CBCentralManagerScanOptionAllowDuplicatesKey: true]
        )
        addEvent("SCAN FEBC aktiv · Name kein Filter · Rest \(formatRemaining(remainingSeconds()))")
        publish("suche FEBC-G7-Fenster… \(formatRemaining(remainingSeconds()))")
    }

    private func scheduleRetry(_ reason: String) {
        guard running else { return }

        cancelPerAttemptTasks()
        central.stopScan()
        targetPeripheral = nil
        connectedAt = nil
        localDisconnectRequested = false
        finishAfterLocalDisconnect = false
        retryAfterLocalDisconnect = false
        pendingFinalStatus = ""
        resetPerAttemptData()

        let remaining = remainingSeconds()
        guard remaining > 0 else {
            appendValidationSummaryEvents()
            finishWithoutConnection("Build15 Zeitfenster beendet · \(validationStatusLine())")
            return
        }

        addEvent("RETRY in 3 s · \(reason)")
        publish("Fenster geschlossen · neuer Versuch in 3 s")

        let task = DispatchWorkItem { [weak self] in
            guard let self, self.running else { return }
            self.retryTask = nil
            self.startScan()
        }
        retryTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + min(retryDelaySeconds, remaining), execute: task)
    }

    private func armConnectTimeout(for peripheral: CBPeripheral) {
        connectTimeoutTask?.cancel()
        let task = DispatchWorkItem { [weak self, weak peripheral] in
            guard let self, self.running,
                  let peripheral,
                  self.targetPeripheral?.identifier == peripheral.identifier else { return }

            self.addEvent("CONNECT timeout Attempt #\(self.attemptCount)")
            if peripheral.state == .connected || peripheral.state == .connecting {
                self.requestLocalDisconnect(finalStatus: "Connect-Timeout", retry: true)
            } else {
                self.scheduleRetry("Connect-Timeout")
            }
        }
        connectTimeoutTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + connectTimeoutSeconds, execute: task)
    }

    private func armGattTimeout(for peripheral: CBPeripheral, stage: String) {
        gattTimeoutTask?.cancel()
        let task = DispatchWorkItem { [weak self, weak peripheral] in
            guard let self, self.running,
                  let peripheral,
                  self.targetPeripheral?.identifier == peripheral.identifier else { return }
            self.addEvent("GATT timeout · \(stage)")
            self.requestLocalDisconnect(finalStatus: "GATT-Timeout \(stage)", retry: true)
        }
        gattTimeoutTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + gattTimeoutSeconds, execute: task)
    }

    private func armNotifySetupTimeout(for peripheral: CBPeripheral) {
        notifySetupTimeoutTask?.cancel()
        let task = DispatchWorkItem { [weak self, weak peripheral] in
            guard let self, self.running,
                  let peripheral,
                  self.targetPeripheral?.identifier == peripheral.identifier else { return }
            let waiting = self.pendingNotifyUUIDs.map { self.shortUUID($0) }.sorted().joined(separator: ",")
            self.addEvent("NOTIFY setup timeout · offen=\(waiting)")
            self.requestLocalDisconnect(finalStatus: "Notify-Setup-Timeout", retry: true)
        }
        notifySetupTimeoutTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + notifySetupTimeoutSeconds, execute: task)
    }

    private func armPassiveListen(for peripheral: CBPeripheral) {
        passiveListenTask?.cancel()

        if rxTotal > 0 {
            scheduleFinishAfterRX(for: peripheral)
            return
        }

        addEvent("NOTIFY 4/4 aktiv · passiv \(Int(passiveListenSeconds)) s · Dexcom-TX=0")
        publish("Notify 4/4 aktiv · warte passiv auf RX…")

        let task = DispatchWorkItem { [weak self, weak peripheral] in
            guard let self, self.running,
                  let peripheral,
                  self.targetPeripheral?.identifier == peripheral.identifier else { return }
            self.addEvent("20 s Notify ohne RX")
            self.requestLocalDisconnect(finalStatus: "Notify aktiv · 20 s ohne RX", retry: true)
        }
        passiveListenTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + passiveListenSeconds, execute: task)
    }

    private func scheduleFinishAfterRX(for peripheral: CBPeripheral) {
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

    private func requestLocalDisconnect(
        finalStatus: String,
        finish: Bool = false,
        retry: Bool = false
    ) {
        guard running else { return }

        central.stopScan()
        qualificationTask?.cancel()
        qualificationTask = nil
        connectTimeoutTask?.cancel()
        connectTimeoutTask = nil
        gattTimeoutTask?.cancel()
        gattTimeoutTask = nil
        notifySetupTimeoutTask?.cancel()
        notifySetupTimeoutTask = nil
        passiveListenTask?.cancel()
        passiveListenTask = nil
        rxFinishTask?.cancel()
        rxFinishTask = nil

        pendingFinalStatus = finalStatus
        finishAfterLocalDisconnect = finish
        retryAfterLocalDisconnect = retry

        guard let peripheral = targetPeripheral,
              peripheral.state == .connected || peripheral.state == .connecting else {
            if finish {
                finishWithoutConnection(finalStatus)
            } else if retry {
                scheduleRetry(finalStatus)
            } else {
                finishWithoutConnection(finalStatus)
            }
            return
        }

        localDisconnectRequested = true
        addEvent("LOCAL CANCEL angefordert · \(finalStatus)")
        central.cancelPeripheralConnection(peripheral)
    }

    private func finishWithoutConnection(_ status: String) {
        guard running else { return }

        running = false
        central.stopScan()
        cancelAllTasks()
        targetPeripheral = nil
        connectedAt = nil
        addEvent(status)
        publish(status, finished: true)
    }

    private func finishRemoteAfterRX(_ status: String) {
        guard running else { return }

        running = false
        central.stopScan()
        cancelAllTasks()
        targetPeripheral = nil
        connectedAt = nil
        addEvent(status)
        publish(status, finished: true)
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard running else { return }

        switch central.state {
        case .poweredOn:
            addEvent("Bluetooth poweredOn")
            beginObservationWindow()
        case .poweredOff:
            finishWithoutConnection("Bluetooth aus")
        case .unauthorized:
            finishWithoutConnection("Bluetooth-Berechtigung fehlt")
        case .unsupported:
            finishWithoutConnection("CoreBluetooth nicht unterstützt")
        case .resetting:
            addEvent("Bluetooth resetting")
            publish("Bluetooth wird zurückgesetzt")
        case .unknown:
            addEvent("Bluetooth unknown")
            publish("Bluetooth-Status unbekannt")
        @unknown default:
            addEvent("Bluetooth unknown default")
            publish("Bluetooth-Status unbekannt")
        }
    }

    func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String : Any],
        rssi RSSI: NSNumber
    ) {
        guard running, targetPeripheral == nil else { return }

        let advertisedServices = advertisementData[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID] ?? []
        let connectable = (advertisementData[CBAdvertisementDataIsConnectable] as? NSNumber)?.boolValue
        let name = peripheral.name ?? (advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? "")
        let displayName = name.isEmpty ? "FEBC/ohne Namen" : name
        let servicesText = advertisedServices.isEmpty
            ? "nicht geliefert (Scanfilter FEBC)"
            : advertisedServices.map { $0.uuidString.uppercased() }.joined(separator: ",")
        let connectableText = connectable.map { $0 ? "ja" : "nein" } ?? "unbekannt"

        // Name-independent identity: scanForPeripherals is already filtered to FEBC.
        // If service UUIDs are present in the callback, require FEBC as an extra check.
        if !advertisedServices.isEmpty && !advertisedServices.contains(advertisementUUID) {
            addEvent("ADV ignoriert · FEBC fehlt trotz Scanfilter")
            return
        }

        addEvent("ADV \(displayName) RSSI=\(RSSI) dBm conn=\(connectableText)")
        addEvent("MATCH=FEBC · Name nur Anzeige")
        addEvent("ADV services=\(servicesText)")
        addEvent("ADV id=\(peripheral.identifier.uuidString)")

        guard !protectedPeripheralIDs.contains(peripheral.identifier) else {
            addEvent("ADV ignoriert · geschützter Peripheral")
            publish("bereits verbundenen G7 geschützt")
            return
        }

        guard connectable != false else {
            addEvent("ADV ignoriert · nicht connectable")
            return
        }

        central.stopScan()
        targetPeripheral = peripheral
        peripheral.delegate = self
        lastDeviceName = displayName
        connectedAt = nil
        localDisconnectRequested = false
        finishAfterLocalDisconnect = false
        retryAfterLocalDisconnect = false
        pendingFinalStatus = ""
        resetPerAttemptData()
        attemptCount += 1

        addEvent("Attempt #\(attemptCount) · CONNECT \(displayName)")
        publish("FEBC-Kandidat · verbinde · Name nicht als ID verwendet")
        central.connect(peripheral, options: nil)
        armConnectTimeout(for: peripheral)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        guard running, targetPeripheral?.identifier == peripheral.identifier else { return }

        connectTimeoutTask?.cancel()
        connectTimeoutTask = nil
        connectedAt = Date()
        let liveName = peripheral.name ?? ""
        if !liveName.isEmpty { lastDeviceName = liveName }

        addEvent("CONNECTED #\(attemptCount) \(lastDeviceName)")
        addEvent("Connected time: \(timestamp(connectedAt!))")
        publish("verbunden · 250 ms Stabilitätstest · noch kein Notify")

        qualificationTask?.cancel()
        let task = DispatchWorkItem { [weak self, weak peripheral] in
            guard let self, self.running,
                  let peripheral,
                  self.targetPeripheral?.identifier == peripheral.identifier,
                  peripheral.state == .connected else { return }

            self.addEvent("Connection ≥250 ms · discoverServices 3532")
            self.publish("≥250 ms stabil · prüfe G7-Service 3532")
            peripheral.discoverServices([self.serviceUUID])
            self.armGattTimeout(for: peripheral, stage: "Service 3532")
        }
        qualificationTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + minStableConnectionSeconds, execute: task)
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        guard running, targetPeripheral?.identifier == peripheral.identifier else { return }

        connectTimeoutTask?.cancel()
        connectTimeoutTask = nil
        addEvent("didFailToConnect #\(attemptCount) error=\(error?.localizedDescription ?? "nil")")
        scheduleRetry("Connect fehlgeschlagen")
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        guard running, targetPeripheral?.identifier == peripheral.identifier else { return }

        cancelPerAttemptTasks()

        let source = localDisconnectRequested ? "LOCAL" : "REMOTE/COREBT"
        addEvent("DISCONNECT #\(attemptCount) source=\(source)")
        addEvent("didDisconnect error=\(error?.localizedDescription ?? "nil")")
        addEvent("Connected→Disconnect: \(elapsedMS(from: connectedAt))")

        if localDisconnectRequested {
            let finalStatus = pendingFinalStatus
            let shouldFinish = finishAfterLocalDisconnect
            let shouldRetry = retryAfterLocalDisconnect

            localDisconnectRequested = false
            finishAfterLocalDisconnect = false
            retryAfterLocalDisconnect = false
            pendingFinalStatus = ""

            if shouldFinish {
                running = false
                central.stopScan()
                cancelAllTasks()
                targetPeripheral = nil
                connectedAt = nil
                publish(finalStatus.isEmpty ? "lokaler Disconnect bestätigt" : finalStatus, finished: true)
            } else if shouldRetry {
                scheduleRetry(finalStatus.isEmpty ? "lokaler Retry-Disconnect" : finalStatus)
            } else {
                finishWithoutConnection(finalStatus.isEmpty ? "lokaler Disconnect bestätigt" : finalStatus)
            }
        } else if consecutiveBGRun >= targetConsecutiveBGReadings {
            appendValidationSummaryEvents()
            finishRemoteAfterRX("Build15 BESTÄTIGT · \(validationStatusLine()) · Dexcom-TX 0")
        } else if rxTotal > 0 {
            scheduleRetry("Remote-Disconnect nach RX · \(validationStatusLine())")
        } else {
            scheduleRetry("Remote-Disconnect nach \(elapsedMS(from: connectedAt))")
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard running, targetPeripheral?.identifier == peripheral.identifier else { return }

        gattTimeoutTask?.cancel()
        gattTimeoutTask = nil

        guard error == nil,
              let service = peripheral.services?.first(where: { $0.uuid == serviceUUID }) else {
            addEvent("Service discovery error=\(error?.localizedDescription ?? "nil")")
            requestLocalDisconnect(finalStatus: "Kein G7-Service 3532 · verwerfe Kandidat", retry: true)
            return
        }

        addEvent("G7-FINGERPRINT Stufe 2: Service 3532")
        publish("3532 bestätigt · prüfe 3534/3535/3536/3538")
        peripheral.discoverCharacteristics(nil, for: service)
        armGattTimeout(for: peripheral, stage: "Characteristics")
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard running, targetPeripheral?.identifier == peripheral.identifier else { return }

        gattTimeoutTask?.cancel()
        gattTimeoutTask = nil

        guard error == nil else {
            addEvent("Characteristic discovery error=\(error?.localizedDescription ?? "nil")")
            requestLocalDisconnect(finalStatus: "Characteristics nicht lesbar", retry: true)
            return
        }

        let discovered = service.characteristics ?? []
        addEvent("GATT Characteristics: \(discovered.count)")
        for characteristic in discovered {
            addEvent("\(shortUUID(characteristic.uuid)) props=\(propertyText(characteristic))")
        }

        let byUUID = Dictionary(uniqueKeysWithValues: discovered.map { ($0.uuid, $0) })
        let expectedFound = expectedChannelUUIDs.filter { byUUID[$0] != nil }
        addEvent("G7-FINGERPRINT: \(expectedFound.count)/4 erwartete Channels")

        guard expectedFound.count == expectedChannelUUIDs.count else {
            requestLocalDisconnect(finalStatus: "GATT-Fingerprint unvollständig · kein G7-Match", retry: true)
            return
        }

        expectedCharacteristics = byUUID.filter { expectedChannelUUIDs.contains($0.key) }
        pendingNotifyUUIDs = Set(expectedChannelUUIDs)
        enabledNotifyUUIDs.removeAll()
        failedNotifyUUIDs.removeAll()

        addEvent("G7-MATCH bestätigt · FEBC + 3532 + 4/4 · Name irrelevant")
        publish("G7-Match bestätigt · aktiviere Notify 3534/35/36/38")

        for uuid in expectedChannelUUIDs {
            guard let characteristic = expectedCharacteristics[uuid] else { continue }
            guard characteristic.properties.contains(.notify) || characteristic.properties.contains(.indicate) else {
                pendingNotifyUUIDs.remove(uuid)
                failedNotifyUUIDs.insert(uuid)
                addEvent("SUBSCRIBE \(shortUUID(uuid)) nicht unterstützt")
                continue
            }
            addEvent("SUBSCRIBE \(shortUUID(uuid)) · CCCD only")
            peripheral.setNotifyValue(true, for: characteristic)
        }

        if !failedNotifyUUIDs.isEmpty {
            requestLocalDisconnect(finalStatus: "Nicht alle G7-Channels unterstützen Notify", retry: true)
            return
        }

        armNotifySetupTimeout(for: peripheral)
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?) {
        guard running, targetPeripheral?.identifier == peripheral.identifier else { return }
        guard expectedChannelUUIDs.contains(characteristic.uuid) else { return }

        pendingNotifyUUIDs.remove(characteristic.uuid)

        if let error {
            failedNotifyUUIDs.insert(characteristic.uuid)
            addEvent("NOTIFY \(shortUUID(characteristic.uuid)) ERROR=\(error.localizedDescription)")
        } else if characteristic.isNotifying {
            enabledNotifyUUIDs.insert(characteristic.uuid)
            addEvent("NOTIFY \(shortUUID(characteristic.uuid)) ON")
        } else {
            failedNotifyUUIDs.insert(characteristic.uuid)
            addEvent("NOTIFY \(shortUUID(characteristic.uuid)) OFF/unerwartet")
        }

        publish("Notify \(enabledNotifyUUIDs.count)/4 · offen \(pendingNotifyUUIDs.count) · RX \(rxTotal)")

        guard pendingNotifyUUIDs.isEmpty else { return }

        notifySetupTimeoutTask?.cancel()
        notifySetupTimeoutTask = nil

        guard failedNotifyUUIDs.isEmpty, enabledNotifyUUIDs.count == expectedChannelUUIDs.count else {
            requestLocalDisconnect(finalStatus: "Notify-Setup nicht 4/4", retry: true)
            return
        }

        armPassiveListen(for: peripheral)
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard running, targetPeripheral?.identifier == peripheral.identifier else { return }
        guard expectedChannelUUIDs.contains(characteristic.uuid) else { return }

        if let error {
            addEvent("RX \(shortUUID(characteristic.uuid)) ERROR=\(error.localizedDescription)")
            publish("Notify RX-Fehler auf \(shortUUID(characteristic.uuid))")
            return
        }

        guard let data = characteristic.value else {
            addEvent("RX \(shortUUID(characteristic.uuid)) value=nil")
            return
        }

        let count = (rxCounts[characteristic.uuid] ?? 0) + 1
        rxCounts[characteristic.uuid] = count
        let packetHex = hex(data)
        latestRXHex = "\(shortUUID(characteristic.uuid)) #\(count) \(packetHex)"
        addEvent("RX \(shortUUID(characteristic.uuid)) #\(count) len=\(data.count) HEX=\(packetHex)")

        if firstRXAt == nil {
            firstRXAt = Date()
            addEvent("ERSTER SPONTAN-RX · nach \(elapsedMS(from: connectedAt))")
        }

        if let decoded = passivePacketSummary(data, characteristic: characteristic) {
            addEvent("KLASSE: \(decoded)")
            if decoded.hasPrefix("PASSIV-BG ") {
                latestPassiveBGSummary = decoded
                recordPassiveBGPacket(data)
            }
        }

        if latestPassiveBGSummary.isEmpty {
            publish("Spontan-RX \(rxTotal) · letzter \(shortUUID(characteristic.uuid)) · Dexcom-TX 0")
        } else {
            publish("\(latestPassiveBGSummary) · RX \(rxTotal) · TX 0")
        }
        scheduleFinishAfterRX(for: peripheral)
    }
}

// MARK: - Direct G7 BLE manager
// MARK: - Direct G7 BLE manager
// MARK: - Direct G7 BLE manager

private struct DirectG7Reading {
    let glucoseMgDl: Double
    let date: Date
    let trendMgDlPerMinute: Double?
    let sequence: UInt16
    let sensorAgeSeconds: TimeInterval
    let algorithmStateRaw: UInt8
}

private final class G7DirectBLEManager: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    private let advertisementUUID = CBUUID(string: "FEBC")
    private let serviceUUID = CBUUID(string: "F8083532-849E-531C-C594-30F1F86A4EA5")
    private let controlUUID = CBUUID(string: "F8083534-849E-531C-C594-30F1F86A4EA5")
    private let authUUID = CBUUID(string: "F8083535-849E-531C-C594-30F1F86A4EA5")

    private let onState: (String, String, Bool) -> Void
    private let onReading: (DirectG7Reading) -> Void

    private var central: CBCentralManager!
    private var targetPeripheral: CBPeripheral?
    private var enabled = false
    private var authenticated = false
    private var pendingGlucosePacket: Data?
    private var authTimeoutTask: DispatchWorkItem?
    private var reconnectTask: DispatchWorkItem?
    private var lastDeviceName = ""
    private let verifiedPeripheralIDKey = "xdrip.g7Direct.verifiedPeripheralID.build47"

    // Build 49: Heart-rate-monitor-style connection ownership. Once a real 0x4E packet has
    // verified the G7 peripheral, CoreBluetooth itself owns reconnects between the sensor's
    // short five-minute radio windows. No Timer, delayed DispatchQueue retry or foreground UI
    // activity is required for the verified peripheral.
    private func verifiedPeripheralID() -> UUID? {
        guard let stored = UserDefaults.standard.string(forKey: verifiedPeripheralIDKey) else { return nil }
        return UUID(uuidString: stored)
    }

    private func isVerifiedPeripheral(_ peripheral: CBPeripheral) -> Bool {
        verifiedPeripheralID() == peripheral.identifier
    }

    private func registerVerifiedConnectionEvents(_ identifier: UUID) {
        central.registerForConnectionEvents(options: [.peripheralUUIDs: [identifier]])
        trace41("CONNECTION_EVENTS registered id=\(identifier.uuidString)")
    }

    private func connectVerifiedWithSystemAutoReconnect(_ peripheral: CBPeripheral, reason: String) {
        targetPeripheral = peripheral
        peripheral.delegate = self
        registerVerifiedConnectionEvents(peripheral.identifier)
        trace41("AUTO_CONNECT request reason=\(reason) state=\(peripheral.state.rawValue)")
        central.connect(
            peripheral,
            options: [CBConnectPeripheralOptionEnableAutoReconnect: true]
        )
    }

    // Build 41: persistent BLE lifecycle trace. This deliberately lives inside the existing
    // direct-G7 manager so no Watch UI or complication code needs to change.
    private let lifecycleTraceKey41 = "xdrip.g7Direct.lifecycleTrace41"

    private func trace41(_ event: String) {
        guard let defaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else { return }
        var events = defaults.stringArray(forKey: lifecycleTraceKey41) ?? []
        events.append("\(Date().timeIntervalSince1970)|\(event)")
        if events.count > 80 {
            events.removeFirst(events.count - 80)
        }
        defaults.set(events, forKey: lifecycleTraceKey41)
    }

    private func traceTail41() -> String {
        guard let defaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else { return "no-app-group" }
        let events = defaults.stringArray(forKey: lifecycleTraceKey41) ?? []
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "HH:mm:ss"

        return events.suffix(8).map { item in
            let parts = item.split(separator: "|", maxSplits: 1).map(String.init)
            guard parts.count == 2, let ts = Double(parts[0]) else { return item }
            return "\(formatter.string(from: Date(timeIntervalSince1970: ts))) \(parts[1])"
        }.joined(separator: " · ")
    }

    init(
        onState: @escaping (String, String, Bool) -> Void,
        onReading: @escaping (DirectG7Reading) -> Void
    ) {
        self.onState = onState
        self.onReading = onReading
        super.init()

        central = CBCentralManager(
            delegate: self,
            queue: .main,
            options: [CBCentralManagerOptionRestoreIdentifierKey: "xDrip.G7.Direct.Central"]
        )
    }

    func start() {
        enabled = true
        trace41("START central=\(central.state.rawValue)")
        if central.state == .poweredOn {
            beginDiscovery()
        }
    }

    private func publish(_ status: String) {
        onState("L41 \(status) | \(traceTail41())", lastDeviceName, authenticated)
    }

    private func beginDiscovery() {
        guard enabled, central.state == .poweredOn, targetPeripheral == nil else { return }

        reconnectTask?.cancel()
        reconnectTask = nil
        trace41("SCAN begin")
        publish("suche G7…")

        if let storedID = UserDefaults.standard.string(forKey: verifiedPeripheralIDKey),
           let uuid = UUID(uuidString: storedID),
           let known = central.retrievePeripherals(withIdentifiers: [uuid]).first {
            inspect(known)
            return
        }

        let connected = central.retrieveConnectedPeripherals(withServices: [serviceUUID])
        if let peripheral = connected.first(where: { ($0.name ?? "").hasPrefix("DX") }) ?? connected.first {
            inspect(peripheral)
            return
        }

        central.scanForPeripherals(
            withServices: [advertisementUUID],
            options: [CBCentralManagerScanOptionAllowDuplicatesKey: false]
        )
    }

    private func inspect(_ peripheral: CBPeripheral) {
        guard enabled, targetPeripheral == nil else { return }

        central.stopScan()
        targetPeripheral = peripheral
        peripheral.delegate = self
        lastDeviceName = peripheral.name ?? "unbekannt"
        authenticated = false
        pendingGlucosePacket = nil
        trace41("DISCOVER \(lastDeviceName) state=\(peripheral.state.rawValue)")
        if peripheral.state == .connected {
            publish("G7 verbunden; registriere Notify erneut…")
            if isVerifiedPeripheral(peripheral) {
                registerVerifiedConnectionEvents(peripheral.identifier)
            }
            peripheral.discoverServices([serviceUUID])
        } else if isVerifiedPeripheral(peripheral) {
            publish("Verifiziertes G7 gefunden; System-AutoReconnect…")
            connectVerifiedWithSystemAutoReconnect(peripheral, reason: "inspect-known")
        } else {
            publish("G7 gefunden; verbinde zur Verifizierung…")
            central.connect(peripheral, options: nil)
        }
    }

    private func scheduleReconnect() {
        trace41("RECONNECT immediate")
        reconnectTask?.cancel()
        reconnectTask = nil
        guard enabled, central.state == .poweredOn, targetPeripheral == nil else { return }
        beginDiscovery()
    }

    // Invoked by SwiftUI .backgroundTask(.bluetoothAlert). The handler does not decode or
    // fabricate glucose. It only makes sure the existing xDrip CoreBluetooth connection / GATT
    // subscription is registered so the normal didUpdateValueFor(0x4E) callback can execute.
    func handleBluetoothAlertWake() {
        enabled = true
        trace41("BLUETOOTH_ALERT wake central=\(central.state.rawValue)")

        guard central.state == .poweredOn else { return }

        if let peripheral = targetPeripheral {
            peripheral.delegate = self
            if peripheral.state == .connected {
                peripheral.discoverServices([serviceUUID])
            } else if peripheral.state == .disconnected {
                if isVerifiedPeripheral(peripheral) {
                    connectVerifiedWithSystemAutoReconnect(peripheral, reason: "bluetooth-alert")
                } else {
                    central.connect(peripheral, options: nil)
                }
            }
            return
        }

        beginDiscovery()
    }

    private func armAuthenticationTimeout(for peripheral: CBPeripheral) {
        // Build 46: DO NOT tear down a proven Direct-G7 Notify subscription after 20 seconds.
        // Build 45 demonstrated that valid 0x4E glucose packets reach the direct widget bridge
        // before the legacy app-level authentication flag changes. Cancelling this connection
        // destroyed the very background subscription that must survive while the Watch UI sleeps.
        // Real BLE failures/disconnects are still handled by didFailToConnect/didDisconnectPeripheral.
        authTimeoutTask?.cancel()
        authTimeoutTask = nil
        trace41("AUTH watchdog bypassed; keep notify subscription alive id=\(peripheral.identifier.uuidString)")
    }

    private func parseG7Glucose(_ data: Data) -> DirectG7Reading? {
        guard data.count >= 19, data[0] == 0x4E, data[1] == 0x00 else { return nil }

        let glucoseRaw = littleEndianUInt16(data, offset: 12)
        guard glucoseRaw != 0xFFFF else { return nil }

        let glucose = Double(glucoseRaw & 0x0FFF)
        guard glucose > 0 else { return nil }

        let sequence = littleEndianUInt16(data, offset: 6)
        let messageTimestamp = littleEndianUInt32(data, offset: 2)
        let messageAge = TimeInterval(data[10])
        let sensorAge = TimeInterval(messageTimestamp) + messageAge
        let readingDate = Date().addingTimeInterval(-messageAge)

        let trend: Double?
        if data[15] == 0x7F {
            trend = nil
        } else {
            trend = Double(Int8(bitPattern: data[15])) / 10.0
        }

        return DirectG7Reading(
            glucoseMgDl: glucose,
            date: readingDate,
            trendMgDlPerMinute: trend,
            sequence: sequence,
            sensorAgeSeconds: sensorAge,
            algorithmStateRaw: data[14]
        )
    }


    // Build 43: direct sensor -> App Group -> existing widgets bridge.
    // This path deliberately bypasses WatchStateModel. It runs synchronously from the
    // CoreBluetooth 0x4E receive callback so a fresh G7 value does not wait for the Watch UI.
    private func publishReadingDirectlyToWidgets(_ reading: DirectG7Reading) {
        guard let sharedUserDefaults = UserDefaults(suiteName: Bundle.main.appGroupSuiteName) else {
            trace41("WIDGET_STORE unavailable")
            return
        }

        let stateKey = "complicationSharedUserDefaults.\(Bundle.main.mainAppBundleIdentifier)"
        let sourceKey = "complicationDataSource.\(Bundle.main.mainAppBundleIdentifier)"

        var payload: [String: Any] = [:]
        if let existingData = sharedUserDefaults.data(forKey: stateKey),
           let existingObject = try? JSONSerialization.jsonObject(with: existingData),
           let existingPayload = existingObject as? [String: Any] {
            payload = existingPayload
        }

        let existingDates = (payload["bgReadingDatesAsDouble"] as? [NSNumber])?.map { $0.doubleValue }
            ?? (payload["bgReadingDatesAsDouble"] as? [Double])
            ?? []
        let existingValues = (payload["bgReadingValues"] as? [NSNumber])?.map { $0.doubleValue }
            ?? (payload["bgReadingValues"] as? [Double])
            ?? []

        let count = min(existingDates.count, existingValues.count)
        var merged: [(Date, Double)] = (0..<count).map {
            (Date(timeIntervalSince1970: existingDates[$0]), existingValues[$0])
        }

        // Replace a duplicate copy of the same five-minute sample and keep only recent history.
        merged.removeAll { abs($0.0.timeIntervalSince(reading.date)) < 90 }
        merged.append((reading.date, reading.glucoseMgDl))
        merged = merged
            .filter { $0.0 > Date().addingTimeInterval(-12 * 60 * 60) }
            .sorted { $0.0 > $1.0 }

        let isMgDl = (payload["isMgDl"] as? Bool) ?? true
        let slopeOrdinal = directWidgetSlopeOrdinal(for: reading.trendMgDlPerMinute)

        var deltaValueInUserUnit = 0.0
        if merged.count > 1 {
            let previous = merged[1]
            let interval = reading.date.timeIntervalSince(previous.0)
            if interval > 0, interval <= 7.5 * 60 {
                if isMgDl {
                    deltaValueInUserUnit = reading.glucoseMgDl - previous.1
                } else {
                    let currentMmol = ((reading.glucoseMgDl / 18.0182) * 10).rounded() / 10
                    let previousMmol = ((previous.1 / 18.0182) * 10).rounded() / 10
                    deltaValueInUserUnit = currentMmol - previousMmol
                }
            }
        }

        payload["bgReadingValues"] = merged.map { $0.1 }
        payload["bgReadingDatesAsDouble"] = merged.map { $0.0.timeIntervalSince1970 }
        payload["isMgDl"] = isMgDl
        payload["slopeOrdinal"] = slopeOrdinal
        payload["deltaValueInUserUnit"] = deltaValueInUserUnit

        // These fields are required by ComplicationSharedUserDefaultsModel. Preserve any
        // user/app values already present; use the WatchStateModel defaults only for a truly
        // empty store, e.g. directly after an app update before the UI has ever been opened.
        if payload["urgentLowLimitInMgDl"] == nil { payload["urgentLowLimitInMgDl"] = 60.0 }
        if payload["lowLimitInMgDl"] == nil { payload["lowLimitInMgDl"] = 80.0 }
        if payload["highLimitInMgDl"] == nil { payload["highLimitInMgDl"] = 170.0 }
        if payload["urgentHighLimitInMgDl"] == nil { payload["urgentHighLimitInMgDl"] = 250.0 }
        if payload["keepAliveIsDisabled"] == nil { payload["keepAliveIsDisabled"] = false }

        guard JSONSerialization.isValidJSONObject(payload),
              let encoded = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]) else {
            trace41("WIDGET_STORE encode_failed")
            return
        }

        // Persist before requesting a reload. The Widget Provider already reads this exact key.
        sharedUserDefaults.set(encoded, forKey: stateKey)
        sharedUserDefaults.set("G7 BLE Direct", forKey: sourceKey)
        sharedUserDefaults.set(reading.date.timeIntervalSince1970, forKey: "xdrip.g7Direct.widgetBridge43.lastReadingDate")
        sharedUserDefaults.set(reading.glucoseMgDl, forKey: "xdrip.g7Direct.widgetBridge43.lastBG")
        sharedUserDefaults.set(Int(reading.sequence), forKey: "xdrip.g7Direct.widgetBridge43.lastSequence")
        sharedUserDefaults.set(Date().timeIntervalSince1970, forKey: "xdrip.g7Direct.widgetBridge43.lastWriteAt")

        for complicationKind in ["xDripGraphV33", "xDripBGV36", "xDripDeltaV36"] {
            WidgetCenter.shared.reloadTimelines(ofKind: complicationKind)
        }

        trace41("WIDGET_WRITE seq=\(reading.sequence) bg=\(Int(reading.glucoseMgDl))")
    }

    private func directWidgetSlopeOrdinal(for trend: Double?) -> Int {
        guard let trend else { return 0 }
        if trend >= 3 { return 1 }
        if trend >= 2 { return 2 }
        if trend >= 1 { return 3 }
        if trend > -1 { return 4 }
        if trend > -2 { return 5 }
        if trend > -3 { return 6 }
        return 7
    }

    private func littleEndianUInt16(_ data: Data, offset: Int) -> UInt16 {
        UInt16(data[offset]) | (UInt16(data[offset + 1]) << 8)
    }

    private func littleEndianUInt32(_ data: Data, offset: Int) -> UInt32 {
        UInt32(data[offset])
            | (UInt32(data[offset + 1]) << 8)
            | (UInt32(data[offset + 2]) << 16)
            | (UInt32(data[offset + 3]) << 24)
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        trace41("CENTRAL state=\(central.state.rawValue)")
        switch central.state {
        case .poweredOn:
            publish("Bluetooth ein")
            beginDiscovery()
        case .poweredOff:
            publish("Bluetooth aus")
        case .unauthorized:
            publish("Bluetooth-Berechtigung fehlt")
        case .unsupported:
            publish("CoreBluetooth nicht unterstützt")
        case .resetting:
            publish("Bluetooth wird zurückgesetzt")
        case .unknown:
            publish("Bluetooth-Status unbekannt")
        @unknown default:
            publish("Bluetooth-Status unbekannt")
        }
    }

    func centralManager(_ central: CBCentralManager, willRestoreState dict: [String : Any]) {
        let restored = dict[CBCentralManagerRestoredStatePeripheralsKey] as? [CBPeripheral] ?? []
        let restoredState = restored.first?.state.rawValue ?? -1
        trace41("RESTORE count=\(restored.count) state=\(restoredState)")
        enabled = true

        let verifiedID = verifiedPeripheralID()
        let restoredPeripheral = restored.first(where: { peripheral in
            verifiedID != nil && peripheral.identifier == verifiedID
        }) ?? restored.first(where: { $0.state == .connected }) ?? restored.first

        if let peripheral = restoredPeripheral {
            targetPeripheral = peripheral
            peripheral.delegate = self
            lastDeviceName = peripheral.name ?? "unbekannt"
            authenticated = false
            publish("G7-Verbindung wiederhergestellt")

            if isVerifiedPeripheral(peripheral) {
                registerVerifiedConnectionEvents(peripheral.identifier)
            }

            if peripheral.state == .connected {
                peripheral.discoverServices([serviceUUID])
            } else if isVerifiedPeripheral(peripheral) {
                connectVerifiedWithSystemAutoReconnect(peripheral, reason: "state-restoration")
            } else {
                central.connect(peripheral, options: nil)
            }
            return
        }

        if central.state == .poweredOn {
            beginDiscovery()
        }
    }

    func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String : Any],
        rssi RSSI: NSNumber
    ) {
        let name = peripheral.name ?? (advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? "")
        guard name.hasPrefix("DX") else { return }
        inspect(peripheral)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        trace41("CONNECTED \(peripheral.name ?? "unknown") verified=\(isVerifiedPeripheral(peripheral))")
        targetPeripheral = peripheral
        peripheral.delegate = self
        lastDeviceName = peripheral.name ?? lastDeviceName
        if isVerifiedPeripheral(peripheral) {
            registerVerifiedConnectionEvents(peripheral.identifier)
        }
        publish("BLE verbunden; prüfe G7-Service…")
        armAuthenticationTimeout(for: peripheral)
        peripheral.discoverServices([serviceUUID])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        trace41("CONNECT_FAIL err=\(error?.localizedDescription ?? "nil") verified=\(isVerifiedPeripheral(peripheral))")
        authenticated = false

        if isVerifiedPeripheral(peripheral) {
            targetPeripheral = peripheral
            publish("Verifiziertes G7 noch nicht erreichbar; System-Verbindung bleibt registriert")
            if central.state == .poweredOn, peripheral.state == .disconnected {
                connectVerifiedWithSystemAutoReconnect(peripheral, reason: "connect-failed")
            }
            return
        }

        if targetPeripheral?.identifier == peripheral.identifier {
            targetPeripheral = nil
        }
        publish("Unbestätigte Verbindung fehlgeschlagen; Recovery-Scan…")
        scheduleReconnect()
    }

    // Legacy disconnect callback remains as a fallback. Verified G7 links are immediately
    // re-registered with CoreBluetooth AutoReconnect rather than returning to scanning.
    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        trace41("DISCONNECT_LEGACY err=\(error?.localizedDescription ?? "nil") state=\(peripheral.state.rawValue)")
        guard targetPeripheral?.identifier == peripheral.identifier else { return }

        authTimeoutTask?.cancel()
        authTimeoutTask = nil
        authenticated = false
        pendingGlucosePacket = nil
        peripheral.delegate = self

        if isVerifiedPeripheral(peripheral) {
            targetPeripheral = peripheral
            publish("G7-Fenster beendet; System-AutoReconnect registriert")
            if central.state == .poweredOn, peripheral.state == .disconnected {
                connectVerifiedWithSystemAutoReconnect(peripheral, reason: "legacy-disconnect")
            }
            return
        }

        targetPeripheral = nil
        publish("Unbestätigtes G7 getrennt; Recovery-Scan…")
        scheduleReconnect()
    }

    // watchOS 10+ CoreBluetooth callback used by CBConnectPeripheralOptionEnableAutoReconnect.
    // If isReconnecting is true the operating system already owns the pending reconnect; do not
    // scan, sleep, schedule a timer or issue a competing connection request.
    @available(watchOS 10.0, *)
    func centralManager(
        _ central: CBCentralManager,
        didDisconnectPeripheral peripheral: CBPeripheral,
        timestamp: CFAbsoluteTime,
        isReconnecting: Bool,
        error: Error?
    ) {
        trace41("DISCONNECT_AUTO reconnecting=\(isReconnecting) err=\(error?.localizedDescription ?? "nil")")
        guard targetPeripheral?.identifier == peripheral.identifier else { return }

        authTimeoutTask?.cancel()
        authTimeoutTask = nil
        authenticated = false
        pendingGlucosePacket = nil
        peripheral.delegate = self

        if isVerifiedPeripheral(peripheral) {
            targetPeripheral = peripheral
            registerVerifiedConnectionEvents(peripheral.identifier)
            if isReconnecting {
                publish("G7-Fenster beendet; CoreBluetooth wartet automatisch auf nächsten Sensorzyklus")
            } else if central.state == .poweredOn, peripheral.state == .disconnected {
                publish("G7-Fenster beendet; AutoReconnect wird erneut registriert")
                connectVerifiedWithSystemAutoReconnect(peripheral, reason: "auto-disconnect-not-reconnecting")
            }
            return
        }

        targetPeripheral = nil
        publish("Unbestätigtes G7 getrennt; Recovery-Scan…")
        scheduleReconnect()
    }

    func centralManager(
        _ central: CBCentralManager,
        connectionEventDidOccur event: CBConnectionEvent,
        for peripheral: CBPeripheral
    ) {
        guard isVerifiedPeripheral(peripheral) else { return }
        targetPeripheral = peripheral
        peripheral.delegate = self
        let label: String
        switch event {
        case .peerConnected:
            label = "peerConnected"
        case .peerDisconnected:
            label = "peerDisconnected"
        @unknown default:
            label = "unknown"
        }
        trace41("CONNECTION_EVENT \(label) state=\(peripheral.state.rawValue)")
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        if error != nil {
            publish("G7-Service-Suche fehlgeschlagen")
            central.cancelPeripheralConnection(peripheral)
            return
        }

        guard let service = peripheral.services?.first(where: { $0.uuid == serviceUUID }) else {
            publish("kein G7-Service; suche weiter…")
            central.cancelPeripheralConnection(peripheral)
            return
        }

        publish("G7-Service gefunden; aktiviere Notify…")
        peripheral.discoverCharacteristics(nil, for: service)
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        if error != nil {
            publish("Characteristic-Suche fehlgeschlagen")
            central.cancelPeripheralConnection(peripheral)
            return
        }

        let notifyCharacteristics = (service.characteristics ?? []).filter {
            $0.properties.contains(.notify) || $0.properties.contains(.indicate)
        }

        guard !notifyCharacteristics.isEmpty else {
            publish("keine G7-Notify-Kanäle")
            central.cancelPeripheralConnection(peripheral)
            return
        }

        for characteristic in notifyCharacteristics where !characteristic.isNotifying {
            peripheral.setNotifyValue(true, for: characteristic)
        }

        publish("Notify aktiv; warte auf Dexcom-Auth…")
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?) {
        trace41("NOTIFY \(characteristic.uuid.uuidString.suffix(4)) on=\(characteristic.isNotifying) err=\(error?.localizedDescription ?? "nil")")
        if let error {
            publish("Notify-Fehler: \(error.localizedDescription)")
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard error == nil, let value = characteristic.value, !value.isEmpty else { return }

        if characteristic.uuid == authUUID, value.count >= 3, value[0] == 0x05 {
            authenticated = value[1] == 0x01 && value[2] != 0x02

            if authenticated {
                authTimeoutTask?.cancel()
                authTimeoutTask = nil
                publish("Dexcom-authentifiziert · Direct aktiv")

                if let pendingGlucosePacket,
                   let reading = parseG7Glucose(pendingGlucosePacket) {
                    self.pendingGlucosePacket = nil
                    onReading(reading)
                }
            } else {
                publish("Dexcom-Auth nicht freigegeben")
            }
            return
        }

        guard characteristic.uuid == controlUUID, value[0] == 0x4E else { return }

        let seq41 = value.count >= 8 ? littleEndianUInt16(value, offset: 6) : 0
        let bg41 = value.count >= 14 ? Int(littleEndianUInt16(value, offset: 12) & 0x0FFF) : -1
        trace41("RX4E seq=\(seq41) bg=\(bg41) auth=\(authenticated)")
        UserDefaults.standard.set(peripheral.identifier.uuidString, forKey: verifiedPeripheralIDKey)
        registerVerifiedConnectionEvents(peripheral.identifier)
        trace41("VERIFIED_SOURCE id=\(peripheral.identifier.uuidString) autoreconnect=armed")

        guard let reading = parseG7Glucose(value) else {
            publish("0x4E empfangen; Parser abgelehnt")
            return
        }

        // Build 43/46: every valid sensor packet goes directly to the existing widgets.
        // A received 0x4E also proves that this is the correct live G7 connection, so any legacy
        // auth watchdog must remain cancelled and the GATT Notify subscription must stay intact.
        authTimeoutTask?.cancel()
        authTimeoutTask = nil
        publishReadingDirectlyToWidgets(reading)

        guard authenticated else {
            pendingGlucosePacket = value
            publish("0x4E empfangen · Widgets direkt aktualisiert · Notify bleibt aktiv")
            return
        }

        publish("Direct BG \(Int(reading.glucoseMgDl)) mg/dL")
        onReading(reading)
    }
}

// MARK: - WCSession delegate to handle communications

extension WatchStateModel: WCSessionDelegate {
    func session(_: WCSession, activationDidCompleteWith activationState: WCSessionActivationState, error _: Error?) {
        // keep Watch state changes on the main queue because WCSession delivers delegate callbacks on a non-main queue
        DispatchQueue.main.async { [weak self] in
            guard let self = self, activationState == .activated else { return }

            self.requestWatchStateUpdate()
            // if the AGP tab requested data while activation was pending, send it now
            self.sendPendingAGPRequestIfPossible()
        }
    }

    func sessionReachabilityDidChange(_: WCSession) {
        DispatchQueue.main.async {
            // retry AGP requests that were made before the phone became reachable
            self.sendPendingAGPRequestIfPossible()
        }
    }

    func session(_: WCSession, didReceiveMessageData _: Data) {}

    func session(_: WCSession, didReceiveMessage message: [String: Any]) {
        DispatchQueue.main.async {
            self.processWatchPayloadFromDictionary(dictionary: message)
            self.requestingDataIconColor = ConstantsAppleWatch.requestingDataIconColorActive

            // change the requesting icon color back after a small delay to prevent it
            // flashing on/off too quickly
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                self.requestingDataIconColor = ConstantsAppleWatch.requestingDataIconColorInactive
            }
        }
    }

    func session(_: WCSession, didReceiveApplicationContext applicationContext: [String: Any]) {
        DispatchQueue.main.async {
            self.processWatchPayloadFromDictionary(dictionary: applicationContext)
        }
    }

    func session(_: WCSession, didReceiveUserInfo userInfo: [String: Any] = [:]) {
        DispatchQueue.main.async {
            self.processWatchPayloadFromDictionary(dictionary: userInfo)
        }
    }

    #if os(iOS)
    func sessionDidBecomeInactive(_: WCSession) {}

    func sessionDidDeactivate(_ session: WCSession) {
        session.activate()
    }
    #endif
}
