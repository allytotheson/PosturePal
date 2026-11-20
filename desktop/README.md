# PosturePal desktop app

Native Python/PySide6 desktop companion with Bleak BLE communication and local SQLite history. The schematic spinal model is illustrative.

## Run

From this directory, with Python 3.11 or newer:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m posturepal
```

Select **BLE vest** in the top-right selector, scan, select PosturePal, and connect. Use the nRF52840 firmware; Feather M4 is USB-only. Allow OS Bluetooth permission for the app/terminal and close other BLE clients, since the prototype supports one central connection.

The app supports live regional angles, requested-alert display, calibration, pause/resume, trigger/recovery thresholds, dwell time, status readback, and a bounded diagnostic log/manual command field. Settings require firmware ACK and matching readback. A completed calibration automatically refreshes the firmware baseline. The existing simulator remains available and starts by default.

## Device setup

Verify the physical sensor order: mux channel **0 upper (T3), 1 middle (T12), 2 lower (L5)**. Confirm which signed sensor axis points headward and which points outward from the back. Send the verified `axes <headward> <outward>` command through **Diagnostics**, then `mount-ok`. Hold neutral for the firmware's settling and stillness capture. Follow [firmware setup](../docs/SETUP.md) for mounting verification; axis direction cannot be inferred from the board labels alone. Settings, axes and neutral are RAM-only and must be restored after a power cycle.

Readings are already baseline-relative. Firmware reports differences T3−T12 and T12−L5; do not invert the visual to hide reversed sensor wiring. The app preserves the signed device readings and displays the global requested alert, which is not measured vibration. Production feedback stays on the MCU.

## Faults and history

Faults preserve the firmware cause, clear stale angles/baseline and disable unsupported controls. After correcting the cause, use **Retry device after correcting cause**. The app does not retry state-changing commands automatically. Missing readings clear after 3.5 seconds. Reconnect explicitly after a disconnect; closing the app does not stop on-device monitoring.

SQLite stores source-labeled simulator/BLE sessions, receipt times, angles, reported device state, alert request and effective settings/baseline when known. Battery and device timestamps remain unknown because the firmware does not transmit them. BLE sequences are host counters. Samples checkpoint every five seconds and on disconnect/close. Existing sample databases migrate without discarding earlier rows. History provides paginated sample charts/tables. Local data normally lives in `~/Library/Application Support/TeamB5/PosturePal/` on macOS; recordings are not uploaded.

Diagnostic input/log controls explicitly use readable light backgrounds with dark OS themes. macOS startup repairs hidden flags on bundled Qt platform plugins before window creation, with actionable errors if permissions prevent repair.

## Test

```sh
python -m unittest discover -s tests -v
```

Tests cover protocol fixtures, fragmented notifications, serialized 20-byte writes, ACK/readback, failures/timeouts, Qt threading, calibration, fault recovery, reconnect, persistence/migration and macOS startup. BLE tests use a mocked radio. Real radio reliability, sensor accuracy, physical alerts and end-to-end latency still require bench validation. Current firmware telemetry is about 1 Hz.

See [desktop protocol details](docs/BLE_INTERFACE.md) and [firmware BLE documentation](../docs/BLE.md).
