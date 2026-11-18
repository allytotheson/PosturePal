# nRF52840 BLE integration

The nRF owns sensing, VQF, calibration, thresholds, persistence, alerts and fault
handling. A website only needs to connect, send commands and display readings.
The existing website still needs a developer to add this client: firmware cannot
modify a third-party page. No cloud service or account is needed for this test.

BLE is automatically compiled for **Adafruit Feather nRF52840 Express**, using
Adafruit nRF52 core 1.7.0 and its bundled Bluefruit library. The M4 build remains
USB-only; its hardware does not include a BLE radio. Build/upload with:

```sh
python3 tools/build.py --board nrf52840
python3 tools/build.py --board nrf52840 --upload --port YOUR_PORT
```

## Test interface

From this repository:

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory tools/ble-test
```

Open http://127.0.0.1:8765 in a supported Chrome/Edge desktop browser or serve via
HTTPS for another device. Click **Connect device**, select **PosturePal**. The
page subscribes to notifications and requests status. No readings are fabricated.
Use the device log to resolve errors. Check physical axes before sending `axes`
and `mount-ok`; see [setup](SETUP.md). Calibration and motor commands have the
same behavior over BLE as USB. Settings/baseline remain RAM-only.

Web Bluetooth requires a secure context and a user gesture for device selection.
Browser/platform support varies; Safari/iOS and Firefox are not supported by this
interface. Check `navigator.bluetooth` before offering connection. See the
[Chrome Web Bluetooth guide](https://developer.chrome.com/docs/capabilities/bluetooth).
The local page provides live upper/lower deviations, alert request, status/sensor
queries, pause/resume/calibrate, a command field and a bounded log. Values clear
on disconnect, inactive states or missing updates; they are not historical data.

## GATT contract, protocol version 1

Advertised name: `PosturePal`. Filter by service UUID, not the name. One central
connection is supported. Advertising resumes after disconnect.

| Item | UUID | Operation |
| --- | --- | --- |
| Nordic UART service | `6e400001-b5a3-f393-e0a9-e50e24dcca9e` | Discover |
| RX, browser to device | `6e400002-b5a3-f393-e0a9-e50e24dcca9e` | Write with response |
| TX, device to browser | `6e400003-b5a3-f393-e0a9-e50e24dcca9e` | Subscribe to notifications |

Commands are printable ASCII, at most 159 characters plus newline. Write in chunks
of **20 bytes maximum**, sequentially with response; terminate with LF. CR is
ignored. Invalid characters/oversized lines are discarded as invalid commands.
Do not interleave commands or send concurrent writes. Firmware has a single
completed-command mailbox; additional commands arriving before it is consumed
are dropped. The supplied client serializes writes and waits 100 ms between
commands. A GATT write response means transport receipt, **not** successful command
execution: inspect `ERR`, `ACK`, `EVENT` and `STATUS` output, and read status to
confirm settings. Do not blindly retry state-changing commands.

TX is also ASCII newline-delimited. Notifications are chunks, **not lines**;
buffer until LF. Each line is at most 639 bytes including LF. While calibrated
and active, readings arrive once per second:

```text
upper_deg=8.20 lower_deg=1.50 buzz=1
```

Angles are signed regional deviations from neutral, in degrees. `buzz` is the
requested alert flag, not proof of vibration (including in sensor-only mode).
`EVENT state=...` reports state transitions; `status` returns detailed state,
fault, mounting, settings and `PROTOCOL version=1 transport=newline-ascii`.
The other diagnostic text is intended for people; preserve unknown lines in logs.

USB and BLE have separate input buffers and independent output queues. BLE output
is bounded to 4096 bytes, USB to 2048 bytes; full queues drop complete new lines.
BLE sends at most one 20-byte notification per loop using the nonblocking
SoftDevice API, retrying when buffers are full. There is no lossless recording,
command transaction ID, or replay. Disconnect clears BLE partial commands and
queued output; reconnect, subscribe and request status. Local monitoring continues
when BLE or USB disconnects. Disconnect is not a pause command.

## Copy into the website

Give the developer [posturepal.js](../tools/ble-test/posturepal.js), this document,
and optionally [the test page](../tools/ble-test/index.html). No npm dependencies.

```js
import { PosturePal } from './posturepal.js';
const device = new PosturePal();
device.addEventListener('reading', ({ detail }) => {
  // detail = { upper: 8.2, lower: 1.5, buzz: true }
  renderAngles(detail);
});
device.addEventListener('line', ({ detail }) => console.log(detail));
device.addEventListener('connection', ({ detail }) => showConnected(detail));
connectButton.onclick = async () => {
  try { await device.connect(); } catch (error) { showError(error.message); }
};
pauseButton.onclick = async () => {
  try { await device.send('pause'); } catch (error) { showError(error.message); }
};
```

The website must handle state changes, stale readings, denied/cancelled permission,
disconnects and command errors. Use top-level HTTPS; embedded pages may also need
the host's Bluetooth Permissions Policy. This does not add automatic cloud uploads.

## Prototype limits and verification

This is an **open, unbonded prototype service**: a nearby central can read telemetry
and send commands. Browser permission is not device authentication. Authenticated
pairing/physical authorization needs a separate product decision before deployment
outside controlled bench testing. No OTA update or battery-level service is claimed.

Verified in development: both pinned target builds; existing sanitizer-backed core
and firmware tests; BLE fragment/overflow/mailbox/congestion/disconnect tests.
The reusable JavaScript client also passes mocked tests for framing, parsing,
write chunking, invalid commands, concurrency and write failures:

```sh
node tests/test_ble_client.mjs
```

These tests mock the radio. No firmware was flashed and no real radio, browser
pairing, battery use or motor timing was verified. Browser visual QA was unavailable.

Before considering hardware integration complete:

1. Flash nRF52840; confirm advertising, connect and read status with USB unplugged.
2. Verify axes and calibration; compare BLE values with USB and fixture movement.
3. Check pause, resume, settings validation and fault behavior through the page.
4. Disconnect mid-command; reconnect and confirm no partial command executes.
5. Leave the browser idle/congested, reconnect, and confirm sampling timing via
   `status` remains within limits. Check `max_loop_us`/sample gaps under radio load.
6. Verify physical alert/stop behavior and continued monitoring after disconnect.
