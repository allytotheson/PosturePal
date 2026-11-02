# Diagnosis and sensing method

## What was reviewed

The supplied 14-page `Design_Report.pdf` (especially sections 3, 4, 6.3 and 7),
the supplied 18-page published VQF paper, and the full sketch pasted in the request
were reviewed. No separate original firmware file existed in the repository.
The PDFs are source inputs and have not been modified.

The report already proposes gravity-vector sagittal tilt extraction, adjacent
regional differences, 104 Hz sensing, five-second averaged calibration, and
independent upper/lower timers. It proposes BLE and 500 ms vibration pulses; this
revision implements the selected serial-only scope and requested continuous alert
instead. No medical correctness or validated accuracy is inferred from calibration.

## Diagnosis of the supplied sketch

| Observation | Consequence / likely symptom | VQF's role |
|---|---|---|
| Comment/prints say 30° trigger and 10° recovery, constants are 7.5° and 6.75° | Tests may be interpreted against the wrong settings; recovery margin is only 0.75° | None; print actual settings and separate recovery values |
| One accelerometer sample per sensor sets neutral after an unconditional delay | Noise, movement and startup transient become baseline error | Rest detection helps; averaging and explicit calibration gating are still required |
| Scalar pitch/roll gyro integration uses body `gyroY`/`gyroX` | Only approximately correct near simple aligned motions; ignores coupled rotation kinematics and gyro z contributions | Quaternion strapdown integrates full angular velocity |
| Raw pitch/roll differences assume common anatomical axes | Board rotation mixes lateral and forward motion; subtracting neutral cannot fix axis swaps or scale/cross-axis effects | None; proper sensor-to-body rotations are required |
| Euclidean norm of Euler differences | An engineering score, not generally a 3D relative rotation angle; pitch is limited by its extraction formula | Keep interpretable sagittal regional differences; do not label the result a 3D joint angle |
| T3–L5 included in maximum across three pairs | Can dominate adjacent regions, or cancel opposing local changes; not the report's two-region rule | None; adjacent regions control alerts, total is diagnostic |
| One timer follows maximum of changing regions | Alternating regions can collectively sustain the maximum without one region persisting | None; use independent timers |
| `delay(10)` plus sequential I2C and unrestricted serial printing | Processing is slower/variable relative to 104 Hz; samples may be skipped | VQF needs correctly timed fresh data; it is not a scheduler |
| Fixed complementary `ALPHA=0.98` | Physical correction time constant varies with loop time | VQF derives coefficients from explicit sample periods |
| Invalid `dt` replaced by 10 ms | Lost elapsed motion is concealed rather than handled | None; stop alerts and invalidate continuity on data loss |
| `getEvent()` returns true regardless of underlying `_read()` status in pinned library | Existing failure branches do not prove sensor integrity | None; checked transactions are needed |
| Motor setters return void; `motorRunning=false` is assigned without readback | MCU can claim shutdown even if the driver retains a nonzero RTP command | None; checked writes/readback and UNKNOWN state are needed |
| Error halt attempts stop once, then loops forever | A transient failure during shutdown never gets another stop attempt | None; latch fault and retry shutdown |

The original radians/s-to-degrees/s conversion is appropriate for its degree-based
filter; the replacement must **not** repeat that conversion before VQF. There is
no evidence of a missing recovery branch: original code does stop when its maximum
score is below recovery. A nonzero residual score (bad calibration, filter error,
vest displacement or vibration) can keep the state alerting; a failed motor write
can leave hardware vibrating after the software has left the alert state. Logs
and an independent motor/current observation separate these cases.

Large whole-body leaning need not produce any regional bend: all three sensors
can rotate together, so pairwise differences cancel. Lowering thresholds cannot
turn that metric into a whole-trunk inclination detector. Conversely, a small
slouch should change at least one adjacent regional measurement when the mounts
follow the skin/segment motion; inspect those raw changes before blaming thresholds.

