# PosturePal

Three LSM6DSOX IMUs estimate **upper and lower regional sagittal tilt changes**
relative to a user-calibrated neutral posture. Full six-axis VQF improves rotation
integration and bias estimation; heading-independent gravity projections avoid
comparing the independent filters' drifting yaw angles.

The original sketch's single-sample calibration, approximate pitch/roll
integration, inconsistent threshold messages, combined-region timer, and
unchecked motor writes can all contribute to missed alerts or continued buzzing.
Changing the filter alone cannot correct mounting movement or a failed stop command.

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

The build checks pinned dependencies and compiles for
`adafruit:nrf52:feather52840`; it does not upload. Firmware starts paused with the
motor commanded off. Verify/set the common mounting axes, acknowledge `mount-ok`,
and hold neutral through ten seconds of settling plus five seconds of stillness
checked calibration. Mounting, settings and baseline are RAM-only and must be
established again after a reset. Once running, USB disconnection does not pause
local monitoring.

Default limits (7.5° trigger, 4° recovery, two seconds) are **tuning values**.
Lateral bending is logged but does not cause alerts. BLE and the desktop app are
outside this revision. Hardware performance and physical motor shutdown have not
been verified; register readback confirms register state, not actuator motion.
