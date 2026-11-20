# Verification record

## Identified actuator drive configuration, 2026-11-09

The user identified Adafruit motor 1201 and DRV2605L breakout 2305 and supplied
a PCB image with driver supply labeled 3V3. Configured ERM open-loop signed RTP,
enabled supply compensation, set/verifed OD_CLAMP=138 and raised alert RTP from
32 to 127. TI equation 6 gives nominal full-scale average output 2.979 V. The
actuator datasheet rates 3.0 V (2.5–3.8 V operating range; <=2.3 V starting voltage).
The clamp is checked before motor start and in periodic verification. No posture
threshold or continuous-alert timing changed; sensor-only mode still bypasses it.

All four sanitizer suites passed. Sketch tests assert clamp/control configuration,
continuous RTP=127, zero/standby recovery, and fault-stop on a corrupted clamp.
Both builds passed: M4 105660 bytes flash; nRF52840 122388 bytes flash and 15844
bytes static RAM. No upload, measured voltage, current or physical startup test
was performed. Calculated register settings do not establish actuator performance.

## Motor-mode clarity and full-scale diagnostics, 2026-11-09

Initialization now identifies default hardware motor mode explicitly. Hyphenated
motor-on/off input produces a syntax reminder without changing mode or restarting
hardware. Full-scale IMU faults now identify sensor/channel, accel versus gyro,
axis and signed raw value; the +/-32000 guard remains unchanged.
All four sanitizer suites pass, including positive acceleration and negative gyro
range faults, motor shutdown and rejected hyphenated command without a new event.
Both builds pass: M4 105100 bytes flash; nRF52840 121588 bytes flash and 15844
bytes static RAM. No upload or physical actuator test was performed.

## Initialization bus diagnostics, 2026-11-08

IMU initialization errors now distinguish mux selection failure from sensor
begin failure and include channel/address. Added fault-only scan across channels
0–7, addresses 0x6A/0x6B, at 100/400 kHz. It reads WHO_AM_I, reports expected
LSM6DSOX identity 0x6C and restores 400 kHz. Checks are spread across loop passes.
Tests verify correct identity, one missing branch, upstream mux failure and clock
restoration. All four host sanitizer runs and M4 build passed (104932 bytes flash).
No scan of physical hardware or upload was performed.

## Explicit sensor-only test mode, 2026-11-08

Added `motor off` / `motor on`, accepted even from FAULT. Sensor-only entry makes
one best-effort stop attempt, then bypasses all motor initialization, start/stop,
periodic verification and fault-stop transactions while retaining IMU validation.
It reinitializes the sensors; the mode survives retry but resets on reboot.
Hardware-required mode remains the startup default. Compact buzz output in
sensor-only mode represents the alert decision; status marks the driver DISABLED.

All four sanitizer suites pass. Tests simulate an absent motor, calibration,
alert/recovery without any driver transactions after entry, retry preserving the
opt-out, failure when hardware mode is reenabled without a driver, and successful
hardware-mode retry when communication is restored. M4 build passed at 103172
bytes flash. No upload or physical sensor-only run was performed.

## Gravity correction and return-to-neutral diagnostics, 2026-11-08

Wearer logs showed a lower-region offset that remained outside recovery limits
while the user attempted to return to neutral. Those regional readings alone
cannot distinguish filter settling/gyro error, sensor assignment, actual sensor
orientation changes or attachment movement.

VQF tauAcc is now 1 second, previously 3 seconds: stronger accelerometer/gravity
correction while retaining both bias-estimation paths. This also increases
sensitivity to translational acceleration and is a tuning change, not a proven
hardware drift fix. No automatic baseline tracking was introduced.

Calibration now saves each sensor's mean neutral tilt for diagnostics as well
as the existing two regional baselines. Explicit sense reports per-sensor VQF
tilt, change from neutral, instantaneous acceleration-derived tilt, a quiet flag,
filter-minus-gravity difference, gyro magnitude, rest flag and mean acquisition
rate since initialization. Its three rows are scheduled across separate loops.
The default one-second compact display is unchanged.

