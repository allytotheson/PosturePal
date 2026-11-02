# Verification record

Completed on 2026-11-02. The replacement was compiled and software-tested; it was
not uploaded, run on a Feather, or validated on a wearer.

## Feather target compilation

Command from repository root:

```sh
python3 tools/build.py
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
