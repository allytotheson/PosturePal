# Setup and operation

## Wiring and dependencies

Use the Feather's normal `Wire` SDA/SCL pins, common ground, and appropriate
3.3 V logic/pull-ups. Verify wearable cable capacitance and 400 kHz signal quality.
Only one mux channel is enabled at a time.

| Device | Mux channel | Seven-bit I2C address |
|---|---:|---:|
| PCA9548A | upstream | 0x70 |
| T3 LSM6DSOX | 0 | 0x6B |
| T12 LSM6DSOX | 1 | 0x6A |
| L5 LSM6DSOX | 2 | 0x6A |
| DRV2605L + ERM | 3 | 0x5A |

Pin these versions; do not substitute the Arduino Mbed nRF528x core:

| Dependency | Version | Use |
|---|---|---|
| Adafruit nRF52 Boards | 1.7.0 | Feather core, Wire, USB Serial |
| Adafruit LSM6DS | 4.7.4 | IMU initialization and configuration |
| Adafruit DRV2605 Library | 1.2.4 | Driver initialization |
| Adafruit BusIO | 1.17.4 | Adafruit dependency |
| Adafruit Unified Sensor | 1.1.15 | Adafruit dependency |
| Official VQF | 2.1.2 | Already vendored, unmodified, with MIT license |

Runtime reads, configuration readbacks and motor commands use checked `Wire`
transactions because the Adafruit convenience methods do not propagate all errors.
Do not install a different VQF wrapper. The VQF headers and implementation stay
in the same folder as `PosturePal.ino`.

With Arduino CLI installed, initial dependency setup is:

```sh
arduino-cli core update-index --additional-urls https://adafruit.github.io/arduino-board-index/package_adafruit_index.json
arduino-cli core install adafruit:nrf52@1.7.0 --additional-urls https://adafruit.github.io/arduino-board-index/package_adafruit_index.json
arduino-cli lib install "Adafruit BusIO@1.17.4" "Adafruit Unified Sensor@1.1.15" "Adafruit LSM6DS@4.7.4" "Adafruit DRV2605 Library@1.2.4"
python3 tools/build.py
```

`tools/build.py` needs Python 3 and Arduino CLI, checks exact installed versions
and VQF checksums, and writes to `build/feather52840`. Set `ARDUINO_CLI` to an
executable path if it is not in PATH. On macOS it can also find the CLI bundled
inside `/Applications/Arduino IDE.app`. `POSTUREPAL_BUILD_DIR` overrides the build
directory. The script never installs dependencies or uploads firmware.

## Required optimization setting

Adafruit core 1.7.0 defaults to `-Ofast`, which permits compilers to assume NaNs
do not occur. VQF intentionally uses NaNs to initialize its low-pass filter state;
the sketch also rejects nonfinite inputs. Build with `-O2`. The sketch refuses
a fast-math build instead of silently accepting this incompatibility.

The build script sets `compiler.optimization_flag=-O2`. A direct CLI equivalent is:

```sh
arduino-cli compile --fqbn adafruit:nrf52:feather52840 --build-property compiler.optimization_flag=-O2 firmware/PosturePal
```

For the Arduino IDE, select **Adafruit Feather nRF52840 Express** under Adafruit
nRF52 Boards. Before compiling, add the line below to `platform.local.txt` beside
the installed core's `platform.txt` (preserve existing settings), then restart
the IDE. This core setting may need restoration after board-package updates.

```ini
compiler.optimization_flag=-O2
```

Typical core paths:

- macOS: `~/Library/Arduino15/packages/adafruit/hardware/nrf52/1.7.0/`
- Linux: `~/.arduino15/packages/adafruit/hardware/nrf52/1.7.0/`
- Windows: `%LOCALAPPDATA%\Arduino15\packages\adafruit\hardware\nrf52\1.7.0\`

Open `firmware/PosturePal/PosturePal.ino`. Its neighboring headers and `.cpp`
are part of the sketch. Use the IDE upload button after selecting the actual port,
or upload an already compiled CLI build:

```sh
arduino-cli board list
arduino-cli upload --fqbn adafruit:nrf52:feather52840 --port YOUR_PORT --input-dir build/feather52840 firmware/PosturePal
```

No upload or device reset was performed during development of this revision.

## Mounting and first calibration

The actual board-axis mapping is unknown. Matching boards do not establish which
axis is anatomical forward/left/up. The identity matrix in the sketch is an
**unverified placeholder**, and cannot arm alerts by itself.

1. On a fixture, identify the labeled signed axis pointing headward and the
   signed axis pointing outward from the back. These must be perpendicular.
   Headward becomes body +z; inward (negative outward) becomes body +x; +y is
   computed as `z cross x` (left). Use matching physical mounting for all boards.
2. Open USB Serial at 115200 with newline termination. Send `status`, then
   `axes <headward> <outward>`. Example: `axes +Y +Z` **only** if +Y is headward
   and +Z is outward. All six signed axis names are supported. This sets a common
   proper rotation and clears calibration and mounting acknowledgment.
3. Check `SENSE upBody` and `tilt`. On an upright fixture, upBody should be near
   `(0,0,1)` and sagittal tilt near zero. Pitch the fixture forward: sagittal tilt
   should increase on every board by the reference angle. Check lateral motion
   and return. Allow settling after initialization.
4. Fit the marked mounts firmly and provide cable strain relief. Send `mount-ok`
   only after checking the mapping and fixture behavior. Acknowledgment does not
   automatically discover or prove axis alignment.
5. Hold neutral. Firmware settles filters for ten seconds, then averages at least
   500 observations spanning five continuous seconds. All three VQFs must report
   rest, acceleration norms must be within 0.05 g of gravity, and all six sensor
   sagittal/lateral tilts must stay within 1° peak-to-peak. Movement resets the window.
6. `BASELINE` reports four circular means and all six peak-to-peak variations.
   `MONITORING` indicates successful calibration. If averaging cannot complete
   within 60 seconds, firmware enters `FAULT`. Fix motion/mounting/noise, then
   use `retry`. Investigate before relaxing stillness limits.

For independently rotated boards, replace the common `axes` assignment with
separately verified proper matrices in the firmware; the supplied serial interface
assumes the matching orientations you reported. Calibration cannot compensate
arbitrary axis swaps or recover anatomical alignment.

## Commands

Commands are case-sensitive ASCII, maximum 159 characters, ending in newline.
Malformed or extra arguments are rejected; overflowed lines are discarded.

| Command | Behavior |
|---|---|
| `help` | Command summary |
| `status` | State, mapping, settings, baseline, last fault |
| `axes +Y +Z` | Example common mapping; clears baseline and mounting acknowledgment |
| `mount-ok` | Acknowledge verified mounting and start settling/calibration |
| `calibrate` | Stop motor, clear baseline, repeat settling and averaging |
| `pause` | Stop motor, reset timers, continue filters/diagnostics |
| `resume` | Resume with valid baseline; otherwise start calibration |
| `retry` | Reinitialize hardware/filters, clear fault, recalibrate if mounting acknowledged |
| `set 7.5 4 7.5 4 2000` | Upper trigger/recovery, lower trigger/recovery, persistence ms |

`set` requires finite degrees with `0 < recovery < trigger <= 90` and an integer
duration from 1 through 3,600,000 ms. It acknowledges applied settings and resets
both timers; if alerting, it first stops the motor. These bounds are interface
guards, not demonstrated accuracy. Settings do not change the baseline. In `FAULT`,
only `help`, `status` and `retry` are accepted.

Settings, mapping, acknowledgment and baseline are RAM-only. Every reset requires
repeating axes verification and calibration. USB is required for this setup and
later commands; disconnecting it after calibration does not stop monitoring.
No extra button or GPIO wiring is assumed.

## Diagnostics and faults

At 5 Hz, `DATA` reports sagittal/lateral deviations, aggregate sagittal deviation,
baseline, limits, persistence settings/timers, state, requested motor state,
register confirmation, sample ages, read-time skew, rest flags, and dropped log
lines. `SENSE` reports body up vectors, absolute sagittal sensor tilts, acquisition
counts, maximum observed sample gaps and calibration count. Use `valid=1` before
interpreting deviations: stale values remain in memory during setup/fault and are
flagged invalid. `status` includes lateral baselines. Timers are meaningful in
`MONITORING`; in `ALERT`, latching/recovery governs behavior.

Output is a bounded queue drained in at most 64-byte writes per loop. Congested
or disconnected output is dropped instead of stalling acquisition. Transition
messages are enqueued immediately but are best-effort; inspect `status` after
reconnecting. High-rate desktop plotting/25 Hz BLE is not implemented.

Failed transactions, excessive sample gaps, stale data, configuration mismatches,
invalid quaternions, near-full-scale readings, near-zero acceleration, singular
tilts, and driver-state failures latch `FAULT` and invalidate calibration. Firmware
attempts RTP zero, GO zero and standby immediately, then retries every 250 ms.
A fault never silently resumes. RTP/mode readback is checked before reporting
`ON_REG` or `OFF_REG`; `UNKNOWN` means confirmation failed. Neither label proves
actual vibration.

The core's `Wire` and Adafruit initialization routines contain blocking waits;
software cannot run shutdown if one hangs. No unsupported `Wire.setWireTimeout()`
call is used. A physical bus fault can prevent any stop command reaching the
driver. Guaranteed shutdown requires an independent motor enable/power path,
outside the supplied wiring.

## ERM drive assumptions

The ERM part, rated voltage, supply and current limits were not supplied.
Firmware retains Adafruit initialization, explicitly selects ERM, open-loop
operation and **signed RTP**, and starts at RTP 32/127 instead of the original
maximum 127. Zero is neutral in signed open-loop RTP. It does not perform actuator
auto-calibration or claim the default voltage clamp matches your motor. Check
motor specifications and driver OD_CLAMP before wearable trials; adjust
`MOTOR_RTP` after bench measurements. Low amplitude does not establish a verified
voltage/current limit. Continuous vibration follows your request and supersedes
the report's pulse proposal. Check temperature, supply droop and sensing noise
with the actual motor running. See [TI's driver datasheet](https://www.ti.com/lit/ds/symlink/drv2605l.pdf).