All four sanitizer runs passed. A sketch simulation adds 1 degree/second gyro
bias to L5, holds neutral for 30 seconds, sustains a slouch for 20 seconds without
baseline adaptation, returns to neutral and checks motor shutdown, then holds
30 seconds and checks both residual regional deviations below 1 degree.
This uses ideal acceleration and consistent fixture angles, not real mounting,
sensor temperature changes or translational acceleration. M4 build passed at
102380 bytes flash. No upload or hardware return-repeatability test was performed.

## Wearable calibration tolerance, 2026-11-08

A hardware run repeatedly restarted its capture and timed out. Earlier progress
messages did not distinguish rest-flag, acceleration or angle-sway rejection, so
the screenshot alone does not establish the exact failing condition.

Calibration no longer requires VQF's bias-estimator rest flag. It requires each
sensor's raw gyro vector magnitude at or below 5 degrees/second and acceleration
norm within 10% of gravity, plus a 2-degree (previously 1-degree) sagittal
peak-to-peak envelope. The 3-second settle, 2-second window, 200-frame minimum,
hardware checks and timeout remain. There is no forced acceptance at timeout.
Text-only progress names sensor motion/acceleration blockers or angle-window
resets. Explicit status includes CAL_INFO limits and the last blocker.

All four sanitizer runs passed. Regression coverage includes 1.6-degree sway
acceptance, 2.1-degree sway rejection, calibration with small raw gyro offset,
rejection of 10 degrees/second motion and recovery once motion stops. M4 build
passed at 101132 bytes flash. No upload or physical baseline-quality validation
was performed; new limits are wearable tuning values.

## Sagittal-only angle validity, 2026-11-08

Removed the lateral projection guard, angle calculation, regional differences
and calibration baselines. Calibration checks three sagittal tilts and averages
two sagittal regions. An undefined lateral projection can no longer cause a
geometry fault or block calibration. The sagittal projection itself must remain
finite with magnitude at least 0.174; otherwise forward/backward tilt is
unobservable and a sagittal-specific fault stops monitoring.

Core tests accept an exactly lateral-singular but sagittal-valid vector and
still reject a sagittal-singular vector. The actual sketch simulation moves all
IMUs to 85 degrees forward, remains geometry-valid, and completes recalibration
there. Core/sketch suites pass under sanitizers in both precision configurations.
Both builds pass: M4 100260 bytes flash; nRF52840 112644 bytes flash and 15692
bytes static RAM. No upload or physical validation was performed.

## I2C clock restoration, 2026-11-08

Hardware reported `IMU gap imu=2 gap_us=16153 limit_us=16000` during settling.
Inspection of installed BusIO 1.17.4 showed Adafruit_I2CDevice::begin calls
Wire.begin; SAMD 1.7.17 Wire.begin resets to TWI_CLOCK=100000. The firmware's
original 400 kHz setting was therefore overwritten during device initialization.
Initialization now reapplies 400 kHz after all driver begins, before startup
flushing and sampling. Retry uses the same path. The 16 ms gap guard is unchanged.

The fake device begins now model this clock reset, and sketch tests assert
400 kHz after boot and retry. All four host sanitizer runs pass; M4 build passes
at 105732 bytes flash. No upload or physical bus measurement was performed, so
resolution of the hardware gap still needs confirmation after flashing.

## Compact serial output, 2026-11-08

Automatic angle/sensor values are suppressed before calibration and while paused
or faulted. Calibration prints text-only progress. In MONITORING and ALERT, one
line per second reports only upper_deg, lower_deg and the continuous-drive buzz
request. Automatic numeric BASELINE and DATA/SENSE dumps were removed. Manual
status retains troubleshooting details; manual sense reports sensor vectors/tilts.
Sampling, fault limits, alert thresholds and continuous drive are unchanged.

