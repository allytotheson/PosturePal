# Feather M4 Express

The current PosturePal sketch supports the Feather M4 Express and the original
Feather nRF52840 Express. Only a small SAMD USB include/build guard and board build
settings were needed, so both use `firmware/PosturePal/`; there is no separate
firmware copy to keep synchronized. The filter, calibration, sensor addresses,
mux channels, haptic control, commands and thresholds are unchanged.

## Board research and compatibility

Adafruit's [overview](https://learn.adafruit.com/adafruit-feather-m4-express-atsamd51/overview)
specifies an ATSAMD51J19A Cortex-M4F at 120 MHz, 512 KB internal flash,
192 KB RAM and 2 MB external QSPI flash. The M4 Express has no onboard BLE radio.
The existing sketch already uses USB Serial with no BLE dependencies, so there
is no BLE functionality to remove. It does not use the external flash.

The [pinout](https://learn.adafruit.com/adafruit-feather-m4-express-atsamd51/pinouts)
confirms 3.3 V logic and hardware I2C on the labeled **SDA/SCL** pins (Arduino
21/22). Connect the existing PCA9548A upstream bus there, with common ground;
keep the three LSM6DSOX units and DRV2605L on the mux channels listed in
[SETUP.md](SETUP.md). No firmware pin remapping is needed because it uses `Wire`,
not numeric GPIO assignments. The M4 has no default SDA/SCL pull-ups: check the
pull-ups already present on your breakout boards and keep the upstream logic
at 3.3 V. The configured bus speed remains 400 kHz.

Two build details matter:

- **Use TinyUSB.** The SAMD 1.7.17 default Arduino USB implementation inserts
  `delay(10)` in `Serial_::operator bool()`. This sketch checks `Serial` during
  every logger drain, and extra checks occur for diagnostic lines. That delay
  would interfere with the 104 Hz sampling schedule. TinyUSB has no fixed delay
  in this check and reports actual transmit FIFO capacity for bounded writes.
  The sketch now rejects a SAMD build without TinyUSB.
- **Enable floating-point printf and preserve NaNs.** The SAMD platform links
  newlib-nano; `-Wl,-u,_printf_float` retains the float formatting used by
  `vsnprintf` for `DATA`, `SENSE`, settings and baselines. Choose `Fast (-O2)`;
  avoid the `-Ofast` options because VQF relies on IEEE NaN behavior. SAMD uses
  the `opt` board menu, rather than nRF52's `compiler.optimization_flag` property.

Implementation references: [SAMD USB source](https://github.com/adafruit/ArduinoCore-samd/blob/1.7.17/cores/arduino/USB/CDC.cpp),
[TinyUSB CDC source](https://github.com/adafruit/Adafruit_TinyUSB_Arduino/blob/3.1.5/src/arduino/Adafruit_USBD_CDC.cpp),
[SAMD build recipes](https://github.com/adafruit/ArduinoCore-samd/blob/1.7.17/platform.txt),
and [board menu definitions](https://github.com/adafruit/ArduinoCore-samd/blob/1.7.17/boards.txt).

## Build and upload

The existing installed **Adafruit SAMD Boards 1.7.17** was used and is pinned for
reproducibility. Keep the same sensor libraries listed in SETUP.md: LSM6DS 4.7.4,
DRV2605 1.2.4, BusIO 1.17.4 and Unified Sensor 1.1.15. The verified M4 build uses
the core-bundled TinyUSB 3.1.5. No board packages or libraries were changed.

For a new installation, follow Adafruit's
[Arduino setup guide](https://learn.adafruit.com/adafruit-feather-m4-express-atsamd51/using-with-arduino-ide)
for Arduino SAMD support and Adafruit SAMD support, then install the pinned core:

```sh
arduino-cli core update-index --additional-urls https://adafruit.github.io/arduino-board-index/package_adafruit_index.json
arduino-cli core install adafruit:samd@1.7.17 --additional-urls https://adafruit.github.io/arduino-board-index/package_adafruit_index.json
arduino-cli lib install "Adafruit BusIO@1.17.4" "Adafruit Unified Sensor@1.1.15" "Adafruit LSM6DS@4.7.4" "Adafruit DRV2605 Library@1.2.4"
```

From the repository root:

```sh
sh tools/test.sh
python3 tools/build.py
```

The default is now M4; `--board feather-m4` selects it explicitly. The script
checks pinned versions and vendored VQF checksums, selects TinyUSB and `-O2`, adds
float formatting support, and writes `build/feather_m4/`. By default it only compiles; it explicitly prints
NOT flashed. To build and upload, close Serial Monitor and run:

```sh
python3 tools/build.py --upload --port YOUR_PORT
```

Replace `YOUR_PORT` with the port selected under Arduino IDE Tools > Port.
Upload is never automatic without `--upload`.
The original target remains available via `--board nrf52840`.

Direct compile/upload commands:

```sh
arduino-cli compile --fqbn adafruit:samd:adafruit_feather_m4:opt=fast,usbstack=tinyusb --build-path build/feather_m4 --build-property compiler.c.elf.extra_flags=-Wl,-u,_printf_float --build-property compiler.cpp.extra_flags=-DVQF_SINGLE_PRECISION firmware/PosturePal
arduino-cli board list
arduino-cli upload --fqbn adafruit:samd:adafruit_feather_m4:opt=fast,usbstack=tinyusb --port YOUR_PORT --input-dir build/feather_m4 firmware/PosturePal
```

For Arduino IDE, open `firmware/PosturePal/PosturePal.ino` and select:

- Board: **Adafruit Feather M4 Express (SAMD51)** under Adafruit SAMD Boards.
- CPU Speed: **120 MHz (standard)**.
- Optimize: **Fast (-O2)**.
- USB Stack: **TinyUSB**.

Add this line to `platform.local.txt` beside the SAMD core's `platform.txt`,
preserving existing settings, then restart the IDE:

```ini
compiler.c.elf.extra_flags=-Wl,-u,_printf_float
compiler.cpp.extra_flags=-DVQF_SINGLE_PRECISION
```

On this Mac the directory is
`~/Library/Arduino15/packages/adafruit/hardware/samd/1.7.17/`.
This is a manual IDE configuration step; the build script supplies the flag
without changing installed files. Restore the setting if a core update removes it.
The nRF52 `compiler.optimization_flag` IDE override is not used for this SAMD build.

Open USB Serial at 115200 with newline termination and follow the axis verification,
`mount-ok`, settling and calibration procedure in SETUP.md. Send `status` after
connecting; startup messages may have been dropped before the port opened.
Mapping, acknowledgment and baseline still reset on every power cycle. After
calibration, monitoring continues locally when USB is disconnected.

Calibration now takes about **5 seconds** (3 s settling + 2 s stable averaging).
`CAL` progress lines explain the wait; movement restarts capture. After mounting
checks, send `axes +X +Z` for the confirmed +X-headward/+Z-outward orientation,
then `mount-ok`. Later, use `calibrate` to replace the baseline.

## M4 timing update

Repeated hardware screenshots showed acquisition gaps crossing the 16 ms guard.
The M4 now uses upstream VQF single precision (the Cortex-M4F supports hardware
single precision) while retaining the upstream source and NaN handling. nRF52840
continues to use its original double configuration. The SAMD sketch rejects
a build missing the single-precision flag. Sensor diagnostic formatting is
spread across three loop passes, one IMU per pass, instead of one large burst.
`status` reports `feather-v3`, `vqf_bits=32` on M4, and a `TIMING` line showing
maximum loop, filter, diagnostic-formatting and command times since boot. Gap
faults include the zero-based sensor number, actual gap and unchanged 16000 us
limit. This is a performance mitigation; the root cause and sustained timing
on the physical board still require confirmation after uploading.

## Verification

Build and host tests completed on 2026-11-08. M4 compilation with warnings enabled
passed, reporting **107796 bytes (21%)** of the 507904-byte application flash
limit. This CLI/core combination did not report static RAM use in its summary.
The generated compiler commands confirmed `-O2` and TinyUSB for the sketch,
VQF and USB CDC source; the linker map confirmed `_printf_float` was retained.
An intentional build with the Arduino USB stack failed with the new TinyUSB
diagnostic. The original nRF52840 target also compiled successfully during
the migration; see VERIFICATION.md for the later serial-output update.
The host geometry/filter and actual-sketch state-machine suites passed with
AddressSanitizer and UndefinedBehaviorSanitizer. These tests use simulated I2C
and do not establish real SAMD timing or electrical behavior.
Serial diagnostics now include an explicit `buzz=0/1`, named upper/lower degree
readings, trigger flags and pending timers. The sketch test additionally checks
five seconds of sustained RTP drive, recovery output, and off-requested but
unconfirmed output during a simulated motor communication failure.

No upload or hardware reset was performed. Confirm float-valued serial output,
sample gaps, calibration, alert/recovery and USB-disconnected operation on the
actual M4 using [VALIDATION.md](VALIDATION.md). The higher CPU clock alone does
not establish sustained three-filter throughput. Existing motor configuration
and mounting assumptions in SETUP.md still need bench verification.

## Compact serial display

The latest version hides automatic sensor values until calibration completes.
During monitoring/alert it prints only `upper_deg`, `lower_deg` and `buzz=0/1`
once per second. Setup progress and errors remain visible. Use `status` or
`sense` explicitly for troubleshooting or axis verification; the detailed
periodic DATA/SENSE stream described in earlier verification records is removed.

The latest timing fix restores `Wire` to 400 kHz after all Adafruit device
initialization calls, which otherwise reset SAMD Wire to 100 kHz. This also
applies on `retry`. The 16 ms sample-gap guard remains enabled. Build and clock-reset
regression tests pass; hardware confirmation still requires uploading the fix.

Angle validity and calibration now use sagittal angles only. Lateral projections
are not calculated or checked; their singularities cannot fault usable sagittal
readings. An undefined sagittal projection still stops detection.

Wearable calibration now tolerates 2 degrees of sagittal sway over its two-second
capture. Instead of requiring the VQF rest flag, it checks angular speed up to
5 degrees/second and acceleration norm within 10% of gravity. Progress messages
name the blocker; `status` includes CAL_INFO. These limits still need physical
baseline-quality testing. No unstable baseline is forced through on timeout.
