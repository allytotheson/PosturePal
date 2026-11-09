# PosturePal

Three LSM6DSOX IMUs estimate **upper and lower regional sagittal tilt changes**
relative to a user-calibrated neutral posture. Full six-axis VQF improves rotation
integration and bias estimation; heading-independent gravity projections avoid
comparing the independent filters' drifting yaw angles.

The original sketch's single-sample calibration, approximate pitch/roll
integration, inconsistent threshold messages, combined-region timer, and
unchecked motor writes can all contribute to missed alerts or continued buzzing.
Changing the filter alone cannot correct mounting movement or a failed stop command.

- [Feather M4 Express setup and migration notes](docs/FEATHER_M4.md)
- [Complete Arduino firmware](firmware/PosturePal/PosturePal.ino)
- [Dependencies, build/upload, axis mapping, and serial commands](docs/SETUP.md)
- [Diagnosis, coordinate frames, method, and limitations](docs/METHOD.md)
- [Fixture tests, wearer tests, and tuning procedure](docs/VALIDATION.md)
- [Build/test results and remaining hardware checks](docs/VERIFICATION.md)

From the repository root:

```sh
sh tools/test.sh
python3 tools/build.py
```

The build defaults to **Feather M4 Express** (Adafruit SAMD 1.7.17, TinyUSB,
`-O2`). Use `python3 tools/build.py --board nrf52840` for the original nRF52840.
Both boards share the same firmware; the script checks pinned dependencies and
uploads only with `--upload --port YOUR_PORT`. Firmware starts paused with the
motor commanded off. Verify/set the common mounting axes, acknowledge `mount-ok`,
and hold neutral through three seconds of settling plus two seconds of stillness
checked calibration. Mounting, settings and baseline are RAM-only and must be
established again after a reset. Once running, USB disconnection does not pause
local monitoring.

Default limits (7.5° trigger, 4° recovery, two seconds) are **tuning values**.
Lateral angles are not calculated or used for calibration, alerts or angle faults. BLE and the desktop app are
outside this revision. Hardware performance and physical motor shutdown have not
been verified; register readback confirms register state, not actuator motion.