Both precision configurations passed core/sketch sanitizer tests, including three
readings in a three-second monitoring interval, no readings during setup,
calibration, pause or fault, and explicit sense access. Target builds passed:
M4 105700 bytes flash; nRF52840 118020 bytes flash and 15868 bytes static RAM.
No upload or hardware execution was performed.

## Repeated M4 sampling-gap investigation, 2026-11-08

After correcting all three IMU addresses to 0x6A, hardware screenshots showed
readings followed by a latched acquisition-gap fault, including after retry.
This establishes that initialization succeeds but the original 16 ms polling
guard is being crossed; it does not identify which operation caused the delay.

The M4 build now defines upstream `VQF_SINGLE_PRECISION` globally for C++ units.
VQF's internal Butterworth filter state remains double precision as upstream
requires. The geometry helper accepts either float or double quaternion arrays.
Automatic SENSE formatting is spread over three loop passes, one IMU per pass.
The sampling limit and fixed filter period were not relaxed. Firmware identifier
is now `feather-v3`; status reports VQF precision and timing maxima, and gap faults
include the sensor index and actual gap duration.

All four sanitizer-enabled host runs passed: core and sketch, in both float and
double VQF configurations. Tests include a deliberately injected 20 ms scheduling
gap that must still fault and report its sensor/duration. Both board builds
passed: M4 106916 bytes flash; nRF52840 119076 bytes flash and 15868 bytes static
RAM. Upstream VQF checksums still match. No upload or hardware timing measurement
was performed; this mitigation is not yet confirmed to resolve the physical fault.

## Short calibration and explicit upload, 2026-11-08

Calibration now uses 3 seconds of settling and a 2-second stable window with at
least 200 samples. The existing rest, acceleration and 1-degree peak-to-peak
checks remain; movement restarts capture. One-second `CAL` progress messages
show waiting/capture status. `status` identifies `POSTUREPAL firmware=feather-v2`.
Both sanitizer-enabled suites passed, including completion within 5.5 seconds
on the stationary simulator and repeat calibration through the serial command.
The M4 build passed (107796 bytes flash). These checks do not establish physical
filter settling or baseline quality with the shorter interval; fixture tests
remain necessary.

The build script now prints BUILD ONLY / NOT flashed by default. Explicit
`--upload --port YOUR_PORT` builds then uploads; missing `--port` is rejected
before building. No hardware upload was performed. Board discovery during this
change showed no USB Feather port.

## Serial monitoring update, 2026-11-08

The automatic 5 Hz `DATA` stream now names `upper_deg` and `lower_deg`, adds
`buzz=0/1` and per-region `over` flags, and labels limits and times with units.
`buzz` reports the continuous-drive request; `motor` independently reports
register confirmation. Pending timers show zero outside `MONITORING`.
This replaces the old `sag`, `trig`, `rec`, `dur`, `timer` and `motor_req`
field names; consumers of those fields must use the new names documented in SETUP.md.
No detection thresholds or motor drive behavior changed.

Both sanitizer-enabled host suites passed. The sketch simulation additionally
checks sustained RTP drive over five seconds, on/off serial flags, defaults,
and `buzz=0 motor=UNKNOWN` when a fault requests a stop without confirmation.
Both pinned target builds passed with warnings enabled:

- Feather M4: 107356 bytes flash (21%); RAM not reported by the build summary.
- nRF52840: 118164 bytes flash (14%), 15852 bytes static RAM (6%).

No upload or physical validation was performed. The earlier record below
describes the original nRF52840 revision; M4 setup and migration verification
are in [FEATHER_M4.md](FEATHER_M4.md).

Completed on 2026-11-02. The replacement was compiled and software-tested; it was
not uploaded, run on a Feather, or validated on a wearer.

## Feather target compilation

Command from repository root:

```sh
python3 tools/build.py --board nrf52840
```

Actual output:

```text
Pinned dependencies verified. Building with -O2 (IEEE NaN behavior).
Sketch uses 117972 bytes (14%) of program storage space. Maximum is 815104 bytes.
Global variables use 15852 bytes (6%) of dynamic memory, leaving 221716 bytes for local variables. Maximum is 237568 bytes.
```

