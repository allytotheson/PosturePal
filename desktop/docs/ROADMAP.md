# Software milestones

## Completed

Native Python/PySide6 desktop UI, schematic 3D renderer, simulator, SQLite session summaries/settings events, paginated sample history, and native Bleak integration with the Feather v3 Nordic UART text protocol. Real-device mode includes service-filtered discovery, selection, connect/disconnect, threaded asynchronous I/O, state/readback reconciliation, calibration and pause/resume commands, trigger/recovery settings, bounded diagnostics and stale-data presentation. Simulator and BLE history remain separate.

Automated firmware-fixture, mocked GATT and Qt integration tests exercise parsing, 20-byte write chunking, command serialization, ACK/readback confirmation, errors/timeouts, reconnect, shutdown, sample persistence and migration. See BLE_INTERFACE.md for the pinned firmware contract.

## Next bench milestones

1. Flash nRF52840, allow OS Bluetooth permission and verify advertising/connection with USB unplugged.
2. Verify physical mounting/axes and neutral calibration; compare regional angles against USB and known fixture positions.
3. Test settings rejection/readback, pause/resume, faults and alert recovery using physical hardware.
4. Disconnect mid-command and reconnect; verify no partial command executes and local feedback continues while the app is disconnected.
5. Measure radio congestion/drop behavior, device sample cadence and actual sensor-to-display latency. Firmware's current ~1 Hz telemetry cannot establish a ≤250 ms display target. There is no device sequence/time in this protocol.
6. Define retention/deletion and recording recovery requirements for long sessions. Verify persisted readings after restart on target machines.

Mock tests and illustrative anatomy do not establish radio reliability, sensor accuracy, physical vibration or end-to-end latency.
