# Desktop / wearable BLE interface

Implemented against [PosturePal firmware commit `6fbfdc0`](https://github.com/allytotheson/PosturePal/tree/6fbfdc052ca903396d3a0d2101d8e232196a0775), specifically [BLE.md](https://github.com/allytotheson/PosturePal/blob/6fbfdc052ca903396d3a0d2101d8e232196a0775/docs/BLE.md) and `firmware/PosturePal/PosturePal.ino`. The teammate's JavaScript client describes the same service; the native app uses Bleak instead of Web Bluetooth.

## Connection and threading

Choose **BLE vest**, **Scan for vests**, select the advertised device, then **Connect vest**. Discovery filters by service UUID and passes the discovered BLEDevice to Bleak (including on macOS). A dedicated asyncio thread owns scanning, connection, notifications and writes. Qt signals deliver events to the UI thread; SQLite and rendering stay on that thread. No new runtime packages are required.

| Item | UUID | Operation |
| --- | --- | --- |
| Nordic UART service | `6e400001-b5a3-f393-e0a9-e50e24dcca9e` | Discover |
| RX, app → vest | `6e400002-b5a3-f393-e0a9-e50e24dcca9e` | Write with response |
| TX, vest → app | `6e400003-b5a3-f393-e0a9-e50e24dcca9e` | Notifications |

Subscribe before sending `status`. Connection is ready after protocol v1, state, settings and baseline readback. Notification fragments are reassembled through LF, with optional CR. Corrupt/oversized lines are discarded through their next LF. Unknown diagnostic lines remain visible in a bounded 200-line log. Commands contain 1–159 printable ASCII characters plus LF, use sequential writes of at most 20 bytes, and wait 100 ms before another command. Concurrent operations are rejected. A failed write disconnects to discard any partial peripheral command.

## Readings and state

Firmware sends `upper_deg=8.20 lower_deg=1.50 buzz=1` about once per second while monitoring/alerting. Signed angles are already relative to the firmware baseline; no desktop baseline subtraction occurs. Firmware wraps deviations to ±180°. A SETTLING/CALIBRATING → MONITORING transition triggers one serialized status readback to refresh the new baseline; calibration and faults invalidate the old baseline immediately. `buzz` is the global requested alert, not measured vibration or a per-region cue. Per-region highlighting only compares the received angles with the read-back trigger settings; the app does not run a production dwell timer or control feedback.

`EVENT state=...` and `STATUS state=...` supply SETTLING, CALIBRATING, MONITORING, ALERT, PAUSED or FAULT. Inactive states clear the live values. Missing samples for 3.5 seconds also clear the values/model, and new readings restore them. Disconnect clears values and effective settings; reconnect is explicit and repeats subscription/status reconciliation. Disconnect does not pause the MCU or disable its local feedback.

Firmware does not report battery, device timestamps, per-region dwell state or a sequence number. Battery/device time are stored as NULL and displayed as unknown. The sequence column is a host counter for BLE, reset per connection, and receipt times are host monotonic/UTC times. This cannot measure sample-to-display latency or detect every dropped device sample.

## Settings and commands

Settings use `set <upperTrigger> <upperRecovery> <lowerTrigger> <lowerRecovery> <durationMs>`. Validate `0 < recovery < trigger <= 90` and integer duration 1…3600000 ms. UI controls use two-decimal angles and millisecond dwell resolution. Read initial values from firmware; current firmware defaults are triggers 7.5°/7.5°, recovery 4°/4°, duration 2000 ms.

Only `ACK settings applied; regional timers reset` followed by matching `SETTINGS` status readback completes an app settings request and records a settings event. GATT write completion alone does not. Effective sample settings are unknown while application is pending. Rejection or mismatched readback does not record success. A response timeout disconnects, preventing a delayed untagged ACK from completing a later request; reconnect reads the actual device state. Firmware has no command IDs, retries, replay or lossless output guarantee. The app does not automatically retry state-changing commands.

**Pause vest**, **Resume vest** and calibration send `pause`, `resume` and `calibrate`; the UI follows reported state. There is no firmware reset-baseline command. Calibration settles for 3 seconds, captures a continuously still neutral posture for 2 seconds, and may fault if calibration cannot complete. Settings and baseline are RAM-only.

**Diagnostics** exposes the device log and manual command field for `sense`, `help`, mounting setup, `retry` and other firmware commands. Manual `set` is routed to the settings controls instead. On a new device, follow the firmware's physical axis/fixture verification before explicitly sending `axes ...` and `mount-ok`. The app never assumes mounting direction or automatically acknowledges mounting. Errors from firmware are shown in the log and status area.

## Firmware fault recovery

An active BLE connection can carry a firmware FAULT with no angle samples. Preserve the specific `EVENT ... reason=` or `STATUS ... fault=` text even if a later command returns the generic `ERR FAULT latched`. The app displays that cause in a persistent fault panel, clears live samples/baseline, and disables calibration, pause/resume and settings while faulted. Attaching to an already-faulted device shows this panel immediately after status reconciliation.

The explicit **Retry device after correcting cause** button sends `retry` once. It does not assume recovery: subsequent firmware state determines whether the panel remains visible, calibration starts or readings resume. Diagnostic/status queries and disconnect remain available. `IMU near full-scale imu=0 channel=0 source=gyro axis=Y raw=32761 limit=32000` means firmware rejected that sensor value at its configured range guard; the message alone cannot establish whether actual motion, the sensor, wiring/power or a readout problem caused it. Correct the source of invalid readings and retry; investigate repeated faults while stationary with the hardware/firmware owner.

## History and verification

Simulator and BLE modes have separate source-labeled sessions. BLE samples store angles, requested alert, reported device state, effective triggers/recovery/duration and baseline when known. Existing databases migrate their sample table to nullable fields and preserve previous rows; unknown older recovery/alert data remains NULL. Samples checkpoint every five seconds and on disconnect/close.

Tests cover firmware text fixtures at every fragment split, multiple lines per notification, invalid/oversized responses, protocol mismatch, command limits, 20-byte writes, spacing/serialization, ACK/readback, rejection/timeout, failed writes, reconnect and notification startup failure. Qt tests exercise scanning, source changes, the actual worker thread, live readings, state/calibration controls, stale data, disconnect, persistence and migration using a mocked radio.

Hardware validation remains required: flash the BLE-capable nRF52840 build (the Feather M4 is USB-only), allow the app/terminal Bluetooth permission, verify discovery and connection, compare BLE/USB readings, confirm mounting/calibration, test pause/resume and settings, disconnect/reconnect and verify continued on-device monitoring. Real radio reliability, physical vibration, sensor accuracy and end-to-end latency are not established by mock tests.