Exit status: 0. Build warnings were enabled (`--warnings all`); none were emitted
in this build. Output is under ignored `build/feather52840/`, including
`PosturePal.ino.hex` and `.elf`. Static RAM figures do not include all runtime
allocations or establish maximum stack/heap use or real-time performance.

Environment:

- macOS arm64; Arduino CLI 1.5.1 (bundled with the existing Arduino IDE).
- Target `adafruit:nrf52:feather52840`, Adafruit nRF52 Boards 1.7.0.
- ARM GCC 9.2.1, GNU Tools for Arm Embedded Processors 9-2019-q4-major.
- Adafruit LSM6DS 4.7.4, DRV2605 Library 1.2.4, BusIO 1.17.4, Unified Sensor 1.1.15.
- Wire/SPI 1.0 and Adafruit TinyUSB Library 3.6.0, supplied by the board package.
- Official VQF 2.1.2, default double precision, checksums verified by build script.
- `compiler.optimization_flag=-O2` applied to all compilation units.

A separate negative build test with the core's default `-Ofast` failed as
intended, with the sketch's explicit diagnostic:

```text
error: #error "PosturePal/VQF requires IEEE NaN handling. Set compiler.optimization_flag=-O2; see docs/SETUP.md."
```

The sources have no edits to the installed board package or existing libraries.
The setup guide explains the IDE override; the build script supplies the override
without modifying those installations.

## Host software tests

Command:

```sh
sh tools/test.sh
```

Both executables were built using C++11, `-O2 -Wall -Wextra -Werror -pedantic`,
AddressSanitizer and UndefinedBehaviorSanitizer. Actual output:

```text
PASS: geometry, heading invariance, timers/hysteresis/rollover, parsing, calibration, freshness, bus/motor faults, official VQF
PASS: actual sketch boot/mount gate, calibration, commands, common lean, alert/recovery, pause/resume, sensor/motor faults, retry, no-USB monitoring
```

Both exited 0, without sanitizer errors.

`tests/test_core.cpp` checks quaternion direction/sign, arbitrary independent
heading invariance, proper axis transforms, singular projections, common sagittal
lean cancellation, regional angle wrapping, exact threshold/recovery boundaries,
independent regional timing, timer rollover, invalid/nonfinite settings, calibration
averaging across the angle wrap and movement reset, stale/skewed frames, short
reads/NACKs and motor-state confirmation failures. It also runs the actual
vendored VQF on stationary inputs and verifies rest detection and bias estimation.

`tests/test_firmware.cpp` includes the **actual sketch** and official VQF. Fake
Arduino, Adafruit initialization and I2C interfaces simulate measurements and
registers. It exercises the mounting gate, >15 s startup calibration, command
validation/line overflow, common leaning, a regional alert, hysteresis, return to
neutral, pause/resume while alerting, sensor disconnection while buzzing, fault
latching/retry/recalibration, motor unresponsiveness, repeated stop attempts,
data-ready timeout and disconnected USB after setup.

One motor-failure assertion deliberately leaves the simulated RTP register nonzero
while communication is unavailable, confirms UNKNOWN, then verifies that a later
stop succeeds once communication returns. This demonstrates the distinction
between a software shutdown request and confirmed delivery.

These tests do not simulate real I2C latency, electrical behavior, IMU clock
tolerance, every possible driver initialization failure, motor dynamics, or
garment/skin movement. Fake Adafruit calls cannot establish hardware initialization
behavior. The target build establishes API/compile compatibility, not execution.

## Remaining measurements and assumptions

- Exact physical axis mapping remains unknown. Common mapping is assumed because
  the team reported identically mounted axes; `axes` plus fixture checks and
  `mount-ok` are required after each reset.
- Real sustained 104 Hz throughput, no-loss polling, VQF processing time, true
  conversion skew and timing limits need logic-analyzer and movement validation.
