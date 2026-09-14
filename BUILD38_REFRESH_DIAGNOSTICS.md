# Build 38 – Watch complication refresh diagnostics

## Why this build exists

Build 37 finished the visual work for the accepted watch-face complications. Build 38 must not change their layout.

The remaining problem is functional: every new Dexcom G7 glucose value (about every five minutes) should update the xDrip watch-face graph and the two circular widgets without opening xDrip manually.

Previous builds changed WidgetKit timelines and reload behavior but did not prove where the end-to-end chain failed. Build 38 therefore adds diagnostics only.

## Frozen Build 37 UI contract

Do not change:

- rectangular graph layout, range, colors, labels or 150-minute window
- circular BG widget layout, thresholds or minute-tick bezel
- circular Delta widget layout
- widget kinds: `xDripGraphV33`, `xDripBGV36`, `xDripDeltaV36`

## Five stages measured by Build 38

For each BG payload Build 38 records:

1. `iphonePreparedAt` – iPhone WatchManager has prepared a payload containing BG data.
2. `watchReceivedAt` + `watchReceiveChannel` – WatchConnectivity delivered that payload to the Watch via `message`, `applicationContext` or `userInfo`.
3. `appGroupCommittedAt` – WatchStateModel wrote the new complication model to the shared App Group, including the BG value/date committed.
4. `widgetReloadRequestedAt` – the Watch app requested `reloadTimelines` for all three xDrip widget kinds.
5. `providerReadAt` – WidgetKit called the provider and the provider decoded the App Group state, including the BG value/date it saw.

The diagnostic data is stored in the Watch App Group under `xdrip.refreshDiagnostics.v38` and shown on a temporary fourth page in the xDrip Watch app.

## Interpretation

- Stage 1 updates but stage 2 does not: iPhone generated the new state, but WatchConnectivity background delivery is the bottleneck.
- Stage 2 updates but stage 3 does not: Watch received the payload, but WatchStateModel rejected or failed to publish it.
- Stage 3 updates but stage 4 does not: App Group persistence works; reload triggering is the bottleneck.
- Stage 4 updates but stage 5 does not: WidgetKit deferred/ignored the reload request.
- Stage 5 shows the new BG but the watch face remains old: rendering/watch-face refresh is the final bottleneck.

## Test procedure

After installing Build 38, keep the xDrip Watch app closed during normal operation. Allow two to three Dexcom cycles (10–15 minutes). Then open xDrip on the Watch, swipe to the fourth diagnostics page, and capture the displayed trace. Compare the watch-face BG at the same time.

Do not make another refresh-mechanism change until this trace identifies the failing stage.