References for driver behavior: [pinned LSM6DS source](https://github.com/adafruit/Adafruit_LSM6DS/blob/4.7.4/Adafruit_LSM6DS.cpp)
and [pinned DRV2605 source](https://github.com/adafruit/Adafruit_DRV2605_Library/blob/1.2.4/Adafruit_DRV2605.cpp).

## Why full six-axis VQF

Use the causal full C++ `VQF`, with one independent instance per IMU. BasicVQF
omits the useful rest/bias extensions; OfflineVQF requires future samples and
does not belong in real-time haptic control. The official algorithm filters
acceleration in an almost-inertial frame and estimates gyro bias during rest and
motion. This addresses coupled rotation integration, some acceleration-induced
tilt error, and bias drift. It cannot remove sustained unknown linear acceleration,
arbitrary mounting errors, unobserved heading, or sensor-to-skin movement.
[Laidig and Seel, Information Fusion 91 (2023), sections 2.2–2.7](https://doi.org/10.1016/j.inffus.2022.10.014).

The firmware uses the verified API, not an Arduino wrapper:

```cpp
VQFParams params;                      // default tauAcc=3 s, rest/motion bias on
params.magDistRejectionEnabled = false;
VQF filter(params, 1.0/104.0);
// For each new, coherent measurement, SI units:
filter.update(gyrRadiansPerSecond, accMetersPerSecondSquared);
vqf_real_t q[4];
filter.getQuat6D(q);
bool still = filter.getRestDetected();
```

No fake magnetometer values, external gyro-bias subtraction, filter recreation on
each sample, or arbitrary Euler-angle resets are used. `resetState()` is used
only on hardware initialization/retry. Recalibrating neutral normally preserves
the running filter and its bias estimates. Default precision is double.
[Official API and units](https://vqf.readthedocs.io/en/latest/ref_cpp.html),
[official 2.1.2 source](https://github.com/dlaidig/vqf/tree/v2.1.2/vqf/cpp).

## Coordinate frames and quaternion conventions

- `S_i`: each IMU's labeled, right-handed sensor axes. Gyro/acceleration stay in
  this frame when supplied to VQF.
- `B_i`: local anatomical axes at that mounting location: +x anterior/forward,
  +y left, +z headward. These local frames follow their respective back segments;
  they are not all forced to share the same orientation during neutral calibration.
- `E_i`: that filter's gravity-aligned reference frame, +z upward. Its horizontal
  heading is arbitrary and can drift independently of the other two filters.

VQF returns a scalar-first Hamilton quaternion `q=(w,x,y,z)`, whose active
rotation `R(q)` maps `S_i` vectors into `E_i`: `vE=q ⊗ (0,vS) ⊗ conjugate(q)`.
Composition `qA ⊗ qB` applies B then A. Quaternions `q` and `-q` represent the
same rotation. Using a world-to-sensor quaternion here would invert the calculation.
The implementation tests both direction and sign equivalence.

Let `A_i = RbodyFromSensor` be a fixed proper rotation (orthonormal, determinant
+1), verified from physical mounting. It maps *coordinates* from sensor to local
body axes. Neutral calibration stores regional angles; it does not estimate A_i.

```text
uS = transpose(R(q)) * [0,0,1]
   = [2(xz-wy), 2(yz+wx), w²-x²-y²+z²] / ||q||²
uB = A_i * uS
sagittal_i = atan2(-uB.x, uB.z)
lateral_i  = atan2( uB.y, uB.z)
```

The sensor measures upward specific force while stationary, not the downward
gravity-force vector; the reference here is **up**. Sagittal tilt is positive
for forward bending under these axes. The lateral formula is positive for a
rightward segment tilt; verify signs with a fixture. Angles are converted from
radians to degrees only after extraction. Both relevant vertical-plane projections
must have norm at least 0.174 (approximately sin 10°); near-horizontal/singular
orientations outside this seated envelope invalidate the measurement.

The default identity alignment is intentionally unverified. `axes <headward>
<outward>` builds A_i for all three identically mounted boards: row z=headward,
row x=negative outward, row y=z cross x. It checks right-handedness and
orthogonality. `mount-ok` requires a configured mapping and a valid projected
measurement but remains the operator's acknowledgment, not an automatic anatomical
alignment detector. Arbitrarily rotated mounts need separately measured matrices.

This implements the report's section 6.3 gravity projection, explicitly adding
the missing sensor-to-body transform. See also [paper sections 2.1–2.3 and Appendix A](https://doi.org/10.1016/j.inffus.2022.10.014).

## Heading drift and regional deviations

Six-axis data provides no absolute heading reference. Initializing all filters
together or subtracting a neutral relative quaternion does not eliminate later
differential yaw drift. Naive `inverse(qT12) ⊗ qT3` assumes a shared earth frame,
which independent `E_i` frames cannot guarantee. Gyro-bias estimation helps but
does not make general relative heading observable.

The chosen calculation does not compare world headings. For an arbitrary
heading rotation `H_i` about earth up:

```text
R(q_i)' = H_i * R(q_i)
transpose(R(q_i)') * earthUp
  = transpose(R(q_i)) * transpose(H_i) * earthUp
  = transpose(R(q_i)) * earthUp
```

Thus each independent heading offset cancels exactly in the up vector. This
does not mean that physical axial twisting is measured: twisting while inclined
can change gravity's components in anatomical axes and therefore affect projected
angles. Pure vertical-axis rotation is unobservable from gravity. The method
deliberately gives up full 3D inter-segment rotation to obtain useful seated tilt.
[Paper, section 2.2](https://doi.org/10.1016/j.inffus.2022.10.014).

For sagittal tilt, define:

```text
upper = wrap(thetaT3  - thetaT12)
lower = wrap(thetaT12 - thetaL5)
deviation_region = wrap(current_region - circularMeanNeutral_region)
```

Compute lateral regional differences and baselines in the same way, but log them
only. The aggregate T3–L5 sagittal deviation is diagnostic, not a third trigger.
Calibration averages signed angles with sine/cosine sums, avoiding the ±180° mean
discontinuity. A stable nonzero regional baseline is normal.

In aligned sagittal motion, adding a common lean angle to every segment cancels
in these differences. This is an approximate segmentation model for real wearers:
general 3D rotations, different axial alignment, loose mounting and skin motion
can break common-mode cancellation. Neither three point orientations nor their
differences reconstruct vertebral curvature. The report's <5° RMSE goal and the
paper's benchmark errors are not demonstrated PosturePal accuracy.

## Acquisition timing, calibration and alerts

The LSM6DSOX runs gyro and acceleration at nominal 104 Hz. A 1 ms polling schedule
checks both data-ready flags and reads the contiguous 12-byte gyro/acceleration
register block with BDU and auto-increment enabled. At ±250°/s the scale is
8.75 mdps/LSB; at ±2 g it is 0.061 mg/LSB. These raw units are converted to
rad/s and m/s². Register configuration and identity are rechecked periodically.
[ST LSM6DSOX documentation](https://www.st.com/en/mems-and-sensors/lsm6dsox.html).

BDU prevents torn measurement words; it does **not** synchronize all axes/sensors,
provide a sample counter, or preserve an arbitrary backlog. The firmware uses no
FIFO. Each filter advances only on a fresh ready pair, at `Ts=1/104`; polling
timestamps measure read completion, not exact conversion time. A read gap of
16 ms or more faults; no sample for 30 ms faults. Regional evaluation waits for
all three filters to advance and requires read-time skew <=12 ms. These bounds
are conservative tuning defaults to check on hardware; they are not proof of
exact conversion alignment. The 104 Hz oscillators have tolerance and may differ.

A logic analyzer and movement tests must establish actual sustained throughput,
latency and sampling loss. For faster dynamics or verified alignment needs, use
timestamped FIFOs/hardware synchronization and an explicit time-alignment model
in a subsequent revision. Do not update VQF repeatedly with duplicate samples or
invent a variable-dt overload of its API. Read-time skew of 12 ms alone corresponds
to about 0.36° at 30°/s, before filter/mounting errors; true conversion phase can
add uncertainty.

Calibration gates on all rest flags, approximately 1 g acceleration, and a
five-second 1° peak-to-peak envelope in all six projected tilts. These checks reject
many moving calibrations but cannot prove the user's posture is neutral, detect
all slow motion, or validate garment attachment. Ten seconds is an initial settling
interval, not a guaranteed thermal/bias convergence time.

Each region times its own strictly above-trigger sagittal deviation. Equality to
the trigger resets that region's timer. Once either timer completes, the shared
motor latches on. Both absolute deviations must be <=their recovery thresholds
to stop, even if they have already fallen below their trigger thresholds. Pause,
recalibration, setting changes and faults stop feedback and reset timers. The
default 7.5°/4°/2 s settings are experimental values, not clinical boundaries.

Motor commands write and read back RTP and mode; periodic checks also inspect
identity and thermal/overcurrent flags. Failed stop actions do not prevent the
remaining stop actions from being attempted. Software tracks requested state
separately from confirmed register state and never claims physical shutdown from
readback. Driver communication recovery/watchdog behavior is not a guaranteed
motor timeout. [TI DRV2605L datasheet, sections 8.3.11 and 8.5.8](https://www.ti.com/lit/ds/symlink/drv2605l.pdf).

The nRF52 Wire implementation has blocking hardware-event waits; a hanging call
can prevent all later fault handling. This firmware makes best-effort shutdown
attempts for returned errors, not a guarantee against all electrical failures.
[Pinned Wire implementation](https://github.com/adafruit/Adafruit_nRF52_Arduino/blob/1.7.0/libraries/Wire/Wire_nRF52.cpp).