- Neutral repeatability, small-slouch sensitivity, general 3D cross-talk, long-term
  drift and regional RMSE have not been measured.
- Thresholds, recovery limits, settling time and stillness tolerances are initial
  tuning values. No detection-rate, perceptibility, latency, battery-life or
  temperature requirement has been demonstrated.
- Motor part/voltage/current/clamp settings are unspecified. RTP 32 is a bench
  starting value, not a validated actuator configuration.
- Physical shutdown on communication failure is not guaranteed. Wire/initialization
  can block; no independent motor power/enable cutoff exists in the provided wiring.
- Continuous buzzing can perturb the measurements; motor-on/off comparison and
  attachment stability must be tested.
- BLE, desktop visualization, persistent settings and a hardware recalibration
  button are outside this revision. Serial recalibration requires no firmware upload.

Use [VALIDATION.md](VALIDATION.md) for the bench and wearer procedures before
treating the report's engineering targets as achieved performance.

## Reversed sensor placement and loop timing trace, 2026-11-20

Updated physical mux order to 0=L5, 1=T12, 2=T3, including regional formulas,
SENSE labels and calibration movement messages. Axis transforms are unchanged.
Preserved upstream per-sensor polling traces and added a 32-loop integer timing
ring covering commands, acquisition/filtering, evaluation, maintenance,
diagnostic formatting and output draining. It freezes on fault and emits paced
LOOP_TRACE lines; `timing` replays it before retry clears the history.

All host sanitizer suites pass, including both filter precisions and the nRF BLE
sketch configuration. Tests verify reversed regional signs/order, fault trace
replay, a simulated USB write stall attributed to usb=20000, and an external
20 ms scheduling gap. Feather M4 build passes (107492 bytes flash). No firmware
was uploaded; real hardware timing behavior remains to be measured.

## nRF master transfer boundary candidate

The pinned nRF Wire master completes transfers with CPU-triggered STOP/SUSPEND
after LASTRX/LASTTX. A build-local, hash-checked override now uses hardware
shortcuts for nonempty transfers, following Nordic's TWIM byte-boundary timing
requirements. The installed core is not modified. The same replacement methods
are executed by a register-model regression that demonstrates extra clocks
with a delayed software-only stop and no extra clocks with hardware completion.
NACK/error cleanup, repeated starts and bounded receives are also exercised.
This models the proposed mechanism, not a physical waveform capture.

All firmware host suites pass with UBSan; the pinned nRF52840 build succeeds
with the override selected. On the same connected vest, the unmodified timing
build faulted on a near-full-scale gyro value during a quiet USB-only phase
after approximately 34 seconds. The hardware-boundary build then completed
120 seconds USB-only followed by 180 seconds with BLE connected, with the
motor disabled and acquisition active in PAUSED. Each IMU accepted over 31,000
samples; recorded maximum gaps were 12.695, 13.672 and 13.672 ms, below the
unchanged 16 ms guard. No acquisition/range fault occurred in that run.
This supports the driver fix; it does not establish sustained reliability or
prove a physical over-read waveform. The existing fault guards and the
teammate's timing trace remain unchanged.

Isolated movement on the connected vest subsequently confirmed physical upper
on channel 0 and lower on channel 2 (with the middle on 1). The earlier physical
rewiring had already corrected the order, so the reversed placement assumption
in the timing commit is superseded for this setup. The current formulas, SENSE
labels, status mapping and calibration messages again use 0=T3, 1=T12, 2=L5.
Axis transforms remain unchanged. Host tests now also exercise isolated upper
and lower fixture motion through the actual VQF/sketch telemetry, checking both
region assignment and sign. Worn bend direction still requires fresh neutral
calibration and a live movement check after uploading.

The subsequent transition to a worn test produced additional raw-range faults
before a valid worn calibration/bend check completed, followed by a device
disconnect. Whether these events reflected movement or a remaining readout
failure was not established. The short flat bench pass must therefore not be
reported as a complete hardware fix or a successful worn lifecycle test.
