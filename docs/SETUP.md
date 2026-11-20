# Setup and operation

For the current **Feather M4 Express**, start with [FEATHER_M4.md](FEATHER_M4.md).
The board installation, optimization and upload instructions below describe the
original nRF52840 target; wiring, mounting, commands and calibration apply to both.

## Wiring and dependencies

Use the Feather's normal `Wire` SDA/SCL pins, common ground, and appropriate
3.3 V logic/pull-ups. Verify wearable cable capacitance and 400 kHz signal quality.
Only one mux channel is enabled at a time. The single DRV2605L is wired to
the upstream SDA/SCL bus and is accessible regardless of mux selection.
Motor commands do not select a mux channel; the IMUs at 0x6A do not conflict
with the driver at 0x5A.

| Device | Mux channel | Seven-bit I2C address |
|---|---:|---:|
| PCA9548A | upstream | 0x70 |
| T3 LSM6DSOX | 0 | 0x6A |
| T12 LSM6DSOX | 1 | 0x6A |
| L5 LSM6DSOX | 2 | 0x6A |
| DRV2605L + ERM | Main bus (upstream SDA/SCL) | 0x5A |

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
python3 tools/build.py --board nrf52840
```

`tools/build.py` needs Python 3 and Arduino CLI, checks exact installed versions
and VQF checksums, and writes to `build/feather52840`. Set `ARDUINO_CLI` to an
executable path if it is not in PATH. On macOS it can also find the CLI bundled
inside `/Applications/Arduino IDE.app`. `POSTUREPAL_BUILD_DIR` overrides the build
directory. The script never installs dependencies. It uploads only with `--upload --port YOUR_PORT`;
without those flags it only compiles and prints NOT flashed.

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
3. Send `sense` to check `vqf_deg` and quiet `gravity_deg`. On an upright fixture,
   sagittal tilt should be near zero. Pitch the fixture forward: sagittal tilt
   should increase on every board by the reference angle. Check lateral motion
   and return. Allow settling after initialization.
4. Fit the marked mounts firmly and provide cable strain relief. Send `mount-ok`
   only after checking the mapping and fixture behavior. Acknowledgment does not
   automatically discover or prove axis alignment.
5. Hold neutral. Firmware settles filters for three seconds, then averages at least
   200 observations spanning two continuous seconds. Each sensor must have measured angular speed at or below 5 degrees/second,
   acceleration norm within 0.10 g of gravity, and sagittal tilt within 2 degrees
   peak-to-peak. The VQF bias-estimation rest flag is no longer a calibration gate.
   Excess movement resets the window. These are tuning limits, not validated
   measurement accuracy.
6. `MONITORING` indicates successful calibration. Send `status` to inspect the two
   sagittal regional baselines. If averaging cannot complete
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
| `sense` | One-time per-sensor tilt, neutral change and gravity comparison |
| `scan` | In FAULT only: read IMU identities at 0x6A/0x6B on mux channels 0–7, at 100/400 kHz |
| `axes +Y +Z` | Example common mapping; clears baseline and mounting acknowledgment |
| `mount-ok` | Acknowledge verified mounting and start settling/calibration |
| `calibrate` | Stop motor, clear baseline, repeat settling and averaging |
| `pause` | Stop motor, reset timers, continue filters/diagnostics |
| `resume` | Resume with valid baseline; otherwise start calibration |
| `retry` | Reinitialize hardware/filters, clear fault, recalibrate if mounting acknowledged |
| `motor off` | Sensor-only testing; skip driver communication and reinitialize sensors, allowed from FAULT |
| `motor on` | Require and initialize the motor driver again |
| `set 7.5 4 7.5 4 2000` | Upper trigger/recovery, lower trigger/recovery, persistence ms |

`set` requires finite degrees with `0 < recovery < trigger <= 90` and an integer
duration from 1 through 3,600,000 ms. It acknowledges applied settings and resets
both timers; if alerting, it first stops the motor. These bounds are interface
guards, not demonstrated accuracy. Settings do not change the baseline. In `FAULT`,
diagnostic commands, `retry`, and `motor off/on` are accepted.

Settings, mapping, acknowledgment and baseline are RAM-only. Every reset requires
repeating axes verification and calibration. USB or the [nRF52840 BLE interface](BLE.md) can be used for setup and
later commands; disconnecting it after calibration does not stop monitoring.
No extra button or GPIO wiring is assumed.

## Diagnostics and faults

Open Arduino Serial Monitor at **115200 baud** with **Newline** selected.
Before monitoring, only setup instructions, calibration progress and events/errors
are printed automatically; there is no angle or sensor-value stream. Calibration
progress is text only, once per second, and names a blocking sensor/motion or
acceleration check. `status` includes `CAL_INFO` with limits and the last blocker. After successful calibration, during both
`MONITORING` and `ALERT`, one compact line appears every **1000 ms**:

```text
upper_deg=8.20 lower_deg=1.50 buzz=1
```

`upper_deg` and `lower_deg` are signed regional deviations from neutral in degrees.
`buzz=1` means continuous motor drive requested; `buzz=0` means off requested.
It is a command flag, not a physical vibration measurement. Automatic readings
stop in paused, calibration and fault states. State changes and errors still print
immediately, independently of the one-second reading interval.

Each IMU's accelerometer and gyro feed a six-axis VQF at the configured 104 Hz
sensor rate. Upper regional tilt is T3 minus T12; lower is T12 minus L5. Their
calibrated neutral angles are subtracted to give the displayed deviations. Leaning
all three sensors together largely cancels out. These readings describe regional
angle changes, not clinical spinal curvature; wearer accuracy is unmeasured.

Either region must exceed 7.5 degrees in absolute value continuously for 2000 ms
to start buzzing. Each has its own timer. Once started, drive remains continuous
until both regions return to 4 degrees or less. Forward and backward deviations
count; lateral bending does not trigger buzzing. Thresholds remain tuning values.
Change them with `set 7.5 4 7.5 4 2000` (upper trigger/recovery, lower
trigger/recovery, duration). Logging cadence does not change sampling or alert timing.

Detailed values appear **only when explicitly requested**:

- `status`: state, fault reason, timing maxima, driver confirmation, settings,
  baseline and mapping. `MOTOR buzz=0 motor=UNKNOWN` means stop was requested but
  not confirmed. The physical motor could still be running.
- `sense`: three sensor lines for mounting checks; `imu=0` is T3, `imu=1` T12,
  `imu=2` L5. Each shows `vqf_deg`, `neutral_delta_deg`, `gravity_deg`,
  `filter_minus_gravity_deg`, `gyro_dps`, `rest` and `mean_hz` (since initialization).
  Check `valid=1` and `neutral_valid=1` before interpreting neutral changes.
  `gravity_quiet=1` means the current acceleration norm and gyro magnitude pass
  the calibration motion gates; it is not proof that acceleration is gravity only.
  Rows are emitted across three loop passes rather than formatted all at once.

Output uses a bounded queue and writes at most 64 bytes per loop. Congested or
unconnected output is dropped. Send `status` after reconnecting. Default periodic
output no longer includes `DATA`, `SENSE`, limits, timers, raw vectors or baselines.

Failed transactions, excessive sample gaps, stale data, configuration mismatches,
invalid quaternions, near-full-scale readings, near-zero acceleration, undefined sagittal
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

## Adafruit 1201 motor and 2305 driver

The identified actuator is [Adafruit 1201](https://www.adafruit.com/product/1201),
a brushed ERM disc, with [Adafruit 2305 DRV2605L](https://www.adafruit.com/product/2305).
The supplied PCB image labels driver power as 3V3; this is a design assumption,
not a measured loaded voltage. Ensure the DRV_EN net is high and the motor is
connected across OUT+ and OUT-, not from OUT+ to board ground.

The linked [motor specification](https://cdn-shop.adafruit.com/product-files/1201/P1012_datasheet.pdf)
rates it at 3.0 V, with operating range 2.5–3.8 V and starting voltage at or below
2.3 V. Firmware explicitly selects ERM open-loop, signed RTP, and supply
compensation enabled. It writes/verifies OD_CLAMP=138 (0x8A). Per equation 6 of
[TI's datasheet](https://www.ti.com/lit/ds/symlink/drv2605l.pdf), ERM open-loop
full-scale average voltage is 0.02159 × OD_CLAMP, nominally **2.979 V** here.
RTP is now **127/127** for continuous alerts, instead of the previous low 32/127
setting that could fail to start the motor. RTP zero and standby stop the request.
RATED_VOLTAGE is not the reference in this open-loop mode; no actuator
closed-loop auto-calibration is performed. The explicit OD_CLAMP is verified
before starting and in periodic motor checks; corruption latches a fault.

These are calculated settings, not measured motor-terminal voltage/current.
Bench-check startup, voltage, 3.3 V supply droop, continuous-run temperature and
sensor noise with the actual assembly. Driver register readback does not prove
physical motor movement. Posture trigger/recovery thresholds remain unchanged.

Only sagittal projections gate angle validity. No lateral angle is calculated or
used by calibration, alerts or fault checks. When the sagittal projection itself
has magnitude below 0.174, its angle is undefined and monitoring still faults;
ignoring lateral angles cannot recover missing sagittal information.

## Return-to-neutral and apparent drift

The calibrated baseline stays fixed until explicitly recalibrated/reset. VQF
uses a 1-second accelerometer correction time constant (previously 3 seconds)
with both motion/rest gyro-bias estimation enabled. Stronger gravity correction
reduces gyro reliance, but can react more to translational acceleration. It does
not correct a sensor slipping, incorrect channels or an inaccurate neutral pose.

To diagnose an offset, hold the intended neutral pose and send `sense`, then
repeat after about ten seconds without moving. Compare the per-sensor rows:

- VQF tilt changes while quiet gravity tilt stays stable: filter convergence or
  gyro-error effects are plausible; compare filter-minus-gravity disagreement.
- Both change: check sensor/mount movement or acceleration; software cannot tell
  sensor slippage from actual body movement using these sensors alone.
- `mean_hz` materially below 104: investigate acquisition throughput. This is an
  average since initialization and does not prove no individual samples were lost.

Verify channel placement by moving each sensor separately: 0=T3, 1=T12, 2=L5.
On a rigid fixture, test neutral, bend, and return before testing on a wearer.
Wait for the readings to settle before intentional `calibrate`; calibration
changes the reference, so do not repeatedly zero it during the diagnostic test.
The recovery rule remains both absolute regional deviations at or below 4 degrees.

## Testing without a motor driver

After uploading, send `motor off` to enter explicit sensor-only mode. It works
from the missing-driver startup FAULT and initializes the sensors automatically;
no extra retry is necessary. Then send `axes +X +Z` for the confirmed mounting,
followed by `mount-ok`. The normal calibration and alert/recovery rules apply.
The compact output stays unchanged, but `buzz=1` means an alert would command
buzzing; there is no physical motor drive. Status reports `motor=DISABLED enabled=0`.
No driver transactions are attempted after entering the mode. Entry makes one
best-effort stop request if hardware mode was previously enabled; failure is
reported and cannot establish that connected hardware physically stopped.

Mode is RAM-only and survives retry, not reboot. After a reboot, send `motor off`
again. To test the physical driver later, connect it and send `motor on`; hardware
initialization and all motor faults are required again. Sensor/bus faults remain
active in both modes.
Use a space in these commands: `motor-on` and `motor-off` are rejected with a
syntax reminder and do not change mode. Initialization prints an explicit mode
banner. `buzz=1` is a software request/decision, not proof of physical vibration.

Near-full-scale faults now report the zero-based IMU/channel (0=T3, 1=T12, 2=L5),
source (`gyro` or `accel`), X/Y/Z sensor axis and signed raw value. The unchanged
raw guard rejects values at or beyond +/-32000. Keep this information when
reporting a fault; it distinguishes a gyro-rate event from an acceleration event,
but does not by itself distinguish real motion from corrupted measurements.

## Powered sensors that fail initialization

A power LED does not confirm SDA/SCL connectivity or a responding I2C address.
Initialization faults now identify the failing mux channel and sensor address.
While FAULT is latched, send `scan`. It checks mux 0x70 selection and reads
WHO_AM_I (0x0F) at 0x6A and 0x6B on each channel at 100 and 400 kHz. An
LSM6DSOX should report `read=OK id=0x6C lsm6dsox=1`. Unused channels failing
are expected. A mux failure points to the upstream bus; one missing sensor points
to its branch/address/channel. Success at 100 kHz only suggests a bus-speed or
signal-quality issue, not proof that all wiring is otherwise correct.
The scan does not change configured sensor mappings and does not auto-resume;
send `retry` after correcting the cause. It runs only in FAULT so diagnostic bus
work cannot disrupt active sampling. Normal 400 kHz is restored afterward.

## Controlled bus-speed comparison

`bus-rate 100000` and `bus-rate 400000` are diagnostic commands accepted only in
FAULT or PAUSED. They reinitialize the hardware (and restart calibration if
mounting was acknowledged), retain every sensor/motor fault guard, and persist in
RAM across retry but not reboot. Default operation remains 400 kHz. `status`
reports `BUS_CONFIG hz=...`; `scan` temporarily tests both rates then restores the
selected rate. Use this A/B test to investigate signal quality and timing without
silently weakening sample-gap limits. A slower bus is not assumed to fix a fault.

`SCHED` reports maximum time between loop/poll calls, including time outside the
sketch's loop body. `IMU_TIMING` reports per-sensor sample counts, maximum sample
gaps and the last data-ready state while waiting; in STATUS_REG, 0x01 means only
accelerometer data is ready and 0x02 means only gyro data is ready (other bits may
also be set). These counters localize a failure; they do not prove its electrical
or sensor-internal cause. `sense` values are cached and invalid after FAULT.

Before retrying a sampling fault, request `trace 0`, `trace 1` or `trace 2` for
the affected IMU. The last 32 polls are retained in a fixed-size RAM ring and
freeze when acquisition stops. Output is oldest-first, one row every 100 ms;
wait for `TRACE end` before requesting another sensor. This command requires
FAULT, and initialization clears the trace. Each row contains the board's
`at_us`, age since the previous accepted sample, loop/poll intervals and elapsed
bus time (before VQF), plus raw STATUS_REG and a result code: 0 waiting, 1 sample
read, 2 mux-select failure, 3 status-read failure, 4 data-read failure, 5 sample
gap. A sample-read result can still be rejected by later range/geometry checks.
`ready=0xFF` is a sentinel when no status could be read. Times use the board's
`micros()` resolution, including its coarse tick fallback on nRF; unsigned
durations handle clock wrap. The trace adds no acquisition-path printing or
dynamic allocation, and does not relax any fault guard or establish a cause by
itself.
